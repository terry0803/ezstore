---
type: MCP Server
title: EZStore MCP Server 的 6 個報價單工具
description: 報價單 Agent 背後的 6 個 MCP 工具、先複製再改的做法，以及改總價的二分法設定。
resource: http://localhost:8010/mcp
tags: [mcp, quotation, tool]
mcp_tools: [get_quotation, list_customer_quotations, duplicate_quotation, update_pricing_factor, adjust_total_price, convert_to_order]
bisect: { low: 0.01, high: 5.0, max_iterations: 20, tolerance: 0.01 }
max_pricing_factor: 9.9999
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:10:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-21T07:22:17Z }
status: stable
stale_after: 2027-04-01T00:00:00Z
sources:
  - id: mcp-server
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/mcp_server/server.py
    title: MCP Server server.py
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
  - id: local-mcp-fix
    resource: ../../../mcp_server/server.py
    title: 本作業修改後的 MCP Server（客戶辨識、完整分頁、報價因子上限、核准改價）
    author: process:codex
    last_modified: 2026-10-18T02:50:02Z
---

# 工具

Streamable HTTP，Compose 內部 `http://mcp-server:8000/mcp`，對本機開 `http://localhost:8010/mcp`。[^mcp-server]

| 工具 | 參數 | 做什麼 |
|---|---|---|
| `get_quotation` | `quotation_number` | 查報價單與品項 |
| `list_customer_quotations` | `customer_name` | 本地修正版：讀完所有分頁，唯一完全相符優先；模糊結果超過一位時要求完整名稱，報價清單不再截斷於 100 筆[^local-mcp-fix] |
| `duplicate_quotation` | `quotation_number` | 複製成新草稿 |
| `update_pricing_factor` | `quotation_number`、`new_pricing_factor` | 先複製，再改副本的報價因子 |
| `adjust_total_price` | `quotation_number`、`target_total_price` | 先複製，再用二分法調副本的報價因子 |
| `convert_to_order` | `quotation_number` | 依報價單建訂單 |

# 規則

- 改因子與改總價先複製，改的是副本，原單不動，回覆會寫「原始報價單：…（未修改）」。[^mcp-server]
- 每則回覆附純文字連結，例如 `http://localhost:3000/quotations/12`、`http://localhost:3000/orders/11`。[^mcp-server]
- 報價因子與目標總價要是大於 0 的有限數字，否則回「報價因子必須是大於 0 的有限數字」「目標總價必須是大於 0 的有限數字」。找不到報價單回「找不到報價單編號 …」。[^mcp-server]
- 改報價因子時，因子取到小數 4 位後要介於 0.0001 和 9.9999（`max_pricing_factor`），複製前就檢查，超出就不建立副本。[^local-mcp-fix]
- 後端報價因子欄位是 decimal(5,4)。本作業在 Agent 層預檢欄位容量，後端也檢查正因子與儲存範圍。MCP 寫入與二分法仍沿用課程流程；直接呼叫 MCP 仍可能在複製後遇到其他錯誤，必須查詢確認結果再重試。

# 改總價的二分法

`adjust_total_price` 在報價因子 0.01 到 5.0 之間二分搜尋，每次把因子取到小數 4 位、寫回副本看總價，最多 20 次，和目標差不到 0.01 就停。[^mcp-server] 20 次後還沒到，回覆會加一句「注意: 已達最大迭代次數」。所以總價最高只能到定價合計 × 5.0，最低是定價合計 × 0.01。

[^mcp-server]: MCP Server server.py
[^local-mcp-fix]: 本地 mcp_server/server.py；修改範圍見 scripts/check_assignment.py，不代表講師已同意變更。

## 本地修正：議價顧問的版本前提條件

工具數仍為六個。`adjust_total_price` 增加可選 `approval` 參數：顧問提供核准快照與 attested computation 結果時，MCP 先以相同的 20 次二分法及逐項單價捨入驗證候選因子，再呼叫後端 `approved-price-copy` 原子建立最終副本，過程不寫入中間候選草稿。版本不符或核准資料錯誤即拒絕，絕不退回普通複製／更新流程。第一個 Agent 的一般改總價請求未帶此參數時，維持老師原有的先複製與最多 20 次二分法更新流程。來源：本地 `mcp_server/server.py` 與 `backend/services/approved_price.go`。
