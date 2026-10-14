"""Order engine (contract §7): validation, pricing/GST, status flow, stock, numbering, idempotency.

Concurrency model (PostgreSQL, READ COMMITTED):
  * Every state change runs in one transaction that first locks the order row (SELECT ... FOR UPDATE),
    so two confirm/cancel/edit requests on the same order are serialised and see each other's result.
  * Confirm/cancel then lock the affected Inventory rows in primary-key order (no deadlocks between
    orders that share SKUs), check, and write. Stock can't be oversold because the check and the
    decrement happen while holding the row locks; the DB CHECK (quantity >= 0) is a final backstop.
"""
import hashlib
import json
from collections import OrderedDict
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone

from catalog.models import Inventory, Product, StockMovement
from core.errors import (IdempotencyConflict, InsufficientStock, InvalidTransition, NotFound, OrderLocked,
                         ValidationFailed)
from core.money import GST_RATE, fmt, to_money
from dealers.models import Dealer

from .models import DailyOrderSequence, IdempotencyKey, Order, OrderItem

S = Order.Status

# Allowed status actions (contract §7.2). Anything else -> 409 INVALID_TRANSITION.
TRANSITIONS = {
    "confirm": ({S.DRAFT}, S.CONFIRMED),
    "dispatch": ({S.CONFIRMED}, S.DISPATCHED),
    "deliver": ({S.DISPATCHED}, S.DELIVERED),
    "cancel": ({S.DRAFT, S.CONFIRMED}, S.CANCELLED),
}

MAX_QUANTITY = 1_000_000


# ------------------------------------------------------------------ pricing & serialisation
def line_amounts(unit_price, quantity):
    """GST per line (contract §7.4): tax = round_half_up(subtotal * 0.18, 2)."""
    subtotal = to_money(Decimal(unit_price) * quantity)
    tax = to_money(subtotal * GST_RATE)
    return subtotal, tax, subtotal + tax


def serialize_order(order):
    items, subtotal, tax_total = [], Decimal("0.00"), Decimal("0.00")
    for item in order.items.all():
        # DRAFT follows the live catalogue price; from CONFIRMED on, the locked price is used.
        unit_price = item.locked_unit_price if item.locked_unit_price is not None else item.product.price
        line_sub, line_tax, line_total = line_amounts(unit_price, item.quantity)
        subtotal += line_sub
        tax_total += line_tax
        items.append({
            "sku": item.product.sku,
            "name": item.product.name,
            "quantity": item.quantity,
            "unit_price": fmt(unit_price),
            "line_subtotal": fmt(line_sub),
            "line_tax": fmt(line_tax),
            "line_total": fmt(line_total),
        })
    return {
        "order_number": order.order_number,
        "dealer_id": order.dealer_id,
        "status": order.status,
        "items": items,
        "subtotal": fmt(subtotal),
        "tax_total": fmt(tax_total),
        "grand_total": fmt(subtotal + tax_total),
        "created_at": timezone.localtime(order.created_at).isoformat(),
        "updated_at": timezone.localtime(order.updated_at).isoformat(),
    }


def order_queryset():
    return Order.objects.prefetch_related("items__product")


def get_order(order_number):
    try:
        return order_queryset().get(order_number=order_number)
    except Order.DoesNotExist:
        raise NotFound(f"Order {order_number} not found.")


# ------------------------------------------------------------------ validation
def validate_items(raw_items):
    """Validate an items array; returns an OrderedDict {Product: quantity} in request order."""
    if not isinstance(raw_items, list) or not raw_items:
        raise ValidationFailed("An order needs at least one item.", [{"field": "items", "message": "must be a non-empty list"}])
    errors, wanted = [], OrderedDict()
    for i, it in enumerate(raw_items):
        if not isinstance(it, dict):
            errors.append({"field": f"items[{i}]", "message": "must be an object with sku and quantity"})
            continue
        sku, qty = it.get("sku"), it.get("quantity")
        if not isinstance(sku, str) or not sku.strip():
            errors.append({"field": f"items[{i}].sku", "message": "is required"})
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            errors.append({"field": f"items[{i}].quantity", "message": "must be an integer >= 1"})
        elif qty > MAX_QUANTITY:
            errors.append({"field": f"items[{i}].quantity", "message": f"must be at most {MAX_QUANTITY}"})
        if isinstance(sku, str) and sku.strip():
            sku = sku.strip()
            if sku in wanted:
                errors.append({"field": f"items[{i}].sku", "message": f"duplicate SKU {sku}"})
            else:
                wanted[sku] = qty
    products = {p.sku: p for p in Product.objects.filter(sku__in=list(wanted))}
    for sku in wanted:
        if sku not in products:
            errors.append({"field": "items", "message": f"unknown SKU {sku}"})
    if errors:
        raise ValidationFailed("Invalid order items: " + "; ".join(e["message"] for e in errors) + ".", errors)
    return OrderedDict((products[sku], qty) for sku, qty in wanted.items())


def validate_dealer(dealer_id):
    if isinstance(dealer_id, bool) or not isinstance(dealer_id, int) or not 0 < dealer_id < 2**63:
        raise ValidationFailed("dealer_id must be the id of an existing dealer.",
                               [{"field": "dealer_id", "message": "must be an integer dealer id"}])
    try:
        return Dealer.objects.get(pk=dealer_id)
    except Dealer.DoesNotExist:
        raise ValidationFailed(f"Unknown dealer {dealer_id}.", [{"field": "dealer_id", "message": "unknown dealer"}])


# ------------------------------------------------------------------ order numbers
def next_order_number(now=None):
    """ORD-YYYYMMDD-NNNN with the IST date and a per-day sequence.

    A single INSERT ... ON CONFLICT DO UPDATE ... RETURNING is atomic in PostgreSQL: concurrent callers
    queue on the row lock and each gets a distinct value. It runs inside the caller's transaction, so a
    rolled-back create leaves a gap (allowed) but can never hand out the same number twice.
    """
    day = timezone.localtime(now or timezone.now()).date()  # TIME_ZONE = Asia/Kolkata
    table = DailyOrderSequence._meta.db_table
    with connection.cursor() as cur:
        cur.execute(
            f"INSERT INTO {table} (day, last_value) VALUES (%s, 1) "
            f"ON CONFLICT (day) DO UPDATE SET last_value = {table}.last_value + 1 RETURNING last_value",
            [day],
        )
        seq = cur.fetchone()[0]
    return f"ORD-{day:%Y%m%d}-{seq:04d}"


# ------------------------------------------------------------------ create / edit
def request_fingerprint(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def create_order(body, idempotency_key=None):
    """Create a DRAFT. Returns (order, created: bool). created=False means an idempotent replay."""
    if not isinstance(body, dict):
        raise ValidationFailed("Request body must be a JSON object.")
    key = (idempotency_key or "").strip()[:255]
    if not key:
        return _create_draft(body), True

    fingerprint = request_fingerprint(body)
    with transaction.atomic():
        try:
            with transaction.atomic():  # savepoint
                # If another request holding the same key is mid-flight, PostgreSQL blocks this INSERT on
                # the unique index until that transaction ends: on commit we get IntegrityError and replay
                # its order below; on rollback our INSERT simply succeeds and we create the order.
                record = IdempotencyKey.objects.create(key=key, request_hash=fingerprint)
        except IntegrityError:
            record = IdempotencyKey.objects.select_related("order").get(key=key)
            if record.request_hash != fingerprint:
                raise IdempotencyConflict("This Idempotency-Key was already used with a different request body.")
            return get_order(record.order.order_number), False
        order = _create_draft(body)
        record.order = order
        record.save(update_fields=["order"])
    return order, True


@transaction.atomic
def _create_draft(body):
    dealer = validate_dealer(body.get("dealer_id"))
    items = validate_items(body.get("items"))
    order = Order.objects.create(order_number=next_order_number(), dealer=dealer, status=S.DRAFT)
    OrderItem.objects.bulk_create([OrderItem(order=order, product=p, quantity=q) for p, q in items.items()])
    return get_order(order.order_number)


def _lock_order(order_number):
    try:
        return Order.objects.select_for_update().get(order_number=order_number)
    except Order.DoesNotExist:
        raise NotFound(f"Order {order_number} not found.")


@transaction.atomic
def replace_items(order_number, body):
    order = _lock_order(order_number)
    if order.status != S.DRAFT:
        raise OrderLocked(f"Order {order_number} is {order.status} and can no longer be edited.")
    if not isinstance(body, dict):
        raise ValidationFailed("Request body must be a JSON object.")
    items = validate_items(body.get("items"))
    order.items.all().delete()
    OrderItem.objects.bulk_create([OrderItem(order=order, product=p, quantity=q) for p, q in items.items()])
    order.save(update_fields=["updated_at"])
    return get_order(order_number)


# ------------------------------------------------------------------ status actions
def _check_transition(order, action):
    allowed_from, target = TRANSITIONS[action]
    if order.status not in allowed_from:
        raise InvalidTransition(f"Cannot {action} an order that is {order.status}.",
                                [{"from": order.status, "action": action}])
    return target


@transaction.atomic
def confirm_order(order_number):
    order = _lock_order(order_number)  # serialises concurrent actions on this order
    target = _check_transition(order, "confirm")
    lines = list(order.items.select_related("product").order_by("product_id"))
    # Lock every inventory row this order touches, always in product_id order (deadlock-free).
    stock = {inv.product_id: inv for inv in
             Inventory.objects.select_for_update().filter(product_id__in=[l.product_id for l in lines]).order_by("product_id")}
    short = []
    for line in lines:
        available = stock[line.product_id].quantity if line.product_id in stock else 0
        if line.quantity > available:
            short.append((line, available))
    if short:  # all-or-nothing: raising rolls back; nothing has been written yet
        raise InsufficientStock(
            " ".join(f"Insufficient stock for {l.product.name}. Available: {a}, Requested: {l.quantity}" for l, a in short),
            [{"sku": l.product.sku, "requested": l.quantity, "available": a} for l, a in short],
        )
    for line in lines:
        inv = stock[line.product_id]
        Inventory.objects.filter(pk=inv.pk).update(quantity=F("quantity") - line.quantity)
        StockMovement.objects.create(product_id=line.product_id, order=order, kind=StockMovement.Reason.ORDER_CONFIRM,
                                     delta=-line.quantity, quantity_after=inv.quantity - line.quantity)
        line.locked_unit_price = line.product.price  # price lock (contract §7.4)
    OrderItem.objects.bulk_update(lines, ["locked_unit_price"])
    order.status, order.confirmed_at = target, timezone.now()
    order.save(update_fields=["status", "confirmed_at", "updated_at"])
    return get_order(order_number)


@transaction.atomic
def cancel_order(order_number):
    order = _lock_order(order_number)
    was = order.status
    target = _check_transition(order, "cancel")
    if was == S.CONFIRMED:
        # The status check above ran under the order row lock, so only one cancel can ever get here
        # for a CONFIRMED order: stock is restored exactly once.
        lines = list(order.items.order_by("product_id"))
        stock = {inv.product_id: inv for inv in
                 Inventory.objects.select_for_update().filter(product_id__in=[l.product_id for l in lines]).order_by("product_id")}
        for line in lines:
            inv = stock.get(line.product_id) or Inventory.objects.create(product_id=line.product_id, quantity=0)
            Inventory.objects.filter(pk=inv.pk).update(quantity=F("quantity") + line.quantity)
            StockMovement.objects.create(product_id=line.product_id, order=order, kind=StockMovement.Reason.ORDER_CANCEL,
                                         delta=line.quantity, quantity_after=inv.quantity + line.quantity)
    order.status = target
    order.save(update_fields=["status", "updated_at"])
    return get_order(order_number)


@transaction.atomic
def advance_order(order_number, action):
    """dispatch / deliver: pure status moves with no stock effect."""
    order = _lock_order(order_number)
    order.status = _check_transition(order, action)
    order.save(update_fields=["status", "updated_at"])
    return get_order(order_number)
