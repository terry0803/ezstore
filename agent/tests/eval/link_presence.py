"""程式判定指標 link_present：回覆要附純文字系統連結，不可用 Markdown 連結。

檔名用 link_presence.py，和 eval-lab 第 5 節、scripts/grading 的檔名一致。

- 回覆出現 Markdown 連結 [文字](網址) → 0
- eval_case_id 以 off_topic 開頭的離題案例不需要連結 → 1
- 回覆說「找不到」（查無資料）不需要明細連結 → 1（eval-lab 第 5 節的修正）
- 其他案例必須含 http(s)://…/quotations/<id> 或 /orders/<id> → 1，否則 0
"""

import re

_LINK = re.compile(r"https?://\S+/(quotations|orders)/\d+")
_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\([^)]+\)")


def _response_text(instance) -> str:
    response = instance.get("response") or {}
    if isinstance(response, str):
        return response
    parts = response.get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


def evaluate(instance):
    text = _response_text(instance)
    case_id = str(instance.get("eval_case_id", ""))
    if _MARKDOWN_LINK.search(text):
        return {"score": 0, "explanation": "使用了 Markdown 連結，spec 要求純文字連結"}
    if case_id.startswith("off_topic"):
        return {"score": 1, "explanation": "離題案例不需要連結"}
    if "找不到" in text:
        return {"score": 1, "explanation": "查無資料的回覆不需要明細連結"}
    if _LINK.search(text):
        return {"score": 1, "explanation": "回覆含純文字 /quotations/<id> 或 /orders/<id> 連結"}
    return {"score": 0, "explanation": "回覆缺少純文字 /quotations/<id> 或 /orders/<id> 連結"}
