import re
import threading
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import TestCase, TransactionTestCase

from core.testutils import JsonClientMixin, make_dealer, make_product, stock_of
from orders import services


class DraftOrderTests(JsonClientMixin, TestCase):
    def setUp(self):
        self.dealer = make_dealer()
        make_product("BRK-1044", price="1459.50", stock=136)
        make_product("FIL-1012", price="100.25", stock=5, name="Air Filter - RE Classic 350")

    def create(self, items, **headers):
        return self.post_json("/api/orders/", {"dealer_id": self.dealer.id, "items": items}, **headers)

    def test_contract_example_totals(self):
        r = self.create([{"sku": "BRK-1044", "quantity": 3}])
        self.assertEqual(r.status_code, 201, r.content)
        o = r.json()
        self.assertEqual(o["status"], "DRAFT")
        self.assertRegex(o["order_number"], r"^ORD-\d{8}-\d{4}$")
        line = o["items"][0]
        self.assertEqual((line["unit_price"], line["line_subtotal"], line["line_tax"], line["line_total"]),
                         ("1459.50", "4378.50", "788.13", "5166.63"))
        self.assertEqual((o["subtotal"], o["tax_total"], o["grand_total"]), ("4378.50", "788.13", "5166.63"))

    def test_gst_rounds_half_up_per_line(self):
        # 100.25 x 1 = 100.25; tax 18.045 -> 18.05 (ROUND_HALF_UP). Two lines are rounded separately.
        o = self.create([{"sku": "FIL-1012", "quantity": 1}, {"sku": "BRK-1044", "quantity": 1}]).json()
        self.assertEqual(o["items"][0]["line_tax"], "18.05")
        self.assertEqual(o["items"][1]["line_tax"], "262.71")  # 1459.50 x 0.18 = 262.71
        self.assertEqual(o["tax_total"], "280.76")
        self.assertEqual(o["grand_total"], "1840.51")

    def test_validation_errors(self):
        bad_bodies = [
            {"dealer_id": self.dealer.id, "items": []},
            {"dealer_id": self.dealer.id},
            {"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": 0}]},
            {"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": -2}]},
            {"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": 1.5}]},
            {"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": "3"}]},
            {"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": True}]},
            {"dealer_id": self.dealer.id, "items": [{"sku": "NOPE-0000", "quantity": 1}]},
            {"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": 1}, {"sku": "BRK-1044", "quantity": 2}]},
            {"dealer_id": 999999, "items": [{"sku": "BRK-1044", "quantity": 1}]},
            {"dealer_id": "x", "items": [{"sku": "BRK-1044", "quantity": 1}]},
            {"items": [{"sku": "BRK-1044", "quantity": 1}]},
        ]
        for body in bad_bodies:
            self.assertError(self.post_json("/api/orders/", body), 400, "VALIDATION_ERROR")
        self.assertEqual(self.client.get("/api/orders/").json()["count"], 0)

    def test_draft_follows_price_then_locks_on_confirm(self):
        n = self.create([{"sku": "BRK-1044", "quantity": 1}]).json()["order_number"]
        self.patch_json("/api/products/BRK-1044/", {"price": "1500.00"})
        self.assertEqual(self.client.get(f"/api/orders/{n}/").json()["items"][0]["unit_price"], "1500.00")
        self.post_json(f"/api/orders/{n}/confirm/")
        self.patch_json("/api/products/BRK-1044/", {"price": "2000.00"})
        o = self.client.get(f"/api/orders/{n}/").json()
        self.assertEqual(o["items"][0]["unit_price"], "1500.00")
        self.assertEqual(o["grand_total"], "1770.00")

    def test_draft_does_not_touch_stock(self):
        self.create([{"sku": "BRK-1044", "quantity": 100}])
        self.assertEqual(stock_of("BRK-1044"), 136)

    def test_list_filters_and_404(self):
        self.create([{"sku": "BRK-1044", "quantity": 1}])
        other = make_dealer("DLR-002", "Other")
        self.post_json("/api/orders/", {"dealer_id": other.id, "items": [{"sku": "BRK-1044", "quantity": 1}]})
        self.assertEqual(self.client.get(f"/api/orders/?dealer_id={other.id}").json()["count"], 1)
        self.assertEqual(self.client.get("/api/orders/?status=DRAFT").json()["count"], 2)
        self.assertEqual(self.client.get("/api/orders/?status=CONFIRMED").json()["count"], 0)
        self.assertError(self.client.get("/api/orders/ORD-20260101-9999/"), 404, "NOT_FOUND")

    def test_put_replaces_items_only_while_draft(self):
        n = self.create([{"sku": "BRK-1044", "quantity": 1}]).json()["order_number"]
        r = self.put_json(f"/api/orders/{n}/", {"items": [{"sku": "FIL-1012", "quantity": 2}]})
        self.assertEqual([i["sku"] for i in r.json()["items"]], ["FIL-1012"])
        self.assertError(self.put_json(f"/api/orders/{n}/", {"items": []}), 400, "VALIDATION_ERROR")
        self.post_json(f"/api/orders/{n}/confirm/")
        self.assertError(self.put_json(f"/api/orders/{n}/", {"items": [{"sku": "BRK-1044", "quantity": 1}]}), 409, "ORDER_LOCKED")
        self.assertError(self.put_json("/api/orders/ORD-20260101-9999/", {"items": []}), 404, "NOT_FOUND")


class StatusFlowTests(JsonClientMixin, TestCase):
    def setUp(self):
        self.dealer = make_dealer()
        make_product("BRK-1044", stock=10)
        make_product("FIL-1012", stock=3, name="Air Filter - RE Classic 350")

    def new(self, items=None):
        body = {"dealer_id": self.dealer.id, "items": items or [{"sku": "BRK-1044", "quantity": 2}]}
        return self.post_json("/api/orders/", body).json()["order_number"]

    def act(self, n, action):
        return self.post_json(f"/api/orders/{n}/{action}/")

    def test_happy_path(self):
        n = self.new()
        for action, status in (("confirm", "CONFIRMED"), ("dispatch", "DISPATCHED"), ("deliver", "DELIVERED")):
            r = self.act(n, action)
            self.assertEqual(r.json()["status"], status)
        self.assertEqual(stock_of("BRK-1044"), 8)

    def test_invalid_transitions(self):
        n = self.new()
        for action in ("dispatch", "deliver"):
            self.assertError(self.act(n, action), 409, "INVALID_TRANSITION")
        self.act(n, "confirm")
        for action in ("confirm", "deliver"):
            self.assertError(self.act(n, action), 409, "INVALID_TRANSITION")
        self.act(n, "dispatch")
        for action in ("confirm", "dispatch", "cancel"):
            self.assertError(self.act(n, action), 409, "INVALID_TRANSITION")
        self.act(n, "deliver")
        for action in ("confirm", "dispatch", "deliver", "cancel"):
            self.assertError(self.act(n, action), 409, "INVALID_TRANSITION")
        self.assertError(self.act("ORD-20260101-9999", "confirm"), 404, "NOT_FOUND")

    def test_cancel_draft_and_confirmed(self):
        d = self.new()
        self.assertEqual(self.act(d, "cancel").json()["status"], "CANCELLED")
        self.assertEqual(stock_of("BRK-1044"), 10)
        self.assertError(self.act(d, "cancel"), 409, "INVALID_TRANSITION")
        c = self.new()
        self.act(c, "confirm")
        self.assertEqual(stock_of("BRK-1044"), 8)
        self.act(c, "cancel")
        self.assertEqual(stock_of("BRK-1044"), 10)
        self.assertError(self.act(c, "cancel"), 409, "INVALID_TRANSITION")  # restored once only
        self.assertEqual(stock_of("BRK-1044"), 10)

    def test_insufficient_stock_is_all_or_nothing_and_lists_every_short_line(self):
        n = self.new([{"sku": "BRK-1044", "quantity": 12}, {"sku": "FIL-1012", "quantity": 4}])
        err = self.assertError(self.act(n, "confirm"), 409, "INSUFFICIENT_STOCK")
        self.assertEqual(sorted(err["details"], key=lambda d: d["sku"]), [
            {"sku": "BRK-1044", "requested": 12, "available": 10},
            {"sku": "FIL-1012", "requested": 4, "available": 3},
        ])
        self.assertIn("Insufficient stock for Brake Pad Set - Bajaj Pulsar 150. Available: 10, Requested: 12", err["message"])
        self.assertIn("Insufficient stock for Air Filter - RE Classic 350. Available: 3, Requested: 4", err["message"])
        self.assertEqual((stock_of("BRK-1044"), stock_of("FIL-1012")), (10, 3))
        self.assertEqual(self.client.get(f"/api/orders/{n}/").json()["status"], "DRAFT")

    def test_one_short_line_blocks_the_others(self):
        n = self.new([{"sku": "BRK-1044", "quantity": 1}, {"sku": "FIL-1012", "quantity": 4}])
        err = self.assertError(self.act(n, "confirm"), 409, "INSUFFICIENT_STOCK")
        self.assertEqual(len(err["details"]), 1)
        self.assertEqual(stock_of("BRK-1044"), 10)

    def test_inventory_update_does_not_change_orders(self):
        n = self.new()
        self.act(n, "confirm")
        self.put_json("/api/inventory/BRK-1044/", {"quantity": 0})
        self.assertEqual(self.client.get(f"/api/orders/{n}/").json()["status"], "CONFIRMED")
        self.act(n, "cancel")
        self.assertEqual(stock_of("BRK-1044"), 2)


class OrderNumberTests(JsonClientMixin, TestCase):
    def test_daily_sequence_uses_ist_date(self):
        # 2026-10-11 20:00 UTC is already 2026-10-12 01:30 in India.
        late_utc = datetime(2026, 10, 11, 20, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(services.next_order_number(late_utc), "ORD-20261012-0001")
        self.assertEqual(services.next_order_number(late_utc), "ORD-20261012-0002")
        self.assertEqual(services.next_order_number(datetime(2026, 10, 13, 4, 0, tzinfo=ZoneInfo("UTC"))), "ORD-20261013-0001")


class IdempotencyTests(JsonClientMixin, TestCase):
    def setUp(self):
        self.dealer = make_dealer()
        make_product("BRK-1044")
        self.body = {"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": 2}]}

    def test_replay_returns_original(self):
        a = self.post_json("/api/orders/", self.body, **{"Idempotency-Key": "k1"})
        b = self.post_json("/api/orders/", self.body, **{"Idempotency-Key": "k1"})
        self.assertEqual(a.status_code, 201)
        self.assertIn(b.status_code, (200, 201))
        self.assertEqual(a.json()["order_number"], b.json()["order_number"])
        self.assertEqual(self.client.get("/api/orders/").json()["count"], 1)

    def test_same_key_different_body(self):
        self.post_json("/api/orders/", self.body, **{"Idempotency-Key": "k2"})
        other = {**self.body, "items": [{"sku": "BRK-1044", "quantity": 3}]}
        self.assertError(self.post_json("/api/orders/", other, **{"Idempotency-Key": "k2"}), 409, "IDEMPOTENCY_CONFLICT")

    def test_failed_request_does_not_burn_the_key(self):
        bad = {**self.body, "items": []}
        self.assertError(self.post_json("/api/orders/", bad, **{"Idempotency-Key": "k3"}), 400, "VALIDATION_ERROR")
        self.assertEqual(self.post_json("/api/orders/", self.body, **{"Idempotency-Key": "k3"}).status_code, 201)


def _in_threads(n, fn):
    """Run fn(i) in n threads released at the same moment; each thread closes its own DB connection."""
    barrier, results = threading.Barrier(n), [None] * n

    def worker(i):
        try:
            barrier.wait()
            results[i] = fn(i)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


class ConcurrencyTests(JsonClientMixin, TransactionTestCase):
    def setUp(self):
        self.dealer = make_dealer()
        make_product("BRK-1044", stock=5)
        make_product("FIL-1012", stock=1000, name="Air Filter")

    def test_parallel_confirms_never_oversell(self):
        numbers = [services.create_order({"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": 1}]})[0].order_number
                   for _ in range(12)]
        codes = _in_threads(12, lambda i: self.client.post(f"/api/orders/{numbers[i]}/confirm/").status_code)
        self.assertEqual(codes.count(200), 5)
        self.assertEqual(codes.count(409), 7)
        self.assertEqual(stock_of("BRK-1044"), 0)

    def test_parallel_double_cancel_restores_once(self):
        n = services.create_order({"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": 3}]})[0].order_number
        services.confirm_order(n)
        codes = _in_threads(8, lambda i: self.client.post(f"/api/orders/{n}/cancel/").status_code)
        self.assertEqual(codes.count(200), 1)
        self.assertEqual(stock_of("BRK-1044"), 5)

    def test_crossing_multi_line_orders_do_not_deadlock(self):
        numbers = []
        for i in range(10):
            items = [{"sku": "BRK-1044", "quantity": 0 + 1}, {"sku": "FIL-1012", "quantity": 1}]
            numbers.append(services.create_order({"dealer_id": self.dealer.id, "items": items if i % 2 else items[::-1]})[0].order_number)
        codes = _in_threads(10, lambda i: self.client.post(f"/api/orders/{numbers[i]}/confirm/").status_code)
        self.assertEqual(codes.count(200), 5)
        self.assertEqual(stock_of("FIL-1012"), 995)

    def test_parallel_creates_get_unique_numbers(self):
        body = {"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": 1}]}
        numbers = _in_threads(15, lambda i: self.post_json("/api/orders/", body).json()["order_number"])
        self.assertEqual(len(set(numbers)), 15)
        self.assertTrue(all(re.match(r"^ORD-\d{8}-\d{4}$", n) for n in numbers))

    def test_parallel_idempotent_creates_make_one_order(self):
        key = str(uuid.uuid4())
        body = {"dealer_id": self.dealer.id, "items": [{"sku": "BRK-1044", "quantity": 1}]}
        numbers = _in_threads(10, lambda i: self.post_json("/api/orders/", body, **{"Idempotency-Key": key}).json()["order_number"])
        self.assertEqual(len(set(numbers)), 1)
        self.assertEqual(self.client.get("/api/orders/").json()["count"], 1)
