---
type: API Endpoint
title: EZStore 後端 REST API（報價與訂單）
description: 報價單、訂單、客戶與預設報價因子的 REST 端點，以及查詢參數。
resource: http://localhost:8080/api/v1
tags: [api, quotation, order]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:10:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-16T17:29:21Z }
status: stable
stale_after: 2027-04-01T00:00:00Z
sources:
  - id: routes
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/backend/routes/routes.go
    title: EZStore 後端 routes.go
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
  - id: order-repo
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/backend/repositories/order_repo.go
    title: EZStore 後端 order_repo.go
    author: team:ezstore-workshop
    last_modified: 2026-10-12T06:42:48Z
---

# 端點

前綴都是 `/api/v1`。本機是 `http://localhost:8080`，Compose 內部是 `http://backend:8080`，前端 nginx 也會把 `/api/` 轉過去。[^routes]

| 方法與路徑 | 用途 | 查詢參數 |
|---|---|---|
| `GET /quotations` | 報價單清單（含品項） | `page`、`page_size`（最多 100）、`status`、`customer_id`、`quotation_number`（精確） |
| `GET /quotations/{id}` | 單張報價單（含客戶與品項） | |
| `PUT /quotations/{id}` | 修改報價單，後端重算金額 | |
| `POST /quotations/{id}/duplicate` | 複製成新草稿 | |
| `POST /quotations/{id}/publish` | 發佈 | |
| `DELETE /quotations/{id}` | 刪除（已發佈的不行） | |
| `GET /orders` | 訂單清單 | `page`、`page_size`、`status`、`customer_id` |
| `GET /orders/{id}` | 單筆訂單 | |
| `POST /orders` | 建立訂單 | |
| `GET /customers` | 客戶清單 | `search`（名稱模糊搜尋）、`page`、`page_size` |
| `GET /pricing-factor/{level}` | 預設報價因子 | |

`GET /orders` 不能用報價單篩選。要找某張報價單有沒有訂單，先用報價單的 `customer_id` 篩，再比對每筆訂單的 `quotation_id`。[^order-repo]

清單回傳格式是 `{"data": [...], "total": N, "page": 1, "page_size": 20}`。

議價顧問 Agent 只用 `GET`。會改資料的動作一律經 [報價單 Agent](/system/quotation-agent.md) 處理。

[^routes]: EZStore 後端 routes.go
[^order-repo]: EZStore 後端 order_repo.go
