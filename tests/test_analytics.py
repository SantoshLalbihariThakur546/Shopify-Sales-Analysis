"""Validate the analytics against the figures published in the project report and
against the reference CSVs produced by the original Python notebook."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend import analytics as A
from backend.config import BASE_DIR, DATA_FILE
from backend.data_loader import DataLoadError, load_sales_store
from backend.filters import Filters, apply_filters

REF = BASE_DIR / "data" / "reference"

# Figures quoted in Shopify_Sales_Analysis_Report.pdf
REPORT = {
    "rows": 7431, "orders": 7431, "customers": 4431, "product_types": 14,
    "sales_incl_tax": 4598960.87, "sales_excl_tax": 4180873.52, "tax": 418087.35,
    "aov": 618.89, "units": 7534,
    "repeat": 2039, "one_order": 2392, "mean_orders": 1.68, "median_orders": 1, "max_orders": 7,
    "top10_n": 444, "top10_share": 0.220, "top20_n": 887, "top20_share": 0.378,
    "top_product": "Running Shoes", "top_product_sales": 1616946.28, "top_product_share": 0.352,
    "top3_share": 0.713,
    "peak_day": ("2025-03-24", 752227.32), "low_day": ("2025-03-18", 578282.08),
}


class AnalyticsTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = load_sales_store(DATA_FILE)
        cls.df = cls.store.df
        cls.col = "Total Price Usd"


class TestKpisMatchReport(AnalyticsTestBase):
    def test_headline_kpis(self):
        k = A.kpis(self.df, self.col)
        self.assertAlmostEqual(k["sales_incl_tax"], REPORT["sales_incl_tax"], places=2)
        self.assertAlmostEqual(k["sales_excl_tax"], REPORT["sales_excl_tax"], places=2)
        self.assertAlmostEqual(k["tax"], REPORT["tax"], places=2)
        self.assertEqual(k["orders"], REPORT["orders"])
        self.assertEqual(k["customers"], REPORT["customers"])
        self.assertAlmostEqual(k["aov"], REPORT["aov"], places=2)
        self.assertEqual(k["units"], REPORT["units"])

    def test_repeat_customers(self):
        k = A.kpis(self.df, self.col)
        self.assertEqual(k["repeat_customers"], REPORT["repeat"])
        self.assertEqual(k["one_order_customers"], REPORT["one_order"])
        self.assertAlmostEqual(k["repeat_share"], 0.460, places=3)
        self.assertEqual(k["avg_orders_per_customer"], REPORT["mean_orders"])

    def test_excl_tax_basis(self):
        k = A.kpis(self.df, "Subtotal Price")
        self.assertAlmostEqual(k["sales"], REPORT["sales_excl_tax"], places=2)
        self.assertAlmostEqual(k["aov"], REPORT["sales_excl_tax"] / REPORT["orders"], places=2)

    def test_tax_reconciles(self):
        k = A.kpis(self.df, self.col)
        self.assertAlmostEqual(k["sales_excl_tax"] + k["tax"], k["sales_incl_tax"], places=1)


class TestAgainstReferenceCsvs(AnalyticsTestBase):
    def test_daily_matches_notebook_export(self):
        ref = pd.read_csv(REF / "daily_sales_summary.csv")
        rows = A.daily_sales(self.df, self.col, self.store.date_min, self.store.date_max)
        self.assertEqual(len(rows), len(ref))
        for mine, theirs in zip(rows, ref.itertuples(index=False)):
            self.assertEqual(mine["date"], theirs[0])
            self.assertEqual(mine["orders"], theirs.Orders)
            self.assertAlmostEqual(mine["sales"], theirs.Revenue, delta=0.01)
            self.assertEqual(mine["customers"], theirs.Customers)
            self.assertEqual(mine["units"], theirs.Quantity)

    def test_peak_and_low_day(self):
        rows = A.daily_sales(self.df, self.col, self.store.date_min, self.store.date_max)
        peak = max(rows, key=lambda r: r["sales"])
        low = min(rows, key=lambda r: r["sales"])
        self.assertEqual((peak["date"], peak["sales"]), REPORT["peak_day"])
        self.assertEqual((low["date"], low["sales"]), REPORT["low_day"])

    def test_products_match_notebook_export(self):
        ref = pd.read_csv(REF / "product_sales_summary.csv")
        rows = A.product_summary(self.df, self.col)["rows"]
        self.assertEqual([r["product_type"] for r in rows], ref["Product Type"].tolist())
        for mine, theirs in zip(rows, ref.itertuples(index=False)):
            self.assertAlmostEqual(mine["sales"], theirs.Revenue, delta=0.01)
            self.assertAlmostEqual(mine["sales_excl_tax"], theirs.Subtotal, delta=0.01)
            self.assertEqual(mine["orders"], theirs.Orders)
            self.assertEqual(mine["units"], theirs.Quantity)
            self.assertEqual(mine["customers"], theirs.Customers)

    def test_customer_summary_agrees(self):
        ref = pd.read_csv(REF / "customer_summary.csv")
        freq = A.customer_frequency(self.df)
        self.assertEqual(freq["total_customers"], len(ref))
        self.assertEqual(freq["repeat_customers"], int((ref["Distinct_Orders"] > 1).sum()))
        self.assertEqual(freq["max_orders"], int(ref["Distinct_Orders"].max()))
        top = A.top_customers(self.df, self.col, 1, reveal=True)[0]
        best = ref.sort_values("Total_Spend_USD", ascending=False).iloc[0]
        self.assertEqual(top["customer"], str(int(best["Customer Id"])))
        self.assertAlmostEqual(top["spend"], best["Total_Spend_USD"], delta=0.01)


class TestReportFindings(AnalyticsTestBase):
    def test_product_findings(self):
        p = A.product_summary(self.df, self.col)
        first = p["rows"][0]
        self.assertEqual(first["product_type"], REPORT["top_product"])
        self.assertAlmostEqual(first["sales"], REPORT["top_product_sales"], places=2)
        self.assertAlmostEqual(first["share"], REPORT["top_product_share"], places=3)
        self.assertAlmostEqual(p["top3_share"], REPORT["top3_share"], places=3)
        self.assertEqual(p["count"], REPORT["product_types"])
        self.assertAlmostEqual(sum(r["share"] for r in p["rows"]), 1.0, places=3)
        self.assertAlmostEqual(p["rows"][-1]["cumulative_share"], 1.0, places=3)

    def test_customer_findings(self):
        f = A.customer_frequency(self.df)
        self.assertEqual(f["median_orders"], REPORT["median_orders"])
        self.assertEqual(f["max_orders"], REPORT["max_orders"])
        self.assertEqual(sum(b["customers"] for b in f["buckets"]), REPORT["customers"])

    def test_concentration(self):
        c = A.concentration(self.df, self.col)
        self.assertEqual(c["top10"]["n"], REPORT["top10_n"])
        self.assertAlmostEqual(c["top10"]["share"], REPORT["top10_share"], places=3)
        self.assertEqual(c["top20"]["n"], REPORT["top20_n"])
        self.assertAlmostEqual(c["top20"]["share"], REPORT["top20_share"], places=3)


class TestHelpers(unittest.TestCase):
    def test_ceil_pct_is_exact(self):
        self.assertEqual(A.ceil_pct(30, 10), 3)        # float maths would give 4
        self.assertEqual(A.ceil_pct(4431, 10), 444)
        self.assertEqual(A.ceil_pct(4431, 20), 887)
        self.assertEqual(A.ceil_pct(0, 10), 0)

    def test_num_handles_bad_values(self):
        self.assertEqual(A.num(float("nan")), 0.0)
        self.assertEqual(A.num(None), 0.0)
        self.assertEqual(A.num(float("inf")), 0.0)
        self.assertEqual(A.num(1.005, 2), 1.0)

    def test_mask_id_never_reveals_the_whole_id(self):
        self.assertEqual(A.mask_id(2865), "•••65")
        self.assertEqual(A.mask_id(865), "•••65")
        self.assertEqual(A.mask_id(10), "•••0")
        self.assertEqual(A.mask_id(7), "•••")
        self.assertEqual(A.mask_id(0), "•••")
        for cid in (0, 5, 42, 123, 6500):
            visible = A.mask_id(cid).replace("•", "")
            self.assertNotEqual(visible, str(cid))              # never the full id
            self.assertTrue(str(cid).endswith(visible))         # only a trailing part


class TestFiltersAndEmptyData(AnalyticsTestBase):
    def test_product_filter_equals_reference_row(self):
        sub = apply_filters(self.df, Filters(product_types=("Running Shoes",)))
        k = A.kpis(sub, self.col)
        self.assertAlmostEqual(k["sales"], REPORT["top_product_sales"], places=2)
        self.assertEqual(k["orders"], 2618)

    def test_date_filter_single_day(self):
        import datetime as dt
        sub = apply_filters(self.df, Filters(start=dt.date(2025, 3, 24), end=dt.date(2025, 3, 24)))
        self.assertAlmostEqual(A.kpis(sub, self.col)["sales"], 752227.32, places=2)

    def test_filters_compose(self):
        sub = apply_filters(self.df, Filters(product_types=("Sandals",), provinces=("California",)))
        self.assertTrue((sub["Product Type"] == "Sandals").all())
        self.assertTrue((sub["Province"] == "California").all())

    def test_every_function_survives_an_empty_selection(self):
        import datetime as dt
        empty = self.df.iloc[0:0]
        self.assertEqual(A.kpis(empty, self.col)["orders"], 0)
        days = A.daily_sales(empty, self.col, dt.date(2025, 3, 18), dt.date(2025, 3, 20))
        self.assertEqual([d["sales"] for d in days], [0.0, 0.0, 0.0])
        self.assertEqual(len(A.hourly_orders(empty, self.col)), 24)
        self.assertEqual(A.product_summary(empty, self.col)["rows"], [])
        self.assertEqual(A.customer_frequency(empty)["total_customers"], 0)
        self.assertEqual(A.concentration(empty, self.col)["top10"]["n"], 0)
        self.assertEqual(A.top_customers(empty, self.col), [])
        self.assertEqual(A.provinces(empty, self.col)["rows"], [])
        self.assertEqual(A.gateways(empty, self.col)["rows"], [])

    def test_reversed_window_returns_nothing(self):
        import datetime as dt
        self.assertEqual(A.daily_sales(self.df, self.col, dt.date(2025, 3, 24), dt.date(2025, 3, 18)), [])


class TestLoader(unittest.TestCase):
    def test_no_personal_data_in_memory(self):
        store = load_sales_store(DATA_FILE)
        forbidden = [c for c in store.df.columns if "name" in c.lower() or "zip" in c.lower()]
        self.assertEqual(forbidden, [])

    def test_quality_numbers_match_report(self):
        q = load_sales_store(DATA_FILE).quality
        self.assertEqual(q["rows"], 7431)
        self.assertEqual(q["source_columns"], 19)
        self.assertEqual(q["missing_product_id"], 11)
        self.assertEqual(q["missing_variant_id"], 4)
        self.assertEqual(q["days"], 7)
        by_id = {c["id"]: c for c in q["checks"]}
        self.assertEqual(by_id["duplicates"]["value"], 0)
        self.assertEqual(by_id["reconciliation"]["status"], "ok")

    def test_missing_file_has_helpful_message(self):
        with self.assertRaises(DataLoadError) as ctx:
            load_sales_store(Path("definitely_not_here.xlsx"))
        self.assertIn("SHOPIFY_DATA_FILE", str(ctx.exception))

    def test_missing_columns_are_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.csv"
            pd.DataFrame({"Order Number": [1], "Customer Id": [1]}).to_csv(bad, index=False)
            with self.assertRaises(DataLoadError) as ctx:
                load_sales_store(bad)
            self.assertIn("Invoice Date", str(ctx.exception))

    def test_unsupported_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = Path(tmp) / "data.txt"
            odd.write_text("x")
            with self.assertRaises(DataLoadError):
                load_sales_store(odd)

    def test_minimal_csv_and_bad_rows_are_dropped_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mini.csv"
            pd.DataFrame(
                {
                    "Order Number": [1, 2, 3],
                    "Customer Id": [10, 10, 11],
                    "Invoice Date": ["2025-03-18 10:00", "not a date", "2025-03-19 11:30"],
                    "Product Type": ["Boots", "Boots", None],
                    "Quantity": [1, 1, 2],
                    "Subtotal Price": [100.0, 50.0, 80.0],
                    "Total Price Usd": [110.0, 55.0, 88.0],
                    "Total Tax": [10.0, 5.0, 8.0],
                }
            ).to_csv(path, index=False)
            store = load_sales_store(path)
            self.assertEqual(store.quality["rows"], 3)
            self.assertEqual(store.quality["rows_used"], 2)          # bad date dropped
            by_id = {c["id"]: c for c in store.quality["checks"]}
            self.assertEqual(by_id["invalid_rows"]["value"], 1)
            self.assertIn("Unspecified", set(store.df["Product Type"]))  # blank type labelled
            self.assertEqual(set(store.df["Province"]), {"Unknown"})     # optional column absent


if __name__ == "__main__":
    unittest.main()
