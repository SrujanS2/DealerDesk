"""python manage.py seed_data — load data/catalogue.csv and data/dealers.csv.

Idempotent: products and dealers are upserted on their business keys (sku, dealer_code) with
INSERT ... ON CONFLICT, so running it twice never creates duplicates. Starting stock is only written
for products that have no inventory row yet: re-seeding never overwrites live stock.

The forecasting inputs (sales_history, lead_times, promo/festival calendars) are read straight from
data/ by forecasting/data.py, so they need no tables.
"""
import csv
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Inventory, Product
from core.money import parse_price
from dealers.models import Dealer

PRODUCT_FIELDS = ["name", "category", "brand", "vehicle_fitment", "price", "description"]
DEALER_FIELDS = ["name", "city", "phone", "email", "gstin", "credit_limit"]


def read_csv(path):
    if not path.exists():
        raise CommandError(f"Missing data file: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


class Command(BaseCommand):
    help = "Load the files in data/ into the database. Safe to run more than once."

    def handle(self, *args, **options):
        data_dir = settings.DATA_DIR
        products, stock, skipped = [], {}, 0
        seen = set()
        for row in read_csv(data_dir / "catalogue.csv"):
            sku, price = row.get("sku", ""), parse_price(row.get("price"))
            if not sku or price is None or sku in seen:
                skipped += 1
                continue
            seen.add(sku)
            products.append(Product(sku=sku, name=row.get("name", ""), category=row.get("category", ""),
                                    brand=row.get("brand", ""), vehicle_fitment=row.get("vehicle_fitment", ""),
                                    price=price, description=row.get("description", "")))
            try:
                stock[sku] = max(0, int(row.get("stock") or 0))
            except ValueError:
                stock[sku] = 0

        dealers, seen = [], set()
        for row in read_csv(data_dir / "dealers.csv"):
            code = row.get("dealer_code", "")
            if not code or code in seen:
                continue
            seen.add(code)
            dealers.append(Dealer(dealer_code=code, name=row.get("name", ""), city=row.get("city", ""),
                                  phone=row.get("phone", ""), email=row.get("email", ""), gstin=row.get("gstin", ""),
                                  credit_limit=Decimal(row.get("credit_limit") or "0")))

        with transaction.atomic():
            Product.objects.bulk_create(products, update_conflicts=True, unique_fields=["sku"], update_fields=PRODUCT_FIELDS)
            ids = dict(Product.objects.filter(sku__in=stock).values_list("sku", "id"))
            Inventory.objects.bulk_create([Inventory(product_id=ids[s], quantity=q) for s, q in stock.items()],
                                          ignore_conflicts=True)  # keep live stock on a re-seed
            Dealer.objects.bulk_create(dealers, update_conflicts=True, unique_fields=["dealer_code"], update_fields=DEALER_FIELDS)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(products)} products ({Product.objects.count()} in DB), "
            f"{len(dealers)} dealers ({Dealer.objects.count()} in DB)" + (f", skipped {skipped} bad rows" if skipped else "")))
