---
type: Glossary Term
title: 報價因子（pricing_factor）
description: 報價單上的折扣倍率，單價 = 定價 × 報價因子。
tags: [glossary, pricing-factor]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:30:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-20T09:46:26Z }
status: stable
stale_after: 2027-04-01T00:00:00Z
sources:
  - id: pricing-formula
    resource: /system/pricing-formula.md
    title: 報價金額怎麼算
    author: claude-code/claude-opus-5-5
    last_modified: 2026-10-16T17:10:00Z
---

# 意思

報價因子是報價單上的倍率，所有品項共用一個：單價 = 定價 × 報價因子。[^pricing-formula] 0.8 就是打八折，1.0 是原價，大於 1 是比定價貴。

系統存到小數 4 位。各客戶等級的預設值見 [客戶等級與預設報價因子](/system/customer-levels.md)，能降到多少見 [報價因子下限](/policies/pricing-factor-floor.md)。

# 例子

QT-20260330-001 的報價因子是 0.95，A4 影印紙定價 650，單價就是 617.5。

[^pricing-formula]: 報價金額怎麼算
