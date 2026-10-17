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
                            │     ├─（rules）→ cite_sources（條目有結構化規則，不呼叫模型）
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
| `retrieve_knowledge` | 函式 | 讀最多兩個條目（每個 1000 字）組成回答的輸入。已作廢的條目只有問到舊規定才讀。條目有結構化規則（`rule_kind`）就跳過模型，直接到 `cite_sources` |
| `answer_with_knowledge` | `LlmAgent` | 只依條目內容回答（只用在沒有結構化規則的條目，例如報價公式、名詞） |
| `cite_sources` | 函式 | 規則條目由程式照 frontmatter 寫出每一級門檻和核准者。其他條目檢查回答的數字都出自條目，不符合就改列條目描述。最後附依據與信任等級 |
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

- 用戶端（`a2a_client.py`）：a2a-sdk 1.2 抓報價單 Agent 的 agent card，確認名稱是 `quotation_agent`、有需要的 skill，再送 message（`return_immediately`，對方先回 task 編號）、用 `tasks/get` 查到 task 結束、取 artifact 文字。JSON-RPC 一律送回取得 card 的同一個位址：經前端 nginx 連的時候，card 裡寫的 `http://agent:8080` 是 Compose 內部位址。
- 沒有用 ADK 的 `RemoteA2aAgent`：ADK 2.11 會拒絕不是 https、也不是 loopback 的 card 位址（`_validate_card_rpc_targets`），Docker 內部網路的 `http://agent:8080` 用不了。
- 伺服端：`fast_api_app.py` 也開 `/a2a/pricing_advisor`，agent card 列四個 skill。A2A 回覆只帶 `respond` 節點的文字。

```bash
uv run python scripts/a2a_demo.py   # 外部 client → 報價單 Agent；外部 client → 議價顧問 → 報價單 Agent（會改資料）
```

## 安全與信任

會改資料的只有一條路：`apply_price` 或 `order_check` 通過規則，才經 A2A 交給報價單 Agent。下面這些檢查都是程式，不靠模型自律：

- **一般操作不轉原句**：模型判成「一般報價單操作」時，句子帶有改價、報價因子、轉訂單這類字，改走試算或轉訂單檢查；有報價單編號時送出的是程式組的查詢或複製句，原句只有在沒有報價單編號時才轉（報價單 Agent 的寫入動作都要編號）。
- **問句只試算**：「如果改成 200000 呢？」就算模型判成要改，也只試算；「降 2 萬」「打九折」這類相對說法不自己換算，改問總價。
- **門檻不靠四捨五入**：判斷用不四捨五入的毛利率，並把二分法可能少調一格（報價因子 −0.0001）算進去。例如 191333 顯示 25.00%，實際 24.9998%，要主管核准。
- **規則缺了就不放行**：毛利率或報價因子下限的規則作廢、過期、不存在或寫錯時，至少要主管核准；客戶等級不在下限表裡也一樣。
- **計算與驗證程式要登記**：`computation_sha256`、`attester_sha256` 對不上或沒登記，就不執行；試算條目作廢就不跑，過期就不自動改價。顯示數字前會從後端重讀報價單，和收據裡的資料來源比對。
- **改完再核對**：報價單 Agent 改完後，從後端重新讀新報價單算一次，確認原單沒動。
- **轉訂單排隊**：同一張報價單的轉訂單一次只做一個，輪到時重讀報價單和訂單再判斷一次。兩個人同時要轉同一張單，只會轉一次。
- **結果不明先擋**：經 A2A 轉訂單遇到逾時、取消，或報價單 Agent 回「操作中斷」「可能已經建立」這類回覆時，那張單先擋住不讓人重送，因為遠端可能還在建立訂單。要有證據才放行：送出時先拿到 task 編號（沒拿到就用這邊產生的對話編號），下一次要轉時問報價單 Agent 那個 task 的狀態，還在跑就繼續擋；task 停了（或對方已經沒有這個 task），再等 MCP 呼叫後端的逾時（2 分鐘）過去，重讀訂單仍沒有才送。查不到 task 狀態也繼續擋。確認沒送出、核對成功、明確回報失敗，或重讀時已有訂單（照樣依規則不轉），會直接解除。排隊和這個紀錄都在程序裡，重啟後就不記得，議價顧問只能跑一個容器。
- **只開給本機**：Compose 把 8502 綁在 `127.0.0.1`，網頁介面和 A2A 端點沒有登入機制。

還沒處理的：

- 轉單排隊和「結果不明」紀錄只在議價顧問程序的記憶體裡，不能跑多個容器。重啟會忘記紀錄，如果剛好在遠端還沒做完時重啟，重啟後可能重送；遇到結果不明時，照提示等一下再試讓程式重新檢查，或先到系統確認，不要用重啟來解除。沒有做持久化的冪等鍵。
- 規則條目還沒有人簽核時一樣會套用，回覆會標「未驗證」；要嚴格的話，簽核前不要拿來給業務用。
- OKF v0.2 的 `verified` 只是文字，`human:` 誰都寫得出來；登記的 sha256 也放在同一個知識庫裡。知識庫的可信度靠 git 的審查紀錄，以及 `okf verify` 對照系統。
- 報價單 Agent 的 A2A 和 Chat UI 經前端 nginx（3000 埠）開放，沒有登入，這是課程提供的架構。
- 關聯圖 `viz.html` 用 Google 官方 viewer，會直接把條目的 Markdown 轉成 HTML，知識庫必須是可信的內容。

## 執行

整套系統加上議價顧問（模型設定讀根目錄 `.env`）：

```bash
docker compose -p ezstore -f docker-compose.yml -f docker-compose.build.yml -f docker-compose.advisor.yml up -d --build
docker compose -p ezstore exec db psql -U ezstore -f /scripts/seed-test-data.sql   # 重灌測試資料
```

網頁介面 http://localhost:8502/dev-ui/ ，agent card http://localhost:8502/a2a/pricing_advisor/.well-known/agent-card.json 。

本機開發：

```bash
cd advisor && cp .env.example .env
uv sync --group dev --extra eval
agents-cli playground --port 8502       # 和 Docker 的 advisor 擇一，不能同時佔 8502
```

`run_dialog.py`（示範對話）和 `a2a_demo.py` 會新增複製單和訂單，跑之前先重灌 seed。seed 會先 `TRUNCATE` 再寫入，資料會回到初始的 12 張報價單、10 筆訂單。要在另一套資料庫上跑，就建一份 `.env.test.local`（Git 已忽略），把 `BACKEND_API`、`QUOTATION_AGENT_URL`、`ADVISOR_URL`、`FRONTEND_URL` 改成那套環境的位址，再用 `uv run --env-file .env.test.local python scripts/run_dialog.py`。

```bash
uv run python scripts/run_dialog.py
```

預設模型是 `gemini-3.8-flash`。測試時 `.env` 設 `AGENT_MODEL=gemini-3.1-flash-lite` 省額度。Compose 讀根目錄的 `.env`，在這個資料夾直接跑讀 `advisor/.env`。

| 變數 | 預設 | 用途 |
|---|---|---|
| `AGENT_MODEL` | `gemini-3.8-flash` | `understand` 與 `answer_with_knowledge` 的模型（政策問答遇到有結構化規則的條目不呼叫）；`openai/` 開頭改走 OpenAI 相容 API |
| `MODEL_MAX_ATTEMPTS` | `6` | 每次呼叫 Gemini 最多試幾次；額度少的時候設成 1 |
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
