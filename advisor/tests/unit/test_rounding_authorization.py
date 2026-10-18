import copy
from types import SimpleNamespace

import pytest
from pricing_advisor import agent
from pricing_advisor.computation import attest_receipt, run_price_change_impact
from pricing_advisor.okf import Bundle
from pricing_advisor.policies import evaluate_price_change

@pytest.mark.asyncio
async def test_low_price_plateau_requires_approval_before_delegating(bundle_path, fake_backend, monkeypatch):
    q = copy.deepcopy(await fake_backend.find_quotation('QT-20260330-001'))
    q.update(customer_level='vip', pricing_factor='1', total_price='4000', profit_amount='3000')
    q['customer']['level'] = 'vip'
    q['items'] = [{'product_id': 9001, 'list_price':'0.04','product_cost':'0.01','quantity':100000}]
    fake_backend.quotations = {q['quotation_number']: q}
    fake_backend.products = {9001: {'list_price':'0.04','cost':'0.01'}}
    bundle = Bundle(bundle_path)
    receipt = await run_price_change_impact(bundle, fake_backend, q['quotation_number'], 3000)
    assert receipt['result']['new_factor'] == '0.6337'
    assert receipt['result']['new_total'] == '3000.00'
    assert attest_receipt(bundle, receipt)['ok']
    assert evaluate_price_change(bundle, receipt['result']).approval == 'sales_manager'
    monkeypatch.setattr(agent, 'backend', fake_backend)
    monkeypatch.setattr(agent, '_bundle', lambda: bundle)
    event = await agent.apply_price(SimpleNamespace(state={}), {'quotation_number':q['quotation_number'], 'target_total':3000})
    assert event.actions.route == 'done'
    assert '核准' in event.output
    assert '0.6337' in event.output
