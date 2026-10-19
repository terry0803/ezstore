import pytest
from quotation_agent import agent

@pytest.mark.parametrize("change", ["調高 300000", "提高 300000", "調低 300000", "增加 300000"])
@pytest.mark.parametrize("field,label", [("target_total_price","總價"),("new_pricing_factor","報價因子")])
def test_relative_followup_is_not_taken_as_an_absolute_price(change, field, label):
    value, blocks_history = agent._numeric_target(label + change, field, allow_bare=True)
    assert value is None
    assert blocks_history
