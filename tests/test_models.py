import unittest

from tests import helpers  # noqa: F401
from core.models import (MAX_SCORE, QUESTIONNAIRE, Admin, Adopter, AdoptionApplication, Citizen,
                         DonationTransaction, RescueCase, User, hash_password, verify_password)


class UserTests(unittest.TestCase):
    def test_user_is_abstract(self):
        with self.assertRaises(TypeError):
            User("U1", "A", "a@b.com", "9876543210", "201001")

    def test_inheritance_and_permissions(self):
        adopter = Adopter("U1", "Riya", "r@x.com", "9876543210", "201001")
        self.assertIsInstance(adopter, Citizen)
        self.assertTrue(adopter.can("report_sos"))          # inherited from Citizen
        self.assertTrue(adopter.can("track_applications"))
        admin = Admin("U2", "Meera", "m@x.com", "9876543211", "201001")
        self.assertTrue(admin.can("allocate_funds") and admin.can("accept_case") and admin.can("donate"))
        self.assertFalse(adopter.can("allocate_funds"))

    def test_round_trip_and_password(self):
        user = Citizen("U1", "Karan Malhotra", "k@x.com", "9876543210", "201001")
        user.set_password("Secret@123")
        clone = User.from_dict(user.to_dict())
        self.assertIsInstance(clone, Citizen)
        self.assertTrue(clone.check_password("Secret@123"))
        self.assertFalse(clone.check_password("secret@123"))
        self.assertNotIn("password_hash", clone.public_dict())

    def test_hash_is_salted(self):
        self.assertNotEqual(hash_password("Same@123", iterations=1000), hash_password("Same@123", iterations=1000))
        self.assertFalse(verify_password("x", "not-a-hash"))


class RescueCaseTests(unittest.TestCase):
    def test_status_flow(self):
        case = RescueCase("RC-1", "U1", "Dog", "Critical", "Hit by car", "201001")
        self.assertEqual(case.estimated_cost, "15000")
        with self.assertRaises(ValueError):
            case.advance()                                  # needs a rescuer
        self.assertEqual(case.advance(rescuer_id="U2"), "Assigned")
        self.assertTrue(case.assigned_at)
        for expected in ["In Transit", "Sheltered/In Treatment", "Recovered"]:
            self.assertEqual(case.advance(), expected)
        self.assertIsNone(case.next_status())
        with self.assertRaises(ValueError):
            case.advance()

    def test_notes(self):
        case = RescueCase("RC-1", "U1", "Cat", "Low", "Eye infection", "201001")
        case.add_note("Drops given", "Arjun")
        case.add_note("Better", "Arjun")
        self.assertEqual(len(case.notes_list()), 2)


class ScoringTests(unittest.TestCase):
    def test_max_score_is_100(self):
        self.assertEqual(MAX_SCORE, 100)

    def test_preapproval_threshold(self):
        best = {k: list(q["options"])[0] for k, q in QUESTIONNAIRE.items()}
        worst = {k: list(q["options"])[-1] for k, q in QUESTIONNAIRE.items()}
        good = AdoptionApplication("AP-1", "U1", "Riya", "A001", **best)
        poor = AdoptionApplication("AP-2", "U1", "Riya", "A001", **worst)
        self.assertEqual((good.score, good.status), ("100", "Pre-Approved"))
        self.assertEqual(poor.status, "Under Review")
        self.assertLess(int(poor.score), 65)

    def test_donation_id_format(self):
        self.assertRegex(DonationTransaction.new_id(), r"^PC-DON-\d{8}-[0-9A-F]{6}$")


if __name__ == "__main__":
    unittest.main()
