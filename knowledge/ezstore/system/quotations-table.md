---
type: PostgreSQL Table
title: 報價單資料表（quotations、quotation_items）
description: 報價單與報價品項的欄位、狀態，以及測試資料裡存值和重算不一致的報價單。
resource: postgresql://db:5432/ezstore/public/quotations
tags: [quotation, schema, data-quality]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:10:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-17T04:49:26Z }
status: stable
stale_after: 2027-04-01T00:00:00Z
sources:
  - id: quotation-model
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/backend/models/quotation.go
    title: EZStore 後端 models/quotation.go
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
  - id: seed
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/scripts/seed-test-data.sql
    title: 測試資料 seed-test-data.sql
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
---

# Schema

`quotations`（一張報價單一筆）[^quotation-model]

| 欄位 | 型別 | 說明 |
|---|---|---|
| `quotation_number` | varchar(50)，唯一 | 格式 `QT-YYYYMMDD-NNN` |
| `customer_id` | uint | 客戶 |
| `customer_level` | varchar(20) | 建單當下的客戶等級：`vip`、`standard`、`new` |
| `pricing_factor` | decimal(5,4) | 報價因子 |
| `total_price` | decimal(14,2) | 總價 |
| `profit_amount` | decimal(14,2) | 利潤 |
| `profit_rate` | decimal(5,4) | 利潤率 |
| `status` | varchar(20) | `draft`（草稿）或 `published`（已發佈），預設 `draft` |
| `notes` | text | 備註；複製出來的單會寫「複製自 QT-…」 |

`quotation_items`（報價品項）[^quotation-model]

| 欄位 | 說明 |
|---|---|
| `product_id`、`product_name` | 產品與名稱快照 |
| `product_cost`、`list_price` | 建單當下的成本與定價快照 |
| `unit_price`、`quantity`、`subtotal` | 單價、數量、小計 |

計算方式見 [報價金額怎麼算](/system/pricing-formula.md)。

# 測試資料的不一致

2026-10-17 用後端 API 讀出 12 張報價單、依品項重算後比對：[^seed]

- QT-20260115-001 存的總價是 253500，品項小計加起來是 253350。
- 7 張存的利潤和重算不同：QT-20260115-001（存 72000、重算 66150）、QT-20260120-001（82120、86570）、QT-20260210-001（21320、22720）、QT-20260218-001（39450、52130）、QT-20260325-001（66060、68060）、QT-20260326-001（39960、52960）、QT-20260328-001（33000、38500）。
- 單價都等於定價 × 報價因子。

測試資料是 SQL 直接寫入，沒有經過後端重算。後端建立、修改、複製的報價單沒有這個問題。

[^quotation-model]: EZStore 後端 models/quotation.go
[^seed]: 測試資料 seed-test-data.sql
