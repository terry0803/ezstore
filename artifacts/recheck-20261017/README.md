# 2026-10-17 本輪重查證據

本目錄記錄以 `e68052e` 為起點的再次審核、重現及修復。**本輪已完成：離線／資料庫／瀏覽器驗證、Gemini 30＋5 項功能驗收與主站部署核對。** 整體說明見[本輪完整檢查紀錄](../../reports/本輪完整檢查紀錄.md)。

## 已完成的非模型驗證

| 項目 | 結果 | 來源 |
|---|---|---|
| Advisor | 167 通過；封鎖 socket／DNS，無真實模型呼叫 | [摘要](advisor-review-summary.json)、[最終日誌](advisor-final-tests.log) |
| MCP | 17 通過 | [最終日誌](mcp-unit-final.log) |
| Backend | 21 通過＝14 既有測試＋7 真實 PostgreSQL 整合案例 | [最終日誌](backend-integration-final.log) |
| Frontend | E2E 15 通過；unit 7 通過；build 通過 | [E2E](frontend-e2e-after.log)、[unit](frontend-unit-final.log)、[build](frontend-build-final.log) |
| Scripts | 28 測試＋28 子測試通過 | [日誌](scripts-offline.log) |
| First Agent | 172 通過、0 失敗、1 個 ADK experimental warning；5.04 秒 | [日誌](agent-offline.log) |
| OKF | 17 條、0 error、0 warning；可驗證項目 10／10，另 7 條 unverified | [validate](okf-validate.log)、[verify](okf-verify.log) |

[Frontend／backend／MCP 摘要](frontend-backend-mcp-summary.json)保存範圍、檔案 hash、隔離環境及清理結果。這批元件測試沒有呼叫模型，也沒有寫入主資料庫；真實 PostgreSQL 測試使用短期獨立資源。E2E 的對話測試不能算成真實 Gemini 推論。

## 失敗重現與修復對照

- Backend： [修正前 5 題失敗](backend-integration-before.log) → [最終 21 題通過](backend-integration-final.log)。涵蓋預載 Customer 蓋回舊 ID、並行替換品項混合、舊 draft 覆蓋發布狀態；另外確認發布後不能用舊狀態刪除。第一 Agent／MCP 的重複轉單行為保留。
- Frontend： [三種表單快取回歸先失敗](frontend-e2e-before-cache-fix.log) → [完整 15 題通過](frontend-e2e-after.log)。客戶、產品、報價單儲存後立即重開均顯示已儲存值。
- Advisor： [基線 159 題通過](advisor-baseline-tests.log) → [新增情境先重現 5 題失敗](advisor-regression-before.log) → [最終 167 題通過](advisor-final-tests.log)。新增案例針對 timeout／cancel 後遠端仍可能寫入、未確認完成回覆、派送前失敗及規則重讀失敗；A2A cleanup 不再取代原始結果。詳細界線見[摘要](advisor-review-summary.json)。
- First Agent： [關鍵字安全案例](../../agent/tests/unit/test_keyword_safety.py)區分否定／流程說明與真正操作，並保留「不要修改原單，請複製」等合法指令；最終離線 172 題已通過，追加真實模型 5／5 通過，見下方原始結果。

上述失敗日誌刻意保留作為修正前證據。它們不是最新狀態，也不能為使提交看起來全綠而改寫原始內容。

## 真實 Gemini 與部署：已完成

- [完整功能驗收](gemini-acceptance.json)：30／30、37 回合、37 可見模型事件，32,775 tokens。兩次 Gemini 503 保留於 `attempt_failures`，接續未完成項目後完成；不是全程無重試。
- [追加回歸](gemini-guards.json)：5／5、6 回合、6 可見事件，4,782 tokens，無失敗重試；涵蓋否定／教學不寫入、保留原單的正常複製與同時轉單只有一張。
- [主站 UI](main-ui.json)：1 個 Gemini 只讀查詢成功，[截圖](main-ui-gemini.jpg)保存實際畫面；沒有瀏覽器警告／錯誤。
- [主站部署](main-deployment.json)：六服務／六端點正常，12 報價單、10 訂單及明細未變。第一次舊 MCP 映像識別不一致已重新建立並驗證。
- [總表](summary.json)：最終測試計數、來源檔案 SHA-256、模型範圍與剩餘限制。最終 guard 調整後重跑全部離線及追加真實案例，完整30題亦包含更早的核心結果。
- [清理](isolated-cleanup.log)：本輪隔離容器、網路、資料卷均移除；主環境繼續運行。

可見用量不包含全部遠端 A2A、UI 或失敗呼叫，不等於帳單。全部完整快照比較均在相應案例前後完成，不只比較資料筆數。

本輪未執行 Qwen，未重跑教師獨立 grader。教師規格預設 `gemini-3.8-flash`，與本輪實際模型不同；這項差異需揭露。

## 歷史評分證據

`previous-grading/` 是先前結果的選取副本，不是這輪重新跑出的分數：

- 98.4（原始總分 98.373333）：[報告](previous-grading/20261017_155043/report.md)、[結構化報告](previous-grading/20261017_155043/report.json)，以及 [guardrails](previous-grading/20261017_155043/guardrails/run1/results_20261017_155322.json)、[actions](previous-grading/20261017_155043/actions/run1/results_20261017_155627.json)、[extra](previous-grading/20261017_155043/extra/run1/results_20261017_155751.json) 逐題原始結果。
- 99.2（四捨五入後顯示分數）：[變形題報告](previous-grading/20261017_165103/report.md)、[結構化報告](previous-grading/20261017_165103/report.json)、[逐題原始結果](previous-grading/20261017_165103/variants/run1/results_20261017_170013.json)。

模型評審低分的兩題不能合稱「理由都說完全正確」：各組一題有正確評語，另一題理由為空。判讀方式見[可信賴度報告](../../reports/可信賴度報告.md)。歷史分數不能當成教師正式成績或本輪新修復的驗收分數。

## 可攜性與限制

連結使用 repository 內相對位置。日誌內保留執行當時路徑、容器名稱、測試用 localhost 連結與時間，供追溯使用；它們不是換機後可直接點開的線上服務。來源 hash 僅對應各摘要產生時的檔案，不自動代表後續所有修改已驗證。檔案完整性見 `evidence-manifest.json`；雜湊對應本機原始位元組，Git 文字換行轉換可能改變換機後的雜湊。

Advisor 防重狀態仍僅在單一程序記憶體中，不持久、不能跨副本，未提供跨重啟 exactly-once 保證。完整限制、正式錄影／字幕等提交狀態，請以[本輪報告](../../reports/本輪完整檢查紀錄.md)為準。

## 再檢查一次（second-check/）

使用者要求再檢查一次時的紀錄：報價單 Agent 181、議價顧問 171 個離線測試（[agent](second-check/agent-offline.log)、[advisor](second-check/advisor-offline.log)），後端 21 個（[臨時 PostgreSQL](second-check/backend-postgres.log)），學生自我驗收 96.8（[報告](second-check/grading-student/report.md)），變化題 98.7（[報告](second-check/grading-variants/report.md)）。找到的兩個問題和修法見[本輪完整檢查紀錄](../../reports/本輪完整檢查紀錄.md)第 7 節。

