---
type: Policy
title: 報價單轉訂單規則
description: 只有已發佈的報價單可以轉訂單，同一張報價單不重複轉。
tags: [policy, order, conversion]
demo_policy: true
rule_kind: order_conversion
require_status: published
block_if_existing_order: true
ignore_order_status: [cancelled]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:20:00Z }
status: stable
stale_after: 2027-01-01T00:00:00Z
sources:
  - id: orders-table
    resource: /system/orders-table.md
    title: 訂單資料表（orders、order_items）
    author: claude-code/claude-opus-5-5
    last_modified: 2026-10-16T17:10:00Z
---

# 規則

> 這是第一次作業的示範規則，不是 EZStore 系統或老師提供的資料。系統本身不會擋，報價單 Agent 也會直接轉。

1. 報價單要是已發佈（`published`）才可以轉訂單。草稿代表還沒送給客戶，要先在系統發佈。
2. 已經有訂單的報價單不再轉一次。已取消（`cancelled`）的訂單不算。[^orders-table]
3. 兩條都符合，才經 A2A 請 [報價單 Agent](/system/quotation-agent.md) 轉訂單。

# 為什麼要另外檢查

`convert_to_order` 不看報價單狀態，也不擋重複轉換，同一張轉兩次就會有兩筆訂單。[^orders-table]

# 例子

- QT-20260115-001 已有訂單 ORD-20260118-001，不再轉。
- QT-20260325-001 是草稿，要先發佈。
- QT-20260301-001 已發佈、還沒有訂單，可以轉。

[^orders-table]: 訂單資料表（orders、order_items）
