# Forecasting

- `model.py` — the festival-aligned multiplicative model (level x Diwali-relative lift x promo uplift).
- `backtest.py` — rolling-origin validation against last value / recent mean / same week last year. Results: `BACKTEST.md`.
- `forecast.py` — fits on all history and writes `forecast.csv` (40 SKUs x 4 weeks = 160 rows).

```bash
python ml/backtest.py
python ml/forecast.py
```
