# EZStore

This version retains the six instructor operations and Agent architecture, with explicitly disclosed user-requested fixes in backend, frontend and MCP. Those trees differ from instructor baseline `09f6588`; this does not imply instructor approval. `python scripts/check_assignment.py` reports strict differences; `--allow-user-fixes` permits only the documented repair files. See [current status, deviations and latest results](reports/目前狀態.md).

> A lightweight B2B quotation and order management system.

[中文版](README.zh-TW.md)

---

## Part 1 — For Developers

### Overview

EZStore provides four core modules for managing the B2B sales pipeline:

| Module | Description |
|--------|-------------|
| **Customer Management** | CRUD for companies — name, tax ID, contacts, address, customer level (VIP / Standard / New), credit score |
| **Product Management** | CRUD for products — product number, name, description, cost, list price, inventory, supplier |
| **Quotation Management** | Create, edit, publish, and delete quotations. Pricing is computed from a *pricing factor* applied to list prices. Published quotations become immutable. |
| **Order Management** | CRUD for orders — optionally linked to a published quotation |
| **AI Agent** | Natural language quotation assistant — query, duplicate, adjust pricing factor/total price, convert to order. Google ADK 2.x graph Workflow + Gemini 3.8 Flash + MCP Server, scaffolded with google-agents-cli. |

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Go 1.25 · Gin · GORM · Swagger (swaggo) · Testify |
| Frontend | React 19 · TypeScript · Tailwind CSS 4 · Vite 8 · TanStack React Query · React Hook Form · React Router |
| Database | PostgreSQL 16 |
| AI Agent | Python 3.12 · Google ADK 2.10+ (graph Workflow API) · google-agents-cli 1.7 · Gemini 3.8 Flash · MCP Python SDK 2.x (Streamable HTTP) · uv |
| Build & Deploy | Docker · Docker Compose · Bun (frontend) · Nginx (frontend serving & API proxy) |

### Project Structure

```
ezstore/
├── docker-compose.yml          # Orchestrates all services
├── scripts/
│   └── seed-test-data.sql      # Idempotent test dataset (TRUNCATE + INSERT)
├── .env.example                # GEMINI_API_KEY and agent settings (copy to .env)
├── agent/                      # Quotation agent (ADK 2.x graph Workflow → mcp_server); see agent/README.md
│   ├── quotation_agent/        #   agent.py (Workflow, Intent, nodes), fast_api_app.py (ADK + A2A routes)
│   ├── tests/                  #   unit / integration (offline) and eval datasets + metrics
│   └── Dockerfile, pyproject.toml, uv.lock
├── advisor/                    # Pricing advisor (second agent, calls the quotation agent over A2A); see advisor/README.md
│   ├── pricing_advisor/        #   agent.py, okf.py (bundle reader), policies.py, computation.py, a2a_client.py, okf_cli.py
│   └── tests/, scripts/        #   offline tests; demo dialogue and A2A demo
├── knowledge/ezstore/          # OKF v0.2 bundle: system, policies, computations, playbooks, glossary, references
├── docker-compose.advisor.yml  # Adds the advisor service (published on :8502)
├── mcp_server/
│   ├── Dockerfile
│   ├── pyproject.toml           # mcp>=2.2, httpx (+ uv.lock)
│   └── server.py                # MCPServer (Streamable HTTP) with 6 quotation tools
├── backend/
│   ├── Dockerfile
│   ├── main.go                 # Entry point — Gin + GORM + Swagger init
│   ├── config/config.go        # Database connection (env vars)
│   ├── models/                 # GORM models (Customer, Product, Quotation, Order + items)
│   ├── repositories/           # Data access layer (CRUD, pagination, search)
│   ├── services/               # Business logic (pricing engine, validation)
│   ├── handlers/               # Gin HTTP handlers + Swagger annotations
│   ├── middleware/              # CORS, error handling
│   ├── routes/routes.go        # Route registration
│   └── docs/                   # Auto-generated Swagger files
└── frontend/
    ├── Dockerfile
    ├── nginx.conf              # Reverse proxy /api → backend, SPA fallback
    ├── vite.config.ts
    ├── src/
    │   ├── api/                # Axios API clients
    │   ├── pages/              # Route-level page components
    │   ├── components/         # Shared UI (DataTable, Pagination, StatusBadge, etc.)
    │   ├── types/index.ts      # TypeScript type definitions
    │   ├── App.tsx             # Router + QueryClientProvider
    │   └── main.tsx            # React entry point
    └── e2e/                    # Playwright E2E tests
```

### Prerequisites

The following tools must be installed before developing or running EZStore:

| Tool | Version | Purpose |
|------|---------|---------|
| **Docker** | ≥ 24.0 | Container runtime for all services |
| **Docker Compose** | ≥ 2.20 (included with Docker Desktop) | Multi-container orchestration |
| **Go** | ≥ 1.24 | Backend compilation and development |
| **Bun** | ≥ 1.0 | Frontend package manager and build tool |
| **swag** (Go CLI) | latest | Swagger documentation generation |

> **Docker-only mode:** If you only need to *run* EZStore (not develop), Docker and Docker Compose are sufficient. Go, Bun, and swag are only needed for local development.

#### macOS

```bash
# Install Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Docker Desktop (includes Docker Compose)
brew install --cask docker

# Go
brew install go

# Bun
brew install oven-sh/bun/bun

# swag (Swagger CLI) — requires Go to be installed first
go install github.com/swaggo/swag/cmd/swag@latest
```

After installing Docker Desktop, launch it from Applications and ensure it is running (whale icon in the menu bar).

#### Windows

```powershell
# Install winget (comes with Windows 11; for Windows 10 install "App Installer" from Microsoft Store)

# Docker Desktop (includes Docker Compose)
winget install Docker.DockerDesktop

# Go
winget install GoLang.Go

# Bun
powershell -c "irm bun.sh/install.ps1 | iex"

# swag (Swagger CLI) — requires Go to be installed first; restart terminal after Go install
go install github.com/swaggo/swag/cmd/swag@latest
```

After installing Docker Desktop, launch it and ensure **WSL 2 backend** is enabled (Settings → General → Use the WSL 2 based engine). You may need to restart your computer.

> **Note for Windows users:** All shell commands in this README use Unix-style syntax. Use **Git Bash**, **WSL 2**, or **PowerShell** to run them. If using PowerShell, replace `export VAR=value` with `$env:VAR="value"`.

#### Verify Installation

```bash
docker --version          # Docker version 24.x+
docker compose version    # Docker Compose version v2.x+
go version                # go1.24+
bun --version             # 1.x+
swag --version            # swag version v1.x+
```

### Quick Start (Docker Compose)

**API key (required for the AI Agent, everything else runs without it):**

```bash
cp .env.example .env      # then fill in GEMINI_API_KEY: https://aistudio.google.com/apikey
```

**Start (build from local source, both agents included):**

```bash
docker compose -p ezstore -f docker-compose.yml -f docker-compose.build.yml -f docker-compose.advisor.yml up -d --build
```

On Windows, `.\scripts\start-homework.ps1` does the same (`-SkipBuild` to skip the build, `-Action Status|Restart|Logs`). Plain `docker compose up -d` pulls the workshop's GHCR images, which do not contain this homework. After editing `.env`, run `up -d` again; a plain restart does not pick up new settings.

**Load test data:**

```bash
docker compose -p ezstore exec db psql -U ezstore -f /scripts/seed-test-data.sql
```

The seed runs `TRUNCATE` and then inserts the fixtures, so the data returns to the initial 12 quotations and 10 orders. Demos and evals add copies and orders; reseed before rerunning them.

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| AI Assistant (Chat UI) | http://localhost:3000/agent |
| Backend API | http://localhost:8080/api/v1 |
| Swagger UI | http://localhost:8080/swagger/index.html |
| Health Check | http://localhost:8080/health |

**Run E2E tests (verify the deployment is working):**

```powershell
.\scripts\test-e2e.ps1            # add -SkipBuild to reuse the built test images
```

The script starts a throwaway database and services (project `ezstore-e2e-<random>`), seeds it, runs the UI and API tests, and removes everything including the volume. The main services and data are not touched. On macOS/Linux use `pwsh -File scripts/test-e2e.ps1`.

### Development Mode

```bash
# 1. Start PostgreSQL
docker compose up db -d

# 2. Start backend (hot reload with go run)
cd backend
export DB_HOST=localhost DB_PORT=5432 DB_USER=ezstore DB_PASSWORD=ezstore DB_NAME=ezstore
go run .

# 3. Start frontend (Vite dev server with API proxy)
cd frontend
bun install
bun run dev          # http://localhost:5173
```

### API Documentation

All endpoints are documented with Swagger annotations. Once the backend is running, visit:

```
http://localhost:8080/swagger/index.html
```

### Testing

**Backend unit tests:**

```bash
cd backend
go test ./... -v -cover
```

**Load test dataset** (clears and reinserts; rerunning gives the same data):

```bash
docker compose -p ezstore exec db psql -U ezstore -f /scripts/seed-test-data.sql
```

The seed data includes: 15 customers (5 VIP + 6 Standard + 4 New), 20 products, 12 quotations (8 published + 4 draft), 10 orders (3 pending + 3 confirmed + 2 completed + 2 cancelled).

**Regenerate Swagger docs:**

```bash
cd backend
$(go env GOPATH)/bin/swag init -g main.go --parseDependency --parseInternal
```

### Core Business Logic

**Pricing Factor** — Determines how list prices are adjusted per customer level:

| Customer Level | Default Factor | Effect |
|---------------|----------------|--------|
| VIP | 0.80 | 20% discount |
| Standard | 0.90 | 10% discount |
| New | 1.00 | Full price |

The factor can be manually adjusted per quotation.

**Computation Formulas:**

```
unit_price   = list_price × pricing_factor
subtotal     = unit_price × quantity
total_price  = Σ(subtotal)
profit       = Σ((unit_price − cost) × quantity)
profit_rate  = profit ÷ total_price
```

**Publish Immutability** — Once a quotation is published:
- It cannot be edited (HTTP 403)
- It cannot be deleted (HTTP 403)
- It cannot be published again (HTTP 400)

### AI Agent

EZStore includes a natural-language quotation assistant in `agent/`, built with Google ADK 2.11. The agent is a **graph Workflow**: only one node calls the LLM (intent classification). Tool selection, arguments, clarification and refusal are all deterministic code.

**Architecture:**

```
User → React Chat UI → nginx /agent-api → Agent (ADK FastAPI, port 8080) → MCP Server (port 8000) → Backend REST API
                                               │                                  Streamable HTTP
                                     classify_intent model                       (mcp Python SDK 2.x)
                         Gemini 3.8 Flash (AI Studio key / Vertex AI)
                         or a local OpenAI-compatible model (AGENT_MODEL=openai/..., via LiteLLM)

Workflow graph (agent/quotation_agent/agent.py):

  START → load_context ──(no credentials)──────────────────────────────┐
            │                                                           │
            ├─(approved_price)→ adjust_total_price   ← advisor's approved change via A2A, skips the model
            │
            └─(classify)→ classify_intent (LlmAgent, output_schema=Intent) → route
                            ├─ get_quotation / list_customer_quotations / duplicate_quotation
                            ├─ update_pricing_factor / adjust_total_price / convert_to_order   ← each calls one MCP tool
                            ├─ clarify    (missing or invalid field → "請提供…", keeps state.pending_intent)
                            └─ off_topic  (refusal decided by code)
                          all → respond   (the only node the Chat UI shows)
```

A message that starts with `EZSTORE_APPROVED_PRICE_V1` comes from the pricing advisor over A2A. It carries the approval snapshot (quotation number, target total, factor, total, profit); `load_context` checks its shape and sends it straight to `adjust_total_price`, and the backend re-checks the snapshot inside one transaction before it keeps the copy. A malformed message is refused without calling any tool.

Every user message re-runs the graph from `START`. Cross-turn memory is the session state `pending_intent`. When the state is empty but the previous assistant turn was a clarification (for example a conversation history seeded by an eval case), `load_context` hands the previous user message to the classifier so the request still continues.

**Capabilities:**

| Operation | Description |
|-----------|-------------|
| Query quotation | Look up quotation details by quotation number (uses `GET /quotations?quotation_number=`) |
| List customer quotations | List all quotations for a given customer name |
| Duplicate quotation | Create a new draft copy of a quotation |
| Modify pricing factor | Duplicate first, then update the pricing factor on the copy |
| Modify total price | Duplicate first, then binary-search the pricing factor (≤ 20 iterations) to reach a target total |
| Convert to order | Create an order from the quotation's customer and items, linked via `quotation_id`; the quotation itself is untouched |

**Key design:**
- All modifications use **copy-on-write**: the original quotation is never changed, and the MCP tool's reply (which says so) is shown as is
- All replies carry **plain-text system links** to the quotation/order pages, never Markdown links
- The quotation number is taken from the user's text by a regex, not from the LLM; pricing factor and target total must be greater than 0
- Off-topic requests are **refused by code**: the classifier's `off_topic` intent plus rules for prompt injection and customer/product create-update-delete requests. Missing fields trigger a **clarification turn**
- The agent starts without any credentials (chat replies with a setup message), so `docker compose up` never fails on a missing key

**Environment variables:**

The default model follows the course spec: `gemini-3.8-flash`. To save quota, tests set `AGENT_MODEL=gemini-3.1-flash-lite` in `.env`, the cheapest model this account can call (`gemini-2.5-flash-lite` is closed to new users). Compose reads the root `.env`; running inside `agent/` or `advisor/` reads that folder's `.env`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `GEMINI_API_KEY` | — | AI Studio key (root `.env` for Compose, `agent/.env` for local runs) |
| `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | —, —, `global` | Use Vertex AI instead of an AI Studio key |
| `AGENT_MODEL` | `gemini-3.8-flash` | Model for `classify_intent`. A value starting with `openai/` (e.g. `openai/qwen3.5-9b`) switches to an OpenAI-compatible API |
| `MODEL_MAX_ATTEMPTS` | `6` | Maximum attempts per Gemini call (429 is retried with backoff); set 1 when quota is tight |
| `LOCAL_LLM_BASE` | Compose: `http://host.docker.internal:18081/v1`; local: `http://127.0.0.1:18081/v1` | Endpoint for `openai/` models |
| `MCP_URL` | Compose: `http://mcp-server:8000/mcp`; local: `http://localhost:8010/mcp` | MCP Server |
| `FRONTEND_URL`, `ALLOW_ORIGINS` | `http://localhost:3000` | Links in tool replies, CORS |
| `JUDGE_MODEL` | `AGENT_MODEL` | Judge model for the eval metrics in `agent/tests/eval` |

**Local development:**

```bash
# Whole system; mcp-server is published on :8010 for locally running agents
docker compose -p ezstore -f docker-compose.yml -f docker-compose.build.yml -f docker-compose.advisor.yml up -d --build

cd agent && cp .env.example .env    # fill GEMINI_API_KEY; MCP_URL=http://localhost:8010/mcp
                                    # or Vertex AI: GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT after `gcloud auth application-default login`
uv sync --group dev --extra eval
agents-cli playground               # web UI on http://127.0.0.1:8501 with --port 8501
```

**Tests and evaluation:**

```bash
cd agent
uv run pytest tests/unit tests/integration -q   # no API key; the classifier is faked, MCP tests skip when :8010 is down
agents-cli eval run                              # smoke dataset tests/eval/datasets/basic-dataset.json
agents-cli eval run --dataset tests/eval/datasets/quotation-actions.json     # 6 action cases (writes data; reseed before rerunning)
agents-cli eval run --dataset tests/eval/datasets/quotation-guardrails.json  # 2 refusals + 1 multi-turn clarification
cd .. && python3 scripts/grading/grade_agent.py --suite scripts/grading/student-suite.json   # 0–100 self-acceptance score
```

The four metrics in `agent/tests/eval/eval_config.yaml` use custom functions with AI Studio or local-model adapters. This does not remove the installed CLI’s own evaluation requirements:
- The tested cloud prompt-metric path in `agents-cli` v1.10.0 stopped because it could not resolve a GCP project. That path also needs authorized cloud credentials, such as ADC. This does not make every evaluation cloud-only or imply a course requirement to purchase cloud services: the workshop allows AI Studio API keys, and the TA uses a private grading suite. See `scripts/local_eval/README.md` for the distinction.
- A local model served with a single slot needs `agents-cli eval run --concurrency 1`.

Trustworthiness evaluation labs for learners: [eval-lab-quick.md](eval-lab-quick.md) (25 min, in class) and [eval-lab.md](eval-lab.md) (60–90 min, full version). Results of the full lab for this agent and the one-page report: [reports/可信賴度報告.md](reports/可信賴度報告.md) (Chinese).

### Second Agent: Pricing Advisor (A2A + OKF knowledge)

`advisor/` adds a second agent (app name `pricing_advisor`) for sales staff. When a customer asks for a lower price or wants an order, it reads the company rules in the OKF knowledge bundle `knowledge/ezstore/`, runs the bundle's sanctioned computation to get the new margin, decides whether a manager has to approve, and only then hands the change to the quotation agent over A2A. Design and usage: [advisor/README.md](advisor/README.md).

```
Sales → ADK web UI (:8502/dev-ui) or an A2A client
        → Pricing advisor ──reads──→ OKF bundle knowledge/ezstore
             │  └─ GET ──→ Backend REST API
             └─ A2A (JSON-RPC) ──→ Quotation agent (/a2a/quotation_agent) ── MCP ──→ Backend
```

- **A2A**: both agents serve A2A from `fast_api_app.py`; each agent card lists its skills (one per operation for the quotation agent). A2A replies carry only the `respond` node's text, the same text the Chat UI shows. After a change, the advisor re-reads the result from the backend to check it.
- **OKF**: the bundle follows Open Knowledge Format v0.2 with 17 concepts (system facts, pricing and order rules, an Attested Computation, a negotiation playbook, glossary). `uv run okf validate` checks conformance, `uv run okf verify` checks system facts against the source code and the running system and records `process:okf-verify`, `uv run okf viz` writes the graph viewer `knowledge/ezstore/viz.html`.
- The approval thresholds in `knowledge/ezstore/policies/` are demo rules made up for this homework; EZStore itself has no approval process.

```bash
docker compose -p ezstore -f docker-compose.yml -f docker-compose.build.yml -f docker-compose.advisor.yml up -d --build
```

A2A demo: `cd advisor && uv run python scripts/a2a_demo.py` (external client → pricing advisor → quotation agent; it writes data, so reseed first).

### License

This project is licensed under the [MIT License](LICENSE).

---

## Part 2 — For AI Coding Agents

> This section is written for AI coding assistants (Claude Code, Gemini CLI, GitHub Copilot, Antigravity, Cursor, Aider, etc.). It provides structured, machine-friendly context to help you work effectively in this codebase.

### Project Identity

- **Name:** EZStore
- **Purpose:** B2B quotation and order management system
- **Language:** Go (backend), TypeScript/React (frontend), Python 3.12 (agent + MCP server)
- **Database:** PostgreSQL 16
- **Deployment:** Docker Compose (5 services: db, backend, frontend, agent, mcp-server)

### Architecture Pattern

The backend follows a **3-layer architecture**:

```
HTTP Request → Handler (Gin) → Service (business logic) → Repository (GORM/DB)
```

- **Handlers** parse HTTP input, call services, return JSON. Include Swagger annotations.
- **Services** contain validation and business logic. Never access `*gin.Context`.
- **Repositories** wrap GORM queries. Return models or errors, never HTTP concepts.

### Key File Paths

| Concern | Path |
|---------|------|
| Backend entry point | `backend/main.go` |
| Database config | `backend/config/config.go` |
| All models | `backend/models/*.go` |
| All repositories | `backend/repositories/*.go` |
| All services | `backend/services/*.go` |
| All handlers | `backend/handlers/*.go` |
| Route registration | `backend/routes/routes.go` |
| CORS middleware | `backend/middleware/cors.go` |
| Error response helper | `backend/middleware/error_handler.go` |
| Pricing factor defaults | `backend/models/customer.go` → `DefaultPricingFactor()` |
| Quotation calculation | `backend/services/quotation_service.go` → `computeTotals()`, `buildItems()` |
| Frontend entry | `frontend/src/main.tsx` |
| React router | `frontend/src/App.tsx` |
| TypeScript types | `frontend/src/types/index.ts` |
| API clients | `frontend/src/api/*.ts` |
| Page components | `frontend/src/pages/*.tsx` |
| Shared components | `frontend/src/components/shared/*.tsx` |
| Agent workflow graph | `agent/quotation_agent/agent.py` (`Workflow`, `Intent`, node functions) |
| Agent classifier instruction / fixed replies | `agent/quotation_agent/agent.py` (`CLASSIFIER_INSTRUCTION`, `REFUSAL_TEXT`, `clarify`) |
| Agent FastAPI app | `agent/quotation_agent/fast_api_app.py` |
| Agent eval | `agent/tests/eval/eval_config.yaml`, `agent/tests/eval/datasets/*.json`, metric files `agent/tests/eval/*.py` |
| MCP Server (6 tools, mcp 2.x `MCPServer`) | `mcp_server/server.py` |
| Agent Chat UI | `frontend/src/pages/AgentChatPage.tsx` |
| Agent API client | `frontend/src/api/agentApi.ts` |
| Docker orchestration | `docker-compose.yml` |
| Test dataset | `scripts/seed-test-data.sql` |
| Pricing advisor workflow | `advisor/pricing_advisor/agent.py` |
| OKF knowledge bundle | `knowledge/ezstore/` (tools: `advisor/pricing_advisor/okf_cli.py`) |
| Price-change computation (Attested Computation) | `knowledge/ezstore/computations/price-change-impact.md`, `references/computations/price_change_impact.py` |

### Database Schema Summary

6 tables. All main entities use GORM soft-delete (`deleted_at`). Item tables use hard delete.

```
customers         → id, name, tax_id (unique, 8 digits), contact_name, contact_phone,
                    contact_email, address, level (vip|standard|new), credit_score (0-100)

products          → id, product_number (unique), name, description, cost, list_price,
                    inventory, supplier

quotations        → id, quotation_number (unique, auto: QT-YYYYMMDD-NNN),
                    customer_id (FK), customer_level (snapshot), pricing_factor,
                    total_price, profit_amount, profit_rate,
                    status (draft|published), notes

quotation_items   → id, quotation_id (FK, CASCADE), product_id (FK),
                    product_name (snapshot), product_cost (snapshot), list_price (snapshot),
                    unit_price, quantity, subtotal

orders            → id, order_number (unique, auto: ORD-YYYYMMDD-NNN),
                    customer_id (FK), quotation_id (FK, nullable),
                    total_price, status (pending|confirmed|completed|cancelled), notes

order_items       → id, order_id (FK, CASCADE), product_id (FK),
                    product_name (snapshot), unit_price, quantity, subtotal
```

**Important:** Quotation/order items store *snapshots* of product data (name, cost, list_price) at creation time. This ensures historical accuracy if product data changes later.

### REST API Endpoints

Base path: `/api/v1`

```
GET    /health                        → { status: "ok" }
GET    /api/v1/pricing-factor/:level  → { level, pricing_factor }

# Customers
GET    /api/v1/customers              → paginated list (?page, ?page_size, ?search)
GET    /api/v1/customers/:id
POST   /api/v1/customers
PUT    /api/v1/customers/:id
DELETE /api/v1/customers/:id          → soft delete

# Products
GET    /api/v1/products               → paginated list (?page, ?page_size, ?search)
GET    /api/v1/products/:id
POST   /api/v1/products
PUT    /api/v1/products/:id
DELETE /api/v1/products/:id           → soft delete

# Quotations
GET    /api/v1/quotations             → paginated list (?page, ?page_size, ?status, ?customer_id, ?quotation_number)
GET    /api/v1/quotations/:id         → includes items[] and customer
POST   /api/v1/quotations             → body: { customer_id, pricing_factor, notes, items: [{product_id, quantity}] }
PUT    /api/v1/quotations/:id         → draft only; same body as POST
POST   /api/v1/quotations/:id/publish → sets status to published (irreversible)
DELETE /api/v1/quotations/:id         → draft only; soft delete

# Orders
GET    /api/v1/orders                 → paginated list (?page, ?page_size, ?status, ?customer_id)
GET    /api/v1/orders/:id             → includes items[] and customer
POST   /api/v1/orders                 → body: { customer_id, quotation_id?, notes, items: [{product_id, unit_price, quantity}] }
PUT    /api/v1/orders/:id
DELETE /api/v1/orders/:id             → soft delete
```

### Pricing Computation Rules

When a quotation is created or updated, the backend:

1. Fetches the customer → snapshots `customer_level`
2. For each item: fetches the product → snapshots `product_name`, `product_cost`, `list_price`
3. Computes `unit_price = list_price × pricing_factor`
4. Computes `subtotal = unit_price × quantity`
5. Computes `total_price = Σ(subtotal)`
6. Computes `profit_amount = Σ((unit_price − cost) × quantity)`
7. Computes `profit_rate = profit_amount ÷ total_price` (guarded: returns 0 if total is 0)

Default pricing factors: VIP → 0.80, Standard → 0.90, New → 1.00 (defined in `backend/models/customer.go`).

### Business Rules and Constraints

- **Tax ID**: must be exactly 8 digits (`^\d{8}$`)
- **Customer level**: must be one of `vip`, `standard`, `new`
- **Credit score**: integer 0–100
- **Product cost and list_price**: must be ≥ 0 (Decimal, never float)
- **Quantity**: must be > 0
- **Published quotation**: cannot be edited, deleted, or re-published
- **Quotation/Order numbers**: auto-generated as `QT-YYYYMMDD-NNN` / `ORD-YYYYMMDD-NNN`
- **Soft delete**: customers, products, quotations, orders use `deleted_at`
- **Hard delete**: quotation_items and order_items are physically deleted on parent update

### Common Developer Commands

```bash
# Full stack (Docker)
docker compose -p ezstore -f docker-compose.yml -f docker-compose.build.yml -f docker-compose.advisor.yml up -d --build
docker compose -p ezstore -f docker-compose.yml -f docker-compose.build.yml -f docker-compose.advisor.yml down  # stop; keep database volume

# Backend
cd backend
go run .                                  # start API server (port 8080)
go test ./... -v -cover                   # run all tests
go build -o ezstore-api .                 # build binary
$(go env GOPATH)/bin/swag init -g main.go --parseDependency --parseInternal  # regenerate swagger

# Frontend
cd frontend
bun install                               # install dependencies
bun run dev                               # dev server (port 5173, proxies /api to :8080)
bun run build                             # production build → dist/

# MCP Server
cd mcp_server
uv sync && BACKEND_URL=http://localhost:8080 MCP_PORT=8010 uv run python server.py

# Agent (reads agent/.env: GEMINI_API_KEY, MCP_URL, AGENT_MODEL, LOCAL_LLM_BASE)
cd agent
uv sync --group dev --extra eval
agents-cli playground                     # local web UI
agents-cli run "我要查詢報價單，報價單編號：QT-20260330-001"
uv run pytest tests/unit tests/integration -q
agents-cli eval run                       # LLM-judged eval over tests/eval/datasets
```

### Common Modification Scenarios

**Adding a new field to an existing entity (e.g., adding `fax` to Customer):**
1. Add the field to the model in `backend/models/customer.go` (with GORM + JSON tags)
2. GORM AutoMigrate in `main.go` handles the schema change automatically
3. Update validation in `backend/services/customer_service.go` if needed
4. Update the handler's Swagger annotations in `backend/handlers/customer_handler.go`
5. Add the field to `frontend/src/types/index.ts`
6. Update the form in `frontend/src/pages/CustomerFormPage.tsx`
7. Update the table columns in `frontend/src/pages/CustomerListPage.tsx`
8. Regenerate Swagger docs

**Adding a new API endpoint:**
1. Create or update handler function in `backend/handlers/` with Swagger annotations
2. Add business logic in `backend/services/`
3. Add data access in `backend/repositories/` if needed
4. Register the route in `backend/routes/routes.go`
5. Add frontend API function in `frontend/src/api/`
6. Regenerate Swagger docs

**Adding a new entity:**
Follow the existing pattern: model → repository → service → handler → route. Each entity has its own file in each layer. Reference `customer` as the simplest complete example.

If Docker Desktop cannot mount the source drive on Windows, run `.\scripts\start-homework.ps1 -DockerBindCache "$env:LOCALAPPDATA\EZStore\docker-bind-cache"`. Each Start refreshes scripts and knowledge snapshots and builds the services while retaining the database. The selected cache path is remembered. After knowledge edits or a real human signature, run `-Action SyncKnowledge` and open a new conversation. Without a configured cache, direct mounts are used.
