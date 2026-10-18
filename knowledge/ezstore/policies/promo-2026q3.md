---
type: Policy
title: 2026 第三季新客戶優惠
description: 2026 年第三季把 new 等級客戶的報價因子下限暫時降到 0.85，10 月 1 日起失效。
tags: [policy, promotion, pricing-factor]
demo_policy: true
rule_kind: factor_floor_override
applies_to_level: new
factor_floor: 0.85
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:20:00Z }
status: stable
stale_after: 2026-09-30T16:00:00Z
sources:
  - id: factor-floor
    resource: /policies/pricing-factor-floor.md
    title: 報價因子下限
    author: claude-code/claude-opus-5-5
    last_modified: 2026-10-16T17:20:00Z
---

# 優惠內容

> 這是第一次作業的示範規則，用來示範 OKF 的 `stale_after`：過了這個時間，條目就過期，不能再拿來判斷。

2026 年 7 月 1 日到 9 月 30 日（台灣時間），new 等級客戶的報價因子下限從 0.90 暫時降到 0.85。[^factor-floor]

`stale_after` 是 2026-09-30T16:00:00Z，也就是台灣時間 10 月 1 日 0 點。之後改回 [報價因子下限](/policies/pricing-factor-floor.md) 的 0.90。

[^factor-floor]: 報價因子下限
