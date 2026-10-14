# DECISIONS.md — AI / ML track

Line numbers refer to the files as committed.

## 1. Schema: models, relationships, on_delete

| Model | Purpose | Key constraints |
|---|---|---|
| `Product` (`catalog/models.py:5`) | Catalogue row. `sku` is the business key used in URLs and order lines. | `sku` unique; `price` `DECIMAL(12,2)` with DB check `price > 0`; index on `category` |
| `Inventory` (`catalog/models.py:26`) | Available stock, 1:1 with Product | DB check `quantity >= 0` (`catalog/models.py:36`) |
| `StockMovement` (`catalog/models.py:42`) | Append-only ledger of every stock change (audit only) | index `(product, created_at)` |
| `Dealer` (`dealers/models.py:4`) | Dealer master; `credit_limit` stored, not enforced | `dealer_code` unique |
| `Order` (`orders/models.py:5`) | Header: number, dealer, status, timestamps | `order_number` unique; indexes `(dealer, status)`, `(status)` |
| `OrderItem` (`orders/models.py:29`) | Line: product + quantity; `locked_unit_price` stays NULL while DRAFT and is set on confirm (`orders/models.py:36`) | unique `(order, product)`; check `quantity >= 1` |
| `DailyOrderSequence` (`orders/models.py:46`) | One row per IST day; last NNNN issued | PK `day` |
| `IdempotencyKey` (`orders/models.py:54`) | `Idempotency-Key` → request hash + order | `key` unique |
| `ChatSession` / `ChatMessage` (`assistant/models.py:4`, `:20`) | Assistant memory per (session_id, dealer) | unique `(session_id, dealer)` |

Inventory is its own table rather than a column on Product. Confirming an order locks inventory rows with `SELECT … FOR UPDATE`, so a separate table means those locks never block catalogue writes such as a supplier price update, and the reverse. Money is never stored as a float. Line amounts are derived from `unit_price × quantity` rather than stored. A DRAFT's price must follow the catalogue, and a CONFIRMED order's price is frozen in `locked_unit_price`.

**on_delete choices**
- `Inventory.product` CASCADE (`catalog/models.py:30`): stock has no meaning without the product.
- `Order.dealer` PROTECT (`orders/models.py:15`): orders are financial records, so deleting a dealer must never delete them.
- `OrderItem.order` CASCADE (`orders/models.py:31`): a line is part of its order.
- `OrderItem.product` PROTECT (`orders/models.py:33`): a product that appears on any order can't be deleted, so history stays complete.
- `StockMovement.product` CASCADE (`catalog/models.py:51`): the ledger belongs to the product. In practice PROTECT on OrderItem already prevents deleting any product that was ever ordered.
- `StockMovement.order` SET_NULL (`catalog/models.py:52`): keep the stock history even if an order row were ever removed.
- `IdempotencyKey.order` CASCADE (`orders/models.py:60`): the key exists only to point at its order.
- `ChatSession.dealer` CASCADE (`assistant/models.py:12`) and `ChatMessage.session` CASCADE (`assistant/models.py:24`): chat memory is disposable and holds no financial data.

## 2. Retrieval

`assistant/retrieval.py` uses lexical BM25 plus an explicit vehicle resolver, with no embeddings. This is deliberate:

- **Fitment is decided by exact tokens.** "Duke 390" and "Duke 200" are close neighbours in embedding space, and recommending the wrong one is the worst failure for a parts dealer. `resolve_vehicle` (`assistant/retrieval.py:105`) requires every number the dealer typed to appear in the fitment (`:122`). Aliases ("RE" → Royal Enfield, "ns 200" → NS200) are handled by tokenising both split and joined forms.
- **Ranking.** BM25 per query word group (the word plus its synonyms, `SYNONYMS` at `:28`), multiplied by coverage² (`:173`). So "brake pads" ranks Brake Pad Sets far above Tank Pads, which only match "pad". Results are filtered to the resolved fitment plus Universal items. If the vehicle isn't in the catalogue at all (e.g. Activa), only Universal items are returned, together with the list of vehicles we do stock (`:155`).
- **Index.** The 600 products sit in memory and are rebuilt when the catalogue fingerprint (count, max `updated_at`) changes (`:189`). Search is deterministic, which matters because the grader runs each test 3 times. It also needs no extra API calls or model downloads. **Price and stock are never part of the index**: they are read from the database on every tool call.

**Where it fails:** pure semantic paraphrases with no shared words ("something to stop my bike" for brake pads) unless the lexicon covers them; misspellings ("brk pads"); and vehicles we don't stock. The LLM partly makes up for this by rewriting the dealer's text into catalogue terms before calling `search_parts`. Hybrid search with a small embedding model would be my next step.

## 3. The tool-calling loop

1. `ChatView` (`assistant/views.py`) validates `session_id`, `dealer_id` and `message`, then calls `run_turn` (`assistant/agent.py:212`).
2. `run_turn` loads memory for this (session_id, dealer) with `load_history` (`:84`). It builds `[system prompt] + history + [user]` (`:219`). The system prompt (`:34`) states the grounding, fitment, draft-only, injection and off-topic rules.
3. `_answer` (`:202`) runs up to 6 rounds of `_tool_round` (`:182`). Each round calls the provider through `assistant/llm.py` (OpenAI-compatible client for Gemini, OpenAI and Groq at `:121`; Anthropic converted at `:177`) with the three tool schemas. Every tool call the model returns is appended to `tool_calls` in order (`:193`), executed against the live database by `run_tool` (`assistant/tools.py:192`), and fed back as a `tool` message (`:194`). When the model answers with text, the loop ends. After 36 seconds tools are no longer offered, forcing a text answer (`:184`), which keeps the response under 60 seconds.
4. The draft reply is checked by `verify_reply` (`:225`, defined at `:141`). If it fails, the model gets one repair round with the specific problems listed (`REPAIR_PROMPT`, `:53`). The repair round can call tools again.
5. The turn is persisted (`:243`) and the response returned. `cited_skus` (`:165`) are the SKUs mentioned in the reply that exist in the database. `actions` come from `create_draft_order` (`assistant/tools.py:151`).

## 4. Prices and stock: never a stale figure

- **Tools read the database at call time.** `_product_view` (`assistant/tools.py:93`) reads `price` and `Inventory.quantity` on every call; nothing is cached.
- **Old figures are removed from memory.** On replay, tool results from earlier turns lose every price/stock/total field (`_redact`, `assistant/agent.py:72`), keeping only SKUs, names and order numbers. To state a figure, the model has to call a tool in this turn.
- **Code checks every figure.** `verify_reply` (`assistant/agent.py:141`) extracts every rupee amount and stock-like count from the reply and checks each against figures returned by tools *in this turn* (`_collect_figures`, `:108`). Price × quantity is allowed for quantities the dealer mentioned. Figures stated without any tool call this turn, unknown SKUs, and discount promises all trigger a repair round. Tested in `assistant/tests.py` (`test_invented_figure_triggers_repair`).
- **Drafts use the same order rules.** `create_draft_order` calls the same `orders.services.create_order` as `POST /api/orders/`, with an idempotency key scoped to the turn (`assistant/tools.py:165`), so a repeated identical call can't create two drafts. Order totals come from the same GST code.

**Limit:** the figure check is regex-based. Numbers written in words ("forty-two units") would get past it.

## 5. Untrusted supplier descriptions

Layered defences:
1. **Sanitising.** `sanitize_text` (`assistant/tools.py:83`) drops any sentence of catalogue text matching `INJECTION_RE` (`:70`): instructions to AIs, "ignore previous…", fake `[system]:` tags, "admin mode", discount codes, "confirm … order", "without checking". On the real catalogue it removes exactly the two planted sentences (CHN-1037, BDY-1070) and changes nothing else.
2. **Labelling.** Tool results are JSON tagged `"type": "catalogue_data"`, and the system prompt says catalogue text is data written by suppliers, never instructions (`assistant/agent.py:49`).
3. **Capability limits, the real guarantee.** No tool can confirm orders, change prices or touch stock. Even a fully hijacked model can only create a DRAFT under the requesting dealer's id, with prices computed by our code.
4. **Output check.** A reply offering "% off", promo or coupon codes or `VIKMO-…` codes fails verification (`PROMISE_RE`, `assistant/agent.py:67`).

**Where it stops working:** a paraphrased injection that avoids every pattern (for example, phrased as a product fact: "this item is free for all dealers this week") gets past layer 1. It then depends on the model following the system prompt. Layers 3 and 4 still stop any action or explicit discount code. An LLM-based classifier on catalogue text at ingest time would be the next step.

## 6. Forecasting approach and validation

`ml/model.py` is a festival-aligned multiplicative model:

`forecast = level(sku) × festive(weeks to Diwali, sku) × promo(sku)` (only when a promo is planned, `ml/model.py:64`)

- **festive:** a multiplier for each week from 8 weeks before to 4 weeks after the Diwali week. It is learned by pooling, across SKUs, sales near each past Diwali divided by the SKU's normal non-promo level (`ml/model.py:83`). It is indexed by distance to Diwali (`weeks_to_diwali`, `:41`), not calendar week, so the lift moves with the festival: 2024-11-01, 2025-10-21, 2026-11-08. A per-SKU sensitivity, shrunk towards 1, scales the pooled curve (`:109`).
- **promo:** each SKU's promo-week uplift over its local baseline, shrunk towards the pooled ≈2.1× (`:122`). I checked history and found promo and festive effects multiply, not add: observed festive promo weeks match or exceed the product.
- **level:** an exponentially weighted mean (half-life 4 weeks) of the last 12 non-promo weeks, each divided by its own festive factor (`:138`).

**Validation:** rolling-origin backtest in `ml/backtest.py`, with results in `ml/BACKTEST.md`. The key fold uses origin **2025-09-15**: it sits exactly as far from Diwali 2025 as the real forecast window sits from Diwali 2026 (5 to 2 weeks before), and the model there learns its festive curve from 2024 alone. Six further non-festive folds cover Dec 2025 to Aug 2026. Against the brief's baselines (last value, recent mean over 4, 8 or 12 weeks, same week last year):

| Fold | Model WAPE | Best baseline WAPE |
|---|---|---|
| Festive (2025-09-15) | **19.8%** | 27.6% (same week last year) |
| Non-festive (6 folds) | **18.9%** | 27.0% (4-week mean) |

The model beats the best baseline per SKU on 26/38 SKUs in the festive fold and 35/40 overall. I fixed the settings before tuning; a sweep of half-life and window changed festive WAPE by less than 1 point, so I kept the original values.

**The line that stops leakage:** `ml/model.py:78`, `history = sales[sales["week_start"] < origin].copy()`. Every estimate inside `fit` uses only `history`. The backtest also cuts the training data independently (`ml/backtest.py:46`). The only future input is the planned promo calendar, which the brief says is known in advance.

## 7. Worst SKUs, and how each special case is handled

- **Worst in the festive backtest:** CHN-1073, BRK-1090 and BRK-1019 (2.4×, 2.3× and 1.8× the best baseline's MAE). CHN-1073 barely responds to Diwali, so applying the pooled lift over-forecasts it. BRK-1019 has strong promo spikes that land in festive weeks, and its 2025 response was larger than its 2024 one. With only two Diwali seasons, per-SKU sensitivity is noisy; that's why it is shrunk.
- **Promotions:** the planned flags in `promo_calendar.csv` are used as known future inputs, with a per-SKU uplift shrunk towards the pooled uplift.
- **Diwali:** weeks-to-Diwali indexing; see Q6. The 2026 window is 5 to 2 weeks before Diwali, so the lift is about 1.05× to 1.6×, lower than "same week last year" implies. Diwali 2025 was 18 days earlier, which is exactly why that baseline over-forecasts.
- **Rarely sold SKUs** (BRK-1088, ELE-1006, ELE-1031, GRP-1043, with 38–60% zero weeks): level is the plain mean of the last 26 weeks (`ml/model.py:146`), with no EWMA chasing single sales, and they get no festive sensitivity of their own.
- **New SKUs** (CHN-1006, BRK-1105, 6 weeks each): level is the mean of the last 4 weeks (`ml/model.py:143`), times the pooled festive curve. Their demand is still ramping up, so they may be under-forecast.

## 8. Weakest part, and what I'd do with two more days

**Weakest:** the assistant has only been tested against a scripted fake LLM in the unit tests, plus `scripts/assistant_eval.py` for live runs. Its live behaviour depends on the provider. My guardrails (figure verification, redacted memory, capability limits) reduce variance, but the regex-based figure check and pattern-based injection filter are heuristics.

**With two more days:**
1. Run `scripts/assistant_eval.py` across all four providers, 20 runs each, and tune the prompt on the failures.
2. Hybrid retrieval: BM25 plus a small embedding model, with a fuzzy-matching layer for misspelt vehicles.
3. A probabilistic forecast (quantiles) so safety stock reflects forecast error, not just historical sigma, plus a hierarchical prior for festive sensitivity.
4. A React portal: catalogue, cart → confirm with stock errors, assistant chat.

---

### Bonus parts (Django-track features also built)

- **Overselling:** `confirm_order` (`orders/services.py:223`) locks the order row (`:224`), then the inventory rows in `product_id` order (`:229`), checks every line, and raises `INSUFFICIENT_STOCK` before writing anything if any line is short (`:235`). Only then does it decrement (`:242`). Without the locks, two confirms could both read stock=1 and both succeed. The DB check `quantity >= 0` is a last backstop.
- **GST:** `line_amounts` (`orders/services.py:41`) uses `Decimal` throughout and rounds tax per line with `ROUND_HALF_UP` (`:44`, `core/money.py:10`). Floats would produce errors like 18.044999…; Decimal's default `ROUND_HALF_EVEN` would round 18.045 to 18.04.
- **Order numbers:** a single atomic `INSERT … ON CONFLICT (day) DO UPDATE … RETURNING` (`orders/services.py:144`).
- **Idempotency:** the key row is inserted first (`:171`). A concurrent duplicate blocks on the unique index until the first transaction commits, then replays the stored order (`:172`).
- **Transitions:** a single `TRANSITIONS` table (`:30`) checked under the order row lock (`:214`). A cancel restores stock only from CONFIRMED, while holding that lock (`:257`), so restoration happens exactly once.
- **Supplier sync:** fetch everything first (`supplier/sync.py:63`), with at most 5 attempts per request, honouring `Retry-After` on 429 (`:104`) and backing off after 5xx. Then validate and de-duplicate by latest `updated_at` (`:135`, `:158`), and apply in one transaction under an advisory lock (`:176`). A fetch failure raises before anything is written, so nothing changes. Comparing every synced field makes a second run report `updated: 0`.
