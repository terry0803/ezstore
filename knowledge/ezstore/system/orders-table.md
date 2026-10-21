---
type: PostgreSQL Table
title: 訂單資料表（orders、order_items）
description: 訂單欄位、和報價單的關聯，以及測試資料裡已經轉成訂單的報價單。
resource: postgresql://db:5432/ezstore/public/orders
tags: [order, schema]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:10:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-21T03:50:03Z }
status: stable
stale_after: 2027-04-01T00:00:00Z
sources:
  - id: order-model
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/backend/models/order.go
    title: EZStore 後端 models/order.go
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
  - id: mcp-server
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/mcp_server/server.py
    title: MCP Server server.py（convert_to_order）
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
  - id: seed
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/scripts/seed-test-data.sql
    title: 測試資料 seed-test-data.sql
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
---

# Schema

`orders`[^order-model]

| 欄位 | 說明 |
|---|---|
| `order_number` | 格式 `ORD-YYYYMMDD-NNN` |
| `customer_id` | 客戶 |
| `quotation_id` | 來源報價單，可以是空的（直接下單） |
| `total_price` | 訂單總價 |
| `status` | 預設 `pending`；測試資料另有 `confirmed`、`completed`、`cancelled` |

`order_items` 存產品、單價、數量、小計。

# 報價單轉訂單

MCP 工具 `convert_to_order` 依報價單的客戶與品項建一筆訂單，`quotation_id` 指回報價單，備註寫「從報價單 QT-… 轉換」。報價單本身不會改，也不會被發佈。[^mcp-server] 系統沒有擋重複轉換，同一張報價單轉兩次就會有兩筆訂單。

# 測試資料裡已經有訂單的報價單

重灌 seed 後：[^seed]

| 報價單 | 訂單 | 訂單狀態 |
|---|---|---|
| QT-20260115-001 | ORD-20260118-001 | completed |
| QT-20260120-001 | ORD-20260125-001 | confirmed |
| QT-20260205-001 | ORD-20260208-001 | confirmed |
| QT-20260210-001 | ORD-20260212-001 | completed |
| QT-20260218-001 | ORD-20260322-001 | pending |
| QT-20260305-001 | ORD-20260308-001 | confirmed |
| QT-20260310-001 | ORD-20260325-001 | pending |

QT-20260301-001 已發佈但還沒有訂單；QT-20260325-001、QT-20260326-001、QT-20260328-001、QT-20260330-001 是草稿。轉訂單前的檢查見 [轉訂單規則](/policies/order-conversion.md)。

[^order-model]: EZStore 後端 models/order.go
[^mcp-server]: MCP Server server.py（convert_to_order）
[^seed]: 測試資料 seed-test-data.sql
