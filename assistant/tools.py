"""The three tools the LLM may call. Every figure they return is read from the database at call time.

Tool results are wrapped as data (`"type": "catalogue_data"`) and catalogue free text goes through
`sanitize_text`, which drops sentences that look like instructions to an AI. The tools themselves are
the hard boundary: none of them can confirm an order, change a price, or touch stock.
"""
import re
import uuid

from catalog.models import Product
from core.errors import ApiError
from core.money import fmt
from orders import services as order_services

from .retrieval import get_index

MAX_RESULTS = 10

TOOL_SPECS = [
    {
        "name": "search_parts",
        "description": (
            "Search the parts catalogue. Returns matching products with their CURRENT price (INR) and "
            "available stock from the database. Use it to find parts from a natural-language request. "
            "Pass the dealer's vehicle separately in `vehicle` when known."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What the dealer is looking for, e.g. 'brake pads' or a SKU."},
                "vehicle": {"type": "string", "description": "Vehicle make/model if known, e.g. 'KTM Duke 390'."},
                "category": {"type": "string", "description": "Optional exact category filter."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "check_stock",
        "description": "Get the live available stock and current price (INR) for one or more SKUs.",
        "parameters": {
            "type": "object",
            "properties": {"skus": {"type": "array", "items": {"type": "string"}, "description": "SKUs, e.g. ['BRK-1044']."}},
            "required": ["skus"],
        },
    },
    {
        "name": "create_draft_order",
        "description": (
            "Create a DRAFT order for the current dealer (it does not confirm the order or reserve stock). "
            "Only call this when the dealer has clearly asked to order / reserve / put aside specific "
            "products and quantities."),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"sku": {"type": "string"}, "quantity": {"type": "integer", "minimum": 1}},
                        "required": ["sku", "quantity"],
                    },
                }
            },
            "required": ["items"],
        },
    },
]
TOOL_NAMES = {t["name"] for t in TOOL_SPECS}

# Sentences in supplier text that address an AI / try to change behaviour are removed, not obeyed.
INJECTION_RE = re.compile(
    r"(ignore|disregard|forget|override)\b.{0,40}\b(instruction|prompt|rule|above|previous|prior)"
    r"|\b(system|developer|assistant)\s*(prompt|message|note)?\s*[\]:>]"
    r"|\b(admin|developer|god|jailbreak|dan)\s+mode\b"
    r"|\b(note|message|instruction)s?\s+(for|to)\s+(the\s+)?(ai|assistant|llm|model|bot|chatbot)s?\b"
    r"|\byou\s+are\s+now\b|\bact\s+as\b|\bpretend\b"
    r"|\b(promo|discount|coupon|voucher)\s*code\b|\b\d{1,3}\s*%\s*off\b"
    r"|\bconfirm\b.{0,30}\border\b|\bwithout\s+checking\b"
    r"|<\s*/?\s*(system|instructions?|prompt)\s*>",
    re.IGNORECASE,
)


def sanitize_text(text, limit=200):
    """Keep only sentences of supplier text that read like product information."""
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", str(text))
    kept = [s for s in sentences if s.strip() and not INJECTION_RE.search(s)]
    out = " ".join(kept).strip()
    return out[:limit]


def _product_view(p):
    stock = p.inventory.quantity if hasattr(p, "inventory") else 0
    return {
        "sku": p.sku,
        "name": sanitize_text(p.name, 160),
        "brand": sanitize_text(p.brand, 64),
        "category": p.category,
        "vehicle_fitment": p.vehicle_fitment,
        "price_inr": fmt(p.price),
        "stock_available": stock,
        "in_stock": stock > 0,
        "description": sanitize_text(p.description),
    }


def _live_products(skus):
    by_sku = {p.sku: p for p in Product.objects.select_related("inventory").filter(sku__in=skus)}
    return [by_sku[s] for s in skus if s in by_sku]


def search_parts(ctx, query="", vehicle=None, category=None, **_):
    query = str(query or "").strip()[:200]
    vehicle = str(vehicle).strip()[:100] if vehicle else None
    category = str(category).strip()[:64] if category else None
    if not query and not vehicle:
        return {"type": "catalogue_data", "results": [], "note": "Empty query."}
    index = get_index()
    skus, vehicles, vehicle_unknown = index.search(query or "", vehicle, category, limit=MAX_RESULTS)
    if not skus and category:  # a guessed category name should not hide real matches
        skus, vehicles, vehicle_unknown = index.search(query or "", vehicle, None, limit=MAX_RESULTS)
    result = {"type": "catalogue_data", "results": [_product_view(p) for p in _live_products(skus)]}
    if vehicles:
        result["vehicle_matched"] = vehicles
    if vehicle_unknown:
        result["note"] = (f"No vehicle called '{vehicle}' in our catalogue; only Universal items are shown. "
                          f"Vehicles we stock parts for: {', '.join(v for v in index.vehicles if v != 'Universal')}.")
    elif not result["results"]:
        result["note"] = "No matching products in the catalogue."
    elif len(vehicles) > 1:
        result["note"] = "The vehicle matched several models; ask the dealer which one if fitment matters."
    return result


def check_stock(ctx, skus=None, **_):
    if isinstance(skus, str):
        skus = [skus]
    skus = [str(s).strip().upper() for s in (skus or []) if str(s).strip()][:MAX_RESULTS * 2]
    found = {p.sku: p for p in _live_products(skus)}
    results = []
    for s in skus:
        if s in found:
            v = _product_view(found[s])
            results.append({k: v[k] for k in ("sku", "name", "price_inr", "stock_available", "in_stock")})
        else:
            results.append({"sku": s, "found": False, "note": "No such SKU in the catalogue."})
    return {"type": "catalogue_data", "results": results}


def create_draft_order(ctx, items=None, **_):
    clean = []
    for it in items or []:
        if isinstance(it, dict):
            sku = str(it.get("sku", "")).strip().upper()
            qty = it.get("quantity")
            if isinstance(qty, float) and qty.is_integer():
                qty = int(qty)
            if isinstance(qty, str) and qty.strip().isdigit():
                qty = int(qty.strip())
            clean.append({"sku": sku, "quantity": qty})
    body = {"dealer_id": ctx.dealer.id, "items": clean}
    # Same service and rules as POST /api/orders/. The idempotency key makes a repeated identical call in
    # the same turn return the same draft instead of creating a second one.
    key = f"assistant:{ctx.turn_id}:{order_services.request_fingerprint(body)[:32]}"
    try:
        order, created = order_services.create_order(body, idempotency_key=key)
    except ApiError as exc:
        return {"type": "order_result", "ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    data = order_services.serialize_order(order)
    if created:
        ctx.actions.append({"type": "draft_order_created", "order_number": order.order_number})
    return {
        "type": "order_result", "ok": True, "order_number": data["order_number"], "status": data["status"],
        "items": [{"sku": i["sku"], "name": i["name"], "quantity": i["quantity"], "unit_price_inr": i["unit_price"],
                   "line_total_inr": i["line_total"]} for i in data["items"]],
        "subtotal_inr": data["subtotal"], "gst_inr": data["tax_total"], "grand_total_inr": data["grand_total"],
        "note": "This is a DRAFT. It does not reserve stock until the dealer confirms it in DealerDesk.",
    }


HANDLERS = {"search_parts": search_parts, "check_stock": check_stock, "create_draft_order": create_draft_order}


class TurnContext:
    def __init__(self, dealer):
        self.dealer = dealer
        self.turn_id = uuid.uuid4().hex
        self.actions = []


def run_tool(ctx, name, arguments):
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool {name}. Available tools: {', '.join(sorted(TOOL_NAMES))}."}
    if not isinstance(arguments, dict):
        return {"error": "Tool arguments must be a JSON object."}
    try:
        return handler(ctx, **arguments)
    except TypeError as exc:
        return {"error": f"Bad arguments for {name}: {exc}"}
