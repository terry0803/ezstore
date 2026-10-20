---
type: Policy
title: 報價因子下限
description: 各客戶等級的報價因子最低可以到多少，低於下限要業務主管核准。
tags: [policy, pricing-factor, approval]
demo_policy: true
rule_kind: factor_floor
factor_floor: { vip: 0.70, standard: 0.80, new: 0.90 }
below_floor: { approval: sales_manager, label: 需業務主管核准 }
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:20:00Z }
status: stable
stale_after: 2027-01-01T00:00:00Z
sources:
  - id: customer-levels
    resource: /system/customer-levels.md
    title: 客戶等級與預設報價因子
    author: claude-code/claude-opus-5-5
    last_modified: 2026-10-16T17:10:00Z
---

# 規則

> 這是第一次作業的示範規則，數字由作業設計，不是 EZStore 系統或老師提供的資料。

下限是各等級的預設報價因子再減 0.10：[^customer-levels]

| 客戶等級 | 預設報價因子 | 下限 |
|---|---|---|
| `vip` | 0.80 | 0.70 |
| `standard` | 0.90 | 0.80 |
| `new` | 1.00 | 0.90 |

改價後的報價因子低於下限，就要業務主管核准，毛利率再高也一樣。客戶等級看報價單上記的 `customer_level`。

和 [改價核准層級](/policies/discount-approval.md) 一起看，取比較嚴的層級。

# 例子

QT-20260328-001（天空之城科技，new）定價合計 88000、成本合計 49500。客戶想壓到 76000 時，照 MCP 改總價的二分法試算，報價因子是 0.8637，總價 76005.60，毛利率 34.87%。毛利率夠，但因子低於 new 的下限 0.90，所以要業務主管核准。

2026 第三季曾經把 new 的下限暫時降到 0.85，見 [第三季新客戶優惠](/policies/promo-2026q3.md)，已經過期。

[^customer-levels]: 客戶等級與預設報價因子
