# EZStore

> 輕量級 B2B 報價與訂單管理系統。

[English](README.md)

---

## 第一部分 — 給開發者閱讀

### 功能概述

EZStore 提供四大核心模組，管理 B2B 銷售流程：

| 模組 | 說明 |
|------|------|
| **客戶管理** | 客戶資料的 CRUD — 公司名稱、統一編號、聯絡資訊、地址、客戶等級（VIP / 一般 / 新客戶）、信用評分 |
| **產品管理** | 產品資料的 CRUD — 產品編號、名稱、描述、成本、牌價、庫存、供應商 |
| **報價單管理** | 報價單的建立、修改、發佈、刪除。單價由「報價因子」乘以牌價計算。已發佈的報價單不可再修改。 |
| **訂單管理** | 訂單的 CRUD — 可選擇關聯已發佈的報價單 |
| **AI 智能助理** | 自然語言報價單管理助手 — 查詢、複製、調整報價因子/總價、轉為訂單。Google ADK 2.x Graph Workflow + Gemini 3.8 Flash + MCP Server，以 google-agents-cli 建立骨架。 |

### 技術棧

| 層級 | 技術 |
|------|------|
| 後端 | Go 1.25 · Gin · GORM · Swagger (swaggo) · Testify |
| 前端 | React 19 · TypeScript · Tailwind CSS 4 · Vite 8 · TanStack React Query · React Hook Form · React Router |
| 資料庫 | PostgreSQL 16 |
| AI 智能助理 | Python 3.12 · Google ADK 2.10+（Graph Workflow API）· google-agents-cli 1.7 · Gemini 3.8 Flash · MCP Python SDK 2.x（Streamable HTTP）· uv |
| 編譯部署 | Docker · Docker Compose · Bun（前端）· Nginx（前端服務與 API 反向代理）|

### 專案目錄結構

```
ezstore/
├── docker-compose.yml          # 整合所有服務的編排檔
├── scripts/
│   └── seed-test-data.sql      # 冪等測試資料集（TRUNCATE + INSERT）
├── .env.example                # GEMINI_API_KEY 與 Agent 設定（複製為 .env）
├── agent/                      # 報價單 Agent（ADK 2.x Graph Workflow → mcp_server），說明見 agent/README.md
│   ├── quotation_agent/        #   agent.py（Workflow、Intent、各節點）、fast_api_app.py（ADK 與 A2A 路由）
│   ├── tests/                  #   unit／integration（離線）與 eval 題庫、指標
│   └── Dockerfile、pyproject.toml、uv.lock
├── advisor/                    # 議價顧問 Agent（第二個 Agent，A2A 呼叫報價單 Agent），說明見 advisor/README.md
│   ├── pricing_advisor/        #   agent.py、okf.py（讀知識庫）、policies.py、computation.py、a2a_client.py、okf_cli.py
│   └── tests/、scripts/        #   離線測試；示範對話與 A2A 示範
├── knowledge/ezstore/          # OKF v0.2 知識庫：system、policies、computations、playbooks、glossary、references
├── docker-compose.advisor.yml  # 加上議價顧問服務（對本機開 8502）
├── mcp_server/
│   ├── Dockerfile
│   ├── pyproject.toml           # mcp>=2.2、httpx（含 uv.lock）
│   └── server.py                # MCPServer（Streamable HTTP），6 個報價單工具
├── backend/
│   ├── Dockerfile
│   ├── main.go                 # 入口 — Gin + GORM + Swagger 初始化
│   ├── config/config.go        # 資料庫連線（環境變數）
│   ├── models/                 # GORM 模型（Customer、Product、Quotation、Order + 明細）
│   ├── repositories/           # 資料存取層（CRUD、分頁、搜尋）
│   ├── services/               # 業務邏輯（報價計算引擎、驗證）
│   ├── handlers/               # Gin HTTP 處理器 + Swagger 註解
│   ├── middleware/              # CORS、錯誤處理
│   ├── routes/routes.go        # 路由註冊
│   └── docs/                   # 自動產生的 Swagger 文件
└── frontend/
    ├── Dockerfile
    ├── nginx.conf              # 反向代理 /api → 後端、SPA fallback
    ├── vite.config.ts
    ├── src/
    │   ├── api/                # Axios API 用戶端
    │   ├── pages/              # 頁面元件
    │   ├── components/         # 共用 UI（DataTable、Pagination、StatusBadge 等）
    │   ├── types/index.ts      # TypeScript 型別定義
    │   ├── App.tsx             # Router + QueryClientProvider
    │   └── main.tsx            # React 入口
    └── e2e/                    # Playwright E2E 測試（規劃中）
```

### 開發環境需求

開發或執行 EZStore 前，需要安裝以下工具：

| 工具 | 版本 | 用途 |
|------|------|------|
| **Docker** | ≥ 24.0 | 容器運行環境 |
| **Docker Compose** | ≥ 2.20（Docker Desktop 已內含） | 多容器編排 |
| **Go** | ≥ 1.24 | 後端編譯與開發 |
| **Bun** | ≥ 1.0 | 前端套件管理與建置工具 |
| **swag**（Go CLI） | latest | Swagger 文件產生 |

> **僅執行模式：** 如果只需要*執行* EZStore（不做開發），只需安裝 Docker 與 Docker Compose。Go、Bun、swag 僅在本機開發時需要。

#### macOS

```bash
# 安裝 Homebrew（若尚未安裝）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Docker Desktop（包含 Docker Compose）
brew install --cask docker

# Go
brew install go

# Bun
brew install oven-sh/bun/bun

# swag（Swagger CLI）— 需要先安裝 Go
go install github.com/swaggo/swag/cmd/swag@latest
```

安裝 Docker Desktop 後，從「應用程式」啟動，確認選單列出現鯨魚圖示代表正在運行。

#### Windows

```powershell
# 安裝 winget（Windows 11 已內建；Windows 10 請從 Microsoft Store 安裝「應用程式安裝程式」）

# Docker Desktop（包含 Docker Compose）
winget install Docker.DockerDesktop

# Go
winget install GoLang.Go

# Bun
powershell -c "irm bun.sh/install.ps1 | iex"

# swag（Swagger CLI）— 需要先安裝 Go；安裝 Go 後請重啟終端機
go install github.com/swaggo/swag/cmd/swag@latest
```

安裝 Docker Desktop 後啟動，確認已啟用 **WSL 2 後端**（設定 → 一般 → 使用 WSL 2 引擎）。可能需要重新啟動電腦。

> **Windows 使用者注意：** 本文件的 shell 指令使用 Unix 風格語法。請使用 **Git Bash**、**WSL 2** 或 **PowerShell** 執行。若使用 PowerShell，請將 `export VAR=value` 替換為 `$env:VAR="value"`。

#### 驗證安裝

```bash
docker --version          # Docker version 24.x+
docker compose version    # Docker Compose version v2.x+
go version                # go1.24+
bun --version             # 1.x+
swag --version            # swag version v1.x+
```

### 快速開始（Docker Compose）

**API key（只有 AI 智能助理需要，其他服務沒有也能跑）：**

```bash
cp .env.example .env      # 再填入 GEMINI_API_KEY，取得方式：https://aistudio.google.com/apikey
```

**方式 A — 使用 GHCR 雲端預建 image（預設，免編譯）：**

```bash
docker compose up -d
```

**方式 B — 使用本地原始碼編譯：**

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

**載入測試資料：**

```bash
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql
```

| 服務 | 網址 |
|------|------|
| 前端 | http://localhost:3000 |
| AI 智能助理（Chat UI） | http://localhost:3000/agent |
| 後端 API | http://localhost:8080/api/v1 |
| Swagger UI | http://localhost:8080/swagger/index.html |
| 健康檢查 | http://localhost:8080/health |

**執行 E2E 測試（驗證部署是否正常）：**

```bash
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql
docker compose run --rm e2e
```

### 開發模式

```bash
# 1. 啟動 PostgreSQL
docker compose up db -d

# 2. 啟動後端
cd backend
export DB_HOST=localhost DB_PORT=5432 DB_USER=ezstore DB_PASSWORD=ezstore DB_NAME=ezstore
go run .

# 3. 啟動前端（Vite 開發伺服器，自動代理 /api）
cd frontend
bun install
bun run dev          # http://localhost:5173
```

### API 文件

所有端點皆有 Swagger 註解。後端啟動後，開啟：

```
http://localhost:8080/swagger/index.html
```

### 測試

**後端單元測試：**

```bash
cd backend
go test ./... -v -cover
```

**載入測試資料集**（冪等 — 可安全重複執行）：

```bash
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql
```

測試資料包含：15 位客戶（5 VIP + 6 一般 + 4 新客戶）、20 個產品、12 張報價單（8 已發佈 + 4 草稿）、10 筆訂單（3 待處理 + 3 已確認 + 2 已完成 + 2 已取消）。

**重新產生 Swagger 文件：**

```bash
cd backend
$(go env GOPATH)/bin/swag init -g main.go --parseDependency --parseInternal
```

### 核心業務邏輯

**報價因子** — 根據客戶等級調整牌價：

| 客戶等級 | 預設因子 | 效果 |
|---------|---------|------|
| VIP | 0.80 | 八折 |
| 一般 | 0.90 | 九折 |
| 新客戶 | 1.00 | 原價 |

報價因子可在報價單中手動調整。

**計算公式：**

```
單價     = 牌價 × 報價因子
復價     = 單價 × 數量
總價     = Σ(復價)
獲利金額 = Σ((單價 − 成本) × 數量)
獲利率   = 獲利金額 ÷ 總價
```

**發佈不可變性** — 報價單一旦發佈：
- 不可修改（HTTP 403）
- 不可刪除（HTTP 403）
- 不可重複發佈（HTTP 400）

### AI 智能助理

EZStore 內建自然語言報價單管理助手，程式在 `agent/`，用 Google ADK 2.11 開發。Agent 是一張 **Graph Workflow 圖**：只有意圖分類節點會呼叫 LLM，工具選擇、參數、追問與拒答全部由程式決定。

**架構：**

```
使用者 → React Chat UI → nginx /agent-api → Agent（ADK FastAPI，port 8080）→ MCP Server（port 8000）→ Backend REST API
                                               │                                     Streamable HTTP
                                     classify_intent 用的模型                        （mcp Python SDK 2.x）
                         Gemini 3.8 Flash（AI Studio key 或 Vertex AI）
                         或本機 OpenAI 相容模型（AGENT_MODEL=openai/...，經 LiteLLM）

Workflow 圖（agent/quotation_agent/agent.py）：

  START → load_context ──（沒有憑證）──────────────────────────────────┐
            │                                                           │
            └─（classify）→ classify_intent（LlmAgent，output_schema=Intent）→ route
                            ├─ get_quotation / list_customer_quotations / duplicate_quotation
                            ├─ update_pricing_factor / adjust_total_price / convert_to_order   ← 各呼叫一個 MCP 工具
                            ├─ clarify   （缺欄位或數字不合法就回「請提供…」，意圖暫存在 state.pending_intent）
                            └─ off_topic （由程式決定拒答）
                          全部 → respond （Chat UI 只顯示這個節點的文字）
```

每一則使用者訊息都從 `START` 重新跑一次圖，跨回合的記憶放在 session state 的 `pending_intent`。state 是空的、但上一輪助手正在追問時（例如 eval 題目自己帶進來的對話紀錄），`load_context` 會把上一句使用者的話一起交給分類器，一樣接得下去。

**功能：**

| 操作 | 說明 |
|------|------|
| 查詢報價單 | 根據報價單編號查詢詳細資訊（使用 `GET /quotations?quotation_number=`） |
| 查詢客戶報價單 | 根據客戶名稱列出所有報價單 |
| 複製報價單 | 建立新的草稿副本 |
| 修改報價因子 | 先複製再修改報價因子（原始不變） |
| 修改總價 | 先複製再以二分法調整報價因子（最多 20 次）達到目標總價（原始不變） |
| 報價單轉訂單 | 依報價單的客戶與品項建立訂單並以 `quotation_id` 關聯；報價單本身不動 |

**設計原則：**
- 所有修改都先複製再改副本，原始報價單不會被動到。MCP 工具的回覆本身就有寫這件事，Agent 原樣呈現
- 每則回覆都附 **純文字系統連結**，不用 Markdown 連結
- 報價單編號用正規表示式從使用者原文抓，不靠 LLM；報價因子與目標總價必須大於 0
- 離題請求 **由程式拒答**：分類器判成 `off_topic`，或命中提示注入、客戶／產品增修刪的規則。缺少必要欄位時 **追問一輪**
- 沒有任何憑證時 Agent 照常啟動，對話回覆設定說明，`docker compose up` 不會因缺金鑰而失敗

**環境變數：**

| 變數 | 預設 | 用途 |
|------|------|------|
| `GEMINI_API_KEY` | 無 | AI Studio key（Compose 讀根目錄 `.env`，本機開發讀 `agent/.env`） |
| `GOOGLE_GENAI_USE_VERTEXAI`、`GOOGLE_CLOUD_PROJECT`、`GOOGLE_CLOUD_LOCATION` | 無、無、`global` | 改用 Vertex AI |
| `AGENT_MODEL` | `gemini-3.8-flash` | `classify_intent` 用的模型。以 `openai/` 開頭（例如 `openai/qwen3.5-9b`）就改走 OpenAI 相容 API |
| `LOCAL_LLM_BASE` | Compose：`http://host.docker.internal:18081/v1`；本機：`http://127.0.0.1:18081/v1` | `openai/` 模型的 API 位址 |
| `MCP_URL` | Compose：`http://mcp-server:8000/mcp`；本機：`http://localhost:8010/mcp` | MCP Server |
| `FRONTEND_URL`、`ALLOW_ORIGINS` | `http://localhost:3000` | 工具回覆裡的連結、CORS |
| `JUDGE_MODEL` | 同 `AGENT_MODEL` | `agent/tests/eval` 評估指標用的評審模型 |

**本機開發：**

```bash
# 整套系統；mcp-server 對本機開 8010，讓本機跑的 Agent 連得到
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql

cd agent && cp .env.example .env    # 填 GEMINI_API_KEY，MCP_URL=http://localhost:8010/mcp
                                    # 或改走 Vertex AI：先 `gcloud auth application-default login`，再設 GOOGLE_GENAI_USE_VERTEXAI=true 與 GOOGLE_CLOUD_PROJECT
uv sync --group dev --extra eval
agents-cli playground               # 網頁介面（加 --port 8501 就在 http://127.0.0.1:8501）
```

**測試與評估：**

```bash
cd agent
uv run pytest tests/unit tests/integration -q   # 不需金鑰，分類器換成假模型；8010 沒開時 MCP 相關測試會略過
agents-cli eval run                              # 預設的小題庫 tests/eval/datasets/basic-dataset.json
agents-cli eval run --dataset tests/eval/datasets/quotation-actions.json     # 6 個操作案例（會新增資料，重跑前重灌 seed）
agents-cli eval run --dataset tests/eval/datasets/quotation-guardrails.json  # 2 個拒答 + 1 個多輪追問
cd .. && python3 scripts/grading/grade_agent.py --suite scripts/grading/student-suite.json   # 0–100 自我驗收分數
```

`agent/tests/eval/eval_config.yaml` 的四個指標（`custom_response_quality`、`link_present`、`refusal_or_action`、`agent_turn_count`）都是在本機執行的自訂函式，用 AI Studio key 或本機模型都能跑。沒有 GCP 專案的電腦要注意兩件事：
- `agents-cli eval grade` 啟動時還是會建立 Google Cloud Storage 客戶端，需要預設憑證（ADC）。沒有 `gcloud` 的話，把 `GOOGLE_APPLICATION_CREDENTIALS` 指到一個佔位用的 `authorized_user` JSON 檔就好，讀本機題庫時不會用到它。
- 本機模型如果只開一個推論槽，要用 `agents-cli eval run --concurrency 1`。

學員用的可信賴度評鑑 LAB：課堂版 [eval-lab-quick.zh-TW.md](eval-lab-quick.zh-TW.md)（25 分鐘）、完整版 [eval-lab.zh-TW.md](eval-lab.zh-TW.md)（60–90 分鐘，回家做）。這個 Agent 照完整版做完的結果與一頁報告見 [reports/可信賴度報告.md](reports/可信賴度報告.md)。

### 第二個 Agent：議價顧問（A2A 與 OKF 知識庫）

`advisor/` 是另外加做的第二個 Agent（app 名稱 `pricing_advisor`），給業務用。客戶要求降價或轉訂單時，它先查 `knowledge/ezstore/` 的 OKF 知識庫、用知識庫指定的計算試算毛利率，判斷要不要主管核准，可以做的才經 A2A 交給報價單 Agent。設計與執行方式見 [advisor/README.md](advisor/README.md)。

```
業務 → ADK 網頁介面（:8502/dev-ui）或 A2A client
        → 議價顧問 Agent ──讀──→ OKF 知識庫 knowledge/ezstore
             │  └─ GET ──→ Backend REST API
             └─ A2A（JSON-RPC）──→ 報價單 Agent（/a2a/quotation_agent）── MCP ──→ Backend
```

- **A2A**：兩個 Agent 都由 `fast_api_app.py` 開 A2A 端點，agent card 列出各自的 skill（報價單 Agent 是六個操作各一個）。A2A 回覆只帶 `respond` 節點的文字，和 Chat UI 看到的一樣。議價顧問改完資料後，會從後端重新讀一次結果核對。
- **OKF**：知識庫照 Open Knowledge Format v0.2 寫，17 個條目（系統事實、改價與轉訂單規則、Attested Computation、議價流程、名詞）。`uv run okf validate` 檢查格式，`uv run okf verify` 對照原始碼與執行中的系統寫入機器驗證紀錄，`uv run okf viz` 產生關聯圖 `knowledge/ezstore/viz.html`。
- `knowledge/ezstore/policies/` 的核准門檻是作業示範用的虛構規則，EZStore 本身沒有核准流程。

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml -f docker-compose.advisor.yml up -d --build
cd advisor && uv run python scripts/a2a_demo.py   # 外部 client → 議價顧問 → 報價單 Agent（會改資料，先重灌 seed）
```

### 授權

本專案採用 [MIT License](LICENSE) 開源授權。

---

## 第二部分 — 給 AI Coding Agent 閱讀

> 本段為 AI 編程助手設計（Claude Code、Gemini CLI、GitHub Copilot、Antigravity、Cursor、Aider 等），提供結構化的專案上下文，協助快速理解程式碼庫。

### 專案定位

- **名稱：** EZStore
- **用途：** B2B 報價與訂單管理系統
- **語言：** Go（後端）、TypeScript/React（前端）、Python 3.12（Agent + MCP Server）
- **資料庫：** PostgreSQL 16
- **部署：** Docker Compose（5 個服務：db、backend、frontend、agent、mcp-server）

### 架構模式

後端採用**三層式架構**：

```
HTTP 請求 → Handler（Gin）→ Service（業務邏輯）→ Repository（GORM/DB）
```

- **Handler** 解析 HTTP 輸入、呼叫 Service、回傳 JSON。包含 Swagger 註解。
- **Service** 包含驗證與業務邏輯。不存取 `*gin.Context`。
- **Repository** 封裝 GORM 查詢。回傳 model 或 error，不涉及 HTTP 概念。

### 關鍵檔案路徑

| 用途 | 路徑 |
|------|------|
| 後端入口 | `backend/main.go` |
| 資料庫設定 | `backend/config/config.go` |
| 所有 Model | `backend/models/*.go` |
| 所有 Repository | `backend/repositories/*.go` |
| 所有 Service | `backend/services/*.go` |
| 所有 Handler | `backend/handlers/*.go` |
| 路由註冊 | `backend/routes/routes.go` |
| CORS 中介層 | `backend/middleware/cors.go` |
| 錯誤回應輔助函式 | `backend/middleware/error_handler.go` |
| 報價因子預設值 | `backend/models/customer.go` → `DefaultPricingFactor()` |
| 報價計算邏輯 | `backend/services/quotation_service.go` → `computeTotals()`、`buildItems()` |
| 前端入口 | `frontend/src/main.tsx` |
| React 路由 | `frontend/src/App.tsx` |
| TypeScript 型別 | `frontend/src/types/index.ts` |
| API 用戶端 | `frontend/src/api/*.ts` |
| 頁面元件 | `frontend/src/pages/*.tsx` |
| 共用元件 | `frontend/src/components/shared/*.tsx` |
| Docker 編排 | `docker-compose.yml` |
| 測試資料集 | `scripts/seed-test-data.sql` |
| 議價顧問 Workflow | `advisor/pricing_advisor/agent.py` |
| OKF 知識庫 | `knowledge/ezstore/`（工具：`advisor/pricing_advisor/okf_cli.py`） |
| 改價試算（Attested Computation） | `knowledge/ezstore/computations/price-change-impact.md`、`references/computations/price_change_impact.py` |

### 資料庫 Schema 摘要

共 6 張表。主要實體使用 GORM 軟刪除（`deleted_at`）。明細表使用硬刪除。

```
customers         → id, name, tax_id（唯一, 8碼數字）, contact_name, contact_phone,
                    contact_email, address, level（vip|standard|new）, credit_score（0-100）

products          → id, product_number（唯一）, name, description, cost, list_price,
                    inventory, supplier

quotations        → id, quotation_number（唯一, 自動: QT-YYYYMMDD-NNN）,
                    customer_id（FK）, customer_level（快照）, pricing_factor,
                    total_price, profit_amount, profit_rate,
                    status（draft|published）, notes

quotation_items   → id, quotation_id（FK, CASCADE）, product_id（FK）,
                    product_name（快照）, product_cost（快照）, list_price（快照）,
                    unit_price, quantity, subtotal

orders            → id, order_number（唯一, 自動: ORD-YYYYMMDD-NNN）,
                    customer_id（FK）, quotation_id（FK, 可為空）,
                    total_price, status（pending|confirmed|completed|cancelled）, notes

order_items       → id, order_id（FK, CASCADE）, product_id（FK）,
                    product_name（快照）, unit_price, quantity, subtotal
```

**重要：** 報價單/訂單明細儲存產品資料的*快照*（名稱、成本、牌價），確保產品資料後續修改不影響歷史記錄。

### REST API 端點

Base path: `/api/v1`

```
GET    /health                        → { status: "ok" }
GET    /api/v1/pricing-factor/:level  → { level, pricing_factor }

# 客戶
GET    /api/v1/customers              → 分頁列表（?page, ?page_size, ?search）
GET    /api/v1/customers/:id
POST   /api/v1/customers
PUT    /api/v1/customers/:id
DELETE /api/v1/customers/:id          → 軟刪除

# 產品
GET    /api/v1/products               → 分頁列表（?page, ?page_size, ?search）
GET    /api/v1/products/:id
POST   /api/v1/products
PUT    /api/v1/products/:id
DELETE /api/v1/products/:id           → 軟刪除

# 報價單
GET    /api/v1/quotations             → 分頁列表（?page, ?page_size, ?status, ?customer_id, ?quotation_number）
GET    /api/v1/quotations/:id         → 含 items[] 與 customer
POST   /api/v1/quotations             → body: { customer_id, pricing_factor, notes, items: [{product_id, quantity}] }
PUT    /api/v1/quotations/:id         → 僅草稿可修改；body 同 POST
POST   /api/v1/quotations/:id/publish → 將狀態設為 published（不可逆）
DELETE /api/v1/quotations/:id         → 僅草稿可刪除；軟刪除

# 訂單
GET    /api/v1/orders                 → 分頁列表（?page, ?page_size, ?status, ?customer_id）
GET    /api/v1/orders/:id             → 含 items[] 與 customer
POST   /api/v1/orders                 → body: { customer_id, quotation_id?, notes, items: [{product_id, unit_price, quantity}] }
PUT    /api/v1/orders/:id
DELETE /api/v1/orders/:id             → 軟刪除
```

### 報價計算規則

建立或修改報價單時，後端：

1. 查詢客戶 → 快照 `customer_level`
2. 對每個明細項目：查詢產品 → 快照 `product_name`、`product_cost`、`list_price`
3. 計算 `unit_price = list_price × pricing_factor`
4. 計算 `subtotal = unit_price × quantity`
5. 計算 `total_price = Σ(subtotal)`
6. 計算 `profit_amount = Σ((unit_price − cost) × quantity)`
7. 計算 `profit_rate = profit_amount ÷ total_price`（防護：total 為 0 時回傳 0）

預設報價因子：VIP → 0.80、一般 → 0.90、新客戶 → 1.00（定義於 `backend/models/customer.go`）。

### 業務規則與約束條件

- **統一編號**：必須為 8 位數字（`^\d{8}$`）
- **客戶等級**：必須為 `vip`、`standard`、`new` 其一
- **信用評分**：整數 0–100
- **產品成本與牌價**：必須 ≥ 0（使用 Decimal，不用 float）
- **數量**：必須 > 0
- **已發佈報價單**：不可修改、刪除、重複發佈
- **報價單/訂單編號**：自動產生格式 `QT-YYYYMMDD-NNN` / `ORD-YYYYMMDD-NNN`
- **軟刪除**：customers、products、quotations、orders 使用 `deleted_at`
- **硬刪除**：quotation_items 與 order_items 在父層更新時直接刪除

### 常用開發指令

```bash
# 完整環境（Docker）
docker compose up --build -d
docker compose down -v                    # 停止並移除 volumes
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql

# 後端
cd backend
go run .                                  # 啟動 API 伺服器（port 8080）
go test ./... -v -cover                   # 執行所有測試
go build -o ezstore-api .                 # 編譯
$(go env GOPATH)/bin/swag init -g main.go --parseDependency --parseInternal  # 重新產生 Swagger

# 前端
cd frontend
bun install                               # 安裝依賴
bun run dev                               # 開發伺服器（port 5173，代理 /api 到 :8080）
bun run build                             # 正式建置 → dist/
```

### 常見修改場景

**為現有實體新增欄位（例如在 Customer 新增 `fax`）：**
1. 在 `backend/models/customer.go` 新增欄位（含 GORM + JSON tag）
2. GORM AutoMigrate 於 `main.go` 會自動處理資料表變更
3. 如需要，在 `backend/services/customer_service.go` 更新驗證邏輯
4. 更新 `backend/handlers/customer_handler.go` 的 Swagger 註解
5. 在 `frontend/src/types/index.ts` 新增欄位
6. 更新 `frontend/src/pages/CustomerFormPage.tsx` 的表單
7. 更新 `frontend/src/pages/CustomerListPage.tsx` 的表格欄位
8. 重新產生 Swagger 文件

**新增 API 端點：**
1. 在 `backend/handlers/` 建立或更新 handler 函式（含 Swagger 註解）
2. 在 `backend/services/` 加入業務邏輯
3. 如需要，在 `backend/repositories/` 加入資料存取
4. 在 `backend/routes/routes.go` 註冊路由
5. 在 `frontend/src/api/` 加入前端 API 函式
6. 重新產生 Swagger 文件

**新增實體：**
依循現有模式：model → repository → service → handler → route。每個實體在每一層都有獨立檔案。可參考 `customer` 作為最簡單的完整範例。
