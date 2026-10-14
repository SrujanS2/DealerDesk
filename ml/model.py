"""Festival-aligned multiplicative demand model for the 40 forecast SKUs.

    forecast(sku, week) = level(sku) x festive(weeks_to_diwali(week)) x promo(sku, week)

level    Current baseline demand: an exponentially-weighted mean of the SKU's recent non-promo weeks
         (each history week first divided by its own festive factor, so a level estimated next to a
         festival is not inflated).
festive  Demand multiplier by "weeks relative to the Diwali week" (-8..+4), learned from past
         seasons, pooled across SKUs. Indexing by distance-to-Diwali instead of calendar week is
         what lets the lift move with the festival (2024-11-01, 2025-10-21, 2026-11-08).
promo    Promotion uplift: per-SKU ratio of promo weeks to their local non-promo baseline, shrunk
         towards the pooled uplift when the SKU has few promo weeks.

Special cases
  * Intermittent SKUs (>= 30% zero weeks): level = mean of the last 26 weeks (no EWMA chasing zeros).
  * New SKUs (< 13 weeks of history): level = mean of the last 4 weeks.

Every estimate is computed only from the history passed in; `fit` never sees data on or after
`origin` (see the cut in fit()).
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

REL_MIN, REL_MAX = -8, 4          # weeks around the Diwali week that can carry a festive effect
LEVEL_HALFLIFE = 4                # weeks; EWMA half-life of the level
LEVEL_WINDOW = 12                 # non-promo weeks used for the level
PROMO_PRIOR_WEIGHT = 4            # pseudo-observations pulling a SKU's promo uplift to the pooled one
INTERMITTENT_ZERO_SHARE = 0.30
NEW_SKU_WEEKS = 13
SENS_PRIOR_WEIGHT = 1.0          # in units of sum((lift-1)^2); ~3 strongly-festive weeks


def diwali_week_starts(festival_dates):
    """Monday of the week containing each Diwali."""
    days = pd.to_datetime(pd.Series(festival_dates))
    return sorted((days - pd.to_timedelta(days.dt.dayofweek, unit="D")).dt.normalize())


def weeks_to_diwali(week_start, diwali_weeks):
    """Signed distance in weeks to the nearest Diwali week (0 = the Diwali week itself)."""
    week_start = pd.Timestamp(week_start)
    return min(((week_start - d).days // 7 for d in diwali_weeks), key=abs)


@dataclass
class FestivalModel:
    origin: pd.Timestamp
    diwali_weeks: list
    festive: dict = field(default_factory=dict)        # rel week -> multiplier
    promo_global: float = 1.0
    promo_sku: dict = field(default_factory=dict)
    level: dict = field(default_factory=dict)
    sensitivity: dict = field(default_factory=dict)  # sku -> how strongly it follows the pooled festive lift

    def festive_factor(self, week_start, sku=None):
        rel = weeks_to_diwali(week_start, self.diwali_weeks)
        pooled = self.festive.get(rel, 1.0)
        return 1.0 + self.sensitivity.get(sku, 1.0) * (pooled - 1.0)

    def predict(self, sku, week_start, promo_flag):
        value = self.level.get(sku, 0.0) * self.festive_factor(week_start, sku)
        if promo_flag:
            value *= self.promo_sku.get(sku, self.promo_global)
        return max(0.0, float(value))


def _local_baseline(series, promo):
    """Centered rolling median of non-promo weeks: the 'normal' demand around each week."""
    clean = series.where(promo == 0)
    return clean.rolling(9, center=True, min_periods=3).median()


def fit(sales, festival_dates, origin):
    """Fit on weekly sales strictly before `origin` (the first week being forecast)."""
    origin = pd.Timestamp(origin)
    history = sales[sales["week_start"] < origin].copy()  # <- the only data the model ever sees
    model = FestivalModel(origin=origin, diwali_weeks=diwali_week_starts(festival_dates))
    history["rel"] = history["week_start"].map(lambda w: weeks_to_diwali(w, model.diwali_weeks))
    history = history.sort_values(["sku", "week_start"])

    # 1) Festive multipliers. For every SKU-season, compare each week near Diwali with the SKU's
    #    "normal" level: the median of its non-promo weeks 9..20 weeks before the Diwali week, or, if the
    #    season starts too early in the data, 5..16 weeks after it. Pool with a median across SKU-seasons.
    ratios, sku_ratios = {}, {}
    for sku, g in history.groupby("sku"):
        g = g.set_index("week_start")
        if len(g) < 26 or g["units_sold"].mean() < 3:
            continue  # too short / too sparse to say anything about seasonality
        for dw in model.diwali_weeks:
            pre = g[(g.index >= dw - pd.Timedelta(weeks=20)) & (g.index <= dw - pd.Timedelta(weeks=9)) & (g["promo_flag"] == 0)]
            post = g[(g.index >= dw + pd.Timedelta(weeks=5)) & (g.index <= dw + pd.Timedelta(weeks=16)) & (g["promo_flag"] == 0)]
            ref = pre["units_sold"] if len(pre) >= 6 else post["units_sold"]
            if len(ref) < 6 or ref.median() <= 0:
                continue
            base = ref.median()
            win = g[(g["rel"] >= REL_MIN) & (g["rel"] <= REL_MAX) & (g["promo_flag"] == 0)]
            win = win[(win.index >= dw + pd.Timedelta(weeks=REL_MIN)) & (win.index <= dw + pd.Timedelta(weeks=REL_MAX))]
            for _, row in win.iterrows():
                ratios.setdefault(int(row["rel"]), []).append(row["units_sold"] / base)
                sku_ratios.setdefault(sku, []).append((int(row["rel"]), row["units_sold"] / base))
    for rel in range(REL_MIN, REL_MAX + 1):
        r = ratios.get(rel, [])
        # Shrink weakly-supported weeks towards 1.0 (no effect).
        n = len(r)
        model.festive[rel] = float((np.median(r) * n + 1.0 * 5) / (n + 5)) if n else 1.0

    # Per-SKU sensitivity: least-squares slope of (observed ratio - 1) on (pooled lift - 1) over the SKU's
    # strongly-festive weeks, shrunk towards 1.0 (= follows the pooled curve) with SENS_PRIOR_WEIGHT.
    for sku, obs in sku_ratios.items():
        x = np.array([model.festive[rel] - 1.0 for rel, _ in obs])
        y = np.array([ratio - 1.0 for _, ratio in obs])
        keep = np.abs(x) >= 0.2
        if keep.sum() == 0:
            continue
        x, y = x[keep], y[keep]
        sxx = float((x * x).sum())
        beta = float((x * y).sum() / sxx)
        model.sensitivity[sku] = float(np.clip((beta * sxx + 1.0 * SENS_PRIOR_WEIGHT) / (sxx + SENS_PRIOR_WEIGHT), 0.0, 2.0))

    # 2) Promotion uplift relative to the local non-promo baseline, de-seasonalised.
    promo_obs = {}
    for sku, g in history.groupby("sku"):
        g = g.set_index("week_start")
        fest = np.array([model.festive_factor(w, sku) for w in g.index])
        adj = g["units_sold"] / fest
        base = _local_baseline(adj, g["promo_flag"])
        sel = (g["promo_flag"] == 1) & (base > 0)
        if sel.any():
            promo_obs[sku] = list((adj[sel] / base[sel]).values)
    pooled = [v for vs in promo_obs.values() for v in vs]
    model.promo_global = float(np.median(pooled)) if pooled else 1.0
    for sku, vs in promo_obs.items():
        n = len(vs)
        model.promo_sku[sku] = float((np.median(vs) * n + model.promo_global * PROMO_PRIOR_WEIGHT) / (n + PROMO_PRIOR_WEIGHT))

    # 3) Level per SKU, on de-seasonalised, non-promo weeks.
    for sku, g in history.groupby("sku"):
        g = g.set_index("week_start")
        fest = np.array([model.festive_factor(w, sku) for w in g.index])
        adj = (g["units_sold"] / fest)
        if len(g) < NEW_SKU_WEEKS:
            model.level[sku] = float(adj[g["promo_flag"] == 0].tail(4).mean() if (g["promo_flag"] == 0).any() else adj.tail(4).mean())
            continue
        if (g["units_sold"] == 0).mean() >= INTERMITTENT_ZERO_SHARE:
            model.level[sku] = float(adj.tail(26).mean())
            continue
        clean = adj[g["promo_flag"] == 0].tail(LEVEL_WINDOW)
        weights = 0.5 ** (np.arange(len(clean))[::-1] / LEVEL_HALFLIFE)
        model.level[sku] = float(np.average(clean.values, weights=weights))
    return model


def forecast(model, skus, weeks, promo_lookup):
    rows = []
    for sku in skus:
        for w in weeks:
            rows.append({"sku": sku, "week_start": pd.Timestamp(w).strftime("%Y-%m-%d"),
                         "forecast_units": round(model.predict(sku, w, promo_lookup.get((sku, pd.Timestamp(w)), 0)), 2)})
    return pd.DataFrame(rows)
