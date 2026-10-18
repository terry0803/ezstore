"""Check the instructor-owned files and the submission's required artifacts."""
import json
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
BASE = '09f6588c94ecb74b071246c55c32d838fc31e8f7'
PROTECTED = ('backend', 'frontend', 'mcp_server')


USER_FIXES = {
    # 2026-10-18: user approved the six findings (including Taiwan numbering).
    # This list documents the exception; it does not grant instructor approval.
    'backend/handlers/approved_price.go',
    'backend/services/approved_price.go',
    'backend/services/approved_price_test.go',
    'backend/routes/routes.go',
    'backend/handlers/customer_handler.go',
    'backend/handlers/product_handler.go',
    'backend/handlers/quotation_handler.go',
    'backend/handlers/order_handler.go',
    'backend/handlers/pagination.go',
    'backend/handlers/pagination_test.go',
    'backend/repositories/quotation_repo.go',
    'backend/repositories/customer_repo.go',
    'backend/repositories/product_repo.go',
    'backend/repositories/order_repo.go',
    'backend/services/customer_service.go',
    'backend/services/product_service.go',
    'backend/services/pagination.go',
    'backend/services/business_date.go',
    'backend/services/business_date_test.go',
    'frontend/src/pages/AgentChatPage.tsx',
    'frontend/src/pages/CustomerListPage.tsx',
    'frontend/src/pages/ProductListPage.tsx',
    'frontend/src/pages/OrderListPage.tsx',
    'backend/services/quotation_service.go',
    'backend/services/order_service.go',
    'backend/services/pricing_factor_validation_test.go',
    'backend/services/order_validation_test.go',
    'frontend/src/api/agentApi.ts',
    'frontend/src/api/allOptions.ts',
    'frontend/src/components/shared/ErrorMessage.tsx',
    'frontend/src/components/shared/FormRefreshGuard.tsx',
    'frontend/src/pages/QuotationDetailPage.tsx',
    'frontend/src/pages/OrderDetailPage.tsx',
    'frontend/src/pages/QuotationListPage.tsx',
    'frontend/src/pages/CustomerFormPage.tsx',
    'frontend/src/pages/ProductFormPage.tsx',
    'frontend/src/pages/OrderFormPage.tsx',
    'frontend/src/pages/QuotationFormPage.tsx',
    'frontend/e2e/review-regressions.spec.ts',
    'mcp_server/server.py',
    'mcp_server/tests/test_lookup_regressions.py',
}


def check(*, allow_user_fixes=False):
    failures=[]
    changed=subprocess.check_output(['git','diff','--name-only',BASE,'--',*PROTECTED],cwd=ROOT).decode('utf-8').splitlines()
    extra=subprocess.check_output(['git','ls-files','--others','--exclude-standard','--',*PROTECTED],cwd=ROOT).decode('utf-8').splitlines()
    differences=sorted(set(changed+extra))
    unexpected=[path for path in differences if not allow_user_fixes or path not in USER_FIXES]
    if unexpected:
        failures.append({'protected_files_changed':unexpected})
    for folder in ('agent','advisor'):
        project=tomllib.loads((ROOT/folder/'pyproject.toml').read_text(encoding='utf-8'))
        if project['project']['requires-python']!='>=3.12,<3.13':
            failures.append(f'{folder}: Python must be 3.12')
        if 'google-adk[mcp,a2a]>=2.10,<3' not in project['project']['dependencies']:
            failures.append(f'{folder}: required ADK range/extras missing')
        if not (ROOT/folder/'uv.lock').is_file():
            failures.append(f'{folder}: missing uv.lock')
    required={'get_quotation','list_customer_quotations','duplicate_quotation','update_pricing_factor','adjust_total_price','convert_to_order'}
    data=json.loads((ROOT/'agent/tests/eval/datasets/quotation-actions.json').read_text(encoding='utf-8'))
    cases=data.get('eval_cases',[]) if isinstance(data,dict) else data
    if len(cases)!=6 or {row['eval_case_id'] for row in cases}!=required:
        failures.append('First Agent must have the six instructor action cases')
    guardrails=json.loads((ROOT/'agent/tests/eval/datasets/quotation-guardrails.json').read_text(encoding='utf-8'))
    guard_cases=guardrails.get('eval_cases',[])
    if len(guard_cases)!=3 or {row['eval_case_id'] for row in guard_cases}!={'off_topic_weather','off_topic_customer_crud','clarify_then_complete'}:
        failures.append('Teacher guardrail suite must contain exactly the three required non-writing cases')
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0')
    if any(Path(p).name=='.env' for p in tracked):
        failures.append('Private .env must not be tracked')
    if not (ROOT/'advisor/tests/eval/response_safety_wording.py').is_file():
        failures.append('Missing explicitly scoped wording metric')
    return {'teacher_baseline':BASE,'protected_directories':list(PROTECTED),
            'strict_teacher_match':not differences,'protected_differences':differences,
            'mode':'user_authorized_fixes' if allow_user_fixes else 'strict_teacher',
            'note':'User authorized these bug fixes; this is not instructor approval.' if differences else '',
            'passed':not failures,'failures':failures}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-user-fixes',action='store_true',help='Explicitly allow only the documented user-requested fixes; does not assert teacher approval.')
    result=check(allow_user_fixes=parser.parse_args().allow_user_fixes)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    sys.exit(0 if result['passed'] else 1)
