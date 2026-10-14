import csv
import math
import statistics
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from core.testutils import JsonClientMixin, make_product
from forecasting import services


def _csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class ForecastFileTests(TestCase):
    def test_file_shape(self):
        rows = _csv(settings.FORECAST_FILE)
        skus = {r["sku"] for r in _csv(Path(settings.DATA_DIR) / "lead_times.csv")}
        weeks = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]
        self.assertEqual(list(rows[0].keys()), ["sku", "week_start", "forecast_units"])
        self.assertEqual({(r["sku"], r["week_start"]) for r in rows}, {(s, w) for s in skus for w in weeks})
        self.assertEqual(len(rows), 160)
        self.assertTrue(all(float(r["forecast_units"]) >= 0 for r in rows))


class ForecastApiTests(JsonClientMixin, TestCase):
    def setUp(self):
        self.lead = {r["sku"]: int(r["lead_time_weeks"]) for r in _csv(Path(settings.DATA_DIR) / "lead_times.csv")}
        for i, sku in enumerate(self.lead):
            make_product(sku, stock=40 + i)

    def test_forecast_endpoint_matches_file(self):
        sku = next(iter(self.lead))
        expected = [(r["week_start"], float(r["forecast_units"])) for r in _csv(settings.FORECAST_FILE) if r["sku"] == sku]
        body = self.client.get(f"/api/forecast/{sku}/").json()
        self.assertEqual([(f["week_start"], f["forecast_units"]) for f in body["forecast"]], expected)
        self.assertError(self.client.get("/api/forecast/NOPE-0000/"), 404, "NOT_FOUND")

    def test_reorder_formula_and_live_stock(self):
        sku = "FIL-1016"
        self.put_json(f"/api/inventory/{sku}/", {"quantity": 12})
        results = self.client.get("/api/reorder-suggestions/").json()["results"]
        self.assertEqual(len(results), 40)
        row = next(r for r in results if r["sku"] == sku)
        L = self.lead[sku]
        fc = sorted((r["week_start"], float(r["forecast_units"])) for r in _csv(settings.FORECAST_FILE) if r["sku"] == sku)
        ltd = round(sum(u for _, u in fc[:L]), 2)
        hist = sorted((r["week_start"], int(r["units_sold"])) for r in _csv(Path(settings.DATA_DIR) / "sales_history.csv") if r["sku"] == sku)
        sigma = statistics.stdev([u for _, u in hist[-12:]])
        ss = math.ceil(1.65 * sigma * math.sqrt(L))
        self.assertEqual(row["current_stock"], 12)
        self.assertEqual(row["lead_time_weeks"], L)
        self.assertAlmostEqual(row["lead_time_demand"], ltd, places=6)
        self.assertEqual(row["safety_stock"], ss)
        self.assertAlmostEqual(row["reorder_point"], ltd + ss, places=6)
        self.assertEqual(row["reorder_qty"], max(0, math.ceil(ltd + ss - 12)))
        self.put_json(f"/api/inventory/{sku}/", {"quantity": 100000})
        row = next(r for r in self.client.get("/api/reorder-suggestions/").json()["results"] if r["sku"] == sku)
        self.assertEqual(row["reorder_qty"], 0)

    def test_sigma_uses_all_weeks_when_fewer_than_12(self):
        self.assertIn("CHN-1006", services.demand_sigma())  # new SKU with 6 weeks of history
        self.assertGreater(services.demand_sigma()["CHN-1006"], 0)
