# Forecast backtest

Output of `python ml/backtest.py` (rolling origin; each fold trains only on weeks before its origin and forecasts 4 weeks ahead). Lower is better.

```

== Festive fold, origin 2025-09-15 (same Diwali alignment as the real forecast)
                MAE   RMSE  WAPE%
method                           
model          8.87  12.70  19.81
same_week_ly  12.37  17.92  27.63
mean_4w       15.81  23.21  35.32
mean_12w      15.83  23.89  35.36
mean_8w       15.87  23.35  35.46
last_value    16.89  24.23  37.73
model beats best per-SKU baseline on 26/38 SKUs

== Non-festive folds ['2025-12-01', '2026-01-26', '2026-03-23', '2026-05-18', '2026-07-13', '2026-08-24']
                MAE   RMSE  WAPE%
method                           
model          6.48   9.29  18.92
mean_4w        9.26  15.09  27.02
mean_12w       9.48  14.73  27.68
mean_8w        9.58  15.08  27.96
same_week_ly  11.37  18.26  33.19
last_value    11.83  18.86  34.54
model beats best per-SKU baseline on 35/40 SKUs

== All folds
                MAE   RMSE  WAPE%
method                           
model          6.82   9.84  19.08
mean_4w       10.19  16.49  28.50
mean_12w      10.38  16.34  29.04
mean_8w       10.47  16.51  29.29
same_week_ly  11.51  18.21  32.21
last_value    12.55  19.71  35.11
model beats best per-SKU baseline on 35/40 SKUs

Worst SKUs on the festive fold (model MAE / best baseline MAE):
sku
CHN-1073    2.39
BRK-1090    2.26
BRK-1019    1.75
OIL-1004    1.54
BRK-1060    1.30
BRK-1088    1.28
```
