"""要求 Markdown 時，連結維持純文字，但回覆要說明為什麼沒有照做。"""

from quotation_agent.agent import _MARKDOWN_NOTE, _with_markdown_note

REPLY = "報價單編號: QT-20260330-001\n系統連結: http://localhost:3000/quotations/12"


def test_markdown_request_gets_note_and_keeps_plain_link():
    out = _with_markdown_note("請用 Markdown 格式給我報價單 QT-20260330-001 的連結", REPLY)
    assert out.startswith(REPLY)
    assert out.endswith(_MARKDOWN_NOTE)
    assert "](" not in out


def test_md_abbreviation_counts():
    assert _MARKDOWN_NOTE in _with_markdown_note("用 md 給我 QT-20260330-001 的連結", REPLY)


def test_no_note_without_markdown_request():
    assert _with_markdown_note("我要查詢報價單，報價單編號：QT-20260330-001", REPLY) == REPLY


def test_no_note_when_user_declines_markdown():
    assert _with_markdown_note("不要用 Markdown，查 QT-20260330-001", REPLY) == REPLY


def test_no_note_on_replies_without_system_link():
    reply = "找不到報價單 QT-20990101-001。"
    assert _with_markdown_note("請用 Markdown 給我 QT-20990101-001 的連結", reply) == reply
