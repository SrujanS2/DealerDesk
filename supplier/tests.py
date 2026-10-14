"""Supplier sync tests against the bundle's own supplier mock, served on a random local port."""
import importlib.util
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from catalog.models import Product
from core.testutils import JsonClientMixin, make_product, stock_of
from supplier.sync import SupplierClient, clean_feed

_spec = importlib.util.spec_from_file_location("mock_supplier", Path(settings.BASE_DIR) / "supplier_mock" / "mock_supplier.py")
mock_supplier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock_supplier)


def item(sku, price="100.00", ts="2026-10-06T09:00:00Z", **over):
    base = {"supplier_sku": f"SUP-{sku}", "sku": sku, "name": f"Part {sku}", "category": "Brakes", "brand": "B",
            "vehicle_fitment": "Universal", "description": "d", "price": price, "supplier_stock": 900, "updated_at": ts}
    base.update(over)
    return base


class SupplierSyncTests(JsonClientMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mock = mock_supplier.SupplierMock([], "test-key")
        cls.server = mock_supplier.serve(cls.mock, port=0)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        super().tearDownClass()

    def sync(self, key="test-key"):
        with override_settings(SUPPLIER_API_URL=self.url, SUPPLIER_API_KEY=key):
            return self.post_json("/api/sync/supplier/")

    def setUp(self):
        make_product("AAA-0001", price="100.00", stock=7, name="Part AAA-0001", category="Brakes", brand="B",
                     vehicle="Universal", description="d")
        make_product("AAA-0002", price="200.00", stock=9, name="Part AAA-0002", category="Brakes", brand="B",
                     vehicle="Universal", description="d")
        feed = [item("AAA-0001"),                                   # unchanged
                item("AAA-0002", price="250.00"),                   # updated (price)
                item("NEW-0001", price="10.00", ts="2026-10-06T09:00:00Z"),
                item("NEW-0002"), item("", supplier_sku="SUP-BAD1"),  # created x2, rejected (missing sku)
                item("BAD-0003", price="N/A"), item("BAD-0004", price="12.345")]
        feed += [item(f"FIL-{i:04d}") for i in range(30)]           # forces several pages
        feed.append(item("NEW-0001", price="15.00", ts="2026-10-07T09:00:00Z"))  # newer duplicate, on a later page
        feed.append(item("NEW-0001", price="99.00", ts="2026-10-01T09:00:00Z"))  # older duplicate, last
        self.feed = feed

    def configure(self, **kw):
        self.mock.configure(self.feed, **kw)

    def test_full_sync_with_rate_limits_and_transient_failure(self):
        self.configure(throttle_every=3, retry_after=1, transient={1: [500, 503]})
        r = self.sync()
        self.assertEqual(r.status_code, 200, r.content)
        b = r.json()
        self.assertEqual((b["created"], b["updated"], b["unchanged"]), (32, 1, 1))
        self.assertEqual(sorted(x["supplier_sku"] for x in b["rejected"]), ["SUP-BAD-0003", "SUP-BAD-0004", "SUP-BAD1"])
        self.assertEqual(b["pages_fetched"], 2)
        self.assertGreater(b["requests_made"], 3)
        self.assertEqual(Product.objects.get(sku="NEW-0001").price, 15)  # latest updated_at wins
        self.assertEqual(stock_of("NEW-0001"), 0)                         # new products start at 0
        self.assertEqual(stock_of("AAA-0002"), 9)                         # our stock is never touched
        self.assertEqual(Product.objects.get(sku="AAA-0002").price, 250)

    def test_second_run_changes_nothing(self):
        self.configure()
        self.sync()
        b = self.sync().json()
        self.assertEqual((b["created"], b["updated"], b["unchanged"]), (0, 0, 34))

    def test_outage_changes_nothing(self):
        self.configure(outage_pages=[1])
        before = list(Product.objects.order_by("sku").values_list("sku", "price"))
        self.assertError(self.sync(), 502, "SUPPLIER_UNAVAILABLE")
        self.assertEqual(list(Product.objects.order_by("sku").values_list("sku", "price")), before)

    def test_bad_key(self):
        self.configure()
        self.assertError(self.sync(key="wrong"), 502, "SUPPLIER_UNAVAILABLE")
        self.assertEqual(Product.objects.count(), 2)

    def test_at_most_five_attempts_per_request(self):
        self.configure(transient={0: [500] * 5})
        with override_settings(SUPPLIER_API_URL=self.url, SUPPLIER_API_KEY="test-key"):
            client = SupplierClient(sleep=lambda s: None)
            with self.assertRaises(Exception):
                client.fetch_feed()
        self.assertEqual(client.stats.requests_made, 5)

    def test_four_failures_then_success_is_fine(self):
        self.configure(transient={0: [502, 503, 500, 500]})
        with override_settings(SUPPLIER_API_URL=self.url, SUPPLIER_API_KEY="test-key"):
            client = SupplierClient(sleep=lambda s: None)
            self.assertEqual(len(client.fetch_feed()), len(self.feed))
        self.assertEqual(client.stats.requests_made, 4 + 1 + 1)  # 4 failures, then pages 0 and 1


class CleanFeedTests(TestCase):
    def test_rules(self):
        valid, rejected = clean_feed([item("X-1", price="0"), item("X-2", price="-3"), item("X-3", price=None),
                                      {"supplier_sku": "S", "price": "1.00"}, item("X-4", price="10.5"),
                                      item("X-5", ts="2026-01-01T00:00:00Z", price="1.00"), item("X-5", ts="2026-02-01T00:00:00Z", price="2.00")])
        self.assertEqual(len(rejected), 4)
        self.assertEqual(sorted(valid), ["X-4", "X-5"])
        self.assertEqual(str(valid["X-5"][1]), "2.00")
