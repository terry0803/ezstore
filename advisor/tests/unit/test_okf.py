"""OKF 讀取與檢查：§11 conformance、信任等級、過期、作廢、連結、index、frontmatter 編輯。"""

from pricing_advisor.okf import Bundle, parse_time, render_index, split_frontmatter, validate
from pricing_advisor.okf_cli import set_verified


def test_bundle_is_conformant(bundle_path):
    bundle = Bundle(bundle_path)
    assert bundle.errors == []
    assert len(bundle.concepts) == 17
    errors = [i for i in validate(bundle) if i.level == "error"]
    assert errors == []


def test_trust_tiers_and_bare_mapping(bundle_copy):
    concept_file = bundle_copy / "policies" / "discount-approval.md"
    bundle = Bundle(bundle_copy)
    assert bundle.get("policies/discount-approval").trust_tier() == "unverified"

    set_verified(bundle.get("policies/discount-approval"), [{"by": "process:nightly", "at": "2026-10-17T00:00:00Z"}])
    assert Bundle(bundle_copy).get("policies/discount-approval").trust_tier() == "machine-confirmed"

    text = concept_file.read_text(encoding="utf-8").replace(
        "verified:\n  - { by: process:nightly, at: 2026-10-17T00:00:00Z }",
        "verified: { by: human:tester, at: 2026-10-17T01:00:00Z }",
    )
    concept_file.write_text(text, encoding="utf-8")
    concept = Bundle(bundle_copy).get("policies/discount-approval")
    assert concept.verified() == [{"by": "human:tester", "at": parse_time("2026-10-17T01:00:00Z")}]
    assert concept.trust_tier() == "human-reviewed"


def test_malformed_verifier_does_not_count(bundle_copy):
    concept_file = bundle_copy / "policies" / "order-conversion.md"
    for bad in ("verified: { at: 2026-10-17T01:00:00Z }", 'verified: { by: "human:", at: 2026-10-17T01:00:00Z }', "verified: { by: somebody, at: 2026-10-17T01:00:00Z }"):
        text = concept_file.read_text(encoding="utf-8")
        text = "\n".join(l for l in text.splitlines() if not l.startswith("verified:"))
        concept_file.write_text(text.replace("status: stable", f"{bad}\nstatus: stable", 1), encoding="utf-8")
        assert Bundle(bundle_copy).get("policies/order-conversion").trust_tier() == "unverified", bad


def test_same_day_log_line_is_not_repeated(bundle_copy):
    from pricing_advisor.okf_cli import append_log

    bundle = Bundle(bundle_copy)
    append_log(bundle, ["**Verification**: 測試紀錄"])
    append_log(bundle, ["**Verification**: 測試紀錄"])
    assert (bundle_copy / "log.md").read_text(encoding="utf-8").count("測試紀錄") == 1


def test_set_verified_keeps_other_frontmatter(bundle_copy):
    bundle = Bundle(bundle_copy)
    concept = bundle.get("policies/discount-approval")
    before, _, body_before = split_frontmatter(concept.path.read_text(encoding="utf-8"))
    set_verified(concept, [{"by": "human:tester", "at": "2026-10-17T01:00:00Z"}])
    after, _, body_after = split_frontmatter(concept.path.read_text(encoding="utf-8"))
    assert body_after == body_before
    assert {k: v for k, v in after.items() if k != "verified"} == before
    assert after["verified"] == [{"by": "human:tester", "at": parse_time("2026-10-17T01:00:00Z")}]


def test_stale_and_deprecated(bundle_path):
    bundle = Bundle(bundle_path)
    promo = bundle.get("policies/promo-2026q3")
    assert promo.is_stale(parse_time("2026-10-17T00:00:00Z"))
    assert not promo.is_stale(parse_time("2026-08-01T00:00:00Z"))
    assert bundle.get("policies/discount-approval-2025").is_deprecated()
    assert "已作廢" in bundle.listing()
    assert "（已過期）" in bundle.listing()


def test_links_are_resolved_from_bundle_root(bundle_path):
    bundle = Bundle(bundle_path)
    links = bundle.get("policies/discount-approval").links
    assert "system/pricing-formula" in links
    assert "computations/price-change-impact" in links


def test_broken_link_is_only_info(bundle_copy):
    path = bundle_copy / "glossary" / "pricing-factor.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n見 [還沒寫的條目](/glossary/not-yet.md)\n", encoding="utf-8")
    issues = validate(Bundle(bundle_copy))
    broken = [i for i in issues if "not-yet" in i.message]
    assert broken and all(i.level == "info" for i in broken)
    assert not [i for i in issues if i.level == "error"]


def test_missing_type_is_an_error(bundle_copy):
    (bundle_copy / "glossary" / "bad.md").write_text("---\ntitle: 沒有 type\n---\n內容\n", encoding="utf-8")
    bundle = Bundle(bundle_copy)
    assert "glossary/bad" not in bundle.concepts
    assert any(i.level == "error" and "type" in i.message for i in validate(bundle))


def test_render_index_groups_by_type(bundle_path):
    bundle = Bundle(bundle_path)
    text = render_index(bundle, bundle_path / "system")
    assert text.startswith("# A2A Agent")
    assert "* [報價金額怎麼算](pricing-formula.md) - " in text
