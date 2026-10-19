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


@pytest.mark.parametrize('text', [
    f'可以幫我確認複製報價單 {Q} 是否保留備註嗎？',
    f'請問複製 {Q} 會保留備註嗎？',
    f'幫我確認複製 {Q} 後品項還在不在',
    f'Can you check whether copying {Q} keeps the notes?',
])
@pytest.mark.parametrize('classification', ['duplicate_quotation', 'off_topic'])
def test_confirmation_inquiry_never_copies(text, classification):
    """外部檢查：「可以幫我確認複製…是否保留備註嗎？」問的是複製的內容，不能因為「可以幫我」就複製。
    模型判成離題時，關鍵字補救也不能把它變成複製。"""
    event = agent.route(SimpleNamespace(state={'last_user_text': text}),
                        agent.Intent(intent=classification, quotation_number=Q))
    assert event.actions.route not in agent._WRITE_TOOLS


@pytest.mark.parametrize('text', [f'可以幫我複製報價單 {Q} 嗎？', f'是否能幫我複製報價單 {Q}？', f'請確認後幫我複製 {Q}'])
def test_polite_copy_request_still_copies(text):
    event = agent.route(SimpleNamespace(state={'last_user_text': text}),
                        agent.Intent(intent='duplicate_quotation', quotation_number=Q))
    assert event.actions.route == 'duplicate_quotation'


@pytest.mark.parametrize('text', [
    '請把報價單 QT-20260325-001 的總價改成20萬再打九折',
    '請把報價單 QT-20260325-001 的總價改成20萬再打9折',
    'QT-20260325-001 總價改成 200000 打八五折',
    'QT-20260325-001 總價改成 200000，再給 10% off',
])
def test_appended_discount_asks_for_the_final_total(text):
    """外部檢查：「改成20萬再打九折」以前用折扣前的 200000 改價。折扣要追問最後的總價，模型自己算的也不收。"""
    event = agent.route(SimpleNamespace(state={'last_user_text': text}),
                        agent.Intent(intent='adjust_total_price', quotation_number='QT-20260325-001', target_total_price=180000))
    assert event.actions.route == 'clarify'
    assert event.output['missing'] == ['target_total_price']
    assert '折扣是相對的說法' in agent.clarify(event.output)


def test_plain_total_and_factor_are_not_treated_as_discount():
    event = agent.route(SimpleNamespace(state={'last_user_text': '請把報價單 QT-20260325-001 的總價改成 200000'}),
                        agent.Intent(intent='adjust_total_price', quotation_number='QT-20260325-001', target_total_price=200000))
    assert event.actions.route == 'adjust_total_price' and event.output['target_total_price'] == 200000
    event = agent.route(SimpleNamespace(state={'last_user_text': f'{Q} 的報價因子改成 0.9'}),
                        agent.Intent(intent='update_pricing_factor', quotation_number=Q, new_pricing_factor=0.9))
    assert event.actions.route == 'update_pricing_factor'


@pytest.mark.parametrize('text,operation,verb,example', [
    (f'可以幫我確認複製報價單 {Q} 是否保留備註嗎？', 'duplicate_quotation', '複製報價單', f'我要複製報價單，報價單編號：{Q}'),
    (f'可以幫我確認複製報價單 {Q} 是否保留備註嗎？', 'off_topic', '複製報價單', f'我要複製報價單，報價單編號：{Q}'),
    ('請問把 QT-20260301-001 轉訂單會保留備註嗎？', 'convert_to_order', '轉成訂單', '我要將報價單轉訂單，報價單編號：QT-20260301-001'),
])
def test_confirmation_inquiry_gets_its_own_reply(text, operation, verb, example):
    """確認詢問不再回「問做法或假設」：說明沒有執行，告訴使用者怎麼查和怎麼真的做，單號用使用者給的。"""
    event = agent.route(SimpleNamespace(state={'last_user_text': text}), agent.Intent(intent=operation))
    assert event.actions.route == 'off_topic'
    assert event.output.startswith(f'這句是在確認{verb}會怎麼處理，我沒有執行任何操作')
    assert example in event.output and '我要查詢報價單' in event.output
    assert event.output != agent.EXPLAIN_TEXT


def test_how_to_question_keeps_the_explain_reply():
    event = agent.route(SimpleNamespace(state={'last_user_text': f'請問如何複製報價單 {Q}'}), agent.Intent(intent='duplicate_quotation'))
    assert event.output == agent.EXPLAIN_TEXT


@pytest.mark.parametrize('text', [
    f'{Q} 改成 8000 的話毛利多少', f'{Q} 改成 8000 的話', f'幫我算 {Q} 改成 8000 毛利多少',
    f'{Q} 總價改成 8000 利潤剩多少', f'{Q} 改成 8000 毛利率是多少', f'萬一 {Q} 改成 8000，利潤會剩多少',
    f'{Q} 改成 8000 好不好', f'{Q} 總價改成 8000 後毛利幾趴', f'假如把 {Q} 改成 8000', f'要是 {Q} 改成 8000 呢',
])
def test_hypothetical_and_result_questions_never_change_the_price(text):
    """完整檢查：「改成 8000 的話毛利多少」以前真的改價。假設語氣、數量問句、問意見都只是在問。"""
    event = agent.route(SimpleNamespace(state={'last_user_text': text}),
                        agent.Intent(intent='adjust_total_price', quotation_number=Q, target_total_price=8000))
    assert event.actions.route not in agent._WRITE_TOOLS


@pytest.mark.parametrize('text', [
    f'方便的話請幫我把 {Q} 總價改成 8000', f'可以的話，請把 {Q} 總價改成 8000',
    f'幫我把 {Q} 總價改成 8000 好不好', f'如果可以，請把 {Q} 總價改成 8000',
])
def test_polite_openings_and_requests_still_change_the_price(text):
    event = agent.route(SimpleNamespace(state={'last_user_text': text}),
                        agent.Intent(intent='adjust_total_price', quotation_number=Q, target_total_price=8000))
    assert event.actions.route == 'adjust_total_price' and event.output['target_total_price'] == 8000


@pytest.mark.parametrize('text,operation', [
    (f'我需要一份 {Q} 的複本', 'duplicate_quotation'),
    (f'{Q} 可以下單了，幫我建立訂單', 'convert_to_order'),
])
def test_copy_and_order_synonyms_are_requests(text, operation):
    event = agent.route(SimpleNamespace(state={'last_user_text': text}), agent.Intent(intent=operation, quotation_number=Q))
    assert event.actions.route == operation


def test_read_request_with_has_or_not_still_reads():
    """「幫我查…的備註有沒有保留」是查報價單，不是問操作做完了沒。"""
    event = agent.route(SimpleNamespace(state={'last_user_text': f'幫我查 {Q} 的備註有沒有保留'}),
                        agent.Intent(intent='get_quotation', quotation_number=Q))
    assert event.actions.route == 'get_quotation'
    event = agent.route(SimpleNamespace(state={'last_user_text': f'{Q} 轉訂單了嗎'}), agent.Intent(intent='convert_to_order', quotation_number=Q))
    assert event.actions.route == 'off_topic' and '完成狀態' in event.output


def test_trailing_hold_cancels_the_pending_operation():
    event = agent.route(SimpleNamespace(state={'last_user_text': f'{Q}，先不要', 'clarify_source_text': '我要複製報價單',
                                               'pending_intent': {'intent': 'duplicate_quotation', 'quotation_number': None}}),
                        agent.Intent(intent='provide_info', quotation_number=Q))
    assert event.output == agent.CANCEL_TEXT
