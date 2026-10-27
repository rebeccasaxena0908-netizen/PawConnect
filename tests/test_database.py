"""Database layer: constraints, exact money, transactions and race conditions (temp SQLite file)."""
import threading
import unittest
from decimal import Decimal
from unittest import mock

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests import helpers
import config
from analytics import data_handler as dh
from core import workflows as wf
from db.tables import TABLES


def run_together(functions):
    """Start every function at the same instant in its own thread; return (results, errors)."""
    barrier = threading.Barrier(len(functions))
    results, errors = [], []

    def worker(fn):
        barrier.wait()
        try:
            results.append(fn())
        except Exception as error:      # noqa: BLE001 – we inspect the errors in the test
            errors.append(error)
    threads = [threading.Thread(target=worker, args=(fn,)) for fn in functions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results, errors


class DatabaseSetupTests(unittest.TestCase):
    def test_uses_temporary_database(self):
        self.assertIn(helpers.TEMP_DATA, config.DATABASE_URL)
        self.assertNotIn(str(config.BASE_DIR / "data" / "pawconnect.db"), config.DATABASE_URL)

    def test_tables_match_schemas(self):
        for name, columns in config.SCHEMAS.items():
            self.assertEqual([c.name for c in TABLES[name].columns], columns, name)

    def test_migration_matches_models(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from db.tables import metadata
        dh.ensure_files()
        with dh.reading() as conn:
            context = MigrationContext.configure(conn, opts={"compare_type": True})
            self.assertEqual(compare_metadata(context, metadata), [])


class ConstraintTests(unittest.TestCase):
    def setUp(self):
        helpers.fresh_demo_data()

    def _insert_fails(self, name, row):
        with self.assertRaises(IntegrityError):
            dh.append_row(name, row)

    def test_foreign_keys(self):
        donation = dh.load_table("donations").iloc[0].to_dict()
        self._insert_fails("donations", {**donation, "transaction_id": "PC-DON-X1", "donor_id": "U9999"})
        allocation = dh.load_table("allocations").iloc[0].to_dict()
        self._insert_fails("allocations", {**allocation, "allocation_id": "AL-9999", "case_id": "RC-9999"})
        case = dh.load_table("rescue_cases").iloc[0].to_dict()
        self._insert_fails("rescue_cases", {**case, "case_id": "RC-9999", "reporter_id": "U9999"})

    def test_unique_email_and_mobile(self):
        user = dh.load_table("users").iloc[0].to_dict()
        self._insert_fails("users", {**user, "user_id": "U9999", "mobile": "9999999999"})   # same e-mail
        self._insert_fails("users", {**user, "user_id": "U9999", "email": "new@example.com"})

    def test_check_constraints(self):
        case = dh.load_table("rescue_cases").iloc[0].to_dict()
        self._insert_fails("rescue_cases", {**case, "case_id": "RC-9998", "status": "Lost"})
        self._insert_fails("rescue_cases", {**case, "case_id": "RC-9998", "injury_level": "Severe"})
        self._insert_fails("rescue_cases", {**case, "case_id": "RC-9998", "status": "Assigned", "rescuer_id": ""})
        donation = dh.load_table("donations").iloc[0].to_dict()
        self._insert_fails("donations", {**donation, "transaction_id": "PC-DON-X2", "amount": "-5"})
        self._insert_fails("donations", {**donation, "transaction_id": "PC-DON-X3",
                                         "contribution_type": "Specific Medical Case", "case_id": ""})

    def test_not_null(self):
        case = dh.load_table("rescue_cases").iloc[0].to_dict()
        self._insert_fails("rescue_cases", {**case, "case_id": "RC-9997", "description": ""})

    def test_money_is_exact_integer_paise(self):
        donor = wf.find_user("ananya@example.com")
        before = wf.funds_available("Emergency Feed Fund")
        for _ in range(10):        # 10 × ₹10.10 must be exactly ₹101.00 (floats would drift)
            wf.make_donation(donor, "10.10", "Emergency Feed Fund", "UPI", {"upi": "ananya@okaxis"})
        self.assertEqual(wf.funds_available("Emergency Feed Fund") - before, Decimal("101.00"))
        with dh.reading() as conn:
            raw = conn.execute(text("SELECT amount FROM donations WHERE amount = 1010")).fetchall()
        self.assertEqual(len(raw), 10)                       # stored as 1010 paise
        self.assertEqual(dh.find_row("donations", "amount", "10.10")["amount"], "10.10")


class TransactionTests(unittest.TestCase):
    def setUp(self):
        helpers.fresh_demo_data()
        self.admin = wf.find_user("admin@pawconnect.org")
        self.donor = wf.find_user("ananya@example.com")

    def test_donation_rolls_back_if_audit_fails(self):
        before = len(dh.load_table("donations"))
        with mock.patch.object(dh, "log_event", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                wf.make_donation(self.donor, 500, "General Shelter Fund", "UPI", {"upi": "ananya@okaxis"})
        self.assertEqual(len(dh.load_table("donations")), before)

    def test_allocation_rolls_back_if_a_step_fails(self):
        case_id = dh.load_table("rescue_cases").query("status == 'In Transit'")["case_id"].iloc[0]
        before_allocations = len(dh.load_table("allocations"))
        before_notes = wf.load_case(case_id).medical_notes
        with mock.patch.object(dh, "log_event", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                wf.allocate_funds(self.admin, case_id, 100, "Medicines", "General Shelter Fund")
        self.assertEqual(len(dh.load_table("allocations")), before_allocations)
        self.assertEqual(wf.load_case(case_id).medical_notes, before_notes)

    def test_review_rolls_back_if_a_step_fails(self):
        apps = dh.load_table("adoption_applications")
        pending = apps[apps["status"].isin(["Pre-Approved", "Under Review"])].iloc[0]
        with mock.patch.object(dh, "log_event", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                wf.review_application(self.admin, pending["application_id"], "Approved")
        self.assertEqual(dh.find_row("adoption_applications", "application_id",
                                     pending["application_id"])["status"], pending["status"])
        self.assertEqual(dh.find_row("animals", "animal_id", pending["animal_id"])["status"], "Available")


class RaceConditionTests(unittest.TestCase):
    def setUp(self):
        helpers.fresh_demo_data()
        self.admin = wf.find_user("admin@pawconnect.org")
        self.citizen = wf.find_user("karan@example.com")
        self.rescuers = [wf.find_user(e) for e in ("arjun.rescue@pawconnect.org",
                                                   "fatima.rescue@pawconnect.org",
                                                   "rohit.rescue@pawconnect.org")]

    def test_only_one_rescuer_can_accept(self):
        for _ in range(3):
            case = wf.create_rescue_case(self.citizen, "Dog", "Critical", "Dog hit by a car, bleeding",
                                         "201001", use_network=False)
            results, errors = run_together([lambda r=r: wf.accept_case(case.case_id, r) for r in self.rescuers])
            self.assertEqual(len(results), 1, errors)
            self.assertEqual(len(errors), 2)
            self.assertTrue(all(isinstance(e, wf.Conflict) for e in errors), errors)
            saved = wf.load_case(case.case_id)
            self.assertEqual(saved.rescuer_id, results[0].rescuer_id)

    def test_stale_read_cannot_double_accept(self):
        """Even if both rescuers read 'Reported', the conditional UPDATE lets only one through."""
        case = wf.create_rescue_case(self.citizen, "Cat", "Low", "Kitten with a sore eye",
                                     "201001", use_network=False)
        stale = wf.load_case(case.case_id)
        wf.accept_case(case.case_id, self.rescuers[0])
        with mock.patch.object(wf, "load_case", return_value=stale):
            with self.assertRaises(wf.Conflict):
                wf.accept_case(case.case_id, self.rescuers[1])
        self.assertEqual(wf.load_case(case.case_id).rescuer_id, self.rescuers[0].user_id)

    def test_concurrent_allocations_never_overspend(self):
        fund = "Emergency Feed Fund"
        case_id = dh.load_table("rescue_cases").query("status == 'In Transit'")["case_id"].iloc[0]
        available = wf.funds_available(fund)
        share = (available * Decimal("0.4")).quantize(Decimal("1"))      # only 2 of 5 can fit
        results, errors = run_together(
            [lambda: wf.allocate_funds(self.admin, case_id, share, "Food", fund) for _ in range(5)])
        self.assertEqual(len(results), 2, errors)
        self.assertTrue(all(isinstance(e, wf.Conflict) for e in errors), errors)
        self.assertEqual(wf.funds_available(fund), available - 2 * share)
        self.assertGreaterEqual(wf.funds_available(fund), 0)


if __name__ == "__main__":
    unittest.main()
