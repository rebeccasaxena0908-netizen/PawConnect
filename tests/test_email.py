"""E-mail notifications with a fake SMTP server (nothing is ever really sent)."""
import json
import smtplib
import unittest
from unittest import mock

from tests import helpers
import config
from core import workflows as wf
from services import email_service
from services.notification_service import OTPLimitError, OTPManager


class FakeSMTP:
    """Stands in for smtplib.SMTP and remembers every message 'sent'."""
    sent: list = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        if FakeSMTP.fail_with:
            raise FakeSMTP.fail_with

    def send_message(self, message):
        FakeSMTP.sent.append(message)


def body_text(message) -> str:
    return message.get_body(preferencelist=("plain",)).get_content()


def body_html(message) -> str:
    return message.get_body(preferencelist=("html",)).get_content()


class EmailTestCase(unittest.TestCase):
    """Real-mail mode (EMAIL_ENABLED=True) but with the fake server."""

    def setUp(self):
        FakeSMTP.sent, FakeSMTP.fail_with = [], None
        patches = [mock.patch.object(config, "EMAIL_ENABLED", True),
                   mock.patch.object(config, "SMTP_USER", "shelter@gmail.com"),
                   mock.patch.object(config, "SMTP_PASSWORD", "app-password-123"),
                   mock.patch.object(config, "SMTP_FROM", "PawConnect <shelter@gmail.com>"),
                   mock.patch.object(smtplib, "SMTP", FakeSMTP)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        config.OUTBOX_LOG.unlink(missing_ok=True)

    def outbox(self) -> str:
        return config.OUTBOX_LOG.read_text(encoding="utf-8") if config.OUTBOX_LOG.exists() else ""


class OtpEmailTests(EmailTestCase):
    def test_otp_goes_to_the_address_with_the_code(self):
        otp = OTPManager()
        code = wf.send_signup_otp(otp, "Riya.New@Example.com")
        self.assertEqual(len(FakeSMTP.sent), 1)                     # sent exactly once
        message = FakeSMTP.sent[0]
        self.assertEqual(message["To"], "riya.new@example.com")
        self.assertEqual(message["From"], "PawConnect <shelter@gmail.com>")
        self.assertIn(code, body_text(message))
        self.assertIn(" ".join(code), body_html(message))          # big spaced code in the HTML
        self.assertIn("expires in 5 minutes", body_text(message))
        self.assertNotIn(code, message["Subject"])
        self.assertNotIn(code, self.outbox())                       # the log never holds the code
        self.assertNotIn("app-password-123", self.outbox())
        wf.verify_signup_otp(otp, "riya.new@example.com", code)
        with self.assertRaises(wf.ValidationError):
            wf.verify_signup_otp(otp, "riya.new@example.com", code)   # single use

    def test_resend_cooldown_and_hourly_limit(self):
        otp = OTPManager()
        wf.send_signup_otp(otp, "limit@example.com")
        with self.assertRaises(wf.ValidationError) as ctx:
            wf.send_signup_otp(otp, "limit@example.com")             # within 30 s
        self.assertIn("wait", ctx.exception.problems[0])
        self.assertEqual(len(FakeSMTP.sent), 1)                     # nothing sent twice
        clock = [1_000_000.0]
        with mock.patch("services.notification_service.time.time", lambda: clock[0]):
            fresh = OTPManager()
            for _ in range(5):
                fresh.generate("signup:x@example.com", address="x@example.com")
                clock[0] += 31
            with self.assertRaises(OTPLimitError) as ctx:
                fresh.generate("reset:x@example.com", address="x@example.com")   # limit is per address
            self.assertIn("Too many codes", str(ctx.exception))
            clock[0] += 3600
            fresh.generate("signup:x@example.com", address="x@example.com")   # an hour later it works again

    def test_failure_returns_ok_false(self):
        FakeSMTP.fail_with = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
        result = email_service.send_email("a@example.com", "Hi", "text")
        self.assertFalse(result["ok"])
        self.assertIn("app password", result["error"])
        otp = OTPManager()
        with self.assertRaises(wf.DeliveryFailed):                  # the UI can say "try again"
            wf.send_signup_otp(otp, "b@example.com")
        self.assertIn("failed", self.outbox())

    def test_network_failure(self):
        FakeSMTP.fail_with = OSError("Network is unreachable")
        result = email_service.send_email("a@example.com", "Hi", "text")
        self.assertEqual((result["ok"], result["status"]), (False, "failed"))
        self.assertIn("network", result["error"])


class TemplateTests(EmailTestCase):
    def test_html_escaping(self):
        nasty = '<script>alert("x")</script> Riya'
        subject, text, html = email_service.welcome_email(nasty, "Adopter")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        _s, _t, html = email_service.adoption_email("Riya", "AP-0009", "<b>Bruno</b>", "Approved")
        self.assertIn("&lt;b&gt;Bruno&lt;/b&gt;", html)

    def test_receipt_and_updates(self):
        donation = {"transaction_id": "PC-DON-20261027-ABCDEF", "timestamp": "2026-10-27 10:00:00",
                    "donor_name": "Ananya Sharma", "donor_email": "ananya@example.com", "amount": "123456.50",
                    "contribution_type": "Specific Medical Case", "case_id": "RC-0012", "method": "UPI",
                    "masked_account": "an••••@okaxis", "payment_ref": "pay_1", "status": "Success"}
        subject, text, html = email_service.receipt_email(donation)
        for part in ("₹1,23,456.50", "RC-0012", "an••••@okaxis", "80G", "Sandbox payment"):
            self.assertIn(part, html)
        self.assertIn("₹1,23,456.50", text)
        subject, _t, _h = email_service.case_update_email("Karan", "RC-0012", "In Transit")
        self.assertEqual(subject, "Your report RC-0012 is now In Transit")
        for status in ("Pre-Approved", "Approved", "Rejected"):
            subject, _t, html = email_service.adoption_email("Riya", "AP-1", "Bruno", status)
            self.assertIn(status, subject)


class WorkflowEmailTests(EmailTestCase):
    @classmethod
    def setUpClass(cls):
        helpers.fresh_demo_data()

    def _wait_for_mail(self):
        email_service.flush()                                  # let the background sends finish

    def test_sos_update_goes_to_the_reporter(self):
        citizen, rescuer = wf.find_user("karan@example.com"), wf.find_user("arjun.rescue@pawconnect.org")
        case = wf.create_rescue_case(citizen, "Dog", "Low", "Dog with a small cut", "201001", use_network=False)
        wf.accept_case(case.case_id, rescuer)
        wf.advance_case(case.case_id, rescuer, "Picked up")
        self._wait_for_mail()
        update = [m for m in FakeSMTP.sent if case.case_id in m["Subject"]]
        self.assertEqual(len(update), 1)
        self.assertEqual(update[0]["To"], "karan@example.com")
        self.assertEqual(update[0]["Subject"], f"Your report {case.case_id} is now In Transit")

    def test_donation_receipt_by_email(self):
        donor = wf.find_user("ananya@example.com")
        tx, receipt = wf.make_donation(donor, 500, "General Shelter Fund", "UPI", {"upi": "ananya@okaxis"})
        self._wait_for_mail()
        mails = [m for m in FakeSMTP.sent if tx.transaction_id in m["Subject"]]
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0]["To"], "ananya@example.com")
        self.assertIn("₹500.00", body_text(mails[0]))

    def test_no_sms_any_more(self):
        from services import sms_service
        with self.assertRaises(NotImplementedError):
            sms_service.send_sms("9810000001", "hi")
        source = (helpers.ROOT / "core" / "workflows.py").read_text()
        self.assertNotIn("send_sms", source)


class SimulatedModeTests(unittest.TestCase):
    """EMAIL_ENABLED=False (the default without .env): nothing is sent, a line goes to the outbox."""

    def test_falls_back_to_outbox(self):
        config.OUTBOX_LOG.unlink(missing_ok=True)
        with mock.patch.object(config, "EMAIL_ENABLED", False), \
                mock.patch.object(smtplib, "SMTP", side_effect=AssertionError("must not connect")):
            otp = OTPManager()
            code = wf.send_signup_otp(otp, "demo@example.com")
        lines = [json.loads(line) for line in config.OUTBOX_LOG.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(lines[-1]["to"], "demo@example.com")
        self.assertIn("simulated", lines[-1]["status"])
        self.assertNotIn(code, config.OUTBOX_LOG.read_text(encoding="utf-8"))
        self.assertTrue(config.SHOW_OTP_ON_SCREEN)                  # demo mode shows the code instead


if __name__ == "__main__":
    unittest.main()
