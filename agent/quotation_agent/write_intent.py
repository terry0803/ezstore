"""Conservative programmatic write authorization, independent of LLM labels.

Kept identical in both independently built Agent packages. Unrecognized wording
must clarify or remain read-only; a model's positive classification is not consent.

A sentence authorizes a write only when it names an action and none of these hold:
- it asks how something works, what would happen, or describes a result;
- it reports an action that already happened (「複製完了」「昨天我把…改成…」) or what a customer
  wants (「客戶說想壓到…」) without a new request;
- it is a question that is not a polite request (「可以幫我…嗎」 is a request, 「…改了嗎」 is not).
"""
import re
import unicodedata

# 問做法、問會怎樣、要描述：不管怎麼寫都不是要求執行
_EXPLAIN = re.compile(
    r"如何|怎麼|為什麼|說明|解釋|描述|介紹|支援|支持|哪些|(?:是|做|會)什麼|什麼(?:是|意思)"
    r"|會產生|會發生|會怎樣|流程|步驟|假設|如果|是否可行|可不可行|行不行|行得通|可行嗎"
    r"|查一下|查詢|查看|看看|看一下|預覽|估算|試算|算一下|算算|算出|評估|檢查"
    r"|模擬|模拟|計算|计算|比較|比较|分析|推算|推演|假想"
    r"|(?:的|後的|后的)(?:結果|结果|差異|差异|影響|影响)"
    r"|\b(?:preview|estimate|simulate|simulation|calculate|compare|analyze|analyse|what-if)\b"
    r"|\b(?:how|why|what|whether|explain|describe|support)\b",
    re.IGNORECASE,
)
# A hold applies to the whole pending operation, including later clauses.
# Match execution/authorization language rather than requiring a nearby price verb.
_EXECUTION_HOLD = re.compile(
    r"(?:不要|請勿|不用|不必|先不|暫時不|暂时不)(?:真的|實際|实际|立即|馬上|马上)?\s*"
    r"(?:執行|执行|操作|寫入|写入|送出|提交|套用)"
    r"|(?:暫停|暂停|暫緩|暂缓)(?:執行|执行|操作|寫入|写入)?"
    r"|(?:等我|等待我|待我)(?:確認|确认|同意|核准|授權|授权)"
    r"|(?:尚未|還沒|还没|沒有|没有)(?:確認|确认|同意|授權|授权)"
    r"|(?:沒有要|没有要|還沒要|还没要)(?:真的|實際|实际)?(?:改|轉|转|複製|复制|執行|执行)"
    r"|\b(?:do\s+not|don't|not\s+yet|hold\s+off|wait\s+for\s+my\s+(?:approval|confirmation))\b",
    re.IGNORECASE,
)


def has_execution_hold(text: str) -> bool:
    """A global hold must win over classifier labels and pending confirmations."""
    return bool(_EXECUTION_HOLD.search(unicodedata.normalize("NFKC", text)))


# 已經做完的事：動詞後面接「了」「完」
_DONE = re.compile(r"(?:複製|修改|改價|轉(?:成|為)?訂單)(?:了|完(?:了|成)?)")
# 講過去發生的事；後面沒有新的要求就不寫入
_PAST = re.compile(
    r"(?:昨天|前天|之前|先前|上次|剛才|剛剛|曾經|已經)[^，。；;,\n]*(?:複製|修改|改|轉|調|設)"
    r"|\b(?:yesterday|previously)\b",
    re.IGNORECASE,
)
# 轉述客戶、對方想要的價格：是議價的資訊，不是指示
_WISH = re.compile(r"(?:客戶|對方|廠商|買方)[^，。；;,\n]*(?:說|表示|希望|想|要求)")
# 明確在請人做事的字
_REQUEST = re.compile(
    r"請|麻煩|幫我|幫忙|替我|要我|我要|我想|我需要|需要你|想要"
    r"|\b(?:please|can\s+you|could\s+you|would\s+you)\b",
    re.IGNORECASE,
)
# 用問句客氣地請人做事：「可以幫我…嗎」「能不能把…」
_POLITE_QUESTION = re.compile(
    r"可以|可不可以|能不能|能否|可否|是否能|能(?:幫|把|將|替)|麻煩|幫我|幫忙"
    r"|\b(?:can|could|would)\s+you\b|\bplease\b",
    re.IGNORECASE,
)
_QUESTION = re.compile(r"[?？]|[嗎呢]\s*[。.!！]?\s*$")
_STATUS_QUERY = re.compile(
    r"是否(?:已|有|成功|完成)|有沒有|有没有|有否|(?:確認|确认|查證|查证).*(?:已|完成|成功)"
    r"|(?:複製|复制|改價|修改|轉成|轉為|转成|转为|轉單|转单).*(?:了嗎|了吗|成功了?|完成了?)[?？嗎吗]?"
    r"|\b(?:has|have|was|were|did|is)\b.*\b(?:copied|duplicated|converted|changed|completed|succeeded)\b"
    r"|\b(?:confirm|check|verify)\b.*\b(?:already|completed|successful)\b",
    re.IGNORECASE,
)


def is_status_query(text: str) -> bool:
    """Checking whether an operation happened never authorizes another write."""
    return bool(_STATUS_QUERY.search(unicodedata.normalize("NFKC", text)))


_ACTION = re.compile(
    r"複製|改|調|變更|變成|設定|設為|設成|轉|壓|降"
    r"|\b(?:copy|duplicate|clone|convert|turn|set|change|adjust|update)\b|\bfrom\b.+\bto\b",
    re.IGNORECASE,
)
_GREETING = re.compile(r"^(?:你好|您好|嗨|哈囉|hi|hello)[，,!！。\s]*", re.IGNORECASE)
_CONFIRM = re.compile(
    r"^(?:(?:好(?:的)?|那就|那|對)[，,\s]*)*"
    r"(?:(?:請|麻煩)\s*)?(?:(?:幫我|幫忙|直接)\s*)?"
    r"(?:照(?:剛才|剛剛|上一輪)(?:的)?(?:方案|試算|價格|結果)\s*)?"
    r"(?:改|修改|改價|調整)(?:吧)?[。.!！\s]*$"
    r"|^(?:yes[,.]?\s*)?(?:please\s+)?(?:apply|do)(?:\s+it|\s+that)?[.!\s]*$",
    re.IGNORECASE,
)


def is_write_request(text: str) -> bool:
    text = _GREETING.sub("", unicodedata.normalize("NFKC", text).strip())
    if has_execution_hold(text) or is_status_query(text):
        return False
    if is_price_confirmation(text):
        return True
    if not _ACTION.search(text) or _EXPLAIN.search(text) or _DONE.search(text):
        return False
    if (_PAST.search(text) or _WISH.search(text)) and not _REQUEST.search(text):
        return False
    if _QUESTION.search(text) and not _POLITE_QUESTION.search(text):
        return False
    return True


# 客氣的請求句型：客氣的字後面直接接「幫我」「把」「將」（「可以幫我改…嗎」「能不能把…轉成訂單」）。
# 「改成 200000 可以嗎？」沒有這個結構，比較像在問可不可行。
_POLITE_REQUEST = re.compile(
    r"(?:可以|可不可以|能不能|能否|可否|是否能|能|麻煩|請)\s*(?:你|您)?\s*(?:幫我|幫忙|替我|把|將|直接)"
    r"|\b(?:can|could|would)\s+you\b|\bplease\b",
    re.IGNORECASE,
)


def is_polite_request(text: str) -> bool:
    """問句形式但其實是請人做事；議價顧問用它區分「請你改」和「問改了行不行」。"""
    text = _GREETING.sub("", unicodedata.normalize("NFKC", text).strip())
    return bool(_POLITE_REQUEST.search(text)) and is_write_request(text)


def is_price_confirmation(text: str) -> bool:
    """Only an entire confirmation utterance can reuse the last checked price."""
    return bool(_CONFIRM.fullmatch(unicodedata.normalize("NFKC", text).strip()))
