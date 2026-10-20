"""回覆在 ADK 網頁介面（Markdown）要和原本的分行一樣，條列後的文字不能被併進條列。"""

from pricing_advisor.agent import _markdown_lines

REPLY = "QT-20260325-001 改成 180000 的試算：\n- 報價因子 0.8200 → 0.6976\n- 毛利率 32.17% → 20.27%\n判斷：需業務主管核准\n系統連結：http://localhost:3000/quotations/9"


def test_every_line_break_is_kept():
    out = _markdown_lines(REPLY)
    assert out.replace("  \n", "\n").replace("\n\n", "\n") == REPLY


def test_text_after_list_starts_a_new_paragraph():
    out = _markdown_lines(REPLY)
    assert "- 毛利率 32.17% → 20.27%  \n  \n判斷：需業務主管核准" in out


def test_single_line_unchanged():
    assert _markdown_lines("抱歉，我只能協助報價與議價相關的問題。") == "抱歉，我只能協助報價與議價相關的問題。"
