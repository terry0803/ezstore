import asyncio
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("verify_live_agents", ROOT / "scripts" / "verify_live_agents.py")
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


def test_resume_keeps_passes_and_archives_failed_attempt(tmp_path):
    output = tmp_path / "acceptance.json"
    passed = {"case": "a_read", "passed": True, "turns": [], "database_checks": []}
    failed = {"case": "b_policy", "passed": False, "error": "rate limited", "turns": [], "database_checks": []}
    output.write_text(json.dumps({
        "model": "gemini-3.5-flash-lite",
        "isolated_backend": live.BACKEND,
        "results": [passed, failed],
    }), encoding="utf-8")

    acceptance = live.Acceptance(output, set(), "gemini-3.5-flash-lite", resume=True,
                                 min_turn_interval=13)
    try:
        assert acceptance.results == [passed]
        assert acceptance.attempt_failures == [failed]
        assert acceptance.min_turn_interval == 13
        acceptance._save(complete=False, expected_cases=30)
    finally:
        asyncio.run(acceptance.http.aclose())

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["cases_passed"] == 1
    assert report["summary"]["expected_cases"] == 30
    assert report["attempt_failures"][0]["error"] == "rate limited"
