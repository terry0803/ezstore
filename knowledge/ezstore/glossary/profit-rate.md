---
type: Glossary Term
title: 毛利率（profit_rate）
description: 利潤除以總價；利潤是總價減掉品項成本。改價核准就是看這個數字。
tags: [glossary, margin, profit]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:30:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-22T12:50:56Z }
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

毛利率 = 利潤 ÷ 總價，利潤 = 總價 − 成本合計。[^pricing-formula] 系統欄位叫 `profit_rate`，存小數 4 位，0.2027 就是 20.27%。

降價時成本不變，所以總價降多少，利潤就少多少，毛利率掉得比總價快。

# 例子

QT-20260325-001 依品項重算：總價 211560，成本合計 143500，利潤 68060，毛利率 32.17%。資料庫存的利潤是 66060，和重算不同，見 [報價單資料表](/system/quotations-table.md)。

壓到 180000 時，利潤剩 36480.8，毛利率 20.27%，依 [改價核准層級](/policies/discount-approval.md) 要業務主管核准。

[^pricing-formula]: 報價金額怎麼算
