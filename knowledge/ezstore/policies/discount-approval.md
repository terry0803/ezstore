---
type: Policy
title: 改價核准層級（2026 年版）
description: 依改價後的毛利率決定業務能不能自己改、要誰核准，毛利率低於 5% 不可報價。
tags: [policy, discount, approval, margin]
demo_policy: true
rule_kind: margin_tiers
margin_tiers:
  - { min_margin: 0.25, approval: none, label: 業務可直接調整 }
  - { min_margin: 0.15, approval: sales_manager, label: 需業務主管核准 }
  - { min_margin: 0.05, approval: general_manager, label: 需總經理核准 }
below_lowest: { approval: forbidden, label: 不可報價 }
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:20:00Z }
status: stable
stale_after: 2027-01-01T00:00:00Z
sources:
  - id: pricing-formula
    resource: /system/pricing-formula.md
    title: 報價金額怎麼算
    author: claude-code/claude-opus-5-5
    last_modified: 2026-10-16T17:10:00Z
---

# 規則

> 這是第一次作業的示範規則，數字由作業設計，不是 EZStore 系統或老師提供的資料。系統本身沒有核准流程。

改價後的毛利率（利潤 ÷ 總價）決定核准層級：

| 改價後毛利率 | 核准層級 |
|---|---|
| 25% 以上（0.25） | 業務可直接調整 |
| 15% 以上、未滿 25%（0.15–0.25） | 需業務主管核准 |
| 5% 以上、未滿 15%（0.05–0.15） | 需總經理核准 |
| 未滿 5%（0.05），或虧損 | 不可報價 |

毛利率用品項重算，不用資料庫存的 `profit_amount`，算法見 [報價金額怎麼算](/system/pricing-formula.md)。[^pricing-formula] 改價的數字要用 [改價影響試算](/computations/price-change-impact.md) 算，驗證通過才可以拿來判斷。

同一次改價也要看 [報價因子下限](/policies/pricing-factor-floor.md)，兩條規則取比較嚴的那一個。

# 例子

QT-20260325-001（神盾局科技，vip）定價合計 258000、成本合計 143500。報價因子取到小數 4 位後：

| 目標總價 | 報價因子 | 毛利率 | 層級 |
|---|---|---|---|
| 200000 | 0.7751 | 28.24% | 業務可直接調整 |
| 180000 | 0.6976 | 20.27% | 需業務主管核准（因子也低於 vip 下限 0.70） |
| 160000 | 0.6202 | 10.32% | 需總經理核准 |
| 150000 | 0.5814 | 4.33% | 不可報價 |

舊版規則見 [2025 年版](/policies/discount-approval-2025.md)，已作廢。

[^pricing-formula]: 報價金額怎麼算
