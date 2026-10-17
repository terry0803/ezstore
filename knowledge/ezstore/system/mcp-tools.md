---
type: MCP Server
title: EZStore MCP Server 的 6 個報價單工具
description: 報價單 Agent 背後的 6 個 MCP 工具、先複製再改的做法，以及改總價的二分法設定。
resource: http://localhost:8010/mcp
tags: [mcp, quotation, tool]
mcp_tools: [get_quotation, list_customer_quotations, duplicate_quotation, update_pricing_factor, adjust_total_price, convert_to_order]
bisect: { low: 0.01, high: 5.0, max_iterations: 20, tolerance: 0.01 }
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:10:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-17T03:58:50Z }
status: stable
stale_after: 2027-04-01T00:00:00Z
sources:
  - id: mcp-server
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/mcp_server/server.py
    title: MCP Server server.py
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
---

# 工具

Streamable HTTP，Compose 內部 `http://mcp-server:8000/mcp`，對本機開 `http://localhost:8010/mcp`。[^mcp-server]

| 工具 | 參數 | 做什麼 |
|---|---|---|
| `get_quotation` | `quotation_number` | 查報價單與品項 |
| `list_customer_quotations` | `customer_name` | 客戶名稱模糊搜尋，完全相符的優先 |
| `duplicate_quotation` | `quotation_number` | 複製成新草稿 |
| `update_pricing_factor` | `quotation_number`、`new_pricing_factor` | 先複製，再改副本的報價因子 |
| `adjust_total_price` | `quotation_number`、`target_total_price` | 先複製，再用二分法調副本的報價因子 |
| `convert_to_order` | `quotation_number` | 依報價單建訂單 |

# 規則

- 會改資料的工具都先複製，改的是副本，原單不動，回覆會寫「原始報價單：…（未修改）」。[^mcp-server]
- 每則回覆附純文字連結，例如 `http://localhost:3000/quotations/12`、`http://localhost:3000/orders/11`。[^mcp-server]
- 報價因子與目標總價要大於 0，否則回「報價因子必須大於 0」「目標總價必須大於 0」。找不到報價單回「找不到報價單編號 …」。[^mcp-server]

# 改總價的二分法

`adjust_total_price` 在報價因子 0.01 到 5.0 之間二分搜尋，每次把因子取到小數 4 位、寫回副本看總價，最多 20 次，和目標差不到 0.01 就停。[^mcp-server] 20 次後還沒到，回覆會加一句「注意: 已達最大迭代次數」。所以總價最高只能到定價合計 × 5.0，最低是定價合計 × 0.01。

[^mcp-server]: MCP Server server.py
