# 本地自我驗收（不是助教正式成績）

`run.py` 用原版 `agents-cli eval generate` 取得真正的 Agent 執行紀錄，再直接呼叫本地評審介接。權重、題目條件與後端核對沿用 `scripts/grading/grade_agent.py` 和原 `student-suite.json`，不修改教師 rubric、不提供假 ADC。這個替代流程的結果只可標為「本地自我驗收」，不等於助教私有題庫的正式成績，也不表示已執行 CLI 的雲端評分服務。

兩個 LLM 指標使用 `JUDGE_MODEL`（未指定則用 `AGENT_MODEL`）；相同模型自評可能有偏差。保留完整 trace，不截掉較晚的工具呼叫；缺少回覆或模型錯誤時失敗，不以無效 0 分當成功結果。

只允許隔離後端 `127.0.0.1:58080`、MCP `127.0.0.1:58010/mcp`、Agent `127.0.0.1:58501`。先建立專用測試 Compose 與資料卷，將種子資料載入該隔離資料庫；不可重灌日常的 `ezstore-db-1`。以本輪保存的 `work/ezstore_fixes_20261018/compose.yml` 為重現環境（機器路徑需依實際位置調整）。

```powershell
# 在 ezstore 專案根目錄，隔離服務已啟動且其模型與以下設定相同
$env:AGENT_MODEL = 'openai/qwen3.5-9b'
$env:JUDGE_MODEL = 'openai/qwen3.5-9b'
$env:LOCAL_LLM_BASE = 'http://127.0.0.1:18081/v1'
$env:BACKEND_API = 'http://127.0.0.1:58080/api/v1'
$env:MCP_URL = 'http://127.0.0.1:58010/mcp'
$env:FRONTEND_URL = 'http://localhost:53000'
$env:PYTHONIOENCODING = 'utf-8'
uv run --project advisor --no-sync python scripts/local_eval/run.py --repo . --suite scripts/grading/student-suite.json --backend http://127.0.0.1:58080 --mcp-url http://127.0.0.1:58010/mcp --no-reseed
```

產物在 `artifacts/grading/<當次時間>/`，包含原始 traces、逐指標分數、理由及後端核對。`--no-reseed` 是強制參數，避免教師腳本內的日常資料庫重灌指令被執行。

講義第 10 頁允許 Google AI Studio API key，Vertex AI／GCP 是可選路徑；第 17 頁描述助教在本機使用私有題庫，沒有把正式成績等同於雲端評分。目前安裝的 `agents-cli` v1.10.0 在 `refusal_or_action` 這類 prompt 指標上走雲端評分服務，因未能解析 GCP project 而停止。這是工具的執行環境限制，不是老師要求購買雲端服務。

GCP project 是 Google Cloud 的專案識別；ADC（Application Default Credentials）是程式取得 Google Cloud 身分憑證的機制。選用上述雲端評分路徑時，需設定真實專案及具備權限的認證。此次直接收到的是「找不到專案」錯誤；標準本機 ADC 檔也未建立，但尚未進行雲端權限、API 啟用或計費驗證。AI Studio API key 本身不能當作已完成這些設定的證據。
