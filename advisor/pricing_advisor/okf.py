"""OKF v0.2 知識庫的讀取與檢查（consumer 端）。

依 Open Knowledge Format v0.2（GoogleCloudPlatform/open-knowledge-format 的 SPEC.md）：

- 不是 index.md、log.md 的 .md 檔都是一個條目，要有 YAML frontmatter 和非空的 type（§4、§11）
- 信任等級由 verified 推導：沒有 → unverified；只有非 human: 的 → machine-confirmed；
  有 human: 的 → human-reviewed。單一個 { by, at } 當成一個元素的清單（§5.2、§5.3）
- status 沒寫當 stable；now >= stale_after 就是過期（§5.4、§5.5）
- 連結以 / 開頭是相對於知識庫根目錄，其他相對於條目所在目錄；連不到的連結不算錯（§6）
"""

from __future__ import annotations

import ast
import functools
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

RESERVED_FILES = ("index.md", "log.md")
TRUST_LABELS = {
    "unverified": "未驗證",
    "machine-confirmed": "機器驗證",
    "human-reviewed": "人工審核",
}

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)^---[ \t]*(?:\r?\n|\Z)", re.S | re.M)
_LINK_RE = re.compile(r"\]\(([^)\s]+?\.md)(?:#[^)]*)?\)")
_FOOTNOTE_USE_RE = re.compile(r"\[\^([^\]\s]+)\](?!:)")
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]\s]+)\]:", re.M)
_ACTOR_RE = re.compile(r"^(human:\S+|process:\S+|team:\S+|[^\s:/]+/\S+)$")
_LOG_DATE_RE = re.compile(r"^## (.+?)\s*$", re.M)
_INDEX_ENTRY_RE = re.compile(r"^\* \[([^\]]+)\]\(([^)]+)\)(?: - (.*))?$")


class OKFError(ValueError):
    """知識庫或條目不符合 OKF 的格式。"""


def split_frontmatter(text: str) -> tuple[dict | None, str, str]:
    """回傳 (frontmatter, frontmatter 原文, body)。沒有 frontmatter 時第一個值是 None。"""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None, "", text
    raw = match.group(1)
    try:
        data = yaml.safe_load(raw) if raw.strip() else {}
    except yaml.YAMLError as e:
        raise OKFError(f"frontmatter 不是合法的 YAML：{e}") from e
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise OKFError("frontmatter 必須是 key: value 的對應")
    return data, raw, text[match.end():]


def parse_time(value: Any) -> datetime | None:
    """把 frontmatter 裡的時間轉成有時區的 datetime；沒寫時區當 UTC。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def format_time(value: Any) -> str:
    parsed = parse_time(value)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if parsed else ""


def format_date_tw(value: Any) -> str:
    """顯示用：轉成台灣時間的日期，例如 2026-10-17。"""
    parsed = parse_time(value)
    if not parsed:
        return ""
    from datetime import timedelta

    return (parsed.astimezone(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")


def utc_now() -> datetime:
    """現在時間。OKF_NOW 可以指定（測試與示範用）。"""
    override = os.getenv("OKF_NOW")
    return parse_time(override) if override else datetime.now(timezone.utc)


@dataclass
class Concept:
    """一個 OKF 條目。id 是相對於知識庫根目錄、去掉 .md 的路徑。"""

    id: str
    path: Path
    frontmatter: dict
    body: str
    links: list[str] = field(default_factory=list)

    @property
    def type(self) -> str:
        return str(self.frontmatter.get("type") or "")

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title") or self.id.rsplit("/", 1)[-1])

    @property
    def description(self) -> str:
        return str(self.frontmatter.get("description") or "")

    @property
    def tags(self) -> list[str]:
        tags = self.frontmatter.get("tags") or []
        return [str(t) for t in tags] if isinstance(tags, list) else [str(tags)]

    @property
    def status(self) -> str:
        return str(self.frontmatter.get("status") or "stable")

    def verified(self) -> list[dict]:
        value = self.frontmatter.get("verified")
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
        return []

    def trust_tier(self) -> str:
        actors = [str(v.get("by", "")) for v in self.verified()]
        if not actors:
            return "unverified"
        if any(a.startswith("human:") for a in actors):
            return "human-reviewed"
        return "machine-confirmed"

    def last_verified(self) -> dict | None:
        events = [v for v in self.verified() if parse_time(v.get("at"))]
        return max(events, key=lambda v: parse_time(v["at"])) if events else None

    def stale_after(self) -> datetime | None:
        return parse_time(self.frontmatter.get("stale_after"))

    def is_stale(self, now: datetime | None = None) -> bool:
        limit = self.stale_after()
        return bool(limit and (now or utc_now()) >= limit)

    def is_deprecated(self) -> bool:
        return self.status == "deprecated"

    def sources(self) -> list[dict]:
        value = self.frontmatter.get("sources")
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [s for s in value if isinstance(s, dict)]
        return []

    def trust_note(self, now: datetime | None = None) -> str:
        """給使用者看的一句話：信任等級、最後驗證者與日期、是否過期或作廢。"""
        tier = self.trust_tier()
        note = TRUST_LABELS[tier]
        last = self.last_verified()
        if last:
            note += f"，{last.get('by')} {format_date_tw(last.get('at'))}"
        if self.is_deprecated():
            note += "，已作廢"
        elif self.is_stale(now):
            note += f"，{format_date_tw(self.stale_after())} 起過期"
        return note


class Bundle:
    """整個知識庫。載入時不合格式的條目放進 errors，不會讓整個知識庫失敗。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        if not self.root.is_dir():
            raise OKFError(f"找不到知識庫目錄：{self.root}")
        self.concepts: dict[str, Concept] = {}
        self.errors: list[str] = []
        for path in sorted(self.root.rglob("*.md")):
            if path.name in RESERVED_FILES:
                continue
            rel = path.relative_to(self.root).as_posix()
            try:
                fm, _, body = split_frontmatter(path.read_text(encoding="utf-8"))
            except OKFError as e:
                self.errors.append(f"{rel}：{e}")
                continue
            if fm is None:
                self.errors.append(f"{rel}：沒有 frontmatter")
                continue
            if not str(fm.get("type") or "").strip():
                self.errors.append(f"{rel}：frontmatter 沒有 type")
                continue
            concept = Concept(id=rel[:-3], path=path, frontmatter=fm, body=body)
            concept.links = self._links(body, path.parent)
            self.concepts[concept.id] = concept

    def _relative_id(self, path: Path) -> str | None:
        try:
            rel = path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return None
        return rel[:-3] if rel.endswith(".md") else rel

    def _links(self, body: str, doc_dir: Path) -> list[str]:
        found: list[str] = []
        for target in _LINK_RE.findall(body):
            if "://" in target:
                continue
            base = self.root / target.lstrip("/") if target.startswith("/") else doc_dir / target
            concept_id = self._relative_id(base)
            if concept_id and concept_id not in found:
                found.append(concept_id)
        return found

    def resolve_path(self, value: str, concept: Concept | None = None) -> Path:
        """path-valued 欄位（§6.2）轉成檔案路徑；不允許跑出知識庫。"""
        if value.startswith("/") or concept is None:
            target = self.root / value.lstrip("/")
        else:
            target = concept.path.parent / value
        resolved = target.resolve()
        root = self.root.resolve()
        if resolved != root and root not in resolved.parents:
            raise OKFError(f"路徑跑出知識庫：{value}")
        return resolved

    def get(self, concept_id: str) -> Concept | None:
        key = concept_id.strip().lstrip("/")
        return self.concepts.get(key[:-3] if key.endswith(".md") else key)

    def find(self, *, type_name: str | None = None, rule_kind: str | None = None) -> list[Concept]:
        result = []
        for concept in self.concepts.values():
            if type_name and concept.type != type_name:
                continue
            if rule_kind and concept.frontmatter.get("rule_kind") != rule_kind:
                continue
            result.append(concept)
        return result

    def listing(self, now: datetime | None = None) -> str:
        """漸進揭露用的目錄：每個條目一行「id｜標題｜描述」，作廢與過期會標出來。"""
        lines = []
        for concept in sorted(self.concepts.values(), key=lambda c: c.id):
            if concept.id.startswith("references/"):
                continue
            flags = ""
            if concept.is_deprecated():
                flags = "（已作廢）"
            elif concept.is_stale(now):
                flags = "（已過期）"
            lines.append(f"{concept.id}｜{concept.title}{flags}｜{concept.description}")
        return "\n".join(lines)


@functools.lru_cache(maxsize=4)
def _cached_bundle(root: str, signature: tuple) -> Bundle:
    return Bundle(root)


def load_bundle(root: str | Path) -> Bundle:
    """讀知識庫；檔案沒有變動時沿用上次讀的結果。"""
    root_path = Path(root)
    signature = tuple(
        (p.as_posix(), p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(root_path.rglob("*"))
        if p.is_file()
    )
    return _cached_bundle(str(root_path.resolve()), signature)


# ---------------------------------------------------------------------------
# 檢查（§11 conformance 與其他建議）
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    level: str  # error：不符合 §11；warning：建議修正；info：提醒
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.where}：{self.message}"


def _check_actor(where: str, value: Any, issues: list[Issue], field_name: str) -> None:
    if not isinstance(value, dict) or not value.get("by"):
        issues.append(Issue("warning", where, f"{field_name} 要有 by"))
        return
    if not _ACTOR_RE.match(str(value["by"])):
        issues.append(Issue("warning", where, f"{field_name}.by「{value['by']}」不符合 actor 寫法（§7）"))
    if "at" in value and parse_time(value.get("at")) is None:
        issues.append(Issue("warning", where, f"{field_name}.at 不是 ISO 8601 時間"))


def _check_index_file(bundle: Bundle, path: Path, issues: list[Issue]) -> None:
    rel = path.relative_to(bundle.root).as_posix()
    try:
        fm, _, body = split_frontmatter(path.read_text(encoding="utf-8"))
    except OKFError as e:
        issues.append(Issue("error", rel, str(e)))
        return
    is_root = path.parent.resolve() == bundle.root.resolve()
    if fm is not None:
        if not is_root:
            issues.append(Issue("error", rel, "只有根目錄的 index.md 可以有 frontmatter（§8）"))
        elif set(fm) - {"okf_version"}:
            issues.append(Issue("error", rel, "根目錄 index.md 的 frontmatter 只能有 okf_version（§8、§12）"))
    if not re.search(r"^# .+", body, re.M):
        issues.append(Issue("error", rel, "index.md 至少要有一個 # 標題的區段（§8）"))
    for line in body.splitlines():
        match = _INDEX_ENTRY_RE.match(line.strip())
        if not match:
            continue
        target = (path.parent / match.group(2)).resolve()
        if not target.exists():
            issues.append(Issue("warning", rel, f"索引項目連不到：{match.group(2)}"))


def _check_log_file(bundle: Bundle, path: Path, issues: list[Issue]) -> None:
    rel = path.relative_to(bundle.root).as_posix()
    dates = _LOG_DATE_RE.findall(path.read_text(encoding="utf-8"))
    parsed = []
    for value in dates:
        try:
            parsed.append(date.fromisoformat(value))
        except ValueError:
            issues.append(Issue("error", rel, f"日期標題「{value}」不是 YYYY-MM-DD（§9）"))
    if parsed != sorted(parsed, reverse=True):
        issues.append(Issue("warning", rel, "日期要新的在前（§9）"))


def validate(bundle: Bundle, now: datetime | None = None) -> list[Issue]:
    """檢查整個知識庫。error 是不符合 §11；warning、info 不影響 conformance。"""
    issues = [Issue("error", where.split("：", 1)[0], where.split("：", 1)[-1]) for where in bundle.errors]
    for path in sorted(bundle.root.rglob("index.md")):
        _check_index_file(bundle, path, issues)
    for path in sorted(bundle.root.rglob("log.md")):
        _check_log_file(bundle, path, issues)

    for concept in bundle.concepts.values():
        where = f"{concept.id}.md"
        fm = concept.frontmatter
        for target in concept.links:
            if target not in bundle.concepts and not (bundle.root / target).exists():
                issues.append(Issue("info", where, f"連結的條目還不存在：/{target}.md（§6.1 允許）"))
        source_ids = {str(s.get("id")) for s in concept.sources() if s.get("id")}
        for source in concept.sources():
            if not source.get("resource"):
                issues.append(Issue("warning", where, "sources 的每一筆都要有 resource（§5.1）"))
            if source.get("last_modified") and parse_time(source["last_modified"]) is None:
                issues.append(Issue("warning", where, "sources.last_modified 不是 ISO 8601 時間"))
        defined = set(_FOOTNOTE_DEF_RE.findall(concept.body))
        for label in set(_FOOTNOTE_USE_RE.findall(concept.body)):
            if label not in source_ids:
                issues.append(Issue("warning", where, f"註腳 [^{label}] 對不到 sources 的 id（§5.1）"))
            if label not in defined:
                issues.append(Issue("warning", where, f"註腳 [^{label}] 沒有定義"))
        if "generated" in fm:
            _check_actor(where, fm.get("generated"), issues, "generated")
        for event in concept.verified():
            _check_actor(where, event, issues, "verified")
        if "stale_after" in fm and concept.stale_after() is None:
            issues.append(Issue("warning", where, "stale_after 不是 ISO 8601 時間（§5.5）"))
        if concept.status not in ("draft", "stable", "deprecated"):
            issues.append(Issue("warning", where, f"status「{concept.status}」不是 draft、stable、deprecated（§5.4）"))
        if concept.is_stale(now) and not concept.is_deprecated():
            issues.append(Issue("info", where, f"已過期（stale_after {format_time(concept.stale_after())}）"))
        if concept.type == "Attested Computation":
            _check_computation(bundle, concept, issues)
    return issues


def _check_computation(bundle: Bundle, concept: Concept, issues: list[Issue]) -> None:
    import hashlib

    where = f"{concept.id}.md"
    fm = concept.frontmatter
    if not fm.get("runtime"):
        issues.append(Issue("error", where, "Attested Computation 一定要有 runtime（§10.2）"))
    for key in ("computation", "executor", "attester"):
        if not fm.get(key):
            issues.append(Issue("warning", where, f"缺 {key}"))
    for key, value in (
        ("computation", fm.get("computation")),
        ("executor.resource", (fm.get("executor") or {}).get("resource")),
        ("attester.resource", (fm.get("attester") or {}).get("resource")),
    ):
        if not value:
            continue
        try:
            target = bundle.resolve_path(str(value), concept)
        except OKFError as e:
            issues.append(Issue("error", where, f"{key}：{e}"))
            continue
        if not target.exists():
            issues.append(Issue("warning", where, f"{key} 指的檔案不存在：{value}"))
    pinned = fm.get("computation_sha256")
    if pinned and fm.get("computation"):
        try:
            target = bundle.resolve_path(str(fm["computation"]), concept)
        except OKFError:
            return
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != pinned:
            issues.append(Issue("warning", where, "計算程式和登記的 computation_sha256 不同，需要重新審核"))


# ---------------------------------------------------------------------------
# 產生 index.md（§8）
# ---------------------------------------------------------------------------


def _python_summary(path: Path) -> str:
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    except SyntaxError:
        return ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def _existing_descriptions(index_path: Path) -> dict[str, str]:
    if not index_path.exists():
        return {}
    descriptions = {}
    for line in index_path.read_text(encoding="utf-8").splitlines():
        match = _INDEX_ENTRY_RE.match(line.strip())
        if match and match.group(3):
            descriptions[match.group(2)] = match.group(3)
    return descriptions


def render_index(bundle: Bundle, directory: Path) -> str:
    """產生某個目錄的 index.md：條目依 type 分區，子目錄與程式檔另列。"""
    directory = directory.resolve()
    keep = _existing_descriptions(directory / "index.md")
    groups: dict[str, list[Concept]] = {}
    for concept in bundle.concepts.values():
        if concept.path.parent.resolve() == directory:
            groups.setdefault(concept.type, []).append(concept)
    sections = []
    for type_name in sorted(groups):
        items = sorted(groups[type_name], key=lambda c: (c.is_deprecated(), c.id))
        lines = [f"# {type_name}", ""]
        lines += [f"* [{c.title}]({c.path.name}) - {c.description}" for c in items]
        sections.append("\n".join(lines))
    subdirs = sorted(p for p in directory.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
    if subdirs:
        lines = ["# Subdirectories", ""]
        for sub in subdirs:
            link = f"{sub.name}/index.md"
            lines.append(f"* [{sub.name}]({link}) - {keep.get(link, '')}".rstrip(" -"))
        sections.append("\n".join(lines))
    code = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix == ".py")
    if code:
        lines = ["# Code", ""]
        lines += [f"* [{p.name}]({p.name}) - {_python_summary(p)}".rstrip(" -") for p in code]
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + "\n"
