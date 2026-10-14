"""Small factories shared by the test modules."""
import json
from decimal import Decimal

from catalog.models import Inventory, Product
from dealers.models import Dealer


def make_product(sku="BRK-1044", price="1459.50", stock=100, name=None, vehicle="Bajaj Pulsar 150", category="Brakes",
                 brand="Endurance", description="Direct-fit replacement."):
    p = Product.objects.create(sku=sku, name=name or f"Brake Pad Set - {vehicle}", category=category, brand=brand,
                               vehicle_fitment=vehicle, price=Decimal(price), description=description)
    Inventory.objects.create(product=p, quantity=stock)
    return p


def make_dealer(code="DLR-001", name="ABC Motors"):
    return Dealer.objects.create(dealer_code=code, name=name, city="Kochi")


def stock_of(sku):
    return Inventory.objects.get(product__sku=sku).quantity


class JsonClientMixin:
    def post_json(self, url, body=None, **headers):
        return self.client.post(url, data=json.dumps(body if body is not None else {}), content_type="application/json", headers=headers)

    def put_json(self, url, body, **headers):
        return self.client.put(url, data=json.dumps(body), content_type="application/json", headers=headers)

    def patch_json(self, url, body):
        return self.client.patch(url, data=json.dumps(body), content_type="application/json")

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        err = response.json()["error"]
        self.assertEqual(err["code"], code)
        self.assertIsInstance(err["message"], str)
        self.assertIsInstance(err["details"], list)
        return err
