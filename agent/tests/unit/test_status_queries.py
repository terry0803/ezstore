from types import SimpleNamespace

import pytest
from quotation_agent import agent
from quotation_agent.write_intent import is_write_request

@pytest.mark.parametrize('text', [
    '請確認是否已複製報價單 QT-20260330-001',
    '請確認報價單 QT-20260330-001 是否已轉成訂單',
    '可以幫我確認 QT-20260330-001 有沒有複製成功嗎？',
    '請確認 QT-20260330-001 是否已修改總價到 3000',
    'Has quotation QT-20260330-001 already been copied?',
])
@pytest.mark.parametrize('label', ['off_topic','provide_info','duplicate_quotation','convert_to_order','adjust_total_price'])
def test_status_never_authorizes_write_or_reuses_pending(text, label):
    assert not is_write_request(text)
    assert agent._keyword_operation(text) is None
    event = agent.route(SimpleNamespace(state={
        'last_user_text': text, 'pending_intent': {'intent': 'convert_to_order', 'quotation_number': 'QT-20260330-001'},
        'clarify_source_text': '我要轉成訂單',
    }), {'intent': label, 'quotation_number': 'QT-20260330-001', 'target_total_price': 3000})
    assert event.actions.route == 'off_topic'
    assert event.actions.state_delta['pending_intent'] is None
    assert '尚未核實' in event.output

@pytest.mark.parametrize('text', ['請複製報價單 QT-20260330-001', '可以幫我把 QT-20260330-001 轉成訂單嗎？'])
def test_explicit_requests_still_authorize(text):
    assert is_write_request(text)
