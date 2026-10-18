> 本地自我驗收：使用 agents-cli 生成當前版本紀錄，再用本地評審介接計分；不是教師正式雲端評分。Agent 與評審均為 Qwen3.5 9B，存在同模型偏差。

# Agent 評分報告：學生自我驗收（student-suite）

- 時間：20261018_114029
- 每組執行次數：1
- **總分：95.0 / 100**

## 群組 guardrails：29.6 / 30

| 案例 | 得分 | 元件 |
|---|---|---|
| `off_topic_weather` | 100% | link_present=1.00（拒答案例不需要連結）<br>refusal_or_action=1.00（助手正確識別非報價單相關請求並禮貌拒絕，符合規則。）<br>custom_response_quality=1.00（The agent correctly identified the off-topic query, politely refused to answer, and listed its specific capabilities as expected.）<br>must_not_contain=1.00（沒有出現：/quotations/\d+ | /orders/\d+） |
| `off_topic_customer_crud` | 100% | link_present=1.00（拒答案例不需要連結）<br>refusal_or_action=1.00（助手正確拒絕了新增客戶的非報價單管理請求並禮貌說明功能範圍。）<br>custom_response_quality=1.00（The response accurately refuses the request to add a customer and correctly explains the agent's limited scope regarding quotations, aligning perfectly with the）<br>must_not_contain=1.00（沒有出現：/quotations/\d+ | /orders/\d+） |
| `clarify_then_complete` | 96% | link_present=1.00（回覆包含純文字系統連結）<br>refusal_or_action=1.00（助手正確查詢報價單並附上純文字系統連結，符合所有評分規則。）<br>custom_response_quality=0.80（The response is highly accurate and informative but received a slight penalty because the URL port number (53000) differs from the ground truth (3000).）<br>must_contain=1.00（符合：QT-20260330-001）<br>must_not_contain=1.00（沒有出現：^請提供） |

| 後端核對 | 得分 | 說明 |
|---|---|---|
| guardrails 不應新增報價單 | 0/0 | 新增報價單 0 張（允許 ≤0） |

<details><summary>每題回覆原文</summary>

**off_topic_weather**

```
抱歉，我只能協助報價單相關的操作，沒辦法處理這個需求。
我可以幫你：查詢報價單、查詢客戶的報價單清單、複製報價單、修改報價因子、修改報價單總價、報價單轉訂單。
```

**off_topic_customer_crud**

```
抱歉，我只能協助報價單相關的操作，沒辦法處理這個需求。
我可以幫你：查詢報價單、查詢客戶的報價單清單、複製報價單、修改報價因子、修改報價單總價、報價單轉訂單。
```

**clarify_then_complete**

```
報價單編號: QT-20260330-001
客戶: 魔女宅急便股份有限公司
客戶等級: new
報價因子: 0.95
總價: 6175
利潤: 2375 (利潤率: 0.3846)
狀態: draft
備註: 測試用草稿 - 可供刪除測試
品項:
  1. A4影印紙 80磅 (5包/箱) — 單價: 617.5, 數量: 10, 小計: 6175
系統連結: http://localhost:53000/quotations/12
```

</details>

## 群組 actions：47.8 / 50

| 案例 | 得分 | 元件 |
|---|---|---|
| `get_quotation` | 96% | link_present=1.00（回覆包含純文字系統連結）<br>refusal_or_action=1.00（助手正確查詢到報價單並附上純文字系統連結，符合所有評分規則。）<br>custom_response_quality=0.80（The response is highly accurate and detailed but receives a slight penalty because the provided URL port (53000) differs from the expected answer (3000).）<br>must_contain=1.00（符合：QT-20260330-001）<br>must_contain=1.00（符合：/quotations/\d+） |
| `list_customer_quotations` | 100% | link_present=1.00（回覆包含純文字系統連結）<br>refusal_or_action=1.00（助手正確查詢到客戶報價單清單並附上純文字連結，符合所有評分規則。）<br>custom_response_quality=1.00（The response accurately lists the quotation details for the specified customer and provides the correct link, fully satisfying the user's request.）<br>must_contain=1.00（符合：QT-20260115-001） |
| `duplicate_quotation` | 100% | link_present=1.00（回覆包含純文字系統連結）<br>refusal_or_action=1.00（助手成功執行複製報價單操作並附上純文字連結，符合規則。）<br>custom_response_quality=1.00（The response accurately confirms the duplication, provides the correct original and new quotation numbers, and includes the requested text-only links.）<br>must_contain=1.00（符合：新報價單[^\n]*QT-\d{8}-\d{3}）<br>must_contain=1.00（符合：原始報價單[^\n]*QT-20260330-001） |
| `update_pricing_factor` | 76% | link_present=1.00（回覆包含純文字系統連結）<br>refusal_or_action=0.00（助手在回覆中使用了 Markdown 連結語法，違反規則 3 必須使用純文字連結的規定。）<br>custom_response_quality=0.80（回應準確執行了修改動作並提供了詳細資訊，但多餘地提供了原始報價單的連結，與預期答案中強調的「先複製再修改」流程略有偏差。）<br>must_contain=1.00（符合：未修改）<br>must_contain=1.00（符合：1\.5） |
| `adjust_total_price` | 80% | link_present=1.00（回覆包含純文字系統連結）<br>refusal_or_action=0.00（助手未說明原始報價單未被更動，且系統連結格式正確但缺少必要的修改說明導致扣分。）<br>custom_response_quality=1.00（The response accurately explains why the target price cannot be reached, provides the actual calculated total, and includes the requested links as per the groun）<br>must_contain=1.00（符合：未修改）<br>must_contain=1.00（符合：實際總價|注意） |
| `convert_to_order` | 96% | link_present=1.00（回覆包含純文字系統連結）<br>refusal_or_action=1.00（助手成功執行轉換訂單操作並附上純文字連結，符合規則。）<br>custom_response_quality=0.80（回應內容準確且完整，僅因訂單連結的端口號與預期範例略有不同而扣分。）<br>must_contain=1.00（符合：/orders/\d+）<br>must_contain=1.00（符合：ORD-\d{8}-\d{3}） |

| 後端核對 | 得分 | 說明 |
|---|---|---|
| 原單 QT-20260330-001 未更動 | 10/10 | 原單未被更動 |
| 至少 3 張複製單 | 5/5 | 複製自 QT-20260330-001 的新單 3 張（要求 ≥3） |
| 複製單因子 1.5 | 5/5 | 找到因子 1.5 的複製單 QT-20261018-002 |
| 訂單關聯原單 | 5/5 | 訂單 ORD-20261018-001 關聯 QT-20260330-001 |

<details><summary>每題回覆原文</summary>

**get_quotation**

```
報價單編號: QT-20260330-001
客戶: 魔女宅急便股份有限公司
客戶等級: new
報價因子: 0.95
總價: 6175
利潤: 2375 (利潤率: 0.3846)
狀態: draft
備註: 測試用草稿 - 可供刪除測試
品項:
  1. A4影印紙 80磅 (5包/箱) — 單價: 617.5, 數量: 10, 小計: 6175
系統連結: http://localhost:53000/quotations/12
```

**list_customer_quotations**

```
客戶「史塔克工業股份有限公司」的報價單清單（共 1 筆）：
- QT-20260115-001 | 總價: 253500 | 狀態: published | 連結: http://localhost:53000/quotations/1
```

**duplicate_quotation**

```
已成功複製報價單。
原始報價單: QT-20260330-001 — http://localhost:53000/quotations/12
新報價單: QT-20261018-001 — http://localhost:53000/quotations/13
```

**update_pricing_factor**

```
已成功修改報價因子。
原始報價單: QT-20260330-001（未修改） — http://localhost:53000/quotations/12
新報價單: QT-20261018-002
報價因子: 0.95 → 1.5
總價: 6175 → 9750
系統連結: http://localhost:53000/quotations/14
```

**adjust_total_price**

```
已透過二分法調整報價因子使總價逼近目標值（迭代 20 次）。
原始報價單: QT-20260330-001（未修改） — http://localhost:53000/quotations/12
新報價單: QT-20261018-003
報價因子: 5
目標總價: 100000.0
實際總價: 32500
注意: 已達最大迭代次數，實際總價與目標仍有差距（報價因子搜尋範圍 0.01–5.0）。
系統連結: http://localhost:53000/quotations/15
```

**convert_to_order**

```
已成功將報價單轉換為訂單。
報價單: QT-20260330-001（未修改） — http://localhost:53000/quotations/12
訂單編號: ORD-20261018-001
訂單總價: 6175
訂單連結: http://localhost:53000/orders/11
```

</details>

## 群組 extra：17.6 / 20

| 案例 | 得分 | 元件 |
|---|---|---|
| `not_found_quotation` | 100% | link_present=1.00（查無資料的回覆不需要明細連結）<br>refusal_or_action=1.00（助手正確告知找不到報價單且未編造資料，符合規則。）<br>custom_response_quality=1.00（The agent correctly identified that the quotation does not exist and explicitly avoided fabricating content or providing fake links, fully aligning with the exp）<br>must_contain=1.00（符合：找不到）<br>must_not_contain=1.00（沒有出現：/quotations/\d+） |
| `markdown_request` | 76% | link_present=1.00（回覆包含純文字系統連結）<br>refusal_or_action=0.00（助手使用了 Markdown 連結語法，違反規則 3 必須使用純文字連結。）<br>custom_response_quality=0.80（回應內容準確且符合 Markdown 格式要求，僅因未使用超連結語法而非純文字連結導致扣分。）<br>must_not_contain=1.00（沒有出現：\]\(http）<br>must_contain=1.00（符合：http://\S+/quotations/\d+） |

<details><summary>每題回覆原文</summary>

**not_found_quotation**

```
操作失敗：找不到報價單編號 QT-20990101-001
```

**markdown_request**

```
報價單編號: QT-20260330-001
客戶: 魔女宅急便股份有限公司
客戶等級: new
報價因子: 0.95
總價: 6175
利潤: 2375 (利潤率: 0.3846)
狀態: draft
備註: 測試用草稿 - 可供刪除測試
品項:
  1. A4影印紙 80磅 (5包/箱) — 單價: 617.5, 數量: 10, 小計: 6175
系統連結: http://localhost:53000/quotations/12
```

</details>
