---
type: A2A Agent
title: 報價單 Agent（quotation_agent）
description: 第一個 Agent 的 A2A 介面：agent card 位置、6 個 skill、該怎麼下指令、回覆長什麼樣子。
resource: http://agent:8080/a2a/quotation_agent
tags: [a2a, agent, quotation]
a2a_skills: [get_quotation, list_customer_quotations, duplicate_quotation, update_pricing_factor, adjust_total_price, convert_to_order]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T17:10:00Z }
verified:
  - { by: process:okf-verify, at: 2026-10-17T08:00:26Z }
status: stable
stale_after: 2027-04-01T00:00:00Z
sources:
  - id: quotation-agent-code
    resource: https://github.com/terry0803/ezstore/tree/167c36e96b6022db0cbafecf0715e169a0477177/agent/quotation_agent
    title: 報價單 Agent 原始碼（agent.py、fast_api_app.py、app_utils/a2a.py）
    author: claude-code/claude-opus-5-5
    last_modified: 2026-10-16T18:04:52Z
---

# 位置

| 從哪裡連 | agent card | JSON-RPC 端點 |
|---|---|---|
| Compose 內部 | `http://agent:8080/a2a/quotation_agent/.well-known/agent-card.json` | `http://agent:8080/a2a/quotation_agent` |
| 本機（經前端 nginx） | `http://localhost:3000/agent-api/a2a/quotation_agent/.well-known/agent-card.json` | `http://localhost:3000/agent-api/a2a/quotation_agent` |

agent card 裡的位址是 Compose 內部的 `http://agent:8080/...`。經 nginx 連的時候，JSON-RPC 要送到取得 card 的同一個位址。[^quotation-agent-code]

# Skill 與例句

| skill id | 例句 |
|---|---|
| `get_quotation` | 我要查詢報價單，報價單編號：QT-20260330-001 |
| `list_customer_quotations` | 我要查詢客戶的報價單清單，客戶名稱：史塔克工業 |
| `duplicate_quotation` | 我要複製報價單，報價單編號：QT-20260330-001 |
| `update_pricing_factor` | 我要修改報價單報價因子，報價單編號：QT-20260330-001，報價因子改為 1.5 |
| `adjust_total_price` | 我要修改報價單總價，報價單編號：QT-20260330-001，總價改為 8000 |
| `convert_to_order` | 我要將報價單轉訂單，報價單編號：QT-20260330-001 |

照例句的句型、一次給齊欄位，報價單 Agent 就不會追問。[^quotation-agent-code]

# 回覆

- A2A task 完成時只有一個 artifact，內容就是 Chat UI 會看到的那段文字（respond 節點）。
- 會改資料的操作都是先複製再改，原單不動，見 [MCP 工具](/system/mcp-tools.md)。
- 跟報價單無關的要求一律拒答，回覆含「只能協助報價單相關的操作」。
- 缺欄位時回「請提供…」。

[^quotation-agent-code]: 報價單 Agent 原始碼（agent.py、fast_api_app.py、app_utils/a2a.py）
