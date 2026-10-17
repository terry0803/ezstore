# EZStore 議價顧問 Agent（pricing_advisor）

第二個 Agent，給業務用。客戶要求降價或轉訂單時，它先查 OKF 知識庫裡的公司規則、用知識庫指定的計算算出改價後的毛利率，判斷要不要主管核准。可以做的才經 A2A 交給報價單 Agent（`quotation_agent`）去改，改完再從後端讀一次結果核對。

用 Google ADK 2.11 的 Graph Workflow 寫成，骨架由 `agents-cli scaffold create` 產生，和第一個 Agent 同一套做法。

```
業務 → ADK 網頁介面（:8502/dev-ui）或 A2A client
        → 議價顧問 Agent ──讀──→ OKF 知識庫 knowledge/ezstore（規則、公式、計算程式）
             │  └─ GET ──→ 後端 REST API（只讀）
             └─ A2A ──→ 報價單 Agent ── MCP ──→ 後端（先複製再改）
```

> `knowledge/ezstore/policies/` 的核准門檻是作業示範用的虛構規則，EZStore 系統本身沒有核准流程。

## 能做什麼

| 業務說 | Agent 做的事 |
|---|---|
| 毛利率要多少以上，業務才可以自己改價？ | 從知識庫挑條目回答，附來源與信任等級 |
| 神盾局科技想把 QT-20260325-001 壓到 180000，可以嗎？ | 跑 Attested Computation 試算、attester 驗證，依規則判斷核准層級 |
| 那就幫我改 | 再試算一次；業務可直接調整才經 A2A 請報價單 Agent 改總價，要核准就只寫核准申請 |
| 如果改成 200000 呢？ | 問句只試算，不改資料 |
| QT-20260115-001 可以轉訂單嗎？／幫我把 QT-20260301-001 轉成訂單 | 檢查已發佈、沒有訂單，通過才經 A2A 轉訂單 |
| 我要查詢報價單，報價單編號：… | 原句經 A2A 交給報價單 Agent |
| 今天天氣如何？ | 程式拒答 |

## 圖的設計

```
START → load_context ──（no_credentials）─────────────────────────────────┐
          │                                                                │
          └─（classify）→ understand → route                               │
                            ├─ policy_question → retrieve_knowledge        │
                            │     ├─（answer）→ answer_with_knowledge → cite_sources
                            │     └─（direct）─────────────────────────────┤
                            ├─ price_check                                 │
                            ├─ apply_price ──（delegate）→ delegate_a2a    │
                            ├─ order_check ──（delegate）→ delegate_a2a    │
                            ├─ delegate（一般報價單操作）→ delegate_a2a    │
                            ├─ clarify                                     │
                            └─ off_topic                                   │
                          全部 ──────────────────────────────────→ respond ←┘
```

| 節點 | 種類 | 做什麼 |
|---|---|---|
| `load_context` | 函式 | 取出這一句，附上知識庫目錄（每個條目一行 id、標題、描述，作廢與過期會標出來）與前一輪狀態。沒有模型憑證就直接回設定說明 |
| `understand` | `LlmAgent` | 輸出 `AdvisorIntent`：八種意圖之一、報價單編號、目標總價、要讀的條目 id |
| `route` | 函式 | 程式拒答（提示注入、客戶產品增修刪）；報價單編號與金額從原文抓；問句降級成只檢查；缺欄位追問；條目 id 由程式核對，再加一個關鍵字找到的條目 |
| `retrieve_knowledge` | 函式 | 讀最多兩個條目（每個 1000 字）組成回答的輸入。已作廢的條目只有問到舊規定才讀 |
| `answer_with_knowledge` | `LlmAgent` | 只依條目內容回答 |
| `cite_sources` | 函式 | 檢查回答：數字都要出自條目（有據），規則條目的每一級都要講到（完整）。不符合就改列程式依 frontmatter 產生的規則摘要。最後附依據與信任等級 |
| `price_check` | 函式 | 執行改價影響試算 → attester 驗證 → 依規則判斷 |
| `apply_price` | 函式 | 重新試算；業務可直接調整才走 `delegate`，否則寫核准申請，不改資料 |
| `order_check` | 函式 | 讀報價單與同客戶的訂單，依轉訂單規則判斷；要轉而且通過才走 `delegate` |
| `delegate_a2a` | 函式 | 用 A2A 呼叫報價單 Agent，回覆附 task id 與狀態，改完從後端重新讀結果核對 |
| `respond` | 函式 | 唯一輸出給使用者的節點 |

LLM 只做兩件事：聽懂這一句，以及依知識條目寫政策回答。試算數字、核准判斷、要不要經 A2A 改資料都由程式決定。

## OKF 知識庫怎麼用

知識庫在 `../knowledge/ezstore`，照 [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md) 寫：每個條目是有 YAML frontmatter 的 Markdown，`type` 必填，條目之間用連結形成關聯圖，根目錄 `index.md` 帶 `okf_version: "0.2"`。

| 規格 | Agent 怎麼用 |
|---|---|
| `index.md` 漸進揭露（§8） | `understand` 先看目錄，挑要讀的條目 |
| `verified` 推導信任等級（§5.3） | 每個依據都標「未驗證／機器驗證／人工審核」 |
| `status: deprecated`（§5.4） | 不拿來判斷，只在問到舊規定時讀 |
| `stale_after`（§5.5） | 過期的規則不套用，回覆會寫出來（例如第三季新客戶優惠） |
| `sources` 與註腳（§5.1） | 事實條目的每句話都對到原始碼或測試資料 |
| Attested Computation（§10） | 改價數字只能來自 `computations/price-change-impact`。executor 先確認計算程式的 sha256 和條目登記的一樣才執行，attester 檢查程式、參數、來源資料、重算結果、要顯示的數字五件事，任一項不符就不顯示數字 |

規則條目把門檻寫在 frontmatter（例如 `margin_tiers`、`factor_floor`），`policies.py` 直接讀這些數字判斷，不經過 LLM。

### 知識庫工具

```bash
uv run okf validate          # 照 §11 檢查，有 error 時 exit 1
uv run okf index             # 重新產生子目錄的 index.md
uv run okf verify            # 對照原始碼與執行中的系統，通過的寫入 process:okf-verify
uv run okf sign policies/discount-approval --by human:<你的 id>   # 看過規則後簽核，變成人工審核
uv run okf viz               # 產生 knowledge/ezstore/viz.html 關聯圖
```

`verify` 檢查 10 個條目，例如：預設報價因子同時對原始碼與 `GET /pricing-factor/{level}`、報價公式對 `quotation_service.go` 與每一筆品項、MCP 工具清單對 MCP Server、agent card 的 skill 對報價單 Agent。`policies/` 是公司決策，程式驗證不了，要人簽核。`viz` 用 Google 官方 viewer 的版型（Apache-2.0，見 `pricing_advisor/okf_viz`）。

## A2A

- 用戶端（`a2a_client.py`）：a2a-sdk 1.2 抓報價單 Agent 的 agent card，確認名稱是 `quotation_agent`、有需要的 skill，再送 message、等 task completed、取 artifact 文字。JSON-RPC 一律送回取得 card 的同一個位址：經前端 nginx 連的時候，card 裡寫的 `http://agent:8080` 是 Compose 內部位址。
- 沒有用 ADK 的 `RemoteA2aAgent`：ADK 2.11 會拒絕不是 https、也不是 loopback 的 card 位址（`_validate_card_rpc_targets`），Docker 內部網路的 `http://agent:8080` 用不了。
- 伺服端：`fast_api_app.py` 也開 `/a2a/pricing_advisor`，agent card 列四個 skill。A2A 回覆只帶 `respond` 節點的文字。

```bash
uv run python scripts/a2a_demo.py   # 外部 client → 報價單 Agent；外部 client → 議價顧問 → 報價單 Agent
```

## 執行

整套系統加上議價顧問（模型設定讀根目錄 `.env`）：

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml -f docker-compose.advisor.yml up -d --build
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql
```

網頁介面 http://localhost:8502/dev-ui/ ，agent card http://localhost:8502/a2a/pricing_advisor/.well-known/agent-card.json 。

本機開發：

```bash
cd advisor && cp .env.example .env
uv sync --group dev --extra eval
agents-cli playground --port 8502       # 和 Docker 的 advisor 擇一，不能同時佔 8502
uv run python scripts/run_dialog.py     # 示範對話（會改資料，先重灌 seed）
```

| 變數 | 預設 | 用途 |
|---|---|---|
| `AGENT_MODEL` | `gemini-3.8-flash` | `understand` 與 `answer_with_knowledge` 的模型；`openai/` 開頭改走 OpenAI 相容 API |
| `LOCAL_LLM_BASE` | `http://127.0.0.1:18081/v1` | `openai/` 模型的位址 |
| `GEMINI_API_KEY`、Vertex AI 三個變數 | 無 | 模型憑證，和報價單 Agent 相同 |
| `BACKEND_API` | `http://localhost:8080/api/v1` | 後端（只用 GET） |
| `QUOTATION_AGENT_URL` | `http://localhost:3000/agent-api/a2a/quotation_agent` | 報價單 Agent 的 A2A 位址 |
| `OKF_BUNDLE` | `../knowledge/ezstore` | 知識庫 |
| `FRONTEND_URL` | `http://localhost:3000` | 回覆裡的報價單連結 |
| `OKF_NOW` | 現在時間 | 判斷過期用的時間，測試與示範用 |

## 測試

```bash
uv run pytest tests/unit tests/integration -q
```

不需要 API key 也不需要服務在跑：LLM 換成假模型、後端換成 `tests/fixtures/seed_snapshot.json`（重灌 seed 後從 API 取的快照）、A2A 對方換成假的。單元測試涵蓋 OKF 讀取與 §11 檢查、試算與 attester（竄改收據、改過計算程式）、規則判斷（作廢、過期、促銷期間）、路由與回答檢查。
