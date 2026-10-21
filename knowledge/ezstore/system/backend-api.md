---
type: API Endpoint
title: EZStore 後端 REST API（報價與訂單）
description: 報價單、訂單、客戶與預設報價因子的 REST 端點，以及查詢參數。
resource: http://localhost:8080/api/v1
tags: [api, quotation, order]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:10:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-21T07:22:17Z }
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

本地修正版的建立／更新報價 API 在寫入前拒絕非正因子、超過 9.9999 或四位小數捨入後為零的因子。此修正位於 `backend/services/quotation_service.go`，屬使用者要求的基底修補，並非上述講師來源已包含的行為。

議價顧問 Agent 只用 `GET`。會改資料的動作一律經 [報價單 Agent](/system/quotation-agent.md) 處理。

[^routes]: EZStore 後端 routes.go
[^order-repo]: EZStore 後端 order_repo.go

## 本地修正：核准版本與改價副本的原子交易

`POST /quotations/{id}/approved-price-copy` 接收 `source`（核准時的完整報價快照）、`target_total`、`factor`、`total`、`profit`。後端在同一筆交易內鎖定來源報價、客戶及依 ID 排序的產品，核對版本、明細、客戶等級、成本與牌價，再建立最終改價草稿。衝突回傳 HTTP 409 / `APPROVAL_CHANGED`，不建立副本，必須重新試算。欄位或結果錯誤也不得退回一般複製 API。這是使用者授權的基底修正，並非老師原版提供的端點。來源：`backend/services/approved_price.go`、`backend/handlers/approved_price.go`；併發驗證見 `backend/services/approved_price_test.go`。

此處的版本前提條件不是身分認證，也不是主管電子簽章。只有顧問判定業務可以直接調整的請求會走這條路；需主管核准的情況仍只產生申請草稿。
