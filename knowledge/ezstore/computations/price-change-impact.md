---
type: Attested Computation
title: 改價影響試算
description: 給報價單編號與目標總價，算出要用的報價因子、改價後的總價、利潤與毛利率，也標出目標是不是超出可調範圍。
tags: [computation, pricing, attested]
runtime: python
parameters:
  - { name: quotation_number, type: string, required: true }
  - { name: target_total, type: number, required: true }
source_parameter: quotation_number
data_source:
  resource: /system/backend-api.md
  request: GET /api/v1/quotations?quotation_number=<quotation_number>&page_size=1，再 GET /api/v1/quotations/<id>
computation: /references/computations/price_change_impact.py
computation_sha256: 599f7193e7e7af8e0de65de23d27df524b5eb4d501d4684d3fc54b83415ece82
attester_sha256: dddfbdb01d8fbea533a6114b72fae9fe7ffcb0ef065b053b5bcc771051c05224
executor:
  resource: /references/skills/run-python-computation.md
  receipt: [computation, computation_sha256, source_url, source_sha256, source, parameters, result, executed_at]
attester:
  resource: /references/attesters/recompute.py
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:30:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-18T05:31:55Z }
status: stable
stale_after: 2027-04-01T00:00:00Z
sources:
  - id: pricing-formula
    resource: /system/pricing-formula.md
    title: 報價金額怎麼算
    author: claude-code/claude-opus-5-5
    last_modified: 2026-10-16T17:10:00Z
  - id: mcp-tools
    resource: /system/mcp-tools.md
    title: EZStore MCP Server 的 6 個報價單工具
    author: claude-code/claude-opus-5-5
    last_modified: 2026-10-16T17:10:00Z
---

# Computation

計算程式在 `computation` 指的檔案，`computation_sha256` 是登記的版本。Agent 只能提供 `quotation_number` 和 `target_total` 兩個值，不能自己算，也不能改程式。

算法照 [報價金額怎麼算](/system/pricing-formula.md)：[^pricing-formula]

1. 定價合計 L = Σ 定價 × 數量，成本合計 C = Σ 成本 × 數量，都用品項重算，不用資料庫存的總價與利潤。
2. 需要的報價因子 = 目標總價 ÷ L，取到小數 4 位。
3. 每項單價 = 定價 × 報價因子，以 ROUND_HALF_UP 捨入到小數兩位；改價後總價 = Σ 捨入後單價 × 數量，利潤 = 總價 − C，毛利率 = 利潤 ÷ 總價（小數 4 位）。和後端存檔使用同一順序，不能改用 L × 因子作為實際總價。
4. 報價因子只能在 0.01 到 5.0 之間，和 `adjust_total_price` 的二分法範圍一樣。[^mcp-tools] 超出時 `reachable` 是 false，結果停在邊界。
5. 核准判斷使用相同捨入規則計算因子少一格的 conservative_total；改價完成後使用 current_factor 與 current_total 核對實際結果。
6. 資料庫存的總價或利潤和重算不同時，寫在 `stored_mismatch`。

# 收據與驗證

executor 照 [執行說明](/references/skills/run-python-computation.md) 回傳收據，attester（`/references/attesters/recompute.py`）檢查五件事：計算程式的 sha256、參數、來源資料的 sha256、重算結果、要顯示的數字。任何一項不符，Agent 就不顯示數字。

計算程式和 attester 的版本各自登記在 `computation_sha256`、`attester_sha256`。檔案被改過或沒有登記，Agent 都不執行；要由人看過程式後用 `okf sign … --repin` 重新登記。顯示數字之前，Agent 會從後端重讀一次報價單，和收據裡的資料來源比對。

`adjust_total_price` 實際改出來的總價會因為二分法停在第 20 次，和試算差一點。試算是事前判斷規則用的，實際結果以報價單 Agent 的回覆為準。

# 用到這個計算的條目

- [改價核准層級](/policies/discount-approval.md)
- [報價因子下限](/policies/pricing-factor-floor.md)
- [業務議價處理流程](/playbooks/price-negotiation.md)

[^pricing-formula]: 報價金額怎麼算
[^mcp-tools]: EZStore MCP Server 的 6 個報價單工具
