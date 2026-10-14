"""Catalogue and inventory business logic (contract §4, §5)."""
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.errors import Duplicate, NotFound, ValidationFailed
from core.money import fmt, parse_price

from .models import Inventory, Product, StockMovement

TEXT_FIELDS = {"name": 255, "category": 64, "brand": 64, "vehicle_fitment": 128, "description": None}


def serialize_product(p):
    inv = getattr(p, "inventory", None)
    return {
        "sku": p.sku,
        "name": p.name,
        "category": p.category,
        "brand": p.brand,
        "vehicle_fitment": p.vehicle_fitment,
        "price": fmt(p.price),
        "stock": inv.quantity if inv else 0,
        "description": p.description,
    }


def get_product(sku):
    try:
        return Product.objects.select_related("inventory").get(sku=sku)
    except Product.DoesNotExist:
        raise NotFound(f"Product {sku} not found.")


def _require_object(data):
    if not isinstance(data, dict):
        raise ValidationFailed("Request body must be a JSON object.")


def _clean_text(data, field, errors, required=False):
    if field not in data:
        if required:
            errors.append({"field": field, "message": "is required"})
        return None
    value = data[field]
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        errors.append({"field": field, "message": "must be a string"})
        return None
    value = value.strip()
    if required and not value:
        errors.append({"field": field, "message": "must not be empty"})
        return None
    limit = TEXT_FIELDS.get(field)
    if limit and len(value) > limit:
        errors.append({"field": field, "message": f"must be at most {limit} characters"})
        return None
    return value


def _clean_price(data, errors, required):
    if "price" not in data:
        if required:
            errors.append({"field": "price", "message": "is required"})
        return None
    price = parse_price(data["price"])
    if price is None:
        errors.append({"field": "price", "message": "must be a positive amount with at most 2 decimal places"})
    return price


def create_product(data):
    _require_object(data)
    errors = []
    sku = data.get("sku")
    if not isinstance(sku, str) or not sku.strip():
        errors.append({"field": "sku", "message": "is required"})
    elif len(sku.strip()) > 32:
        errors.append({"field": "sku", "message": "must be at most 32 characters"})
    fields = {f: _clean_text(data, f, errors, required=(f == "name")) for f in TEXT_FIELDS}
    price = _clean_price(data, errors, required=True)
    if errors:
        raise ValidationFailed("Invalid product.", errors)
    sku = sku.strip()
    if Product.objects.filter(sku=sku).exists():
        raise Duplicate(f"A product with SKU {sku} already exists.", [{"field": "sku", "message": "already exists"}])
    try:
        with transaction.atomic():
            product = Product.objects.create(sku=sku, price=price, **{k: v or "" for k, v in fields.items()})
            Inventory.objects.create(product=product, quantity=0)  # new products start with stock 0
    except IntegrityError:  # lost a race against a concurrent create of the same SKU
        raise Duplicate(f"A product with SKU {sku} already exists.", [{"field": "sku", "message": "already exists"}])
    return get_product(sku)


def update_product(sku, data):
    _require_object(data)
    product = get_product(sku)
    errors = []
    if "sku" in data and data["sku"] != product.sku:
        errors.append({"field": "sku", "message": "cannot be changed"})
    changes = {}
    for f in TEXT_FIELDS:
        if f in data:
            value = _clean_text(data, f, errors, required=(f == "name"))
            if value is not None:
                changes[f] = value
    if "price" in data:
        price = _clean_price(data, errors, required=True)
        if price is not None:
            changes["price"] = price
    if errors:
        raise ValidationFailed("Invalid product update.", errors)
    if changes:
        Product.objects.filter(pk=product.pk).update(updated_at=timezone.now(), **changes)
    return get_product(sku)


def set_inventory(sku, data):
    """PUT /api/inventory/{sku}/: set available stock to exactly `quantity`."""
    product = get_product(sku)  # 404 before validating the body
    _require_object(data)
    qty = data.get("quantity")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
        raise ValidationFailed("quantity must be an integer >= 0.", [{"field": "quantity", "message": "must be an integer >= 0"}])
    reason = data.get("reason") or ""
    if not isinstance(reason, str):
        raise ValidationFailed("reason must be a string.", [{"field": "reason", "message": "must be a string"}])
    with transaction.atomic():
        # Lock the row so a concurrent order confirm can't interleave with the overwrite.
        inv, _ = Inventory.objects.select_for_update().get_or_create(product=product)
        delta = qty - inv.quantity
        inv.quantity = qty
        inv.save(update_fields=["quantity", "updated_at"])
        StockMovement.objects.create(product=product, kind=StockMovement.Reason.MANUAL, delta=delta,
                                     quantity_after=qty, note=reason[:255])
    return {"sku": product.sku, "quantity": qty}
