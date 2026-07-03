"""Render the graph for visualization tools (Obsidian / Mermaid / raw JSON)."""

from __future__ import annotations

from .graph import Graph


def to_json(g: Graph) -> dict:
    return {
        "nodes": [
            {
                "id": nid, "title": a.title, "description": a.description, "resource": a.resource,
                "type": a.type, "timestamp": a.timestamp, "status": a.status, "tags": a.tags,
            }
            for nid, a in g.adrs.items()
        ],
        "edges": [{"from": s, "to": t} for s in g.out for t in g.out[s]],
    }


def to_mermaid(g: Graph) -> str:
    lines = ["graph LR"]
    for nid, adr in g.adrs.items():
        safe_title = adr.title.replace('"', "'")
        lines.append(f'  {nid.replace("-", "_")}["{nid}: {safe_title}"]')
    for s in g.out:
        for t in g.out[s]:
            lines.append(f'  {s.replace("-", "_")} --> {t.replace("-", "_")}')
    return "\n".join(lines)


def to_okf_bundle(g: Graph) -> dict:
    """OKF v0.1 bundle metadata summary with typed relationships."""
    concepts = []
    for nid, a in g.adrs.items():
        # Build typed relationship list from frontmatter edges
        relationships = []
        for rel_type in ("supersedes", "superseded_by", "related"):
            for target in a.fm.get(rel_type, []):
                relationships.append({"type": rel_type, "target": target})
        concepts.append({
            "concept_id": a.path.stem,
            "type": a.type or "adr",
            "title": a.title,
            "description": a.description,
            "resource": a.resource,
            "tags": a.tags,
            "timestamp": a.timestamp,
            "status": a.status,
            "links": sorted(g.out.get(nid, set())),
            "relationships": relationships,
        })
    return {
        "okf_version": "0.1",
        "bundle": {
            "concepts": len(g.adrs),
            "edges": sum(len(v) for v in g.out.values()),
        },
        "concepts": concepts,
    }


def render(g: Graph, fmt: str) -> str | dict:
    fmt = fmt.lower()
    if fmt == "json":
        return to_json(g)
    if fmt == "mermaid":
        return to_mermaid(g)
    if fmt == "okf":
        return to_okf_bundle(g)
    raise ValueError(f"unknown export format: {fmt!r} (use 'json', 'mermaid', or 'okf')")
