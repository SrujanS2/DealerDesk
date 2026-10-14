"""Fit on all history and write ml/forecast.csv (contract §10.1).

    python ml/forecast.py

Trains on every week up to 2026-09-21 and forecasts the four weeks starting 2026-09-28, using the
planned promotions in data/promo_calendar.csv as known future inputs.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model as M  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEEKS = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]


def main():
    sales = pd.read_csv(DATA / "sales_history.csv", parse_dates=["week_start"])
    festivals = pd.read_csv(DATA / "festival_calendar.csv")["date"].tolist()
    skus = pd.read_csv(DATA / "lead_times.csv")["sku"].tolist()
    promo = pd.read_csv(DATA / "promo_calendar.csv", parse_dates=["week_start"])
    promo_lookup = {(r.sku, r.week_start): int(r.promo_flag) for r in promo.itertuples()}

    model = M.fit(sales, festivals, origin=WEEKS[0])
    out = M.forecast(model, skus, WEEKS, promo_lookup)
    assert len(out) == len(skus) * len(WEEKS) and (out["forecast_units"] >= 0).all()
    path = Path(__file__).resolve().parent / "forecast.csv"
    out.to_csv(path, index=False)
    print(f"wrote {len(out)} rows to {path}")
    print("festive multipliers:", {k: round(v, 2) for k, v in model.festive.items()})
    print("pooled promo uplift:", round(model.promo_global, 2))


if __name__ == "__main__":
    main()
