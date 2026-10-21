"""End-to-end tests of the REST API using Flask's test client."""
import csv
import io
import json
import re
import unittest
from urllib.parse import urlencode

import pandas as pd

from backend import create_app
from backend.config import DATA_FILE
from backend.routes import _csv_safe


def _strict_json(text: str):
    """json.loads that rejects NaN / Infinity (which browsers cannot parse)."""
    def reject(token):
        raise ValueError(f"invalid JSON constant {token}")
    return json.loads(text, parse_constant=reject)


class ApiTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

    def get_json(self, url, expected=200):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, expected, resp.get_data(as_text=True)[:300])
        return _strict_json(resp.get_data(as_text=True))


class TestBasics(ApiTestBase):
    def test_health(self):
        data = self.get_json("/api/health")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["rows"], 7431)

    def test_meta(self):
        data = self.get_json("/api/meta")
        self.assertEqual(data["date_min"], "2025-03-18")
        self.assertEqual(data["date_max"], "2025-03-24")
        self.assertEqual(len(data["product_types"]), 14)
        self.assertEqual(data["product_types"][0], "Running Shoes")
        self.assertEqual(data["provinces"][0], "California")
        self.assertEqual({b["id"] for b in data["bases"]}, {"incl_tax", "excl_tax"})

    def test_frontend_is_served(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Shopify Sales", page.data)
        for path in ("/css/styles.css", "/js/main.js", "/js/charts.js", "/js/api.js"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_security_headers(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", resp.headers["Content-Security-Policy"])
        self.assertEqual(resp.headers["Cache-Control"], "no-store")

    def test_unknown_endpoint_is_json_404(self):
        resp = self.client.get("/api/nope")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("error", resp.get_json())

    def test_api_is_read_only(self):
        resp = self.client.post("/api/dashboard")
        self.assertEqual(resp.status_code, 405)
        self.assertIn("error", resp.get_json())


class TestDashboardPayload(ApiTestBase):
    def test_default_payload_matches_report(self):
        d = self.get_json("/api/dashboard")
        k = d["kpis"]
        self.assertEqual(k["sales"], 4598960.87)
        self.assertEqual(k["orders"], 7431)
        self.assertEqual(k["customers"], 4431)
        self.assertEqual(k["aov"], 618.89)
        self.assertEqual(k["repeat_customers"], 2039)
        self.assertEqual(d["period"], {"start": "2025-03-18", "end": "2025-03-24", "days": 7})
        self.assertEqual(len(d["daily"]), 7)
        self.assertEqual(len(d["hourly"]), 24)
        self.assertEqual(d["products"]["count"], 14)
        self.assertEqual(d["customers"]["concentration"]["top10"]["n"], 444)
        self.assertGreaterEqual(len(d["insights"]), 3)
        self.assertLessEqual(len(d["insights"]), 5)
        self.assertTrue(all({"title", "finding", "recommendation", "visual"} <= set(i) for i in d["insights"]))
        self.assertTrue(d["caveats"])

    def test_sections_sum_to_total(self):
        d = self.get_json("/api/dashboard")
        total = d["kpis"]["sales"]
        self.assertAlmostEqual(sum(r["sales"] for r in d["daily"]), total, delta=0.5)
        self.assertAlmostEqual(sum(r["sales"] for r in d["products"]["rows"]), total, delta=0.5)
        self.assertAlmostEqual(sum(r["sales"] for r in d["hourly"]), total, delta=0.5)
        self.assertAlmostEqual(sum(r["sales"] for r in d["gateways"]["rows"]), total, delta=0.5)
        prov = d["provinces"]
        self.assertAlmostEqual(sum(r["sales"] for r in prov["rows"]) + prov["other"]["sales"], total, delta=0.5)

    def test_basis_toggle(self):
        d = self.get_json("/api/dashboard?basis=excl_tax")
        self.assertEqual(d["kpis"]["sales"], 4180873.52)
        self.assertEqual(d["basis"]["id"], "excl_tax")
        self.assertAlmostEqual(d["kpis"]["aov"], 4180873.52 / 7431, places=2)
        self.assertIn("excluding tax", d["insights"][0]["finding"])

    def test_product_filter_repeated_parameter(self):
        q = urlencode([("product_type", "Running Shoes"), ("product_type", "Sandals")])
        d = self.get_json(f"/api/dashboard?{q}")
        self.assertEqual({r["product_type"] for r in d["products"]["rows"]}, {"Running Shoes", "Sandals"})
        self.assertAlmostEqual(d["kpis"]["sales"], 1616946.276 + 103116.673, delta=0.01)
        self.assertTrue(any("Filters are active" in c for c in d["caveats"]))

    def test_product_name_with_apostrophe(self):
        d = self.get_json("/api/dashboard?" + urlencode({"product_type": "Boy's"}))
        self.assertEqual(d["kpis"]["orders"], 13)

    def test_single_day_filter(self):
        d = self.get_json("/api/dashboard?start=2025-03-24&end=2025-03-24")
        self.assertEqual(d["period"]["days"], 1)
        self.assertEqual(d["kpis"]["sales"], 752227.32)
        self.assertNotIn("highest day", d["insights"][0]["finding"])

    def test_province_and_gateway_filters(self):
        d = self.get_json("/api/dashboard?" + urlencode({"province": "California", "gateway": "paypal"}))
        self.assertEqual([r["name"] for r in d["provinces"]["rows"]], ["California"])
        self.assertEqual([r["name"] for r in d["gateways"]["rows"]], ["paypal"])

    def test_range_is_clamped_to_data(self):
        d = self.get_json("/api/dashboard?start=2025-01-01&end=2025-12-31")
        self.assertEqual(d["period"], {"start": "2025-03-18", "end": "2025-03-24", "days": 7})

    def test_empty_selection_is_graceful(self):
        d = self.get_json("/api/dashboard?product_type=Nonexistent")
        self.assertEqual(d["kpis"]["orders"], 0)
        self.assertEqual(d["kpis"]["aov"], 0.0)
        self.assertEqual(len(d["daily"]), 7)
        self.assertEqual(d["insights"][0]["id"], "no-data")
        self.assertEqual(d["products"]["rows"], [])

    def test_range_outside_data_is_graceful(self):
        d = self.get_json("/api/dashboard?start=2026-01-01&end=2026-01-05")
        self.assertEqual(d["kpis"]["orders"], 0)
        self.assertEqual(d["daily"], [])


class TestValidation(ApiTestBase):
    def test_bad_date(self):
        data = self.get_json("/api/dashboard?start=18-03-2025", expected=400)
        self.assertIn("YYYY-MM-DD", data["error"])

    def test_start_after_end(self):
        data = self.get_json("/api/dashboard?start=2025-03-24&end=2025-03-18", expected=400)
        self.assertIn("on or before", data["error"])

    def test_bad_basis(self):
        self.get_json("/api/dashboard?basis=gross", expected=400)

    def test_bad_limit(self):
        self.get_json("/api/customers/top?limit=abc", expected=400)

    def test_limit_is_capped(self):
        d = self.get_json("/api/customers/top?limit=5000")
        self.assertLessEqual(len(d["rows"]), 100)

    def test_sql_like_input_is_just_a_value(self):
        d = self.get_json("/api/dashboard?" + urlencode({"product_type": "'; DROP TABLE x;--"}))
        self.assertEqual(d["kpis"]["orders"], 0)


class TestIndividualEndpoints(ApiTestBase):
    def test_each_endpoint_returns_valid_json(self):
        for url in ("/api/kpis", "/api/sales/daily", "/api/sales/hourly", "/api/products",
                    "/api/customers/frequency", "/api/customers/top", "/api/geo/provinces",
                    "/api/payments", "/api/insights", "/api/data-quality"):
            with self.subTest(url=url):
                self.get_json(url)

    def test_no_nan_anywhere_even_when_empty(self):
        for url in ("/api/dashboard", "/api/dashboard?product_type=Nope", "/api/dashboard?basis=excl_tax"):
            with self.subTest(url=url):
                self.get_json(url)  # strict parser raises on NaN/Infinity

    def test_data_quality_endpoint(self):
        q = self.get_json("/api/data-quality")
        self.assertEqual(q["missing_product_id"], 11)
        self.assertEqual(q["missing_variant_id"], 4)


class TestPrivacy(ApiTestBase):
    def test_customer_ids_masked_by_default(self):
        rows = self.get_json("/api/customers/top")["rows"]
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(r["customer"].startswith("•••") for r in rows))

    def test_customer_ids_revealed_on_request(self):
        rows = self.get_json("/api/customers/top?reveal_ids=true")["rows"]
        self.assertTrue(all(re.fullmatch(r"\d+", r["customer"]) for r in rows))

    def test_names_never_appear_in_any_response(self):
        raw = pd.read_excel(DATA_FILE)
        safe_words = " ".join(raw["Product Type"].astype(str).unique()).lower()
        names = {
            str(n) for n in pd.concat([raw["Billing Address First Name"], raw["Billing Address Last Name"]])
            if len(str(n)) >= 6 and str(n).lower() not in safe_words
        }
        names = sorted(names)[:400]
        blob = ""
        for url in ("/api/dashboard?reveal_ids=true", "/api/meta", "/api/customers/top?reveal_ids=true&limit=100",
                    "/api/data-quality", "/api/products", "/api/geo/provinces?limit=100"):
            blob += self.client.get(url).get_data(as_text=True)
        leaked = [n for n in names if n in blob]
        self.assertEqual(leaked, [])


class TestExports(ApiTestBase):
    def parse(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.content_type)
        self.assertIn("attachment", resp.headers["Content-Disposition"])
        return list(csv.reader(io.StringIO(resp.get_data(as_text=True))))

    def test_daily_export(self):
        rows = self.parse("/api/export/daily.csv")
        self.assertEqual(len(rows), 8)  # header + 7 days
        self.assertEqual(rows[0][0], "Order Date")
        self.assertEqual(rows[1][0], "2025-03-18")
        self.assertEqual(rows[1][1], "945")

    def test_product_export_respects_filters(self):
        rows = self.parse("/api/export/products.csv?" + urlencode({"product_type": "Sandals"}))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], "Sandals")

    def test_csv_formula_injection_is_neutralised(self):
        self.assertEqual(_csv_safe("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(_csv_safe("+1"), "'+1")
        self.assertEqual(_csv_safe("Running Shoes"), "Running Shoes")
        self.assertEqual(_csv_safe(5), 5)


if __name__ == "__main__":
    unittest.main()
