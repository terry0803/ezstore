import pytest

from quotation_agent.agent import _model_max_attempts


@pytest.mark.parametrize(("value", "expected"), [("0", 1), ("1", 1), ("3", 3)])
def test_model_retry_limit(monkeypatch, value, expected):
    monkeypatch.setenv("MODEL_MAX_ATTEMPTS", value)
    assert _model_max_attempts() == expected


def test_model_retry_default(monkeypatch):
    monkeypatch.delenv("MODEL_MAX_ATTEMPTS", raising=False)
    assert _model_max_attempts() == 6
