---
type: Playbook
title: 業務議價處理流程
description: 客戶要求降價或轉訂單時，議價顧問 Agent 和業務照這個順序處理。
tags: [playbook, negotiation, approval]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:30:00Z }
status: stable
stale_after: 2027-01-01T00:00:00Z
---

# 客戶要求降價

1. **確認是哪張報價單、想壓到多少**。缺報價單編號或目標總價就先問。
2. **試算**：跑 [改價影響試算](/computations/price-change-impact.md)，attester 驗證通過才看數字。
3. **對照規則**：[改價核准層級](/policies/discount-approval.md) 看毛利率，[報價因子下限](/policies/pricing-factor-floor.md) 看因子，取比較嚴的層級。已作廢或已過期的規則不用。
4. **業務可直接調整**：經 A2A 請 [報價單 Agent](/system/quotation-agent.md) 修改總價。它會先複製再改，原單不動，回覆附新報價單的連結。
5. **需要核准**：不改資料，整理一段核准申請（報價單、客戶、目前與改價後的報價因子和毛利率、依據的規則），給業務主管或總經理。
6. **不可報價**：直接告訴業務原因，建議改談數量或品項。

# 客戶要轉訂單

1. 依 [轉訂單規則](/policies/order-conversion.md) 檢查：報價單要已發佈，而且還沒有訂單。
2. 通過才經 A2A 請報價單 Agent 轉訂單，回覆附訂單連結。
3. 草稿要先在系統發佈；已經有訂單的，回覆既有的訂單編號。

# 一般查詢

查報價單、查客戶的報價單清單、複製報價單，直接經 A2A 交給報價單 Agent。
