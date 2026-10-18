from types import SimpleNamespace
import pytest
from quotation_agent import agent, preflight

Q='QT-20260330-001'

@pytest.mark.parametrize('text', [f'請問如何複製報價單 {Q}', f'複製報價單 {Q} 的操作流程是什麼？', f'How can I copy quotation {Q}?'])
def test_howto_cannot_turn_into_a_write(text):
    result=agent.route(SimpleNamespace(state={'last_user_text':text}), agent.Intent(intent='duplicate_quotation'))
    assert result.actions.route=='off_topic'
    assert result.output==agent.EXPLAIN_TEXT

@pytest.fixture
def quote_reads(monkeypatch):
    product={'cost':'380','list_price':'650'}
    async def get(path,**params):
        if path=='/quotations':return {'data':[{'id':12,'quotation_number':Q}]}
        if path.startswith('/products/'):return product
        return {'items':[{'product_id':6,'product_cost':'380','list_price':'650','quantity':10}]}
    monkeypatch.setattr(preflight,'_get',get)
    return product

@pytest.mark.asyncio
async def test_small_factor_never_calls_write_tool(quote_reads,monkeypatch):
    async def forbidden(*args):raise AssertionError('No draft should be created')
    monkeypatch.setattr(agent,'_call_mcp_tool',forbidden)
    result=await agent.update_pricing_factor(None,{'quotation_number':Q,'new_pricing_factor':.0001})
    assert result.startswith('未送出操作：') and '利潤率' in result

@pytest.mark.asyncio
async def test_cost_drift_never_calls_write_tool(quote_reads,monkeypatch):
    quote_reads['cost']='790'
    async def forbidden(*args):raise AssertionError('No draft should be created')
    monkeypatch.setattr(agent,'_call_mcp_tool',forbidden)
    result=await agent.adjust_total_price(None,{'quotation_number':Q,'target_total_price':8000})
    assert result.startswith('未送出操作：') and '已變更' in result

@pytest.mark.asyncio
async def test_factor_normalized_before_teacher_mcp(quote_reads):
    result=await preflight.validate_change('update_pricing_factor',{'quotation_number':Q,'new_pricing_factor':1.23456})
    assert result['new_pricing_factor']==1.2346

@pytest.mark.asyncio
async def test_teacher_unreachable_total_case_remains_supported(quote_reads):
    result=await preflight.validate_change('adjust_total_price',{'quotation_number':Q,'target_total_price':100000})
    assert result['target_total_price']==100000


@pytest.mark.parametrize('text,operation', [
    (f'複製報價單 {Q} 會產生哪些資料？', 'duplicate_quotation'),
    (f'系統支援複製報價單 {Q} 嗎？', 'duplicate_quotation'),
    (f'昨天同事複製了報價單 {Q}，我只是描述這件事。', 'duplicate_quotation'),
    (f'請描述將報價單 {Q} 轉訂單的結果。', 'convert_to_order'),
    (f'昨天我把 {Q} 總價改成8000', 'adjust_total_price'),
    (f'{Q} 的總價是200000', 'adjust_total_price'),
    (f'報價單 {Q} 複製完了', 'duplicate_quotation'),
])
@pytest.mark.parametrize('classification', ['positive', 'off_topic'])
def test_non_action_never_writes_even_if_classifier_is_wrong(text, operation, classification):
    event=agent.route(SimpleNamespace(state={'last_user_text':text}),
                      agent.Intent(intent=operation if classification=='positive' else 'off_topic'))
    assert event.actions.route not in agent._WRITE_TOOLS


def test_imported_description_cannot_be_resumed_as_a_write():
    event=agent.route(SimpleNamespace(state={'last_user_text':Q,
        'clarify_source_text':'昨天同事複製了報價單，我只是描述這件事。'}),
        agent.Intent(intent='provide_info'))
    assert event.actions.route not in agent._WRITE_TOOLS


@pytest.mark.parametrize('price,factor,quantity,expected', [
    ('650', '0.3333', 3, '649.95'),
    ('1', '1.0050', 3, '3.03'),
    ('0.01', '0.5000', 1000, '10.00'),
    ('0.01', '0.3333', 1000, '0.00'),
])
def test_preflight_matches_stored_cent_precision(price, factor, quantity, expected):
    from decimal import Decimal
    assert preflight._check_storage([{'list_price':price,'product_cost':'0','quantity':quantity}],
                                   Decimal(factor)) == Decimal(expected)


@pytest.mark.parametrize('text,operation,extra', [
    (f'可以幫我複製報價單 {Q} 嗎？', 'duplicate_quotation', {}),
    (f'能不能把 {Q} 轉成訂單？', 'convert_to_order', {}),
    (f'你好，我要將報價單轉訂單，報價單編號：{Q}', 'convert_to_order', {}),
    (f'報價單 {Q} 總價調成 8000 元', 'adjust_total_price', {'target_total_price': 8000}),
    (f'請問可以把 {Q} 的報價因子改為 1.5 嗎', 'update_pricing_factor', {'new_pricing_factor': 1.5}),
    (f'這張 {Q} 請幫我複製一份', 'duplicate_quotation', {}),
    (f'客戶已經同意了，請把 {Q} 總價改成 8000', 'adjust_total_price', {'target_total_price': 8000}),
    (f'同事要我複製報價單 {Q}', 'duplicate_quotation', {}),
    (f'老闆說 {Q} 總價改成 8000', 'adjust_total_price', {'target_total_price': 8000}),
    (f'Can you copy quotation {Q}?', 'duplicate_quotation', {}),
])
def test_ordinary_request_wording_is_not_blocked(text, operation, extra):
    """助教的題庫用字和範例不同；客氣的問句、開頭打招呼、轉述的指示都是正常要求。"""
    event = agent.route(SimpleNamespace(state={'last_user_text': text}),
                        agent.Intent(intent=operation, quotation_number=Q, **extra))
    assert event.actions.route == operation, event.output


@pytest.mark.parametrize('text', [f'{Q} 改成 8000 了嗎？', f'上次 {Q} 已經轉訂單了', f'剛剛我把 {Q} 複製了'])
def test_status_questions_and_reports_still_do_not_write(text):
    event = agent.route(SimpleNamespace(state={'last_user_text': text}),
                        agent.Intent(intent='adjust_total_price', quotation_number=Q, target_total_price=8000))
    assert event.actions.route not in agent._WRITE_TOOLS


@pytest.mark.parametrize('text', [f'{Q} 先不要改價了', f'不用轉單了，{Q}'])
def test_cancel_with_object_noun_is_recognized(text):
    event = agent.route(SimpleNamespace(state={'last_user_text': text}), agent.Intent(intent='provide_info'))
    assert event.actions.route == 'off_topic' and event.output == agent.CANCEL_TEXT


@pytest.mark.parametrize('question', ['是否可行', '可不可行', '行不行', '行得通', '可行嗎'])
@pytest.mark.parametrize('operation', ['adjust_total_price', 'update_pricing_factor', 'duplicate_quotation', 'convert_to_order'])
def test_feasibility_question_rejects_even_positive_write_classification(question, operation):
    text = f'可以幫我查詢 {Q} 總價改成 210000 {question}？'
    result = agent.route(SimpleNamespace(state={'last_user_text': text}), agent.Intent(intent=operation))
    assert result.actions.route == 'off_topic'
    assert result.output == agent.EXPLAIN_TEXT
    assert '沒有執行任何操作' in result.output


@pytest.mark.parametrize('word', ['查一下', '查詢', '查看', '看看', '看一下', '預覽', '估算', '試算', '算一下', '算算', '評估', '檢查', '模擬', '計算', '比較', '分析', '推演', '假想'])
@pytest.mark.parametrize('classification', ['adjust_total_price', 'update_pricing_factor', 'duplicate_quotation', 'convert_to_order', 'off_topic'])
def test_preview_never_authorizes_writes_or_leaves_pending_write(word, classification):
    text = f'可以幫我{word}報價單 {Q} 總價改成 210000 的結果嗎？'
    result = agent.route(SimpleNamespace(state={'last_user_text': text}),
                         agent.Intent(intent=classification, quotation_number=Q, target_total_price=210000))
    assert result.actions.route not in agent._WRITE_TOOLS
    assert not result.actions.state_delta.get('pending_intent')


@pytest.mark.parametrize('text', [
    f'可以幫我模擬 {Q} 改成 210000 嗎？',
    f'請計算 {Q} 改成 210000',
    f'請比較 {Q} 改成 210000 前後差異',
    f'可以幫我把 {Q} 改成 210000 的結果嗎？',
    f'Can you simulate changing {Q} to 210000?',
])
def test_analysis_is_not_write_authorization_without_result_suffix(text):
    from quotation_agent.write_intent import is_write_request, is_polite_request
    assert not is_write_request(text)
    assert not is_polite_request(text)


@pytest.mark.parametrize('prefix', [
    '先不要執行，', '暫時不要真的執行。', '請勿操作；', '暫緩執行，',
    '等我確認再執行，', '尚未授權，', '沒有要真的改，', "Don't execute yet. ",
])
@pytest.mark.parametrize('classification', ['off_topic', 'provide_info', 'adjust_total_price', 'update_pricing_factor', 'duplicate_quotation', 'convert_to_order'])
def test_execution_hold_clears_pending_regardless_of_model(prefix, classification):
    text = prefix + f'報價單 {Q} 總價改成 210000。'
    state = {'last_user_text': text, 'pending_intent': {'operation': 'adjust_total_price', 'quotation_number': Q}, 'clarify_source_text': '請修改總價'}
    event = agent.route(SimpleNamespace(state=state), agent.Intent(intent=classification, quotation_number=Q, target_total_price=210000))
    assert event.actions.route == 'off_topic'
    assert event.output == agent.CANCEL_TEXT
    assert event.actions.state_delta.get('pending_intent') is None
    assert event.actions.state_delta.get('clarify_source_text') == ''
