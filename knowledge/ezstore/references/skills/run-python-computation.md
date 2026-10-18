---
type: Skill
title: 執行 runtime 為 python 的 Attested Computation
description: executor 的步驟：取得資料來源、綁定參數、執行知識庫指定的計算程式，回傳 attester 要看的收據。
tags: [skill, executor, python]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:30:00Z }
status: stable
---

# 什麼時候用

條目的 `type` 是 `Attested Computation`、`runtime` 是 `python`，而且 `executor.resource` 指到這裡。

# 前提

- 呼叫端只提供條目 `parameters` 宣告過的參數值，型別要對，必填的都要有。
- 不可以自己寫或改計算程式。計算程式就是條目 `computation` 指的那個檔案。

# 步驟

1. **讀條目**：從 frontmatter 取 `parameters`、`source_parameter`、`data_source`、`computation`、`executor.receipt`。
2. **取得資料來源**：依 `data_source` 用 `source_parameter` 的值抓資料。改價影響試算是用 `quotation_number` 呼叫後端 `GET /api/v1/quotations?quotation_number=…&page_size=1` 找到 id，再 `GET /api/v1/quotations/{id}` 取完整 JSON。找不到就回錯誤收據，不要猜。
3. **算來源的指紋**：把 JSON 依 key 排序、不留空白、UTF-8 編碼後算 sha256。
4. **執行計算程式**：讀 `computation` 檔案、算 sha256，載入後呼叫 `compute(來源資料, 其他參數)`。`source_parameter` 只用來抓資料，不傳進 `compute`。
5. **組收據**：只放 `executor.receipt` 列出的欄位：

    ```json
    {
      "computation": "/references/computations/price_change_impact.py",
      "computation_sha256": "<計算程式的 sha256>",
      "source_url": "http://backend:8080/api/v1/quotations/9",
      "source_sha256": "<來源 JSON 的 sha256>",
      "source": {"quotation_number": "QT-20260325-001", "...": "..."},
      "parameters": {"quotation_number": "QT-20260325-001", "target_total": 180000},
      "result": {"new_factor": "0.6977", "new_margin": "0.2028", "...": "..."},
      "executed_at": "2026-10-17T02:00:00Z"
    }
    ```

6. **交給 attester**：把收據交給條目 `attester.resource` 指的程式。驗證通過之前，不可以把數字顯示給使用者。

# 錯誤時

參數綁不上、資料抓不到、計算丟出例外，都回 `{"error": "原因"}`，不要改計算程式來繞過。
