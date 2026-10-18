from types import SimpleNamespace
import pytest
from pricing_advisor import agent
from pricing_advisor.conversion_journal import ConversionJournal

Q='QT-20260325-001'

@pytest.mark.parametrize('text',[f'請問如何複製報價單 {Q}',f'複製報價單 {Q} 的操作流程是什麼？',f'How can I copy quotation {Q}?'])
def test_howto_never_delegates_copy(text):
    result=agent.route(SimpleNamespace(state={'last_user_text':text}),agent.AdvisorIntent(intent='quotation_request'))
    assert result.actions.route=='off_topic'

@pytest.mark.parametrize('text',[f'Change total of {Q} to 200000 or 210000',f'把 {Q} 總價改成200000 / 210000',f'把 {Q} 總價改成2e5',f'先把 {Q} 總價改成2026/10/17',f'把 {Q} 總價改成abc'])
def test_invalid_new_amount_never_falls_back_to_history(text):
    ctx=SimpleNamespace(state={'last_user_text':text,'last_quotation':Q,'last_check':{'quotation_number':Q,'target_total':200000}})
    result=agent.route(ctx,agent.AdvisorIntent(intent='apply_price'))
    assert result.actions.route=='clarify'
    assert result.output['fields']['target_total'] is None

@pytest.mark.asyncio
async def test_cost_drift_is_rejected_before_a2a(fake_backend,monkeypatch):
    q='QT-20260330-001'
    fake_backend.products[6]['cost']='790'
    monkeypatch.setattr(agent,'backend',fake_backend)
    result=await agent.apply_price(SimpleNamespace(state={}),{'quotation_number':q,'target_total':8000})
    assert result.actions.route=='done'
    assert '成本或牌價' in result.output and '沒有改資料' in result.output

@pytest.mark.asyncio
async def test_uncertain_write_survives_restart_and_arbitrary_time(tmp_path,monkeypatch):
    path=tmp_path/'journal.sqlite3'
    first=ConversionJournal(path)
    first[Q]={'kind':'interrupted','since':-10**9}
    restarted=ConversionJournal(path)
    monkeypatch.setattr(agent,'_CONVERT_UNCERTAIN',restarted)
    text=await agent._uncertain_still_open(Q,restarted[Q])
    assert '沒有再次送出' in text
    assert Q in restarted

def test_journal_does_not_lose_entries_when_another_instance_writes(tmp_path):
    first=ConversionJournal(tmp_path/'journal.sqlite3')
    second=ConversionJournal(first.path)
    first[Q]={'kind':'interrupted'}
    second['other']={'kind':'interrupted'}
    assert set(first)=={Q,'other'}
    del second[Q]
    assert Q not in first


@pytest.mark.parametrize('text',[
    f'複製報價單 {Q} 會產生哪些資料？',
    f'系統支援複製報價單 {Q} 嗎？',
    f'昨天同事複製了報價單 {Q}，我只是描述這件事。',
    f'報價單 {Q} 複製完了',
])
@pytest.mark.parametrize('classification',['quotation_request','off_topic'])
def test_copy_description_never_delegates(text, classification):
    event=agent.route(SimpleNamespace(state={'last_user_text':text}),agent.AdvisorIntent(intent=classification))
    assert event.actions.route=='off_topic'


@pytest.mark.parametrize('value',['明天','abc','2026/10/18'])
def test_explicit_invalid_replacement_cannot_reuse_last_check(value):
    state={'last_user_text':f'幫我把 {Q} 總價改到{value}', 'last_quotation':Q,
           'last_check':{'quotation_number':Q,'target_total':200000}}
    event=agent.route(SimpleNamespace(state=state),agent.AdvisorIntent(intent='apply_price'))
    assert event.actions.route=='clarify'
    assert event.output['fields']['target_total'] is None


def test_stated_price_is_read_only_even_when_classified_as_apply_price():
    event=agent.route(SimpleNamespace(state={'last_user_text':f'{Q} 的總價是200000'}),
                      agent.AdvisorIntent(intent='apply_price'))
    assert event.actions.route=='price_check'


@pytest.mark.parametrize('text',['好，幫我改','請照剛才的試算改','apply it'])
def test_only_explicit_confirmation_can_reuse_the_checked_price(text):
    state={'last_user_text':text,'last_quotation':Q,'last_check':{'quotation_number':Q,'target_total':200000}}
    event=agent.route(SimpleNamespace(state=state),agent.AdvisorIntent(intent='apply_price'))
    assert event.actions.route=='apply_price'
    assert event.output=={'quotation_number':Q,'target_total':200000}


@pytest.mark.asyncio
async def test_copy_timeout_warns_that_the_write_may_have_happened(monkeypatch):
    from pricing_advisor.a2a_client import A2AError
    class Peer:
        async def send(self, text):
            raise A2AError('timeout',may_have_written=True)
    monkeypatch.setattr(agent,'quotation_agent',Peer())
    routed=agent.route(SimpleNamespace(state={'last_user_text':f'請複製報價單 {Q}'}),
                       agent.AdvisorIntent(intent='quotation_request'))
    event=await agent.delegate_a2a(None,routed.output)
    assert '可能已送出操作' in event.output and '勿直接重試' in event.output


@pytest.mark.parametrize('text', [f'可以幫我複製報價單 {Q} 嗎？', f'你好，請複製報價單 {Q}', f'這張 {Q} 麻煩複製一份'])
def test_polite_copy_request_is_delegated(text):
    event = agent.route(SimpleNamespace(state={'last_user_text': text}), agent.AdvisorIntent(intent='quotation_request'))
    assert event.actions.route == 'delegate' and '複製' in event.output['text']


def test_polite_price_request_is_a_write_not_only_a_check():
    event = agent.route(SimpleNamespace(state={'last_user_text': f'你好，請把 {Q} 總價壓到 200000'}),
                        agent.AdvisorIntent(intent='apply_price'))
    assert event.actions.route == 'apply_price'


@pytest.mark.asyncio
@pytest.mark.parametrize('reply,released', [
    ('操作失敗：找不到報價單編號 QT-20260301-001\n這次操作可能已經建立了新的報價單或訂單，請先查詢確認，再決定要不要重試，免得重複建立。', True),
    ('操作失敗：找不到資料', True),
    ('未送出操作：目前無法確認報價與商品資料', True),
    ('操作失敗：後端回應 400：資料錯誤\n這次操作可能已經建立了新的報價單或訂單，請先查詢確認，再決定要不要重試，免得重複建立。', False),
])
async def test_only_pre_write_failures_release_the_journal(tmp_path, monkeypatch, reply, released):
    """建訂單之前的讀取失敗確定沒寫入，可以解除；後端 400 可能發生在寫入之後，繼續擋。"""
    import copy
    from pricing_advisor.a2a_client import A2AResult
    from tests.conftest import FakeBackend, SNAPSHOT

    number = 'QT-20260301-001'
    monkeypatch.setattr(agent, 'backend', FakeBackend(quotations=copy.deepcopy(SNAPSHOT['quotations']),
                                                      orders=copy.deepcopy(SNAPSHOT['orders_by_customer'])))
    monkeypatch.setattr(agent, '_CONVERT_LOCKS', {})
    monkeypatch.setattr(agent, '_CONVERT_UNCERTAIN', ConversionJournal(tmp_path / 'journal.sqlite3'))

    class Peer:
        async def send(self, text, on_dispatch=None):
            if on_dispatch:
                on_dispatch('task-1', 'ctx-1')
            return A2AResult(reply, 'task-1', 'ctx-1', 'completed', 'quotation_agent')

    monkeypatch.setattr(agent, 'quotation_agent', Peer())
    event = await agent.order_check(SimpleNamespace(state={}), {'quotation_number': number, 'convert': True})
    await agent.delegate_a2a(None, event.output)
    assert (number not in agent._CONVERT_UNCERTAIN) is released


def test_admin_resolve_requires_an_order_or_explicit_confirmation(tmp_path, monkeypatch, capsys):
    from pricing_advisor import journal_cli as conversion_journal

    path = tmp_path / 'journal.sqlite3'
    monkeypatch.setenv('CONVERSION_JOURNAL', str(path))
    ConversionJournal(path)['QT-20260301-001'] = {'kind': 'interrupted'}
    calls = []

    async def no_order(number):
        calls.append(number)
        return {'id': 1}, []

    monkeypatch.setattr(conversion_journal, '_linked_orders', no_order)
    assert conversion_journal.main(['resolve', 'qt-20260301-001']) == 1
    assert 'QT-20260301-001' in ConversionJournal(path)
    assert conversion_journal.main(['resolve', 'QT-20260301-001', '--confirmed-no-order-written']) == 0
    assert 'QT-20260301-001' not in ConversionJournal(path)

    ConversionJournal(path)['QT-20260115-001'] = {'kind': 'interrupted'}

    async def has_order(number):
        return {'id': 2}, [{'id': 9, 'order_number': 'ORD-1', 'quotation_id': 2}]

    monkeypatch.setattr(conversion_journal, '_linked_orders', has_order)
    assert conversion_journal.main(['resolve', 'QT-20260115-001']) == 0
    assert len(ConversionJournal(path)) == 0
    assert conversion_journal.main(['list']) == 0
    assert '沒有結果不明' in capsys.readouterr().out


@pytest.mark.parametrize('text', [f'{Q} 先不要壓價了', f'{Q} 不改價了', f'不用轉單了，{Q}'])
@pytest.mark.parametrize('classification', ['apply_price', 'provide_info', 'price_check'])
def test_cancel_with_object_noun_is_recognized(text, classification):
    """「壓價了」「改價了」「轉單了」動詞後面還有名詞，也要認得是取消（Gemini 實測找到）。"""
    event = agent.route(SimpleNamespace(state={'last_user_text': text}), agent.AdvisorIntent(intent=classification))
    assert event.actions.route == 'off_topic' and '已經取消' in event.output
