---
type: Policy
title: 改價核准層級（2025 年版，已作廢）
description: 舊版的毛利率核准門檻，已由 2026 年版取代，只留著對照，不可再用。
tags: [policy, discount, approval, deprecated]
demo_policy: true
rule_kind: margin_tiers
margin_tiers:
  - { min_margin: 0.20, approval: none, label: 業務可直接調整 }
  - { min_margin: 0.10, approval: sales_manager, label: 需業務主管核准 }
  - { min_margin: 0.00, approval: general_manager, label: 需總經理核准 }
below_lowest: { approval: forbidden, label: 不可報價 }
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:20:00Z }
status: deprecated
---

# 已作廢

> 這是第一次作業的示範規則，用來示範 OKF 的 `status: deprecated`。

現行規則是 [改價核准層級（2026 年版）](/policies/discount-approval.md)。這份只留著讓舊的報價紀錄看得懂，不可以拿來判斷新的改價。

# 舊版門檻

| 改價後毛利率 | 核准層級 |
|---|---|
| 20% 以上 | 業務可直接調整 |
| 10% 以上、未滿 20% | 需業務主管核准 |
| 0% 以上、未滿 10% | 需總經理核准 |
| 虧損 | 不可報價 |

2026 年版把每一級提高 5 個百分點，毛利率未滿 5% 就不可報價。
