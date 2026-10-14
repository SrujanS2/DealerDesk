"""Rolling-origin backtest of ml/model.py against the brief's three baselines.

    python ml/backtest.py

For each origin, the model and the baselines see only weeks before the origin and forecast the next
4 weeks. The key fold is origin 2025-09-15: it sits at exactly the same distance from Diwali 2025 as
the real forecast window (2026-09-28) sits from Diwali 2026, so it tests the festive logic honestly.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model as M  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HORIZON = 4
FESTIVE_ORIGIN = "2025-09-15"
OTHER_ORIGINS = ["2025-12-01", "2026-01-26", "2026-03-23", "2026-05-18", "2026-07-13", "2026-08-24"]


def load():
    sales = pd.read_csv(DATA / "sales_history.csv", parse_dates=["week_start"])
    festivals = pd.read_csv(DATA / "festival_calendar.csv")["date"].tolist()
    skus = pd.read_csv(DATA / "lead_times.csv")["sku"].tolist()
    return sales, festivals, skus


def baselines(train, sku, weeks):
    g = train[train["sku"] == sku].set_index("week_start")["units_sold"]
    if g.empty:
        return {}
    out = {"last_value": [g.iloc[-1]] * len(weeks)}
    for n in (4, 8, 12):
        out[f"mean_{n}w"] = [g.tail(n).mean()] * len(weeks)
    out["same_week_ly"] = [g.get(w - pd.Timedelta(weeks=52), g.tail(4).mean()) for w in weeks]
    return out


def run_fold(sales, festivals, skus, origin):
    origin = pd.Timestamp(origin)
    weeks = [origin + pd.Timedelta(weeks=h) for h in range(HORIZON)]
    train = sales[sales["week_start"] < origin]                     # no peeking
    test = sales[sales["week_start"].isin(weeks)].set_index(["sku", "week_start"])
    promo = {(r.sku, r.week_start): r.promo_flag for r in test.reset_index().itertuples()}  # promos are known ahead
    model = M.fit(train, festivals, origin)
    rows = []
    for sku in skus:
        if not ((sku, weeks[0]) in test.index) or train[train["sku"] == sku].empty:
            continue
        actual = [test.loc[(sku, w), "units_sold"] for w in weeks]
        preds = {"model": [model.predict(sku, w, promo.get((sku, w), 0)) for w in weeks], **baselines(train, sku, weeks)}
        for name, p in preds.items():
            for w, a, f in zip(weeks, actual, p):
                rows.append({"origin": origin.date(), "sku": sku, "week": w.date(), "method": name, "actual": a, "forecast": f})
    return pd.DataFrame(rows)


def summarise(df, title):
    df = df.assign(err=(df.forecast - df.actual).abs(), sq=(df.forecast - df.actual) ** 2)
    g = df.groupby("method").agg(MAE=("err", "mean"), RMSE=("sq", lambda x: np.sqrt(x.mean())), sum_err=("err", "sum"), sum_act=("actual", "sum"))
    g["WAPE%"] = 100 * g.sum_err / g.sum_act
    # per-SKU MAE relative to the best baseline for that SKU (a scale-free view)
    per = df.groupby(["sku", "method"]).err.mean().unstack()
    base_cols = [c for c in per.columns if c != "model"]
    g.loc["model", "SKUs beating best baseline"] = f"{(per['model'] < per[base_cols].min(axis=1)).sum()}/{len(per)}"
    print(f"\n== {title}")
    print(g[["MAE", "RMSE", "WAPE%"]].round(2).sort_values("MAE").to_string())
    print("model beats best per-SKU baseline on", g.loc["model", "SKUs beating best baseline"], "SKUs")
    return per


if __name__ == "__main__":
    sales, festivals, skus = load()
    fest = run_fold(sales, festivals, skus, FESTIVE_ORIGIN)
    per = summarise(fest, f"Festive fold, origin {FESTIVE_ORIGIN} (same Diwali alignment as the real forecast)")
    other = pd.concat([run_fold(sales, festivals, skus, o) for o in OTHER_ORIGINS])
    summarise(other, f"Non-festive folds {OTHER_ORIGINS}")
    summarise(pd.concat([fest, other]), "All folds")
    worst = (per["model"] / per.drop(columns="model").min(axis=1)).sort_values(ascending=False).head(6)
    print("\nWorst SKUs on the festive fold (model MAE / best baseline MAE):\n" + worst.round(2).to_string())
