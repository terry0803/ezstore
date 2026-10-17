"""把 OKF 知識庫畫成可以點的關聯圖（單一 HTML 檔）。

版型、樣式與前端程式（viz.html、viz.css、viz.js）取自 GoogleCloudPlatform/open-knowledge-format
的 src/reference_agent/viewer，授權是 Apache License 2.0，檔案開頭保留原本的版權聲明。
這裡只改寫產生資料的部分：連結以 / 開頭（相對於知識庫根目錄）也算關聯，sources 指到
知識庫內的條目也畫成關聯，信任等級與過期狀態用 pricing_advisor.okf 計算。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..okf import Bundle, format_time, utc_now

_HERE = Path(__file__).parent
_PALETTE = {
    "Policy": "#f97316",
    "Attested Computation": "#8b5cf6",
    "Business Rule": "#0ea5e9",
    "PostgreSQL Table": "#3b82f6",
    "API Endpoint": "#14b8a6",
    "MCP Server": "#10b981",
    "A2A Agent": "#22c55e",
    "Playbook": "#eab308",
    "Glossary Term": "#a3a3a3",
    "Skill": "#ec4899",
}
_DEFAULT_COLOR = "#94a3b8"


def _event(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    return {"by": value.get("by"), "at": format_time(value.get("at")) or None}


def build_graph(bundle: Bundle) -> dict[str, Any]:
    now = utc_now()
    nodes, edges, seen = [], [], set()
    ids = set(bundle.concepts)
    for concept in sorted(bundle.concepts.values(), key=lambda c: c.id):
        fm = concept.frontmatter
        nodes.append(
            {
                "data": {
                    "id": concept.id,
                    "label": concept.title,
                    "type": concept.type,
                    "description": concept.description,
                    "resource": str(fm.get("resource") or ""),
                    "tags": concept.tags,
                    "status": concept.status,
                    "generated": _event(fm.get("generated")),
                    "verified": [_event(v) for v in concept.verified()],
                    "stale_after": format_time(fm.get("stale_after")),
                    "sources": [
                        {k: (format_time(v) if k == "last_modified" else v) for k, v in s.items()}
                        for s in concept.sources()
                    ],
                    "trust_tier": concept.trust_tier(),
                    "stale": concept.is_stale(now),
                    "color": _PALETTE.get(concept.type, _DEFAULT_COLOR),
                    "size": 30 + min(60, len(concept.body) // 200),
                }
            }
        )
        targets = list(concept.links)
        for source in concept.sources():
            resource = str(source.get("resource") or "")
            if resource.startswith("/") and resource.endswith(".md"):
                targets.append(resource[1:-3])
        for target in targets:
            key = (concept.id, target)
            if target == concept.id or target not in ids or key in seen:
                continue
            seen.add(key)
            edges.append({"data": {"id": f"{concept.id}__{target}", "source": concept.id, "target": target}})
    return {
        "nodes": nodes,
        "edges": edges,
        "bodies": {c.id: c.body for c in bundle.concepts.values()},
        "types": sorted({c.type for c in bundle.concepts.values()}),
        "palette": _PALETTE,
    }


def generate(bundle: Bundle, out: Path, name: str) -> dict[str, int]:
    graph = build_graph(bundle)
    data = json.dumps(graph, ensure_ascii=False, default=str).replace("</", "<\\/")
    html = (
        (_HERE / "viz.html").read_text(encoding="utf-8")
        .replace("/*__VIZ_CSS__*/", (_HERE / "viz.css").read_text(encoding="utf-8"))
        .replace("/*__VIZ_JS__*/", (_HERE / "viz.js").read_text(encoding="utf-8"))
        .replace("__BUNDLE_NAME__", json.dumps(name, ensure_ascii=False))
        .replace("__BUNDLE_DATA__", data)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return {"concepts": len(graph["nodes"]), "edges": len(graph["edges"])}
