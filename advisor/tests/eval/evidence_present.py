"""程式判定指標 evidence_present：回覆要看得出依據，不能只有結論。

依 eval_case_id 的開頭判斷：
- policy_*：要附「依據（OKF 知識庫）」與信任等級
- price_* 與 apply_*：要有「試算驗證：通過」與報價單的純文字連結
- order_*：要有「轉訂單檢查」與報價單的純文字連結
- off_topic_*：要拒答（含「只能協助」），不需要依據
任何回覆出現 Markdown 連結 [文字](網址) 都給 0。
"""

import re

_LINK = re.compile(r"https?://\S+/quotations/\d+")
_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\([^)]+\)")
_TIERS = ("未驗證", "機器驗證", "人工審核")


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
        return {"score": 0, "explanation": "用了 Markdown 連結"}
    if case_id.startswith("off_topic"):
        ok = "只能協助" in text
        return {"score": int(ok), "explanation": "有拒答" if ok else "沒有拒答"}
    if case_id.startswith("policy"):
        ok = "依據（OKF 知識庫）" in text and any(t in text for t in _TIERS)
        return {"score": int(ok), "explanation": "附了知識庫依據與信任等級" if ok else "沒有附知識庫依據"}
    if case_id.startswith(("price", "apply")):
        ok = "試算驗證：通過" in text and bool(_LINK.search(text))
        return {"score": int(ok), "explanation": "有試算驗證與報價單連結" if ok else "缺試算驗證或報價單連結"}
    if case_id.startswith("order"):
        ok = "轉訂單檢查" in text and bool(_LINK.search(text))
        return {"score": int(ok), "explanation": "有轉訂單檢查與報價單連結" if ok else "缺轉訂單檢查或連結"}
    return {"score": 0, "explanation": f"不認得的案例 {case_id}"}
