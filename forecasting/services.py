"""Forecast and reorder suggestions (contract §10.2).

The forecast is served straight from the committed ml/forecast.csv so the API can never disagree with
the file. Lead times and the demand history for sigma come from data/. Files are parsed once and
re-read only if their modification time changes. Stock is always read live from the database.
"""
import csv
import math
import statistics
import threading
from decimal import Decimal

from django.conf import settings

from catalog.models import Inventory
from core.errors import NotFound

SIGMA_WEEKS = 12
_cache, _lock = {}, threading.Lock()


def _read(path, parse):
    """Parse `path` with `parse(rows)`, cached until the file changes."""
    mtime = path.stat().st_mtime
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
    with open(path, newline="", encoding="utf-8-sig") as f:
        value = parse(list(csv.DictReader(f)))
    with _lock:
        _cache[path] = (mtime, value)
    return value


def _parse_forecast(rows):
    out = {}
    for r in rows:
        out.setdefault(r["sku"].strip(), []).append((r["week_start"].strip(), Decimal(r["forecast_units"].strip())))
    return {sku: sorted(weeks) for sku, weeks in out.items()}


def _parse_lead_times(rows):
    return {r["sku"].strip(): int(r["lead_time_weeks"]) for r in rows}  # file order is kept (dicts are ordered)


def _parse_sigma(rows):
    by_sku = {}
    for r in rows:
        by_sku.setdefault(r["sku"].strip(), []).append((r["week_start"].strip(), int(r["units_sold"])))
    sigma = {}
    for sku, weeks in by_sku.items():
        recent = [units for _, units in sorted(weeks)[-SIGMA_WEEKS:]]  # most recent 12 weeks (or all, if fewer)
        sigma[sku] = statistics.stdev(recent) if len(recent) >= 2 else 0.0  # sample std (n - 1)
    return sigma


def forecasts():
    return _read(settings.FORECAST_FILE, _parse_forecast)


def lead_times():
    return _read(settings.DATA_DIR / "lead_times.csv", _parse_lead_times)


def demand_sigma():
    return _read(settings.DATA_DIR / "sales_history.csv", _parse_sigma)


def _num(d):
    """Decimal -> JSON number without float noise (61.70 -> 61.7, 9 -> 9)."""
    d = d.normalize()
    return int(d) if d == d.to_integral_value() else float(d)


def forecast_for(sku):
    lt, fc = lead_times(), forecasts()
    if sku not in lt or sku not in fc:
        raise NotFound(f"No forecast for SKU {sku}.")
    return {"sku": sku, "forecast": [{"week_start": w, "forecast_units": _num(u)} for w, u in fc[sku]]}


def reorder_suggestions():
    lt, fc, sigma = lead_times(), forecasts(), demand_sigma()
    stock = dict(Inventory.objects.filter(product__sku__in=list(lt)).values_list("product__sku", "quantity"))  # live
    results = []
    for sku, L in lt.items():
        weeks = fc.get(sku, [])
        lead_time_demand = sum((u for _, u in weeks[:L]), Decimal("0"))
        safety_stock = math.ceil(1.65 * sigma.get(sku, 0.0) * math.sqrt(L))  # exactly as written in §10.2
        reorder_point = lead_time_demand + safety_stock
        current = stock.get(sku, 0)
        reorder_qty = max(0, math.ceil(reorder_point - current))
        results.append({
            "sku": sku,
            "current_stock": current,
            "lead_time_weeks": L,
            "lead_time_demand": _num(lead_time_demand),
            "safety_stock": safety_stock,
            "reorder_point": _num(reorder_point),
            "reorder_qty": reorder_qty,
        })
    return results
