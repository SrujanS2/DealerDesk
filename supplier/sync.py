"""Supplier catalogue sync (contract §8).

Two phases, so a failed fetch can never leave a half-applied catalogue:
  1. fetch_feed()  — pull every page into memory, retrying each request up to 5 times.
                     Any request that still fails (or a rejected key) raises SupplierUnavailable
                     before a single row has been written.
  2. apply_feed()  — validate, de-duplicate and upsert inside one database transaction.
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

import requests
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from catalog.models import Inventory, Product
from core.errors import SupplierUnavailable
from core.money import parse_price

log = logging.getLogger(__name__)

PAGE_LIMIT = 20
MAX_ATTEMPTS = 5                      # per request, in total (contract §8.3 rule 2)
BACKOFF_SECONDS = (0.5, 1, 2, 4)       # before attempts 2..5 after a 5xx / connection error
MAX_RETRY_AFTER = 30                   # never sleep longer than this on one 429
REQUEST_TIMEOUT = 10
SYNC_DEADLINE = 110                    # stay inside the 120 s budget
SYNCED_FIELDS = ("name", "category", "brand", "vehicle_fitment", "description", "price")
SYNC_LOCK_ID = 80_420_001            # pg advisory lock key for apply_feed


@dataclass
class FetchStats:
    pages_fetched: int = 0
    requests_made: int = 0


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: list = field(default_factory=list)
    pages_fetched: int = 0
    requests_made: int = 0

    def as_dict(self):
        return {"created": self.created, "updated": self.updated, "unchanged": self.unchanged,
                "rejected": self.rejected, "pages_fetched": self.pages_fetched, "requests_made": self.requests_made}


class SupplierClient:
    def __init__(self, base_url=None, api_key=None, session=None, sleep=time.sleep, clock=time.monotonic):
        self.base_url = (base_url if base_url is not None else settings.SUPPLIER_API_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.SUPPLIER_API_KEY
        self.session = session or requests.Session()
        self.sleep, self.clock = sleep, clock
        self.stats = FetchStats()

    def fetch_feed(self):
        """Return every item from every page, following next_cursor until it is null."""
        deadline = self.clock() + SYNC_DEADLINE
        items, cursor, seen_cursors = [], None, set()
        while True:
            page = self._get_page(cursor, deadline)
            self.stats.pages_fetched += 1
            batch = page.get("items")
            if not isinstance(batch, list):
                raise SupplierUnavailable("Supplier returned a page without an items list.")
            items.extend(batch)
            cursor = page.get("next_cursor")
            if not cursor:
                return items
            if cursor in seen_cursors:  # a looping cursor would never finish
                raise SupplierUnavailable("Supplier returned a repeating cursor.")
            seen_cursors.add(cursor)

    def _get_page(self, cursor, deadline):
        params = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        url = f"{self.base_url}/v1/products"
        last_problem = "no attempt made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self.clock() > deadline:
                raise SupplierUnavailable("Supplier sync ran out of time.", [{"cursor": cursor, "last_error": last_problem}])
            self.stats.requests_made += 1
            wait = None
            try:
                resp = self.session.get(url, params=params, headers={"X-Api-Key": self.api_key}, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                last_problem = f"connection error: {exc.__class__.__name__}"
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        last_problem = "invalid JSON"
                elif resp.status_code in (401, 403):
                    raise SupplierUnavailable("Supplier rejected our API key.", [{"status": resp.status_code}])
                elif resp.status_code == 429:
                    last_problem = "429 rate limited"
                    wait = _retry_after(resp.headers.get("Retry-After"))
                elif resp.status_code >= 500:
                    last_problem = f"HTTP {resp.status_code}"
                else:  # other 4xx (e.g. bad cursor): repeating the same request can't help
                    raise SupplierUnavailable(f"Supplier returned HTTP {resp.status_code}.", [{"status": resp.status_code}])
            log.warning("supplier request failed (cursor=%s, attempt %d/%d): %s", cursor, attempt, MAX_ATTEMPTS, last_problem)
            if attempt < MAX_ATTEMPTS:
                delay = wait if wait is not None else BACKOFF_SECONDS[attempt - 1]
                if self.clock() + delay > deadline:
                    raise SupplierUnavailable("Supplier sync ran out of time.", [{"cursor": cursor, "last_error": last_problem}])
                self.sleep(delay)
        raise SupplierUnavailable(f"Supplier request failed after {MAX_ATTEMPTS} attempts ({last_problem}).",
                                  [{"cursor": cursor, "attempts": MAX_ATTEMPTS, "last_error": last_problem}])


def _retry_after(header):
    try:
        return min(MAX_RETRY_AFTER, max(0.0, float(header)))
    except (TypeError, ValueError):
        return 1.0


def _parse_ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def clean_feed(raw_items):
    """Rules 4 and 5: drop invalid items (reported in `rejected`), then keep the latest version per SKU."""
    rejected, latest = [], {}
    for position, item in enumerate(raw_items):
        if not isinstance(item, dict):
            rejected.append({"supplier_sku": None, "reason": "malformed item"})
            continue
        supplier_sku = item.get("supplier_sku")
        sku = item.get("sku")
        if not isinstance(sku, str) or not sku.strip():
            rejected.append({"supplier_sku": supplier_sku, "reason": "missing sku"})
            continue
        price = parse_price(item.get("price"))
        if price is None:
            rejected.append({"supplier_sku": supplier_sku, "reason": "invalid price"})
            continue
        sku = sku.strip()
        if len(sku) > 32:
            rejected.append({"supplier_sku": supplier_sku, "reason": "sku too long"})
            continue
        ts = _parse_ts(item.get("updated_at"))
        # Order key: newest updated_at wins; items without a timestamp lose to any dated one;
        # on an exact tie the later position in the feed wins (deterministic).
        rank = (ts is not None, ts.timestamp() if ts else 0.0, position)
        if sku not in latest or rank > latest[sku][0]:
            latest[sku] = (rank, item, price)
    return {sku: (item, price) for sku, (_, item, price) in latest.items()}, rejected


def _incoming_fields(item, price):
    out = {"price": price}
    for f, limit in (("name", 255), ("category", 64), ("brand", 64), ("vehicle_fitment", 128), ("description", None)):
        v = item.get(f)
        if v is None:
            continue  # field absent in the feed: keep ours
        v = str(v).strip()
        out[f] = v[:limit] if limit else v
    return out


@transaction.atomic
def apply_feed(valid):
    """Rule 6: create / update / unchanged. Never touches Inventory.quantity of existing products."""
    created = updated = unchanged = 0
    with connection.cursor() as cur:  # one sync applies at a time; a second waits, then sees everything as unchanged
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [SYNC_LOCK_ID])
    existing ={p.sku: p for p in Product.objects.select_for_update().filter(sku__in=list(valid))}
    for sku, (item, price) in sorted(valid.items()):
        incoming = _incoming_fields(item, price)
        product = existing.get(sku)
        if product is None:
            product = Product.objects.create(sku=sku, **{"name": "", "category": "", "brand": "",
                                                         "vehicle_fitment": "", "description": "", **incoming})
            Inventory.objects.get_or_create(product=product, defaults={"quantity": 0})  # new SKU: stock 0
            created += 1
            continue
        changes = {f: v for f, v in incoming.items() if getattr(product, f) != v}
        if changes:
            Product.objects.filter(pk=product.pk).update(updated_at=timezone.now(), **changes)
            updated += 1
        else:
            unchanged += 1
    return created, updated, unchanged


def run_sync(client=None):
    client = client or SupplierClient()
    raw = client.fetch_feed()          # raises SupplierUnavailable -> nothing written
    valid, rejected = clean_feed(raw)
    created, updated, unchanged = apply_feed(valid)
    return SyncResult(created, updated, unchanged, rejected, client.stats.pages_fetched, client.stats.requests_made)
