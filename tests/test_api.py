"""REST API tests with Flask's test client (temporary SQLite database, no network)."""
import hashlib
import hmac
import io
import json
import threading
import time
import unittest
from decimal import Decimal

import jwt

from tests import helpers
from api import create_app
from api.client import ConflictError, Forbidden, InvalidInput, PawConnectClient
from config import PAYMENT_SECRET
from core import workflows as wf
from services.api_service import PaymentGatewaySimulator
from services.payment_razorpay import RazorpayGateway

PASSWORDS = {"admin@pawconnect.org": "Admin@123", "arjun.rescue@pawconnect.org": "Rescuer@123",
             "fatima.rescue@pawconnect.org": "Rescuer@123", "rohit.rescue@pawconnect.org": "Rescuer@123",
             "ananya@example.com": "Donor@123", "karan@example.com": "Citizen@123",
             "riya@example.com": "Adopter@123"}


class ApiTestCase(unittest.TestCase):
    razorpay = None

    @classmethod
    def setUpClass(cls):
        helpers.fresh_demo_data()
        cls.app = create_app(testing=True, razorpay=cls.razorpay)
        cls.client = cls.app.test_client()
        cls._tokens = {}

    def token(self, email):
        if email not in self._tokens:
            r = self.client.post("/auth/login", json={"identifier": email, "password": PASSWORDS[email]})
            self.assertEqual(r.status_code, 200, r.get_json())
            self._tokens[email] = r.get_json()["access_token"]
        return {"Authorization": f"Bearer {self._tokens[email]}"}

    def call(self, method, path, email=None, expect=200, **kwargs):
        headers = self.token(email) if email else {}
        r = self.client.open(path, method=method, headers=headers, **kwargs)
        data, is_json = r.data, r.is_json
        body = r.get_json() if is_json else None
        r.close()                                   # also closes files sent with send_file
        self.assertEqual(r.status_code, expect, data[:400])
        if r.status_code >= 400:
            self.assertEqual(set(body), {"error", "details"})          # one error shape everywhere
            self.assertIsInstance(body["details"], list)
        return body if is_json else data

    def open_case(self):
        return self.call("POST", "/cases", "karan@example.com", 201, json={
            "animal_type": "Dog", "injury_level": "Critical", "description": "Dog hit by a bike, bleeding",
            "pincode": "201001", "address": "Old bus stand", "use_network": False})


# ======================================================================= auth
class AuthTests(ApiTestCase):
    def test_health_and_docs(self):
        self.assertEqual(self.call("GET", "/health")["status"], "ok")
        spec = self.call("GET", "/openapi.json")
        for path in ("/auth/login", "/cases/{case_id}/accept", "/funds/allocate", "/payments/webhook"):
            self.assertIn(path, spec["paths"])
        self.assertIn(b"swagger", self.call("GET", "/docs").lower())

    def test_login_and_me(self):
        reply = self.call("POST", "/auth/login", json={"identifier": "9810000001", "password": "Admin@123"})
        self.assertEqual(reply["token_type"], "Bearer")
        self.assertEqual(reply["expires_in"], 3600)
        self.assertNotIn("password_hash", reply["user"])
        claims = jwt.decode(reply["access_token"], self.app.config["JWT_SECRET"], algorithms=["HS256"])
        self.assertEqual(claims["exp"] - claims["iat"], 3600)
        me = self.client.get("/me", headers={"Authorization": "Bearer " + reply["access_token"]}).get_json()
        self.assertEqual(me["role"], "Admin")
        self.assertIn("allocate_funds", me["permissions"])

    def test_bad_credentials_and_tokens(self):
        self.call("POST", "/auth/login", expect=401, json={"identifier": "karan@example.com", "password": "nope"})
        self.call("GET", "/me", expect=401)
        r = self.client.get("/me", headers={"Authorization": "Bearer not-a-token"})
        self.assertEqual(r.status_code, 401)
        expired = jwt.encode({"sub": "U0001", "exp": int(time.time()) - 5}, self.app.config["JWT_SECRET"],
                             algorithm="HS256")
        r = self.client.get("/me", headers={"Authorization": f"Bearer {expired}"})
        self.assertEqual(r.status_code, 401)
        self.assertIn("expired", r.get_json()["error"])
        forged = jwt.encode({"sub": "U0001", "exp": int(time.time()) + 60}, "a-completely-different-secret-key!!", algorithm="HS256")
        self.assertEqual(self.client.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code, 401)

    def test_validation_errors(self):
        body = self.call("POST", "/auth/login", expect=422, json={"identifier": "x"})
        self.assertTrue(any("password" in d for d in body["details"]))
        self.call("POST", "/auth/login", expect=400, data="{oops", content_type="application/json")


class RateLimitTests(ApiTestCase):
    def test_five_failures_per_minute(self):
        for _ in range(5):
            self.call("POST", "/auth/login", expect=401, json={"identifier": "admin@pawconnect.org", "password": "x"})
        r = self.client.post("/auth/login", json={"identifier": "admin@pawconnect.org", "password": "Admin@123"})
        self.assertEqual(r.status_code, 429)          # even the right password waits now
        self.assertIn("Retry-After", r.headers)


class RegistrationTests(ApiTestCase):
    def setUp(self):
        # Every test here comes from 127.0.0.1; start each one with fresh per-IP limits.
        for name in ("otp_sends", "otp_verifies"):
            self.app.extensions["pawconnect"][name]._events.clear()

    FORM = {"name": "Neha Gupta", "email": "neha.api@example.com", "mobile": "9123456781", "role": "Donor",
            "pincode": "201001", "password": "Good@1234", "confirm": "Good@1234"}

    def test_otp_flow(self):
        start = self.call("POST", "/auth/register/start", json=self.FORM)
        self.assertRegex(start["demo_otp"], r"^\d{6}$")
        self.assertIsNone(wf.find_user("neha.api@example.com"))        # nothing saved before the OTP
        wrong = "000000" if start["demo_otp"] != "000000" else "111111"
        self.assertEqual(start["masked_email"], "n•••@example.com")
        self.call("POST", "/auth/register/verify", expect=422, json={"email": self.FORM["email"], "otp": wrong})
        reply = self.call("POST", "/auth/register/verify", expect=201,
                          json={"email": self.FORM["email"], "otp": start["demo_otp"]})
        self.assertEqual(reply["user"]["role"], "Donor")
        self.assertIsNotNone(wf.find_user("neha.api@example.com"))
        # same e-mail again → rejected by check_registration
        self.call("POST", "/auth/register/start", expect=422, json={**self.FORM, "mobile": "9123456782"})

    def test_regex_validation_and_admin_blocked(self):
        body = self.call("POST", "/auth/register/start", expect=422,
                         json={**self.FORM, "mobile": "12345", "pincode": "012345", "role": "Admin"})
        text = " ".join(body["details"])
        self.assertIn("mobile", text)
        self.assertIn("pincode", text)
        self.assertIn("role", text)

    def test_otp_attempts_are_limited(self):
        form = {**self.FORM, "email": "otp.limit@example.com", "mobile": "9123456783"}
        self.call("POST", "/auth/register/start", json=form)
        for _ in range(3):         # OTPManager allows 3 tries per code
            self.call("POST", "/auth/register/verify", expect=422, json={"email": form["email"], "otp": "999999"})
        body = self.call("POST", "/auth/register/verify", expect=422, json={"email": form["email"], "otp": "999999"})
        self.assertIn("Too many", " ".join(body["details"]))

    def test_mobile_is_optional(self):
        form = {**self.FORM, "email": "no.phone@example.com", "mobile": ""}
        start = self.call("POST", "/auth/register/start", json=form)
        reply = self.call("POST", "/auth/register/verify", expect=201,
                          json={"email": form["email"], "otp": start["demo_otp"]})
        self.assertEqual(reply["user"]["mobile"], "")
        # a second account without a mobile is fine too (NULLs never clash)
        other = {**form, "email": "no.phone2@example.com"}
        start = self.call("POST", "/auth/register/start", json=other)
        self.call("POST", "/auth/register/verify", expect=201, json={"email": other["email"], "otp": start["demo_otp"]})

    def test_forgot_password(self):
        unknown = self.call("POST", "/auth/password/forgot", json={"email": "nobody@example.com"})
        known = self.call("POST", "/auth/password/forgot", json={"email": "karan@example.com"})
        self.assertEqual(unknown["message"].split(" uses")[0], known["message"].split(" uses")[0])   # same wording
        self.assertNotIn("demo_otp", unknown)
        body = {"email": "karan@example.com", "otp": known["demo_otp"], "new_password": "weak", "confirm": "weak"}
        self.call("POST", "/auth/password/reset", expect=422, json=body)
        body.update(new_password="Fresh@2026", confirm="Fresh@2026")
        self.call("POST", "/auth/password/reset", json=body)
        self.call("POST", "/auth/password/reset", expect=422, json=body)          # the code works once
        self.call("POST", "/auth/login", json={"identifier": "karan@example.com", "password": "Fresh@2026"})
        actions = set(wf.audit_log(wf.find_user("admin@pawconnect.org"))["action"].head(10))
        self.assertTrue({"PASSWORD_RESET_REQUESTED", "PASSWORD_RESET"} <= actions)


# ======================================================================= permissions
class PermissionTests(ApiTestCase):
    def test_donor_cannot_allocate(self):
        body = self.call("POST", "/funds/allocate", "ananya@example.com", 403, json={
            "case_id": "RC-0001", "amount": "100", "purpose": "Surgery", "source_fund": "General Shelter Fund"})
        self.assertIn("Donor", body["error"])

    def test_role_rules(self):
        case = self.open_case()
        self.call("POST", f"/cases/{case['case_id']}/accept", "karan@example.com", 403)    # citizen
        self.call("POST", f"/cases/{case['case_id']}/accept", "ananya@example.com", 403)   # donor
        self.call("GET", "/cases", "ananya@example.com", 403)
        self.call("GET", "/users", "arjun.rescue@pawconnect.org", 403)
        self.call("GET", "/admin/audit", "riya@example.com", 403)
        self.call("PUT", "/inventory", "karan@example.com", 403, json={"items": []})
        self.call("POST", "/adoption/applications/AP-0003/review", "ananya@example.com", 403,
                  json={"decision": "Approved"})

    def test_each_role_sees_only_its_data(self):
        own = self.call("GET", "/cases", "karan@example.com")
        self.assertTrue(own and all(c["reporter_id"] == "U0009" for c in own))
        queue = self.call("GET", "/cases", "arjun.rescue@pawconnect.org")
        self.assertTrue(all(c["status"] == "Reported" or c["rescuer_id"] == "U0002" for c in queue))
        donations = self.call("GET", "/donations", "ananya@example.com")
        self.assertTrue(donations and all(d["donor_id"] == "U0005" for d in donations))
        everything = self.call("GET", "/donations", "admin@pawconnect.org")
        self.assertGreater(len(everything), len(donations))
        other = next(d for d in everything if d["donor_id"] != "U0005" and d["status"] == "Success")
        self.call("GET", f"/donations/{other['transaction_id']}/receipt", "ananya@example.com", 403)
        users = self.call("GET", "/users", "admin@pawconnect.org")
        self.assertNotIn("password_hash", users[0])


class EmailAdminTests(ApiTestCase):
    def test_status_and_test_mail_are_admin_only_and_hide_the_password(self):
        status = self.call("GET", "/admin/email", "admin@pawconnect.org")
        self.assertIs(status["enabled"], False)               # tests never use real SMTP
        self.assertIn("password_set", status)
        self.assertNotIn("password", {k for k in status if k != "password_set"})
        self.call("GET", "/admin/email", "ananya@example.com", 403)
        self.call("POST", "/admin/email/test", "karan@example.com", 403, json={"to": "x@example.com"})
        result = self.call("POST", "/admin/email/test", "admin@pawconnect.org", json={"to": "check@example.com"})
        self.assertEqual(result["status"], "simulated")
        self.call("POST", "/admin/email/test", "admin@pawconnect.org", 422, json={"to": "not-an-email"})
        recent = self.call("GET", "/admin/email", "admin@pawconnect.org")["recent"]
        self.assertEqual(recent[0]["to"], "check@example.com")
        self.assertNotIn("body", recent[0])


# ======================================================================= concurrency
class RaceTests(ApiTestCase):
    def test_double_accept(self):
        case_id = self.open_case()["case_id"]
        rescuers = ["arjun.rescue@pawconnect.org", "fatima.rescue@pawconnect.org", "rohit.rescue@pawconnect.org"]
        headers = [self.token(email) for email in rescuers]
        barrier, codes = threading.Barrier(len(rescuers)), []

        def press_accept(h):
            client = self.app.test_client()          # one client per thread, like separate phones
            barrier.wait()
            codes.append(client.post(f"/cases/{case_id}/accept", headers=h).status_code)
        threads = [threading.Thread(target=press_accept, args=(h,)) for h in headers]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(codes), [200, 409, 409])
        self.call("POST", f"/cases/{case_id}/accept", rescuers[0], 409)          # and again later

    def test_over_allocation_rejected(self):
        overview = {f["fund"]: f for f in self.call("GET", "/funds/overview", "admin@pawconnect.org")}
        available = Decimal(str(overview["Emergency Feed Fund"]["available"]))
        body = {"case_id": "RC-0001", "purpose": "Food", "source_fund": "Emergency Feed Fund"}
        error = self.call("POST", "/funds/allocate", "admin@pawconnect.org", 409,
                          json={**body, "amount": str(available + 1)})
        self.assertIn("available", error["error"])
        # five admins clicking at once, each asking for 40 %: only two may succeed
        share = (available * Decimal("0.4")).quantize(Decimal("1"))
        h, barrier, codes = self.token("admin@pawconnect.org"), threading.Barrier(5), []

        def allocate():
            client = self.app.test_client()
            barrier.wait()
            codes.append(client.post("/funds/allocate", headers=h, json={**body, "amount": str(share)}).status_code)
        threads = [threading.Thread(target=allocate) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(codes), [201, 201, 409, 409, 409])
        self.assertGreaterEqual(wf.funds_available("Emergency Feed Fund"), 0)


# ======================================================================= payments
class SandboxPaymentTests(ApiTestCase):
    def test_declined_card_is_402(self):
        body = self.call("POST", "/donations", "ananya@example.com", 402, json={
            "amount": "500", "contribution_type": "General Shelter Fund", "method": "Card",
            "card_number": "4000 0000 0000 0002", "expiry": "12/30", "cvv": "123", "card_name": "Ananya Sharma"})
        self.assertIn("declined", body["error"])

    def test_card_never_stored(self):
        reply = self.call("POST", "/donations", "ananya@example.com", 201, json={
            "amount": "750", "contribution_type": "Emergency Feed Fund", "method": "Card",
            "card_number": "4111111111111111", "expiry": "12/30", "cvv": "123", "card_name": "Ananya Sharma"})
        self.assertEqual(reply["donation"]["masked_account"], "Visa •••• 1111")
        export = self.call("GET", "/admin/export/donations", "admin@pawconnect.org").decode()
        self.assertNotIn("4111111111111111", export)
        self.assertNotIn("cvv", json.dumps(reply))

    def test_webhook_signature(self):
        gateway = PaymentGatewaySimulator(secret=PAYMENT_SECRET)
        body, signature = gateway.capture(gateway.create_order(100, "R1"), "UPI", "a@okaxis", "a••@okaxis")
        ok = self.client.post("/payments/webhook", data=body, headers={"X-Razorpay-Signature": signature},
                              content_type="application/json")
        self.assertEqual(ok.status_code, 200)
        tampered = body.replace('"amount":10000', '"amount":1')
        bad = self.client.post("/payments/webhook", data=tampered, headers={"X-Razorpay-Signature": signature},
                               content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        missing = self.client.post("/payments/webhook", data=body, content_type="application/json")
        self.assertEqual(missing.status_code, 400)

    def test_razorpay_needs_keys(self):
        self.assertEqual(self.call("GET", "/payments/config")["gateway"], "sandbox")
        self.call("POST", "/donations", "ananya@example.com", 422, json={
            "amount": "500", "contribution_type": "General Shelter Fund", "method": "Razorpay"})


class _FakeOrders:
    def create(self, data):
        self.last = data
        return {"id": "order_TEST" + data["receipt"][-6:], "amount": data["amount"], "currency": "INR",
                "receipt": data["receipt"], "status": "created"}


class _FakeRazorpayClient:
    """Stands in for razorpay.Client so the tests never call the real API."""
    order = _FakeOrders()


class RazorpayPaymentTests(ApiTestCase):
    razorpay = RazorpayGateway("rzp_test_dummy", "key-secret", "webhook-secret", client=_FakeRazorpayClient())

    def _start(self, amount="1500"):
        reply = self.call("POST", "/donations", "ananya@example.com", 201, json={
            "amount": amount, "contribution_type": "General Shelter Fund", "method": "Razorpay"})
        self.assertEqual(reply["donation"]["status"], "Pending")
        self.assertEqual(_FakeRazorpayClient.order.last["amount"], int(Decimal(amount) * 100))   # paise
        return reply

    def test_checkout_signature(self):
        reply = self._start()
        order_id, tx = reply["checkout"]["order_id"], reply["donation"]["transaction_id"]
        page = self.client.get(reply["checkout"]["url"].replace("http://localhost", ""))
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"checkout.razorpay.com", page.data)
        self.assertNotIn(b"key-secret", page.data)
        forged = {"razorpay_order_id": order_id, "razorpay_payment_id": "pay_FAKE", "razorpay_signature": "0" * 64}
        self.call("POST", "/payments/razorpay/verify", expect=400, json=forged)
        self.assertEqual(wf.get_donation(tx)["status"], "Pending")            # nothing trusted
        good = {**forged, "razorpay_signature": self.razorpay.sign_checkout(order_id, "pay_FAKE")}
        self.assertEqual(self.call("POST", "/payments/razorpay/verify", json=good)["status"], "Success")
        self.assertIn("PawConnect", self.call("GET", f"/donations/{tx}/receipt", "ananya@example.com")["receipt"])

    def test_webhook(self):
        reply = self._start("2200")
        order_id, tx = reply["checkout"]["order_id"], reply["donation"]["transaction_id"]
        event = {"event": "payment.captured",
                 "payload": {"payment": {"entity": {"id": "pay_WH1", "order_id": order_id, "amount": 220000}}}}
        raw = json.dumps(event).encode()
        signature = hmac.new(b"webhook-secret", raw, hashlib.sha256).hexdigest()
        tampered = raw.replace(b"220000", b"1")
        r = self.client.post("/payments/webhook", data=tampered, headers={"X-Razorpay-Signature": signature},
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(wf.get_donation(tx)["status"], "Pending")
        r = self.client.post("/payments/webhook", data=raw, headers={"X-Razorpay-Signature": signature},
                             content_type="application/json")
        self.assertEqual(r.get_json()["status"], "Success")
        # the same webhook delivered twice changes nothing
        r = self.client.post("/payments/webhook", data=raw, headers={"X-Razorpay-Signature": signature},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(wf.get_donation(tx)["status"], "Success")


# ======================================================================= full story
class FullFlowTests(ApiTestCase):
    def test_citizen_rescuer_donor_admin(self):
        citizen, rescuer = "karan@example.com", "arjun.rescue@pawconnect.org"
        donor, admin = "ananya@example.com", "admin@pawconnect.org"
        # 1. citizen reports an injured dog with a photo
        case = self.open_case()
        case_id = case["case_id"]
        self.call("POST", f"/cases/{case_id}/photo", citizen, 200, content_type="multipart/form-data",
                  data={"photo": (io.BytesIO(b"\x89PNG fake"), "dog.png")})
        self.call("POST", f"/cases/{case_id}/photo", citizen, 422, content_type="multipart/form-data",
                  data={"photo": (io.BytesIO(b"MZ"), "virus.exe")})
        self.assertEqual(self.call("GET", f"/cases/{case_id}/photo", citizen), b"\x89PNG fake")
        # 2. the rescuer sees it in the queue, accepts and moves it on
        self.assertIn(case_id, [c["case_id"] for c in self.call("GET", "/cases", rescuer)])
        self.assertEqual(self.call("POST", f"/cases/{case_id}/accept", rescuer)["status"], "Assigned")
        self.call("POST", f"/cases/{case_id}/advance", rescuer, json={"note": "Picked up"})
        updated = self.call("POST", f"/cases/{case_id}/advance", rescuer, json={"note": "At the clinic"})
        self.assertEqual(updated["status"], "Sheltered/In Treatment")
        self.call("POST", f"/cases/{case_id}/notes", rescuer, json={"note": "X-ray done", "estimated_cost": 9000})
        self.call("POST", f"/cases/{case_id}/advance", "fatima.rescue@pawconnect.org", 403)   # not hers
        # 3. a donor pays for this dog's treatment
        gift = self.call("POST", "/donations", donor, 201, json={
            "amount": "2,500", "contribution_type": "Specific Medical Case", "case_id": case_id,
            "method": "UPI", "upi": "ananya@okaxis"})
        self.assertEqual(gift["donation"]["amount"], "2500.00")
        self.assertIn("80G", self.call("GET", f"/donations/{gift['donation']['transaction_id']}/receipt", donor)["receipt"])
        # 4. the admin tops it up from the general fund and approves an adoption
        allocation = self.call("POST", "/funds/allocate", admin, 201, json={
            "case_id": case_id, "amount": "3000", "purpose": "Surgery", "source_fund": "General Shelter Fund"})
        self.assertEqual(allocation["amount"], "3000.00")
        funding = {r["case_id"]: r for r in self.call("GET", "/funds/case-funding", admin)}
        self.assertEqual(funding[case_id]["total_funded"], 5500.0)
        animal_id = self.call("GET", "/animals?available=true", citizen)[0]["animal_id"]
        best = {k: list(q["options"])[0] for k, q in self.call("GET", "/adoption/questionnaire", citizen).items()}
        application = self.call("POST", "/adoption/applications", citizen, 201,
                                json={"animal_id": animal_id, "answers": best, "reason": "Big garden"})
        self.assertEqual(application["status"], "Pre-Approved")
        self.call("POST", f"/adoption/applications/{application['application_id']}/review", admin,
                  json={"decision": "Approved"})
        self.call("POST", f"/adoption/applications/{application['application_id']}/review", admin, 409,
                  json={"decision": "Rejected"})
        self.assertNotIn(animal_id, [a["animal_id"] for a in self.call("GET", "/animals?available=true", citizen)])
        # 5. everything is in the audit log and the stats
        actions = {e["action"] for e in self.call("GET", "/admin/audit", admin)[:30]}
        self.assertTrue({"SOS_REPORTED", "CASE_ACCEPTED", "DONATION_SUCCESS", "FUNDS_ALLOCATED",
                         "ADOPTION_APPROVED"} <= actions)
        self.assertIn(b"<auditLog", self.call("GET", "/admin/audit.xml", admin))
        summary = self.call("GET", "/analytics/summary", donor)
        self.assertGreater(summary["money"]["total"], 0)
        self.assertIn("recovery_rate", summary)
        self.assertTrue(summary["monthly_donations"])

    def test_inventory_round_trip(self):
        items = self.call("GET", "/inventory", "admin@pawconnect.org")
        self.assertIn("low_stock", items[0])
        items = [{k: v for k, v in i.items() if k not in ("low_stock", "updated_at")} for i in items]
        items.append({"item": "Bandages", "category": "Medical supply", "quantity": 12, "unit": "rolls",
                      "reorder_level": 5})
        saved = self.call("PUT", "/inventory", "admin@pawconnect.org", json={"items": items})
        self.assertEqual(saved["saved"], len(items))
        items[0]["quantity"] = -1
        self.call("PUT", "/inventory", "admin@pawconnect.org", 422, json={"items": items})


# ======================================================================= the client class
class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers.fresh_demo_data()

    def test_local_mode_client(self):
        client = PawConnectClient(mode="local")
        self.assertEqual(client.mode, "local")
        client.login("admin@pawconnect.org", "Admin@123")
        self.assertEqual(client.me()["role"], "Admin")
        cases = client.cases()
        self.assertEqual(list(cases.columns)[0], "case_id")
        self.assertGreater(len(cases), 40)
        self.assertEqual(client.funds_overview().loc["General Shelter Fund", "allocatable"], True)
        summary = client.summary()
        self.assertEqual(summary["monthly_donations"].index.dtype.kind, "M")     # datetime index for charts
        donor = PawConnectClient(mode="local")
        donor.login("ananya@example.com", "Donor@123")
        with self.assertRaises(Forbidden):
            donor.allocate("RC-0001", 100, "Surgery", "General Shelter Fund")
        with self.assertRaises(InvalidInput) as ctx:
            donor.donate("5", "General Shelter Fund", "UPI", {"upi": "ananya@okaxis"})
        self.assertTrue(ctx.exception.problems)
        with self.assertRaises(ConflictError):
            client.allocate("RC-0001", 10_000_000, "Surgery", "General Shelter Fund")

    def test_http_mode_reports_unreachable_server(self):
        from api.client import ServerUnavailable
        client = PawConnectClient(base_url="http://127.0.0.1:9", mode="api", timeout=1)
        with self.assertRaises(ServerUnavailable) as ctx:
            client.health()
        self.assertIn("python main.py --api", " ".join(ctx.exception.problems))


if __name__ == "__main__":
    unittest.main()
