import unittest

import numpy as np
import pandas as pd

from tests import helpers
from analytics import data_handler as dh
from analytics import numpy_stats as ns
from analytics import pandas_engine as pe


class NumpyTests(unittest.TestCase):
    def test_financial_summary(self):
        stats = ns.financial_summary([100, 200, 300, np.nan])
        self.assertEqual(stats["total"], 600)
        self.assertEqual(stats["mean"], 200)
        self.assertAlmostEqual(stats["std"], 100.0)
        self.assertEqual(ns.financial_summary([])["total"], 0)

    def test_recovery_rate(self):
        statuses = ["Reported", "Assigned", "Recovered", "Recovered", "In Transit"]
        self.assertAlmostEqual(ns.recovery_rate(statuses), 50.0)   # 2 of 4 rescued
        self.assertEqual(ns.recovery_rate(["Reported"]), 0.0)

    def test_growth_and_outliers(self):
        np.testing.assert_array_equal(ns.growth_rates([100, 150, 75]), [50.0, -50.0])
        amounts = [100] * 30 + [100000]
        self.assertEqual(list(ns.zscore_outliers(amounts)), [30])
        self.assertAlmostEqual(ns.monthly_std([10, 20, 30]), 10.0)


class PandasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers.fresh_demo_data()

    def test_cleaning_drops_bad_rows(self):
        raw = pd.DataFrame([
            {"transaction_id": "T1", "amount": "100", "timestamp": "2026-10-01 10:00:00", "status": "Success",
             "contribution_type": "General Shelter Fund", "donor_email": "", "case_id": ""},
            {"transaction_id": "T2", "amount": "", "timestamp": "2026-10-01 10:00:00", "status": "Success",
             "contribution_type": "General Shelter Fund", "donor_email": "x@y.com", "case_id": ""},
            {"transaction_id": "T3", "amount": "50", "timestamp": "2026-10-02 10:00:00", "status": "Failed",
             "contribution_type": "Emergency Feed Fund", "donor_email": "x@y.com", "case_id": ""},
        ])
        clean = pe.clean_donations(raw)
        self.assertEqual(list(clean["transaction_id"]), ["T1"])
        self.assertEqual(clean.iloc[0]["donor_email"], "(not given)")
        self.assertEqual(pe.missing_value_report(raw).loc["amount", "missing"], 1)

    def test_grouping(self):
        donations = pe.clean_donations(dh.load_table("donations"))
        by_type = pe.donations_by_type(donations)
        self.assertAlmostEqual(by_type["total"].sum(), donations["amount"].sum(), places=2)
        multi = pe.monthly_type_multiindex(donations)
        self.assertEqual(multi.index.nlevels, 2)
        pivot = pe.monthly_type_breakdown(donations)
        self.assertAlmostEqual(pivot["Total"].sum(), donations["amount"].sum(), delta=len(pivot))
        tx = donations["transaction_id"].iloc[0]
        self.assertIsNotNone(pe.get_transaction(donations, tx))

    def test_funds_never_negative(self):
        overview = pe.funds_overview(dh.load_table("donations"), dh.load_table("allocations"))
        self.assertTrue((overview["available"] >= 0).all())
        self.assertGreater(overview.loc["General Shelter Fund", "raised"], 0)

    def test_charts_render(self):
        donations = pe.clean_donations(dh.load_table("donations"))
        allocations = pe.clean_allocations(dh.load_table("allocations"))
        cases = pe.clean_cases(dh.load_table("rescue_cases"))
        figures = [ns.plot_monthly_trend(pe.monthly_donations(donations), pe.monthly_expenditure(allocations)),
                   ns.plot_fund_utilization(pe.utilization_by_purpose(allocations)),
                   ns.plot_case_status(pe.cases_by_status(cases)),
                   ns.plot_donation_distribution(donations["amount"]),
                   ns.plot_funds_by_type(pe.donations_by_type(donations)),
                   ns.plot_fund_utilization(pd.Series(dtype=float))]
        for figure in figures:
            figure.canvas.draw()   # raises if anything is wrong


if __name__ == "__main__":
    unittest.main()
