"""OKF 知識庫的命令列工具。

    uv run okf validate                 照規格 §11 檢查，有 error 時 exit 1
    uv run okf index                    重新產生各子目錄的 index.md（根目錄的手寫，不動）
    uv run okf verify                   對照原始碼與執行中的系統，通過的寫入 process:okf-verify
    uv run okf sign <條目> --by human:<id>   人工審核後簽核（Attested Computation 可加 --repin）
    uv run okf viz                      產生關聯圖 viz.html（Google 官方 viewer 的版型）

知識庫位置用 --bundle 或環境變數 OKF_BUNDLE，預設是 repo 的 knowledge/ezstore。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import timedelta, timezone
from pathlib import Path

from .okf import Bundle, Concept, OKFError, format_time, load_bundle, render_index, utc_now, validate

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_BUNDLE = _REPO / "knowledge" / "ezstore"
_ACTOR_HUMAN = re.compile(r"^human:\S+$")
_FM_BLOCK = re.compile(r"\A(---[ \t]*\r?\n)(.*?)(^---[ \t]*(?:\r?\n|\Z))", re.S | re.M)


# ---------------------------------------------------------------------------
# frontmatter 的文字層編輯：只改 verified 與 computation_sha256，其他行原樣保留
# ---------------------------------------------------------------------------


def _replace_key(frontmatter: str, key: str, new_lines: list[str], after: str | None = None) -> str:
    lines = frontmatter.splitlines()
    out: list[str] = []
    skipping = False
    position = None
    for line in lines:
        if re.match(rf"^{re.escape(key)}\s*:", line):
            skipping = True
            position = len(out)
            continue
        if skipping and (line.startswith((" ", "\t", "-")) or not line.strip()):
            continue
        skipping = False
        out.append(line)
    if position is None:
        position = len(out)
        if after:
            for i, line in enumerate(out):
                if re.match(rf"^{re.escape(after)}\s*:", line):
                    position = i + 1
    out[position:position] = new_lines
    return "\n".join(out) + "\n"


def write_frontmatter_key(path: Path, key: str, new_lines: list[str], after: str | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    match = _FM_BLOCK.match(text)
    if not match:
        raise OKFError(f"{path} 沒有 frontmatter")
    updated = _replace_key(match.group(2), key, new_lines, after)
    path.write_text(match.group(1) + updated + match.group(3) + text[match.end():], encoding="utf-8")


def _verified_lines(entries: list[dict]) -> list[str]:
    if not entries:
        return []
    return ["verified:"] + [f"  - {{ by: {e['by']}, at: {format_time(e['at'])} }}" for e in entries]


def set_verified(concept: Concept, entries: list[dict]) -> None:
    write_frontmatter_key(concept.path, "verified", _verified_lines(entries), after="generated")


def append_log(bundle: Bundle, lines: list[str]) -> None:
    """在根目錄 log.md 的今天（台灣日期）底下加紀錄，新的在前。"""
    log = bundle.root / "log.md"
    today = (utc_now().astimezone(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")
    text = log.read_text(encoding="utf-8") if log.exists() else "# Directory Update Log\n"
    entries = "\n".join(f"* {line}" for line in lines)
    heading = f"## {today}\n"
    if heading in text:
        text = text.replace(heading, f"{heading}{entries}\n", 1)
    else:
        title_end = text.find("\n") + 1
        text = f"{text[:title_end]}\n{heading}{entries}\n{text[title_end:]}"
    log.write_text(re.sub(r"\n{3,}", "\n\n", text), encoding="utf-8")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_validate(bundle: Bundle, args) -> int:
    issues = validate(bundle)
    for issue in issues:
        if args.all or issue.level != "info":
            print(issue)
    errors = sum(1 for i in issues if i.level == "error")
    warnings = sum(1 for i in issues if i.level == "warning")
    tiers = {}
    for concept in bundle.concepts.values():
        tiers[concept.trust_tier()] = tiers.get(concept.trust_tier(), 0) + 1
    print(
        f"\n{len(bundle.concepts)} 個條目；error {errors}、warning {warnings}；"
        f"信任等級 {json.dumps(tiers, ensure_ascii=False)}"
    )
    print("符合 OKF v0.2（§11）" if errors == 0 else "不符合 OKF v0.2（§11）")
    return 1 if errors else 0


def cmd_index(bundle: Bundle, args) -> int:
    for directory in sorted(p for p in bundle.root.rglob("*") if p.is_dir()):
        rel_parts = directory.relative_to(bundle.root).parts
        if any(part.startswith((".", "_")) for part in rel_parts):
            continue
        target = directory / "index.md"
        content = render_index(bundle, directory)
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        if old != content:
            target.write_text(content, encoding="utf-8")
            print(f"更新 {target.relative_to(bundle.root).as_posix()}")
    return 0


def cmd_verify(bundle: Bundle, args) -> int:
    from .okf_verify import VERIFIER, VerifyContext, run

    ctx = VerifyContext(
        bundle,
        repo=Path(args.repo),
        backend_api=args.backend_api,
        mcp_url=args.mcp_url,
        quotation_agent_url=args.quotation_agent_url,
    )
    results = run(ctx, args.only or None)
    now = utc_now()
    passed, failed, log_lines = [], [], []
    for concept_id, (ok, notes) in results.items():
        mark = "通過" if ok else "失敗"
        print(f"[{mark}] {concept_id}")
        for note in notes:
            print(f"    {note}")
        concept = bundle.get(concept_id)
        if concept is None or args.dry_run:
            continue
        others = [e for e in concept.verified() if e.get("by") != VERIFIER]
        entries = others + ([{"by": VERIFIER, "at": now}] if ok else [])
        set_verified(concept, entries)
        (passed if ok else failed).append(concept_id)
    if not args.dry_run:
        if passed:
            log_lines.append(f"**Verification**: `{VERIFIER}` 對照原始碼與執行中的系統，{len(passed)} 個條目通過：" + "、".join(f"`{c}`" for c in passed) + "。")
        if failed:
            log_lines.append(f"**Verification**: `{VERIFIER}` 有 {len(failed)} 個條目沒通過，拿掉機器驗證紀錄：" + "、".join(f"`{c}`" for c in failed) + "。")
        if log_lines:
            append_log(bundle, log_lines)
    print(f"\n通過 {sum(1 for ok, _ in results.values() if ok)}／{len(results)}")
    return 0 if all(ok for ok, _ in results.values()) else 1


def cmd_sign(bundle: Bundle, args) -> int:
    if not _ACTOR_HUMAN.match(args.by):
        print("--by 要用 human:<id>，例如 human:terry0803（規格 §7）", file=sys.stderr)
        return 2
    concept = bundle.get(args.concept)
    if concept is None:
        print(f"找不到條目 {args.concept}", file=sys.stderr)
        return 2
    if concept.type == "Attested Computation":
        path = bundle.resolve_path(str(concept.frontmatter["computation"]), concept)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if concept.frontmatter.get("computation_sha256") != actual:
            if not args.repin:
                print("計算程式和登記的 computation_sha256 不同。看過程式後加 --repin 重新登記。", file=sys.stderr)
                return 2
            write_frontmatter_key(concept.path, "computation_sha256", [f"computation_sha256: {actual}"], after="computation")
            print(f"重新登記 computation_sha256：{actual}")
        concept = load_bundle(bundle.root).get(concept.id)
    entries = [e for e in concept.verified() if e.get("by") != args.by] + [{"by": args.by, "at": utc_now()}]
    set_verified(concept, entries)
    append_log(bundle, [f"**Verification**: `{args.by}` 審核 [{concept.title}](/{concept.id}.md)。{args.note or ''}".strip()])
    print(f"{concept.id}：已由 {args.by} 簽核，信任等級改為人工審核")
    return 0


def cmd_viz(bundle: Bundle, args) -> int:
    from .okf_viz import generate

    out = Path(args.out) if args.out else bundle.root / "viz.html"
    stats = generate(bundle, out, name=args.name or "EZStore 報價知識庫")
    print(f"寫入 {out}：{stats['concepts']} 個條目、{stats['edges']} 條關聯")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="okf", description="EZStore OKF 知識庫工具")
    parser.add_argument("--bundle", default=os.getenv("OKF_BUNDLE") or str(_DEFAULT_BUNDLE))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="照 OKF v0.2 §11 檢查")
    p.add_argument("--all", action="store_true", help="也列出 info")
    sub.add_parser("index", help="重新產生子目錄的 index.md")

    p = sub.add_parser("verify", help="對照原始碼與系統，寫入 process:okf-verify")
    p.add_argument("--repo", default=str(_REPO))
    p.add_argument("--backend-api", default=os.getenv("BACKEND_API", "http://localhost:8080/api/v1"))
    p.add_argument("--mcp-url", default=os.getenv("VERIFY_MCP_URL", "http://localhost:8010/mcp"))
    p.add_argument(
        "--quotation-agent-url",
        default=os.getenv("QUOTATION_AGENT_URL", "http://localhost:3000/agent-api/a2a/quotation_agent"),
    )
    p.add_argument("--only", nargs="*", help="只檢查這些條目")
    p.add_argument("--dry-run", action="store_true", help="只檢查，不寫入")

    p = sub.add_parser("sign", help="人工審核後簽核")
    p.add_argument("concept")
    p.add_argument("--by", required=True, help="human:<id>")
    p.add_argument("--note", default="")
    p.add_argument("--repin", action="store_true", help="Attested Computation：重新登記計算程式的 sha256")

    p = sub.add_parser("viz", help="產生關聯圖 viz.html")
    p.add_argument("--out")
    p.add_argument("--name")

    args = parser.parse_args(argv)
    bundle = Bundle(args.bundle)
    handler = {"validate": cmd_validate, "index": cmd_index, "verify": cmd_verify, "sign": cmd_sign, "viz": cmd_viz}
    return handler[args.command](bundle, args)


if __name__ == "__main__":
    raise SystemExit(main())
