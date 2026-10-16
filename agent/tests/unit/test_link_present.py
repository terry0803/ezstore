"""eval 指標 link_present 的程式判定。"""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "link_present", Path(__file__).parents[1] / "eval" / "link_present.py"
)
link_present = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(link_present)


def score(text, case_id="case"):
    instance = {"response": {"parts": [{"text": text}]}, "eval_case_id": case_id}
    return link_present.evaluate(instance)["score"]


def test_plain_link_passes():
    assert score("系統連結: http://localhost:3000/quotations/12") == 1
    assert score("訂單連結: http://localhost:3000/orders/11") == 1


def test_markdown_link_fails():
    assert score("[報價單](http://localhost:3000/quotations/12)") == 0


def test_missing_link_fails_except_off_topic():
    assert score("好的") == 0
    assert score("抱歉，我只能協助報價單相關的操作", case_id="off_topic_weather") == 1
