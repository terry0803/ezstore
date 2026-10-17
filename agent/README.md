# EZStore 報價單管理 Agent

用 Google ADK 2.11 的 Graph Workflow 寫成的報價單助手。它透過 MCP Server 的 6 個工具操作報價單，由前端 Chat UI（`/agent-api`）呼叫。ADK 的 app 名稱是 `quotation_agent`。

## 圖的設計

```
START → load_context ──（no_credentials）──────────────────────────────┐
          │                                                             │
          └─（classify）→ classify_intent → route                       │
                            ├─ get_quotation                            │
                            ├─ list_customer_quotations                 │
                            ├─ duplicate_quotation                      │
                            ├─ update_pricing_factor                    │
                            ├─ adjust_total_price                       │
                            ├─ convert_to_order                         │
                            ├─ clarify                                  │
                            └─ off_topic                                │
                          全部 ───────────────────────────────→ respond ←┘
```

| 節點 | 種類 | 做什麼 |
|------|------|--------|
| `load_context` | 函式 | 取出使用者這一句。沒有任何模型憑證就直接走 `no_credentials` 到 `respond`，回覆設定說明。有待補的前一輪操作（`state.pending_intent`）就附在提示裡；state 是空的（例如評分題庫預先寫好第一輪）、但上一輪助手像在要資料（沒有系統連結，而且是「請提供」「請問」、問句結尾或「需要…編號」），改附上一輪的對話 |
| `classify_intent` | `LlmAgent` | 唯一呼叫 LLM 的節點。輸出 Pydantic 的 `Intent`：八種意圖之一（6 個操作、`provide_info`、`off_topic`）加上抽出來的欄位 |
| `route` | 函式 | 依 `Intent` 決定下一個節點與工具參數，全部是程式判斷：<br>1. 程式拒答：提示注入（先統一全形半形、大小寫、空白再比對）、客戶／產品增修刪。<br>2. 分類器判成離題時的補救：句子明確是六種操作之一（`_KEYWORD_OPERATIONS`）就改判；正在追問、使用者只回一個編號／數字／客戶名稱，就接回原本的操作（`_bare_answer`）。<br>3. 否定句（「不要複製」）和說明、假設句（「教我如何複製」「如果複製會怎樣」）不會變成寫入。<br>4. 報價單編號和數字一律從使用者原文抓，模型抽到的數字不直接用；含糊、兩個值或相對的說法就追問。<br>缺欄位或數字不合法就走 `clarify` 並存下 `pending_intent`，齊了就走對應的操作節點並清掉 `pending_intent` |
| 6 個操作節點 | 函式 | 各呼叫一個 MCP 工具（`McpToolset.get_tools()` 取得工具後 `run_async`），回傳工具的文字。工具錯誤轉成「操作失敗：…」；會寫入的操作（`_WRITE_TOOLS`）遇到逾時、連不上或後端 5xx，加一句請使用者先查詢確認，因為可能已經建了新單 |
| `clarify` | 函式 | 回「請提供…」列出缺的欄位與已知資料；沒有操作可接時回「請告訴我您要對報價單做什麼操作」 |
| `off_topic` | 函式 | 固定的拒答文字（含「只能協助報價單相關的操作」） |
| `respond` | 函式 | 唯一輸出給使用者看的節點。Chat UI 依事件的 `nodeInfo.path` 只顯示 `respond@N` 的文字 |

幾個設計重點：

- 每則訊息都從 `START` 重跑一次圖，不靠 LLM 記對話。跨回合只靠 `pending_intent` 與上一輪對話。
- LLM 只負責「聽懂」，不決定要不要呼叫工具。所以離題、注入、缺資料這些情況，換模型也不會跑出不該有的工具呼叫。
- 修改類工具在 MCP Server 端就是先複製再改，回覆也已經寫「原始報價單（未修改）」，Agent 原樣呈現，連結都是純文字。
- 路由邊的寫法是 `(route, {"get_quotation": get_quotation, ...})`。ADK 2.11 的 `edges` 裡，一般的 tuple 是一條鏈（`(a, b, c)` 代表 a→b→c），要分支得用 dict。

## A2A

`fast_api_app.py` 在 `/a2a/quotation_agent` 提供 A2A 端點，agent card 在 `/a2a/quotation_agent/.well-known/agent-card.json`：

- skill 是 6 個操作各一個，例句同 spec 1.1–1.6（`OPERATION_DESCRIPTIONS`、`OPERATION_EXAMPLES`）。
- A2A 回覆只帶 `respond` 節點的文字（`app_utils/a2a.py` 的 `only_node_artifacts`），分類器輸出的 Intent JSON 不會出現在 task artifact 裡。
- 第二個 Agent（`../advisor`，議價顧問）就是用這個端點請報價單 Agent 改總價、轉訂單。Compose 內部位址是 `http://agent:8080/a2a/quotation_agent`，本機可以經前端 nginx：`http://localhost:3000/agent-api/a2a/quotation_agent`。

## 新增一個操作

假設 MCP Server 多了一個工具 `publish_quotation(quotation_number)`：

1. `quotation_agent/agent.py` 的常數：
   - `OPERATIONS` 加 `"publish_quotation"`
   - `REQUIRED_FIELDS["publish_quotation"] = ("quotation_number",)`
   - `OPERATION_LABELS["publish_quotation"] = "發佈報價單"`
   - 有新欄位時，`FIELD_LABELS` 也要加
2. `Intent.intent` 的 `Literal` 加上 `"publish_quotation"`；有新欄位就在 `Intent` 加欄位。
3. `CLASSIFIER_INSTRUCTION` 的意圖清單加一行說明。注意 instruction 裡不要寫大括號，ADK 會把 `{...}` 當成 state 變數。
4. 加一個節點函式：

   ```python
   async def publish_quotation(ctx: Context, node_input: dict) -> str:
       return await _call_mcp_tool(ctx, "publish_quotation", node_input)
   ```

5. `root_agent` 的 `edges`：`route` 的路由 dict 加 `"publish_quotation": publish_quotation`，再加一條 `(publish_quotation, respond)`。A2A agent card 也要在 `OPERATION_DESCRIPTIONS`、`OPERATION_EXAMPLES` 各加一筆。
6. 程式防護：
   - 會寫入資料的操作加進 `_WRITE_TOOLS`，否定句、說明句的防護和「可能已經建了新單」的提醒才會套用。
   - 要讓分類器判錯時也能用關鍵字補救，在 `_KEYWORD_OPERATIONS` 加一條（具體的放前面）。
   - 「發佈」目前列在 `_UNSUPPORTED_ACTION_RE`（不支援的動作），新增發佈操作時要從那裡拿掉，否則補救路徑會擋掉它。
7. 測試：`tests/unit/test_route.py` 加路由測試，`tests/unit/test_keyword_safety.py` 加否定句、說明句的正反例；`tests/eval/datasets/quotation-actions.json` 加一題，`eval_case_id` 用工具名。

`McpToolset` 的 `tool_filter` 直接用 `OPERATIONS`，不用另外改。

## 執行

```bash
cp .env.example .env              # GEMINI_API_KEY，MCP_URL=http://localhost:8010/mcp
uv sync --group dev --extra eval
agents-cli playground --port 8501 # http://127.0.0.1:8501
uv run pytest tests/unit tests/integration -q
agents-cli eval run --dataset tests/eval/datasets/quotation-guardrails.json
```

模型由 `AGENT_MODEL` 決定，預設 `gemini-3.8-flash`（講義指定）。設成 `openai/<模型>` 會經 LiteLLM 改走 OpenAI 相容 API（位址 `LOCAL_LLM_BASE`），例如本機 llama.cpp 的 `openai/qwen3.5-9b`。`MODEL_MAX_ATTEMPTS` 是每次呼叫 Gemini 最多試幾次，預設 6，遇到 429 會退避重試；額度少的時候設成 1。評估指標的評審模型用 `JUDGE_MODEL`，沒設就跟 `AGENT_MODEL` 一樣。

測試時為了省額度，`.env` 設 `AGENT_MODEL=gemini-3.1-flash-lite`，這是帳號可用的模型裡最便宜的（`gemini-2.5-flash-lite` 對新帳號已停用，回 404）。Compose 讀根目錄的 `.env`，在這個資料夾直接跑讀 `agent/.env`。
