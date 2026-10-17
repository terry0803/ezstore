# A2A Agent

* [報價單 Agent（quotation_agent）](quotation-agent.md) - 第一個 Agent 的 A2A 介面：agent card 位置、6 個 skill、該怎麼下指令、回覆長什麼樣子。

# API Endpoint

* [EZStore 後端 REST API（報價與訂單）](backend-api.md) - 報價單、訂單、客戶與預設報價因子的 REST 端點，以及查詢參數。

# Business Rule

* [客戶等級與預設報價因子](customer-levels.md) - vip、standard、new 三種客戶等級各自的預設報價因子，以及查詢用的 API。
* [報價金額怎麼算](pricing-formula.md) - 單價、小計、總價、利潤與利潤率的計算方式、後端什麼時候會重算，以及已發佈的報價單不能修改或刪除。

# MCP Server

* [EZStore MCP Server 的 6 個報價單工具](mcp-tools.md) - 報價單 Agent 背後的 6 個 MCP 工具、先複製再改的做法，以及改總價的二分法設定。

# PostgreSQL Table

* [訂單資料表（orders、order_items）](orders-table.md) - 訂單欄位、和報價單的關聯，以及測試資料裡已經轉成訂單的報價單。
* [報價單資料表（quotations、quotation_items）](quotations-table.md) - 報價單與報價品項的欄位、狀態，以及測試資料金額修正的紀錄。
