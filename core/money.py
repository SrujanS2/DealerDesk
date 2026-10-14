"""Money helpers. All money is Decimal end to end; floats never touch a rupee amount."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PAISA = Decimal("0.01")
GST_RATE = Decimal("0.18")


def to_money(value):
    """Quantize a Decimal to 2 places with ROUND_HALF_UP (0.005 -> 0.01)."""
    return Decimal(value).quantize(PAISA, rounding=ROUND_HALF_UP)


def fmt(value):
    """Money as the contract's JSON string with exactly 2 decimals: "1459.50"."""
    return str(to_money(value))


def parse_price(raw):
    """Parse a price from JSON/CSV input.

    Returns a Decimal that is > 0 with at most 2 decimal places, or None if invalid.
    Accepts strings ("1459.50") and JSON numbers; booleans, NaN/Infinity and >2 decimals are rejected.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, float):
        raw = repr(raw)  # 1459.5 -> "1459.5"; avoids binary float artefacts
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    if value.normalize().as_tuple().exponent < -2:  # more than 2 significant decimals, e.g. 12.345
        return None
    if value >= Decimal("10000000000"):  # does not fit DecimalField(max_digits=12, decimal_places=2)
        return None
    return value.quantize(PAISA)
