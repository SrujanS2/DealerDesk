# AI / ML track — design decisions

## 1. Question: What does each model represent, how are the models related, and why is each foreign key's `on_delete` behavior chosen?

**Answer:**
- `Product` is the SKU-keyed catalogue; `Inventory` is a one-to-one stock row; `StockMovement` is the stock audit ledger (`catalog/models.py:5-52`). `Inventory.product` uses `CASCADE` because stock has no meaning without its product. `StockMovement.product` uses `CASCADE` because its history belongs to that product; its optional `order` uses `SET_NULL` so an order removal does not erase the stock event.
- `Dealer` is the dealer master (`dealers/models.py:4-17`). `Order` belongs to a dealer, and `OrderItem` connects an order to a product (`orders/models.py:5-44`). `Order.dealer` is `PROTECT` to preserve financial history; `OrderItem.order` is `CASCADE` because a line has no meaning without its order; `OrderItem.product` is `PROTECT` to preserve the SKU and description of historical sales.
- `DailyOrderSequence` stores the per-day number counter. `IdempotencyKey` optionally points one-to-one to its order (`orders/models.py:46-64`); its `CASCADE` is appropriate because the key only identifies that order.
- `ChatSession` belongs to a dealer and is unique per `(session_id, dealer)`; `ChatMessage` belongs to a session (`assistant/models.py:4-32`). Both use `CASCADE`: conversation memory is disposable, unlike order history.

## 2. Question: How does retrieval work, why were these embedding, indexing, and ranking choices made, and where does retrieval fail?

**Answer:**
Retrieval intentionally uses lexical BM25, not embeddings: exact fitment numbers matter more than semantic similarity for parts. The in-memory index weights name above category/brand above fitment/description, indexes SKU tokens, and expands a small domain synonym list (`assistant/retrieval.py:28-29`, `:85-96`). The vehicle resolver rejects a fitment unless every number in the request appears in it, preventing a Duke 390 query from matching Duke 200 (`assistant/retrieval.py:105-128`). BM25 scores are multiplied by query-token coverage squared, then weak matches are removed (`assistant/retrieval.py:135-183`). The index refreshes when product count or maximum `updated_at` changes; price and stock are fetched separately at tool time (`assistant/retrieval.py:189-198`; `assistant/tools.py:93-110`).

It fails on paraphrases with no shared term, misspellings, and unrecognised vehicle aliases. The fixed synonym list and lexical scores cannot reliably infer intent the catalogue never expresses; unknown vehicles are restricted to Universal-fitment results (`assistant/retrieval.py:28-46`, `:150-158`).

## 3. Question: How does a user message move through the tool-calling loop to the final assistant reply?

**Answer:**
`ChatView.post` validates the request and dealer before calling `run_turn` (`assistant/views.py:11-31`). `run_turn` loads dealer-scoped history, builds system/history/user messages, and asks the LLM to answer or call one of the tool schemas (`assistant/agent.py:212-224`; prompt and rules at `:34-50`). `_answer` allows up to six rounds; `_tool_round` executes each returned call through `run_tool`, appends the JSON result as a tool message, and repeats (`assistant/agent.py:182-209`; dispatch at `assistant/tools.py:192-201`). After 36 seconds it stops offering tools; the turn has a 48-second deadline (`assistant/agent.py:29-33`, `:184-209`). Before persistence, `verify_reply` checks the draft; a failed check triggers one repair attempt, then messages are stored and the reply, cited SKUs, calls, and actions are returned (`assistant/agent.py:242-262`).

## 4. Question: How does the assistant get current prices and stock, and how does it ensure it never states a figure that is not in the database right now?

**Answer:**
`search_parts` and `check_stock` query `Product` and related `Inventory` rows when invoked; `_product_view` formats the database price and stock (`assistant/tools.py:93-110`, `:113-148`). Earlier tool results are redacted from replayed history (`assistant/agent.py:72-101`). `verify_reply` checks parsed currency and stock claims against figures in this turn's tool results, rejects unknown SKUs and discount promises, and can request a repair (`assistant/agent.py:108-160`, `:242-249`; tests at `assistant/tests.py:68-85`).

This is **not** a strict “database at the instant the reply is sent” guarantee: tool values are a read-time snapshot, not held under a lock until the LLM finishes. The verifier is regex-based and only checks claim formats it recognises; numbers written as words or differently phrased claims can evade it. Therefore the accurate claim is “grounded in current-turn tool results and checked for common numeric formats,” not “impossible to state a stale or unsupported figure.”

## 5. Question: Since supplier descriptions are untrusted, how does the assistant resist instructions hidden inside them, and where does that defence stop working?

**Answer:**
Supplier-facing name, brand, and description strings pass through `sanitize_text`, which drops sentences matching `INJECTION_RE`; tool output is tagged `catalogue_data`, and the system prompt says supplier text is data, not instructions (`assistant/tools.py:70-89`, `:93-105`; `assistant/agent.py:45-50`). The tools also limit impact: they can search, check stock, or create a draft, but cannot confirm an order or directly edit price or inventory (`assistant/tools.py:18-61`, `:151-180`).

The filter is pattern-based, not a proof against prompt injection. A paraphrased instruction that matches none of its patterns can reach the model, and safety then depends on the model following the system prompt. The output checker also only catches discount promises matching its patterns (`assistant/agent.py:67`, `:141-160`). The sanitizer does not cover every catalogue field: `category` and `vehicle_fitment` are returned directly (`assistant/tools.py:97-105`).

## 6. Question: What forecasting approach did you use, how did you validate it, and which exact line prevents future data from leaking into training?

**Answer:**
The forecast is `level × Diwali-relative seasonal factor × planned-promotion uplift` (`ml/model.py:1-16`, `:62-66`). The Diwali curve is pooled across SKU-seasons, SKU sensitivity is shrunk toward the pooled curve, and promotion uplift is shrunk toward a global estimate (`ml/model.py:83-119`, `:122-136`). Validation is rolling-origin, four weeks ahead, against last value, 4/8/12-week means, and same-week-last-year (`ml/backtest.py:32-58`). Across all folds, WAPE is 19.08% for the model versus 28.50% for the best listed baseline; in the festive fold it is 19.81% versus 27.63% (`ml/BACKTEST.md:7-16`, `:29-38`).

The leakage guard is `history = sales[sales["week_start"] < origin].copy()` at **`ml/model.py:78`**; the backtest independently applies the same strict cutoff at `ml/backtest.py:43-49`. Planned promotions are future inputs because the promo calendar is treated as known in advance.

## 7. Question: Which SKUs does the forecast handle worst, why, and how are promotions, Diwali, rarely sold SKUs, and new SKUs handled?

**Answer:**
On the festive fold, the largest model-MAE / best-baseline-MAE ratios are CHN-1073 (2.39), BRK-1090 (2.26), and BRK-1019 (1.75) (`ml/BACKTEST.md:40-47`; ratio calculation: `ml/backtest.py:83-84`). These are relative errors, not absolute unit errors. The report does not contain SKU-level residual diagnostics, so it cannot prove a distinct cause for each SKU. A plausible shared weakness is that SKU demand can diverge from the pooled Diwali curve; per-SKU seasonal sensitivity is estimated from limited qualifying observations and shrunk toward the pooled effect (`ml/model.py:83-119`).

Promotions use planned flags and a per-SKU uplift shrunk toward the pooled uplift (`ml/model.py:122-136`; future flags: `ml/forecast.py:21-29`). Diwali is indexed by week-distance, from 8 weeks before to 4 after (`ml/model.py:26`, `:35-45`). For intermittent SKUs with at least 30% zero-sales weeks, level is the mean of the last 26 adjusted weeks; for SKUs with under 13 weeks of history, it is the mean of up to the last four non-promo weeks (or last four weeks if none are non-promo) (`ml/model.py:30-31`, `:140-151`). New and intermittent SKUs still have limited evidence, so their forecasts are less reliable.

## 8. Question: What is the weakest part of the submission, and what would you do with two more days?

**Answer:**
The weakest part is assistant assurance: unit tests use a scripted fake LLM, while real-provider behavior is separate (`assistant/tests.py:1-2`); the safeguards for supplier text and numeric claims are heuristic (`assistant/tools.py:70-89`; `assistant/agent.py:108-160`). A provider can phrase claims outside the verifier's patterns, and a prompt-injection variant can bypass the sanitizer.

With two more days I would:
1. Add a repeatable adversarial evaluation set for prompt injection, SKU/fitment mix-ups, and numeric paraphrases, then run it against each configured provider (`scripts/assistant_eval.py:1-4`).
2. Make verified figures structured tool facts and render those facts deterministically, rather than relying on regex checks of free-form prose; re-check stock transactionally when creating/confirming an order.
3. Add SKU-stratified forecast error diagnostics and prediction intervals, then test safety-stock impact against the same rolling-origin folds.
