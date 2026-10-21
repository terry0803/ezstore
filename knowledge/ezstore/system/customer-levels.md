---
type: Business Rule
title: 客戶等級與預設報價因子
description: vip、standard、new 三種客戶等級各自的預設報價因子，以及查詢用的 API。
resource: http://localhost:8080/api/v1/pricing-factor/{level}
tags: [customer, pricing-factor]
default_pricing_factor: { vip: 0.80, standard: 0.90, new: 1.00 }
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:10:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-21T03:50:03Z }
status: stable
stale_after: 2027-04-01T00:00:00Z
sources:
  - id: customer-model
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/backend/models/customer.go
    title: EZStore 後端 models/customer.go（DefaultPricingFactor）
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
  - id: pricing-factor-handler
    resource: https://github.com/cshliu77/ezstore/blob/09f6588c94ecb74b071246c55c32d838fc31e8f7/backend/handlers/pricing_factor_handler.go
    title: EZStore 後端 pricing_factor_handler.go
    author: team:ezstore-workshop
    last_modified: 2026-10-06T03:58:26Z
---

# 預設報價因子

| 客戶等級 | 預設報價因子 | 意思 |
|---|---|---|
| `vip` | 0.80 | 定價打八折 |
| `standard` | 0.90 | 九折 |
| `new` | 1.00 | 原價 |

數字來自後端的 `DefaultPricingFactor`。[^customer-model] 程式裡不認得的等級字串預設也是 0.90，但 API 只接受這三種等級。

`GET /api/v1/pricing-factor/{level}` 回傳 `{"level": "vip", "pricing_factor": "0.8"}`；等級不是這三種時回 400 `INVALID_LEVEL`。[^pricing-factor-handler] API 說明寫報價人員建單時可以自己調整這個值。[^pricing-factor-handler]

報價單會記下建單當下的客戶等級（`customer_level`）。報價因子能調到多低，見 [報價因子下限](/policies/pricing-factor-floor.md)。

[^customer-model]: EZStore 後端 models/customer.go（DefaultPricingFactor）
[^pricing-factor-handler]: EZStore 後端 pricing_factor_handler.go
