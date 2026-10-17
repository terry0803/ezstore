# 2026-10-17 修正與驗證證據索引

這個資料夾是 10/17 修正時留下的證據。當時用 `gemini-3.5-flash-lite` 跑完 30 題功能驗收（37 輪對話、約 33000 token）。之後 MCP 改總價改回講義原本的流程，測試模型改成更便宜的 `gemini-3.1-flash-lite`，最新結果寫在 `reports/修正與驗證紀錄.md`。

完整說明見 [修正與驗證紀錄](../../reports/修正與驗證紀錄.md)；舊 LAB 分數與方法見 [歷史可信賴度報告](../../reports/可信賴度報告.md)。原始證據保留成功、失敗與中斷紀錄，不把舊執行改寫成新版結果。

## 最新驗證

| 檔案 | 可支持的結論 |
|---|---|
| [gemini-full-acceptance.json](gemini-full-acceptance.json) | 最終 30／30、37 回合、38 可見模型事件；30,932 輸入＋2,321 輸出＝33,253 tokens。含逐題回覆、資料庫核對與 `attempt_failures`。 |
| [final-offline-summary.json](final-offline-summary.json) | 317 個 Python 測試（Agent 115、advisor 158、MCP 16、scripts 28）、28 子測試及 Go 14，零失敗；零真模型呼叫與主庫寫入。 |
| [agent-offline-tests.log](agent-offline-tests.log)／[agent-offline-summary.json](agent-offline-summary.json) | Agent 115／115；保留 Google ADK 實驗功能警告。 |
| [postwrite-advisor-tests.log](postwrite-advisor-tests.log) | advisor 158／158。 |
| [repair-mcp-tests.log](repair-mcp-tests.log) | MCP 16／16（當時的版本，含「複製前拒絕」那題；改回原流程後是 15 個）。 |
| [gemini31-full-acceptance.json](gemini31-full-acceptance.json) | 新版程式用 `gemini-3.1-flash-lite` 重跑 30 題功能實測：30／30，37 輪對話。 |
| [concurrency-result.json](concurrency-result.json) | 同時對同一張報價單複製、改因子、改總價、轉訂單（`scripts/verify_concurrency.py`）。 |
| [concurrency-advisor-result.json](concurrency-advisor-result.json) | 兩個人同時請議價顧問轉同一張單：只建立一張訂單，第二個排隊後重新檢查而沒有轉（`verify_concurrency.py --advisor`）。 |
| [disconnect-result.json](disconnect-result.json) | 真的停掉後端、MCP、A2A 對方，以及改總價途中暫停後端（`scripts/verify_disconnect.py`）。 |
| [scripts-offline-tests.log](scripts-offline-tests.log) | scripts 28／28，另 28 子測試通過。 |
| [repair-go-tests.log](repair-go-tests.log) | Go 14 個測試函式通過；隔離網路、唯讀來源。 |
| [frontend-verification.json](frontend-verification.json) | E2E 12／12、unit 7／7、production build 通過，零模型呼叫／主庫寫入，隔離環境已清理、主容器未變。 |
| [frontend-e2e.log](frontend-e2e.log)／[frontend-unit.log](frontend-unit.log)／[frontend-build.log](frontend-build.log) | 對應前端逐項結果；E2E 包含四位因子與失效 session 復原，受控回應不算真模型驗收。 |
| [frontend-main-containers-before.json](frontend-main-containers-before.json) | 前端隔離測試前的主容器識別，供完整性核對。 |
| [main-deployment.json](main-deployment.json) | 6 個運行服務、6 個 HTTP 200；兩個 Agent 配置為 Gemini 3.5 Flash-Lite；部署前後主庫 12 報價／10 訂單及明細一致。 |
| [main-ui-gemini.jpg](main-ui-gemini.jpg) | 主環境 UI 的靜態截圖；不代替完整操作影片。 |
| [okf-verify-main.log](okf-verify-main.log)／[okf-validate.log](okf-validate.log) | 主環境 verify 10／10；17 條目、0 error、0 warning，機器確認 10、未驗證 7。 |

完整 Gemini 驗收在 `b_stale_failure` 曾遇 429；錯誤記錄顯示當次帳號／模型免費層為 15 RPM。改用每輪至少 13 秒的節奏續跑，保留已通過案例後完成全套。38 是成功保留案例的可見模型事件數，不是所有 HTTP 嘗試總數；33,253 tokens 不包括較早獨立測試的全部用量，也不等於帳單。不要刪除 `attempt_failures` 或把續跑描述成從未中斷。

## 歷史、失敗與中斷紀錄

| 檔案 | 範圍與限制 |
|---|---|
| [local-acceptance.json](local-acceptance.json) | 先前 Qwen 25／25、32 回合；只代表當時版本，不能代替最終 Gemini。 |
| [qwen-second-review-stopped.json](qwen-second-review-stopped.json) | 第二輪 Qwen 檢查中止的 6 個已記錄案例，其中 1 個失敗；不是完整驗收。 |
| [gemini-full-attempt1-unreachable.json](gemini-full-attempt1-unreachable.json) | 首次 Gemini 完整驗收嘗試，記錄 6 個案例、5 個通過；保留修正前失敗。 |
| [gemini-smoke.json](gemini-smoke.json) | 早期 2／2 唯讀案例、3 次成功推論；全部資料前後一致。 |
| [gemini-unavailable-2.5.json](gemini-unavailable-2.5.json) | 早期 2.5 Flash-Lite 不可用，1 次 404、沒有回答。不能算成功案例。 |
| [smoke-repo-tests.log](smoke-repo-tests.log) | 早期工具測試 12＋4 子測試；最新 scripts 全套見上方 28＋28，不重複加總。 |

歷史 LAB 的 94.8／97.8 分、同題庫兩跑與 Markdown 破壞／還原證據原存於 `artifacts/grading/`、`agent/artifacts/` 等目錄，仍受 Git 忽略規則排除。它們不是本資料夾最終 Gemini 驗收的產物；若提交時要求獨立核對歷史 LAB，需另附精選原始 JSON，不應只交報告中的分數敘述。

## 示範資料修復

| 檔案 | 說明 |
|---|---|
| [sql-repair-validation.json](sql-repair-validation.json) | 隔離 PostgreSQL 修正九張示範單（1 總價、7 利潤、9 利潤率），再檢查十二張全跳過；非衍生欄位、明細及其他表保持不變，過期計畫拒絕。 |
| [main-data-after-repair.json](main-data-after-repair.json) | 主庫十二張已正確，待更新零筆。 |
| [main-before-deployment.json](main-before-deployment.json) | 部署前主資料快照，用來核對部署沒有改動資料。 |
| [ezstore-before-fix-20261017.dump](ezstore-before-fix-20261017.dump) | 修復前 PostgreSQL custom dump，26,271 bytes，含教師示範業務資料。保留備份不代表要求把它還原到現有主庫。 |

## 完整性與可攜性

[evidence-manifest.json](evidence-manifest.json) 記錄本資料夾可提交檔案的 byte 數與 SHA-256；不對 manifest 本身做循環雜湊。機器限定的 `compose.test.yml` 排除於 Git 與 manifest，金鑰與 `.env` 不納入證據包。10/17 晚上提交時文字檔的換行從 CRLF 統一成 LF，內容沒變，manifest 依提交的版本重算。

相對連結可隨專案搬移。JSON／log 裡的 `localhost`、Docker 服務名稱、容器識別或測試當時的本機路徑是歷史來源資訊，不表示收件者開啟檔案就能連上當時服務。離線摘要中的暫存 runner 路徑亦是原執行紀錄；不可把該絕對路徑當成跨電腦可直接執行的命令。

若另有新測試或重產證據，請保留原始失敗紀錄，更新索引後重算 manifest；不要只改數字或雜湊去掩蓋檔案內容差異。
