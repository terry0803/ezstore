---
type: PostgreSQL Table
title: 報價單資料表（quotations、quotation_items）
description: 報價單與報價品項的欄位、狀態，以及測試資料金額修正的紀錄。
resource: postgresql://db:5432/ezstore/public/quotations
tags: [quotation, schema, data-quality]
derived_amounts_consistent: true
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:10:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-17T08:00:26Z }
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
    title: 教師原始測試資料 seed-test-data.sql（修正前版本）
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

`derived_amounts_consistent: true` 表示 12 張測試報價單的總價、利潤、利潤率都和品項重算相同（利潤率四捨五入到小數 4 位）。`okf verify` 會讀完所有分頁逐張核對。

# 測試資料的修正前紀錄

2026-10-17 用後端 API 讀出 12 張報價單、依品項重算，課程原始的 seed 有這些差異：[^seed]

- QT-20260115-001 存的總價是 253500，品項小計加起來是 253350。
- 7 張存的利潤和重算不同：QT-20260115-001（存 72000、重算 66150）、QT-20260120-001（82120、86570）、QT-20260210-001（21320、22720）、QT-20260218-001（39450、52130）、QT-20260325-001（66060、68060）、QT-20260326-001（39960、52960）、QT-20260328-001（33000、38500）。
- 單價都等於定價 × 報價因子。

同一天把本專案的 `scripts/seed-test-data.sql` 改成重算的數字：1 筆總價、7 筆利潤、9 筆利潤率。定價、成本、數量、報價因子和訂單沒動，`advisor/tests/fixtures/seed_snapshot.json` 也一起更新。

2026-10-17 另已先在隔離資料庫驗證受條件保護的修復交易，再備份主資料庫並套用九張單的限定欄位修正；主庫重查十二張均已一致，沒有重新灌入種子或清空既有資料。證據見專案 `artifacts/fix-20261017/main-data-after-repair.json` 與 `sql-repair-validation.json`。本條目的機器驗證另由 `okf verify` 對執行中的系統完成後記錄。即使正常種子已一致，任意來源仍可能出現存值與重算差異，計算程式的 `stored_mismatch` 偵測與人工污染快照測試仍保留。

[^quotation-model]: EZStore 後端 models/quotation.go
[^seed]: 教師原始測試資料 seed-test-data.sql（修正前版本）
