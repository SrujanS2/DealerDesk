from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from core.money import fmt, parse_price, to_money


class MoneyTests(SimpleTestCase):
    def test_round_half_up_not_bankers(self):
        self.assertEqual(to_money(Decimal("18.045")), Decimal("18.05"))  # banker's rounding would give 18.04
        self.assertEqual(to_money(Decimal("0.005")), Decimal("0.01"))
        self.assertEqual(to_money(Decimal("788.13")), Decimal("788.13"))

    def test_fmt_two_decimals(self):
        self.assertEqual(fmt(Decimal("1459.5")), "1459.50")
        self.assertEqual(fmt(Decimal("7")), "7.00")

    def test_parse_price(self):
        self.assertEqual(parse_price("1459.50"), Decimal("1459.50"))
        self.assertEqual(parse_price(1459.5), Decimal("1459.50"))
        self.assertEqual(parse_price(12), Decimal("12.00"))
        self.assertEqual(parse_price("12.340"), Decimal("12.34"))
        for bad in ("12.345", "N/A", "", None, 0, "-5", "0.00", True, "NaN", "Infinity", [1]):
            self.assertIsNone(parse_price(bad), bad)


class HealthAndErrorsTests(TestCase):
    def test_health(self):
        r = self.client.get("/api/health/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})

    def test_unknown_url_is_json_404(self):
        r = self.client.get("/api/nope/")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"]["code"], "NOT_FOUND")

    def test_malformed_json_is_validation_error(self):
        r = self.client.post("/api/orders/", data="{bad", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertIsInstance(r.json()["error"]["details"], list)
