from django.test import TestCase

from core.testutils import JsonClientMixin, make_product, stock_of


class ProductApiTests(JsonClientMixin, TestCase):
    def setUp(self):
        make_product("BRK-1044", vehicle="Bajaj Pulsar 150")
        make_product("BRK-1032", vehicle="KTM Duke 390", brand="Brembo")
        make_product("FIL-1012", vehicle="Royal Enfield Classic 350", category="Filters", name="Air Filter - RE Classic 350")

    def test_list_is_paginated_with_filters(self):
        body = self.client.get("/api/products/?page_size=2").json()
        self.assertEqual(body["count"], 3)
        self.assertEqual(len(body["results"]), 2)
        self.assertIsNotNone(body["next"])
        self.assertIsNone(body["previous"])
        self.assertEqual(self.client.get("/api/products/?search=brembo").json()["count"], 1)
        self.assertEqual(self.client.get("/api/products/?search=brk-10").json()["count"], 2)
        self.assertEqual(self.client.get("/api/products/?category=Filters").json()["count"], 1)
        self.assertEqual(self.client.get("/api/products/?category=filters").json()["count"], 0)  # exact
        self.assertEqual(self.client.get("/api/products/?vehicle=duke").json()["count"], 1)

    def test_page_size_capped_at_100(self):
        for i in range(105):
            make_product(f"TST-{i:04d}")
        self.assertEqual(len(self.client.get("/api/products/?page_size=500").json()["results"]), 100)

    def test_create_product_starts_with_zero_stock(self):
        r = self.post_json("/api/products/", {"sku": "NEW-0001", "name": "Thing", "category": "Brakes", "brand": "X",
                                              "vehicle_fitment": "Universal", "price": "99.90", "description": "d"})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["stock"], 0)
        self.assertEqual(r.json()["price"], "99.90")

    def test_create_duplicate_sku(self):
        self.assertError(self.post_json("/api/products/", {"sku": "BRK-1044", "name": "x", "price": "10.00"}), 409, "DUPLICATE")

    def test_create_bad_price(self):
        for price in ("0", "-1.00", "12.345", "abc", None):
            self.assertError(self.post_json("/api/products/", {"sku": "NEW-1", "name": "x", "price": price}), 400, "VALIDATION_ERROR")

    def test_get_and_patch(self):
        self.assertError(self.client.get("/api/products/NOPE-0000/"), 404, "NOT_FOUND")
        r = self.patch_json("/api/products/BRK-1044/", {"price": "1500.00"})
        self.assertEqual(r.json()["price"], "1500.00")
        self.assertError(self.patch_json("/api/products/BRK-1044/", {"sku": "OTHER-1"}), 400, "VALIDATION_ERROR")
        self.assertError(self.patch_json("/api/products/NOPE-0000/", {"price": "1.00"}), 404, "NOT_FOUND")


class InventoryApiTests(JsonClientMixin, TestCase):
    def setUp(self):
        make_product("BRK-1044", stock=136)

    def test_set_quantity(self):
        r = self.put_json("/api/inventory/BRK-1044/", {"quantity": 25, "reason": "count"})
        self.assertEqual(r.json(), {"sku": "BRK-1044", "quantity": 25})
        self.assertEqual(stock_of("BRK-1044"), 25)

    def test_validation_and_404(self):
        for q in (-1, 2.5, "5", None, True):
            self.assertError(self.put_json("/api/inventory/BRK-1044/", {"quantity": q}), 400, "VALIDATION_ERROR")
        self.assertError(self.put_json("/api/inventory/NOPE-0000/", {"quantity": 1}), 404, "NOT_FOUND")
        self.assertEqual(stock_of("BRK-1044"), 136)
