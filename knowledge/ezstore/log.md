# Directory Update Log

## 2026-10-17
* **Verification**: `process:okf-verify` 對照原始碼與執行中的系統，10 個條目通過：`system/customer-levels`、`system/pricing-formula`、`system/quotations-table`、`system/orders-table`、`system/backend-api`、`system/mcp-tools`、`system/quotation-agent`、`computations/price-change-impact`、`glossary/pricing-factor`、`glossary/profit-rate`。
* **Verification**: `process:okf-verify` 對照原始碼與執行中的系統，1 個條目通過：`system/quotation-agent`。
* **Verification**: `process:okf-verify` 對照原始碼與執行中的系統，10 個條目通過：`system/customer-levels`、`system/pricing-formula`、`system/quotations-table`、`system/orders-table`、`system/backend-api`、`system/mcp-tools`、`system/quotation-agent`、`computations/price-change-impact`、`glossary/pricing-factor`、`glossary/profit-rate`。
* **Creation**: 建立知識庫，條目由 `claude-code/claude-opus-5-5` 依 EZStore `workshop-start` 的原始碼與測試資料撰寫。
* **Creation**: 新增 [改價核准層級](/policies/discount-approval.md)、[報價因子下限](/policies/pricing-factor-floor.md)、[轉訂單規則](/policies/order-conversion.md)。這三份是作業示範用的虛構公司規則，尚未經人工審核。
* **Deprecation**: [2025 年版改價核准層級](/policies/discount-approval-2025.md) 標成 `deprecated`，由 2026 年版取代。
* **Creation**: 新增 [改價影響試算](/computations/price-change-impact.md)，計算程式放在 `references/computations/price_change_impact.py`。
