import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('assignment_boundary',ROOT/'scripts/check_assignment.py')
boundary=importlib.util.module_from_spec(spec)
spec.loader.exec_module(boundary)

def test_write_intent_policy_is_identical_in_both_separately_built_agents():
    assert (ROOT/'agent/quotation_agent/write_intent.py').read_bytes()==(ROOT/'advisor/pricing_advisor/write_intent.py').read_bytes()

def test_user_exception_does_not_claim_strict_teacher_compliance():
    result=boundary.check(allow_user_fixes=True)
    assert result['passed'], result
    assert result['strict_teacher_match'] is False
    assert boundary.check()['passed'] is False

def test_unlisted_protected_file_is_not_allowed(monkeypatch):
    original=boundary.subprocess.check_output
    def output(args,**kwargs):
        data=original(args,**kwargs)
        if args[:3]==['git','diff','--name-only']:
            data+=b'frontend/src/unrelated.ts\n'
        return data
    monkeypatch.setattr(boundary.subprocess,'check_output',output)
    assert not boundary.check(allow_user_fixes=True)['passed']
