from types import SimpleNamespace

import pytest
from pricing_advisor import agent
from pricing_advisor.write_intent import is_write_request

@pytest.mark.parametrize('text', [
    '請確認是否已複製報價單 QT-20260330-001',
    '請確認報價單 QT-20260330-001 是否已轉成訂單',
    '可以幫我確認 QT-20260330-001 有沒有複製成功嗎？',
    '請確認 QT-20260330-001 是否已修改總價到 3000',
    'Has quotation QT-20260330-001 already been copied?',
])
@pytest.mark.parametrize('label', ['quotation_request','off_topic','provide_info','convert_order','apply_price'])
def test_status_is_read_only_regardless_of_classifier_and_pending(text, label):
    assert not is_write_request(text)
    event = agent.route(SimpleNamespace(state={
        'last_user_text': text, 'pending': {'intent': 'apply_price', 'quotation_number': 'QT-20260330-001', 'target_total': 3000},
        'last_check': {'quotation_number': 'QT-20260330-001', 'target_total': 3000},
    }), {'intent': label})
    assert event.actions.route == 'off_topic'
    assert event.actions.state_delta['pending'] is None
    assert event.actions.state_delta['last_check'] is None
    assert '尚未核實' in event.output
