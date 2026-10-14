> WATCH Video walkthrough -  [🎥 Watch the DealerDesk video walkthrough](https://drive.google.com/file/d/1r5fdaMXHL1KvNhJczqsf526Ea3BSEIGr/view?usp=sharing)

# VIKMO DealerDesk

DealerDesk is a dealership parts and operations application. It combines a Streamlit dashboard for dealership staff, a Django REST API, PostgreSQL-backed business data, an LLM tool-calling assistant, supplier-feed synchronization, and machine-learning demand forecasts.

The dashboard is implemented in `app.py`. Django models and domain services power both the dashboard and the REST API; they share the configured PostgreSQL database. This is a Python application, not a separate Node/React frontend.

## Project overview

- **Products and catalogue:** search and filter parts by SKU, name, brand, category, vehicle fitment, and stock.
- **Inventory:** inspect and correct live stock, with stock movements recorded by the application.
- **Dealers:** view the dealer directory and its contact and account information.
- **Orders:** create draft orders, calculate GST and totals, and manage order status. Stock and money rules are handled by the shared order service.
- **Supplier sync:** retrieve a paginated supplier feed and apply valid updates safely. A local supplier mock is included for development.
- **DealerDesk AI assistant:** ask about vehicle fitment, live prices and stock, or request a draft order. The assistant can call `search_parts`, `check_stock`, and `create_draft_order`; it cannot confirm orders. The floating orb opens the assistant from the dashboard.
- **Forecasting and reordering:** show four-week SKU forecasts and inventory-aware reorder suggestions using the committed `ml/forecast.csv`.

The assistant supports Gemini, OpenAI, Anthropic, and Groq. A working provider key is needed for live AI answers, but the dashboard and API can start without one. Provider quota, network, or model availability can affect live assistant responses.

## Technology

- Python 3.11 or newer
- Django 5 and Django REST Framework
- PostgreSQL (required; SQLite is deliberately unsupported)
- Streamlit dashboard, with Altair charts
- pandas and NumPy for forecast and inventory analysis
- OpenAI-compatible and Anthropic SDKs for the assistant

## Run the project on Windows

Use PowerShell from the repository root (the directory containing `manage.py` and `requirements.txt`). The same PostgreSQL `DATABASE_URL` is used by the dashboard, API, migrations, and seed command.

### 1. Install Python and PostgreSQL

Install Python 3.11+ and PostgreSQL, or create a PostgreSQL database with a hosted provider such as Neon. Create a database named `dealerdesk` for a local PostgreSQL installation if needed:

```powershell
psql -U postgres -h localhost -c "CREATE DATABASE dealerdesk;"
```

The database account in `DATABASE_URL` must be allowed to connect and create tables. Django also needs permission to create a test database when running the test suite.

### 2. Create the environment and install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, run this once for your Windows user, reopen PowerShell, and activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

If `.venv` already exists, skip `python -m venv .venv`.

### 3. Configure environment variables

Create a local `.env` file from the committed example and edit it:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Set `DATABASE_URL` to your PostgreSQL connection string. For local PostgreSQL, it will have this form:

```text
postgresql://<USER>:<PASSWORD>@localhost:5432/dealerdesk
```

For hosted PostgreSQL, use the provider's connection string and required SSL options, for example `?sslmode=require`. URL-encode special characters in the username or password. Do not commit `.env` or share its secrets.

For live assistant responses, set at least one provider key in `.env`:

| Variable                                              | Purpose                                                                  |
| ----------------------------------------------------- | ------------------------------------------------------------------------ |
| `DATABASE_URL`                                        | **Required.** PostgreSQL connection string.                              |
| `GEMINI_API_KEY`                                      | Gemini assistant key.                                                    |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY` | Alternative assistant provider keys.                                     |
| `LLM_PROVIDER`                                        | Optional provider selection: `gemini`, `openai`, `anthropic`, or `groq`. |
| `LLM_MODEL`                                           | Optional model override.                                                 |
| `SUPPLIER_API_URL`                                    | Supplier endpoint; the local mock uses `http://127.0.0.1:8099`.          |
| `SUPPLIER_API_KEY`                                    | Supplier authentication key; the local mock uses `dev-supplier-key`.     |
| `DJANGO_SECRET_KEY`                                   | Django secret key; configure a private value for non-local use.          |

When multiple assistant keys are set and `LLM_PROVIDER` is empty, the application selects the first configured provider in its configured order. Gemini free-tier quota can be exhausted; a key alone does not guarantee the provider will accept requests.

### 4. Create tables and load starter data

Run these commands once after setting `DATABASE_URL`:

```powershell
python manage.py migrate --noinput
python manage.py seed_data
```

The seed command loads the catalogue and dealer records. It is safe to run again and does not duplicate existing products or dealers.

### 5. Start the dashboard

In the same activated PowerShell window and repository directory:

```powershell
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open **http://localhost:8501**. The dashboard uses the database and Django business services directly; starting the API server is not required just to use the dashboard.

### 6. (Optional) Start the REST API

Open a second PowerShell window at the repository root, activate the same environment, then run:

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver 127.0.0.1:8000 --noreload
```

Check the API health endpoint at **http://localhost:8000/api/health/**. A successful response is:

```json
{ "status": "ok" }
```

The REST API is documented in [API_CONTRACT.md](./API_CONTRACT.md). The API server and dashboard can run at the same time.

### 7. (Optional) Start the supplier mock

The mock is only needed to exercise supplier-feed synchronization. Start it in another PowerShell window at the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python supplier_mock\mock_supplier.py
```

Keep it running while using the supplier sync feature. Its default URL and key match the values in `.env.example`.

## API overview

All endpoints use JSON and are mounted under `/api/`.

| Area      | Endpoints                                                                                          |
| --------- | -------------------------------------------------------------------------------------------------- |
| Health    | `GET /api/health/`                                                                                 |
| Products  | `GET`, `POST /api/products/`; `GET`, `PATCH /api/products/{sku}/`                                  |
| Inventory | `PUT /api/inventory/{sku}/`                                                                        |
| Dealers   | `GET`, `POST /api/dealers/`; `GET /api/dealers/{id}/`                                              |
| Orders    | `GET`, `POST /api/orders/`; order detail and lifecycle actions under `/api/orders/{order_number}/` |
| Supplier  | `POST /api/sync/supplier/`                                                                         |
| Assistant | `POST /api/assistant/chat/`                                                                        |
| Forecast  | `GET /api/forecast/{sku}/`; `GET /api/reorder-suggestions/`                                        |

See [API_CONTRACT.md](./API_CONTRACT.md) for request and response schemas, validation rules, pagination, and error codes.

## Tests and useful commands

The Django test suite uses PostgreSQL and creates a temporary test database. Use a local PostgreSQL instance for the fastest run, and ensure the configured database user may create databases:

```powershell
python manage.py test
```

The tests cover order calculations and status transitions, stock and concurrency safeguards, supplier synchronization, forecasts and reorder calculations, and the assistant tool loop using a fake LLM (so the tests do not consume provider quota).

Optional checks:

```powershell
# Contract smoke test: requires the API server, supplier mock, and seeded data.
python smoke_test.py --base-url http://localhost:8000 --all

# Live assistant evaluation: requires the API server and a working LLM provider key/quota.
python scripts\assistant_eval.py --base-url http://localhost:8000 --runs 3

# Forecast validation or regeneration.
python ml\backtest.py
python ml\forecast.py
```

The live assistant evaluation makes real provider requests and can fail if a model is unavailable or its quota is exhausted. This does not indicate that the Django unit tests or dashboard startup are broken.

## Project structure

```text
app.py                 Streamlit dashboard; uses Django models and services
manage.py              Django management entry point
dealerdesk/            Django settings and root URL configuration
core/                  Shared API utilities, health check, and seed_data command
catalog/               Product and inventory models, services, and API
dealers/               Dealer model and API
orders/                Order models, lifecycle/business rules, and API
supplier/              Supplier synchronization service and API
supplier_mock/         Local paginated supplier mock server
assistant/             LLM providers, tool definitions, retrieval, and tool-calling loop
forecasting/           Forecast and reorder API endpoints
ml/                    Forecast model, backtest, and committed forecast data
data/                  Catalogue, dealer, sales, lead-time, and calendar source data
src/shaders/           ThreeUI shader component source assets
semantic_bloom_renderer.py
                       Streamlit wrapper for the SemanticBloom hero
shader_button_renderer.py
                       Streamlit wrapper for the iridescent catalogue button
scripts/               Live assistant evaluation script
API_CONTRACT.md        API routes, payloads, and behavior contract
HOW_TO_RUN.md          Detailed setup, API examples, and troubleshooting
```
