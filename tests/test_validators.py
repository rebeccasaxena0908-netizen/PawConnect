import unittest
from datetime import date

from tests import helpers  # noqa: F401  (sets up the temp data folder)
from core import validators as v


class RegexTests(unittest.TestCase):
    def test_mobile(self):
        for good in ["9876543210", "6000000000", "+91 98765 43210", "098765-43210"]:
            self.assertTrue(v.is_valid("mobile", good), good)
        for bad in ["5876543210", "987654321", "98765432100", "abcdefghij"]:
            self.assertFalse(v.is_valid("mobile", bad), bad)

    def test_email(self):
        self.assertTrue(v.is_valid("email", "Riya.B+pets@Example.co.in"))
        for bad in ["riya@", "@example.com", "riya example.com", "riya@example"]:
            self.assertFalse(v.is_valid("email", bad), bad)

    def test_upi(self):
        for good in ["ananya@okaxis", "a.b-c_d@ybl", "98765@paytm"]:
            self.assertTrue(v.is_valid("upi", good), good)
        for bad in ["a@okaxis1", "x@", "@okaxis", "a@b"]:
            self.assertFalse(v.is_valid("upi", bad), bad)

    def test_pincode(self):
        self.assertTrue(v.is_valid("pincode", "201001"))
        for bad in ["012345", "20100", "2010011", "20100a"]:
            self.assertFalse(v.is_valid("pincode", bad), bad)

    def test_password_rules(self):
        self.assertEqual(v.password_problems("Admin@123"), [])
        self.assertIn("one symbol such as @ or #", v.password_problems("Admin1234"))
        self.assertEqual(len(v.password_problems("abc")), 4)


class CardTests(unittest.TestCase):
    def test_luhn(self):
        self.assertTrue(v.luhn_check("4111 1111 1111 1111"))
        self.assertTrue(v.luhn_check("4000000000000002"))
        self.assertFalse(v.luhn_check("4111111111111112"))

    def test_expiry(self):
        today = date(2026, 10, 27)
        self.assertTrue(v.expiry_ok("10/26", today))
        self.assertTrue(v.expiry_ok("01/30", today))
        self.assertFalse(v.expiry_ok("09/26", today))
        self.assertFalse(v.expiry_ok("13/27", today))

    def test_masking(self):
        self.assertEqual(v.mask_card("4111111111111111"), "Visa •••• 1111")
        self.assertEqual(v.mask_upi("ananya@okaxis"), "an••••@okaxis")
        self.assertEqual(v.mask_mobile("9876543210"), "98••••••10")


class SanitizeTests(unittest.TestCase):
    def test_strips_html_and_formulas(self):
        self.assertEqual(v.sanitize_text("<b>Hurt</b>   dog\n"), "Hurt dog")
        self.assertEqual(v.sanitize_text("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(len(v.sanitize_text("x" * 900, 50)), 50)

    def test_safe_filename(self):
        self.assertEqual(v.safe_filename("../../etc/passwd"), "etc_passwd")


if __name__ == "__main__":
    unittest.main()
