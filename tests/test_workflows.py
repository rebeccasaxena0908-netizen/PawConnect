"""End-to-end business rules on a temporary copy of the demo data."""
import json
import unittest

from tests import helpers
from analytics import data_handler as dh
from analytics import pandas_engine as pe
from core import workflows as wf
from services.api_service import PaymentGatewaySimulator, offline_location
from services.notification_service import OTPManager, format_inr


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers.fresh_demo_data()
        cls.admin = wf.find_user("admin@pawconnect.org")
        cls.citizen = wf.find_user("karan@example.com")
        cls.rescuer = wf.find_user("arjun.rescue@pawconnect.org")
        cls.donor = wf.find_user("9810000005")             # login by mobile works too

    def test_login(self):
        self.assertIsNotNone(wf.authenticate("ADMIN@pawconnect.org", "Admin@123"))
        self.assertIsNone(wf.authenticate("admin@pawconnect.org", "wrong"))

    def test_registration_rules(self):
        with self.assertRaises(wf.ValidationError) as ctx:
            wf.check_registration("A", "bad", "123", "Admin", "012345", "weak")
        self.assertGreaterEqual(len(ctx.exception.problems), 5)
        with self.assertRaises(wf.ValidationError):        # duplicate e-mail
            wf.check_registration("New Person", "karan@example.com", "9123456780", "Citizen", "201001", "Good@1234")
        user = wf.register_user("Neha Gupta", "neha@example.com", "9123456780", "Donor", "201001", "Good@1234")
        self.assertEqual(user.role, "Donor")
        self.assertTrue(user.user_id.startswith("U"))

    def test_rescue_flow(self):
        case = wf.create_rescue_case(self.citizen, "Dog", "Critical", "Dog bleeding near the gate",
                                     "201001", "Gate 2", photo_bytes=b"fake", photo_name="dog.png",
                                     use_network=False)
        self.assertEqual(case.status, "Reported")
        self.assertTrue(case.latitude and case.photo_path.endswith(".png"))
        with self.assertRaises(wf.ValidationError):
            wf.advance_case(case.case_id, self.rescuer)     # not accepted yet
        wf.accept_case(case.case_id, self.rescuer)
        with self.assertRaises(wf.ValidationError):
            wf.accept_case(case.case_id, self.rescuer)      # can't take twice
        updated = wf.advance_case(case.case_id, self.rescuer, "Picked up")
        self.assertEqual(updated.status, "In Transit")
        other = wf.find_user("fatima.rescue@pawconnect.org")
        with self.assertRaises(wf.PermissionDenied):
            wf.advance_case(case.case_id, other)
        with self.assertRaises(wf.PermissionDenied):
            wf.accept_case(case.case_id, self.donor)        # donors can't rescue

    def test_sos_validation(self):
        with self.assertRaises(wf.ValidationError):
            wf.create_rescue_case(self.citizen, "Dog", "Severe", "short", "012345", use_network=False)

    def test_donation_success_and_decline(self):
        before = len(dh.load_table("donations"))
        tx, receipt = wf.make_donation(self.donor, "2,500", "General Shelter Fund", "Card",
                                       {"card_number": "4111 1111 1111 1111", "expiry": "12/30",
                                        "cvv": "123", "card_name": "Ananya Sharma"})
        self.assertTrue(tx.succeeded)
        self.assertIn("₹2,500.00", receipt)
        saved = dh.find_row("donations", "transaction_id", tx.transaction_id)
        self.assertEqual(saved["masked_account"], "Visa •••• 1111")
        self.assertNotIn("4111111111111111", dh.table_to_csv_bytes("donations").decode())
        with self.assertRaises(wf.ValidationError):
            wf.make_donation(self.donor, 500, "General Shelter Fund", "UPI", {"upi": "fail@upi"})
        # both test donations share the same second, so look at the newest two rows
        self.assertIn("Failed", set(dh.load_table("donations").tail(2)["status"]))
        self.assertEqual(len(dh.load_table("donations")), before + 2)
        with self.assertRaises(wf.ValidationError):
            wf.make_donation(self.donor, 500, "Specific Medical Case", "UPI", {"upi": "a@okaxis"})

    def test_allocation_limits(self):
        available = wf.funds_available("General Shelter Fund")
        case_id = dh.load_table("rescue_cases").query("status == 'Sheltered/In Treatment'")["case_id"].iloc[0]
        with self.assertRaises(wf.ValidationError):
            wf.allocate_funds(self.admin, case_id, available + 1, "Surgery", "General Shelter Fund")
        wf.allocate_funds(self.admin, case_id, 1000, "Surgery", "General Shelter Fund")
        self.assertAlmostEqual(wf.funds_available("General Shelter Fund"), available - 1000, places=2)
        with self.assertRaises(wf.PermissionDenied):
            wf.allocate_funds(self.donor, case_id, 10, "Surgery", "General Shelter Fund")

    def test_adoption_flow(self):
        animal_id = wf.available_animals()["animal_id"].iloc[-1]
        best = {k: list(q["options"])[0] for k, q in wf.QUESTIONNAIRE.items()}
        app = wf.submit_application(self.citizen, animal_id, best, "Lots of love")
        self.assertEqual(app.status, "Pre-Approved")
        with self.assertRaises(wf.ValidationError):
            wf.submit_application(self.citizen, animal_id, best)        # duplicate
        wf.review_application(self.admin, app.application_id, "Approved")
        self.assertEqual(dh.find_row("animals", "animal_id", animal_id)["status"], "Adopted")
        with self.assertRaises(wf.ValidationError):
            wf.submit_application(self.citizen, animal_id, best)        # no longer available

    def test_offline_import(self):
        imported, skipped = wf.import_offline_cases(self.admin, helpers.ROOT / "data" / "sample_offline_cases.csv")
        self.assertEqual(imported, 4)
        self.assertEqual(len(skipped), 2)

    def test_audit_log_and_xml(self):
        log = dh.read_audit_log()
        self.assertGreater(len(log), 100)
        self.assertIn("SOS_REPORTED", set(log["action"]))
        xml = dh.table_to_xml_bytes("users").decode()
        self.assertIn("<users", xml)
        self.assertNotIn("password_hash", xml)
        frame = dh.parse_xml_records(__import__("io").BytesIO(dh.table_to_xml_bytes("animals")))
        self.assertEqual(len(frame), len(dh.load_table("animals")))

    def test_inventory_save_validation(self):
        inv = dh.load_table("inventory")
        bad = inv.copy()
        bad.loc[0, "quantity"] = "-3"
        with self.assertRaises(wf.ValidationError):
            wf.save_inventory(self.admin, bad)
        new = inv.copy()
        new.loc[len(new)] = ["", "Bandages", "Medical supply", "12", "rolls", "5", ""]
        self.assertEqual(wf.save_inventory(self.admin, new), len(inv) + 1)
        self.assertTrue(dh.load_table("inventory")["item_id"].iloc[-1].startswith("INV-"))

    def test_case_funding(self):
        table = pe.case_funding_table(dh.load_table("rescue_cases"), dh.load_table("donations"),
                                      dh.load_table("allocations"))
        self.assertTrue((table["percent_funded"].between(0, 100)).all())
        self.assertTrue((table["gap"] >= 0).all())


class ServiceTests(unittest.TestCase):
    def test_otp(self):
        otp = OTPManager(ttl=60, max_attempts=2)
        code = otp.generate("9876543210")
        self.assertRegex(code, r"^\d{6}$")
        self.assertFalse(otp.verify("9876543210", "000000" if code != "000000" else "111111")[0])
        self.assertTrue(otp.verify("9876543210", code)[0])
        self.assertFalse(otp.verify("9876543210", code)[0])   # single use

    def test_gateway_signature(self):
        gateway = PaymentGatewaySimulator(secret="s3cret")
        order = gateway.create_order(499.5, "R1")
        self.assertEqual(order["amount"], 49950)
        body, signature = gateway.capture(order, "UPI", "a@okaxis", "a••@okaxis")
        self.assertTrue(gateway.verify_signature(body, signature))
        tampered = body.replace("49950", "1")
        self.assertFalse(gateway.verify_signature(tampered, signature))
        self.assertEqual(json.loads(body)["event"], "payment.captured")
        self.assertEqual(gateway.parse_webhook(body)["amount"], 499.5)

    def test_offline_geocode_and_inr(self):
        location = offline_location("201001")
        self.assertIn("Uttar Pradesh", location["state"])
        self.assertEqual(format_inr(1234567.5), "₹12,34,567.50")
        self.assertEqual(format_inr(999), "₹999.00")


if __name__ == "__main__":
    unittest.main()
