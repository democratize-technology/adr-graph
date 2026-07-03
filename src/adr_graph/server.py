"""FastMCP server: the ADR graph as agent-callable verbs.

Every tool resolves the ADR root the same way (explicit arg > ADR_GRAPH_ROOT env
> ./docs/adr) and operates on one freshly built in-memory graph.
"""

from __future__ import annotations

from typing import Any

from pathlib import Path

from fastmcp import FastMCP

from . import mutate
from .config import resolve_root
from .exports import render
from .graph import Graph, canonify

mcp = FastMCP("adr-graph")

_GRAPH_CACHE: dict[Path, tuple[Graph, float]] = {}


def _get_dir_state(root: Path) -> float:
    md_files = list(root.rglob("*.md"))
    if not md_files:
        return 0.0
    return max(f.stat().st_mtime for f in md_files)


def _graph(root_path: str | None) -> Graph:
    root = resolve_root(root_path)
    current_state = _get_dir_state(root)
    cached = _GRAPH_CACHE.get(root)
    if cached:
        cached_graph, cached_state = cached
        if cached_state == current_state:
            return cached_graph
    g = Graph.build(root)
    _GRAPH_CACHE[root] = (g, current_state)
    return g


@mcp.tool
def validate(root: str = "") -> dict[str, Any]:
    """Full topology report. `ok` is False only on genuine rot (undeclared dead
    links or broken reciprocity) — intentional singletons and planned forward
    references are reported under `signals`, never as failures."""
    return _graph(root).report()


@mcp.tool
def okf_conformance(root: str = "") -> dict[str, Any]:
    """OKF v0.1 conformance report: violations (missing required fields),
    warnings (missing recommended fields), and field coverage metrics."""
    return _graph(root).okf_conformance()


@mcp.tool
def find_singletons(root: str = "") -> dict[str, Any]:
    """Disconnected nodes, split into intentional frontier vs orphan suspects."""
    intentional, suspect = _graph(root).singletons()
    return {"intentional_frontier": intentional, "orphan_suspects": suspect}


@mcp.tool
def find_dead_links(root: str = "") -> dict[str, Any]:
    """Unresolved references, split into planned (signal) vs broken (defect)."""
    planned, broken = _graph(root).dead_links()
    return {
        "planned_forward_refs": [{"from": s, "to": t} for s, t in planned],
        "broken_dead_links": [{"from": s, "to": t} for s, t in broken],
    }


@mcp.tool
def check_reciprocity(root: str = "") -> dict[str, Any]:
    """supersede / superseded_by edges that are not mirrored on the other node."""
    breaks = _graph(root).reciprocity_breaks()
    return {"reciprocity_breaks": [{"a": a, "b": b, "detail": d} for a, b, d in breaks]}


@mcp.tool
def neighbors(adr: str, depth: int = 1, root: str = "") -> dict[str, Any]:
    """Authored-link neighbourhood of an ADR — the grounding-context primitive."""
    return _graph(root).neighbors(adr, depth=depth)


@mcp.tool
def export(fmt: str = "json", root: str = "") -> Any:
    """Render the graph as 'json', 'mermaid', or 'okf' (bundle summary with typed relationships)."""
    return render(_graph(root), fmt)


@mcp.tool
def supersede(superseding: str, superseded: str, root: str = "") -> dict[str, Any]:
    """Record that one ADR supersedes another, writing BOTH sides of the edge."""
    return mutate.supersede(resolve_root(root), superseding, superseded)


@mcp.tool
def reconcile_related(adr: str = "", apply: bool = False, root: str = "") -> dict[str, Any]:
    """Derive frontmatter `related` from body links. Dry-run unless apply=True."""
    return mutate.reconcile_related(resolve_root(root), adr_id=adr, apply=apply)


@mcp.tool
def read(adr: str, root: str = "") -> dict[str, Any]:
    """Read a single ADR by ID, returning its frontmatter details and body text."""
    g = _graph(root)
    a = canonify(adr)
    if a not in g.adrs:
        return {"error": f"ADR {a} not found"}
    adr_obj = g.adrs[a]
    from .mutate import _load
    meta, body = _load(adr_obj.path)
    return {
        "id": adr_obj.id,
        "title": adr_obj.title,
        "description": adr_obj.description,
        "resource": adr_obj.resource,
        "type": adr_obj.type,
        "timestamp": adr_obj.timestamp,
        "status": adr_obj.status,
        "tags": adr_obj.tags,
        "metadata": meta,
        "body": body,
    }


@mcp.tool(name="list")
def list_tool(status: str = "", tag: str = "", limit: int = 100, offset: int = 0, root: str = "") -> list[dict[str, Any]]:
    """List all ADRs, optionally filtered by status and/or tag."""
    g = _graph(root)
    adrs = g.list_adrs(status=status, tag=tag, limit=limit, offset=offset)
    return [
        {
            "id": a.id,
            "title": a.title,
            "description": a.description,
            "resource": a.resource,
            "type": a.type,
            "timestamp": a.timestamp,
            "status": a.status,
            "tags": a.tags,
        }
        for a in adrs
    ]


@mcp.tool
def search(query: str, status: str = "", limit: int = 100, offset: int = 0, root: str = "") -> list[dict[str, Any]]:
    """Search for ADRs by title substring match, optionally filtered by status."""
    g = _graph(root)
    adrs = g.search_adrs(query, status=status, limit=limit, offset=offset)
    return [
        {
            "id": a.id,
            "title": a.title,
            "description": a.description,
            "resource": a.resource,
            "type": a.type,
            "timestamp": a.timestamp,
            "status": a.status,
            "tags": a.tags,
        }
        for a in adrs
    ]


@mcp.tool
def path(from_adr: str, to_adr: str, root: str = "") -> dict[str, Any]:
    """Find the BFS shortest path between two ADRs."""
    return _graph(root).find_path(from_adr, to_adr)


@mcp.tool
def set_status(adr: str, status: str, root: str = "") -> dict[str, Any]:
    """Update the status of a single ADR."""
    return mutate.set_status(resolve_root(root), adr, status)


@mcp.tool
def rename(old: str, new: str, dry_run: bool = True, root: str = "") -> dict[str, Any]:
    """Rename/renumber an ADR and cascade updates to all files referencing it."""
    return mutate.rename(resolve_root(root), old, new, dry_run=dry_run)


@mcp.tool
def drift(root: str = "") -> list[dict[str, Any]]:
    """Nodes where frontmatter typed edges and body links disagree."""
    res = _graph(root).drift()
    return [
        {"adr": a, "in_yaml_not_body": f, "in_body_not_yaml": b}
        for a, f, b in res
    ]


@mcp.tool
def blast_radius(adr: str, root: str = "") -> dict[str, Any]:
    """Find downstream ADRs that transitively depend on this ADR."""
    return _graph(root).blast_radius(adr)


@mcp.tool
def propose_adr(title: str, status: str = "proposed", context: str = "", tags: list[str] | None = None, root: str = "") -> dict[str, Any]:
    """Scaffold a new ADR file in the corpus with the next available ID."""
    return mutate.propose(resolve_root(root), title, status, context, tags)


@mcp.tool
def migrate_okf(dry_run: bool = True, root: str = "") -> dict[str, Any]:
    """Migrate the ADR corpus to OKF v0.1 conformance. Ensures type fields, converts
    date→timestamp, synthesizes descriptions, generates index.md. Dry-run by default."""
    return mutate.migrate_okf(resolve_root(root), dry_run=dry_run)


@mcp.resource("adr://{adr_id}")
def adr_resource(adr_id: str) -> str:
    """Get the raw markdown text of a specific ADR."""
    g = _graph(None)
    a = canonify(adr_id)
    if a not in g.adrs:
        raise ValueError(f"ADR {a} not found")
    return g.adrs[a].path.read_text(encoding="utf-8", errors="replace")


@mcp.tool
def hover_context(file_path: str, root: str = "") -> str:
    """Get architectural context for a file path (for IDE hover tooltips)."""
    g = _graph(root)
    adrs = g.get_governing_adrs(file_path)
    if not adrs:
        return "No architectural decisions explicitly govern this path."
    
    lines = ["**Architectural Context**"]
    for a in adrs:
        lines.append(f"- **[{a.id}] {a.title}** (Status: `{a.status}`)")
        if a.fm.get("superseded_by"):
            lines.append(f"  *Warning: Superseded by {', '.join(a.fm['superseded_by'])}*")
    return "\n".join(lines)
