---
type: Business Rule
title: 報價金額怎麼算
description: 單價、小計、總價、利潤與利潤率的計算方式、後端什麼時候會重算，以及已發佈的報價單不能修改或刪除。
tags: [pricing, quotation, formula]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:10:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-20T09:46:26Z }
status: stable
stale_after: 2027-04-01T00:00:00Z
sources:
  - id: quotation-service
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/backend/services/quotation_service.go
    title: EZStore 後端 quotation_service.go（buildItems、computeTotals、Duplicate）
    author: team:ezstore-workshop
    last_modified: 2026-10-12T06:42:48Z
  - id: quotation-model
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/backend/models/quotation.go
    title: EZStore 後端 models/quotation.go
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
---

# 公式

| 欄位 | 算法 |
|---|---|
| 單價 `unit_price` | 定價 `list_price` × 報價因子 `pricing_factor`，先四捨五入到小數兩位（本機修正版） |
| 小計 `subtotal` | 單價 × 數量[^quotation-service] |
| 總價 `total_price` | 所有品項小計相加[^quotation-service] |
| 利潤 `profit_amount` | 每個品項（單價 − 成本 `product_cost`）× 數量，再相加[^quotation-service] |
| 利潤率 `profit_rate` | 利潤 ÷ 總價，總價是 0 時記 0[^quotation-service] |

報價因子存到小數 4 位（`decimal(5,4)`），利潤率也是小數 4 位，金額是小數 2 位。[^quotation-model] 一張報價單只有一個報價因子，所有品項用同一個。

本機修補來源：`backend/services/quotation_service.go`、`backend/services/order_service.go`（2026-10-18，使用者授權修正；上方 GitHub 連結是老師原始基底，不包含這項修補）。

本機修正版使用 ROUND_HALF_UP：先將每項單價捨入到兩位，再乘數量、加總小計；利潤 = 總價 − 成本合計 C。定價合計 L × 因子只能作為未捨入估計，不能代替實際總價。例：650 × 0.3333 → 單價 216.65，數量 3 的小計與總價均為 649.95。這是對老師基底的金額精度修補；新增、修改與複製都套用，既有歷史單據不批次回寫。

# 什麼時候會重算

- 建立、修改（PUT）、複製報價單時，後端會依上面的公式重算。[^quotation-service]
- 複製時會重新讀產品目前的定價與成本，報價因子沿用原單。[^quotation-service]
- 已發佈（`published`）的報價單不能修改也不能刪除。[^quotation-service]

測試資料是直接用 SQL 寫進資料庫的，有些報價單存的利潤和用品項重算的不一樣，見 [報價單資料表](/system/quotations-table.md)。試算一律用品項重算，見 [改價影響試算](/computations/price-change-impact.md)。

[^quotation-service]: EZStore 後端 quotation_service.go（buildItems、computeTotals、Duplicate）
[^quotation-model]: EZStore 後端 models/quotation.go
