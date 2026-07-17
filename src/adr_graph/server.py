"""FastMCP server: the ADR graph as agent-callable verbs.

Every tool resolves the ADR root the same way (explicit arg > ADR_GRAPH_ROOT env
> ./docs/adr) and operates on one freshly built in-memory graph.
"""

from __future__ import annotations

from typing import Any

from pathlib import Path

from collections.abc import Sequence
from fastmcp import FastMCP, Context
from fastmcp.server.providers import Provider
from fastmcp.resources import Resource


from . import mutate
from .config import async_resolve_root
from .exports import render
from .graph import Graph, canonify

mcp = FastMCP("adr-graph", list_page_size=50)

class ADRProvider(Provider):
    async def _list_resources(self) -> Sequence[Resource]:
        g = await _graph(None, None)
        resources = []
        for a in g.adrs.values():
            def make_reader(adr_obj=a):
                def reader() -> str:
                    return adr_obj.path.read_text(encoding="utf-8", errors="replace")
                return reader

            uri = a.resource or f"adr://{a.id}"
            resources.append(
                Resource.from_function(
                    make_reader(a),
                    uri=uri,
                    name=a.title,
                    description=a.description or f"Architectural Decision Record {a.id}",
                )
            )
        return resources

    async def _get_resource(self, uri: str, version: Any = None) -> Resource | None:
        g = await _graph(None, None)
        if uri.startswith("adr://"):
            adr_id = uri[len("adr://"):]
            a = canonify(adr_id)
            if a in g.adrs:
                adr_obj = g.adrs[a]
                if not adr_obj.resource:
                    def make_reader(o=adr_obj):
                        return o.path.read_text(encoding="utf-8", errors="replace")
                    return Resource.from_function(
                        make_reader(adr_obj),
                        uri=uri,
                        name=adr_obj.title,
                        description=adr_obj.description or f"Architectural Decision Record {adr_obj.id}",
                    )

        for adr_obj in g.adrs.values():
            m_uri = adr_obj.resource or f"adr://{adr_obj.id}"
            if m_uri == uri:
                def make_reader(o=adr_obj):
                    return o.path.read_text(encoding="utf-8", errors="replace")
                return Resource.from_function(
                    make_reader(adr_obj),
                    uri=m_uri,
                    name=adr_obj.title,
                    description=adr_obj.description or f"Architectural Decision Record {adr_obj.id}",
                )
        return None

mcp.add_provider(ADRProvider())

_GRAPH_CACHE: dict[Path, tuple[Graph, float]] = {}


def _get_dir_state(root: Path) -> float:
    md_files = list(root.rglob("*.md"))
    if not md_files:
        return 0.0
    return max(f.stat().st_mtime for f in md_files)


async def _graph(ctx: Context | None, root_path: str | None) -> Graph:
    root = await async_resolve_root(ctx, root_path)
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
async def validate(ctx: Context, root: str = "") -> dict[str, Any]:
    """Full topology report. `ok` is False only on genuine rot (undeclared dead
    links or broken reciprocity) — intentional singletons and planned forward
    references are reported under `signals`, never as failures."""
    return await _graph(ctx, root).report()


@mcp.tool
async def okf_conformance(ctx: Context, root: str = "") -> dict[str, Any]:
    """OKF v0.1 conformance report: violations (missing required fields),
    warnings (missing recommended fields), and field coverage metrics."""
    return await _graph(ctx, root).okf_conformance()


@mcp.tool
async def find_singletons(ctx: Context, root: str = "") -> dict[str, Any]:
    """Disconnected nodes, split into intentional frontier vs orphan suspects."""
    intentional, suspect = await _graph(ctx, root).singletons()
    return {"intentional_frontier": intentional, "orphan_suspects": suspect}


@mcp.tool
async def find_dead_links(ctx: Context, root: str = "") -> dict[str, Any]:
    """Unresolved references, split into planned (signal) vs broken (defect)."""
    planned, broken = await _graph(ctx, root).dead_links()
    return {
        "planned_forward_refs": [{"from": s, "to": t} for s, t in planned],
        "broken_dead_links": [{"from": s, "to": t} for s, t in broken],
    }


@mcp.tool
async def check_reciprocity(ctx: Context, root: str = "") -> dict[str, Any]:
    """supersede / superseded_by edges that are not mirrored on the other node."""
    breaks = await _graph(ctx, root).reciprocity_breaks()
    return {"reciprocity_breaks": [{"a": a, "b": b, "detail": d} for a, b, d in breaks]}


@mcp.tool
async def neighbors(ctx: Context, adr: str, depth: int = 1, root: str = "") -> dict[str, Any]:
    """Authored-link neighbourhood of an ADR — the grounding-context primitive."""
    return await _graph(ctx, root).neighbors(adr, depth=depth)


@mcp.tool
async def export(ctx: Context, fmt: str = "json", root: str = "") -> Any:
    """Render the graph as 'json', 'mermaid', or 'okf' (bundle summary with typed relationships)."""
    return render(await _graph(ctx, root), fmt)


@mcp.tool
async def supersede(ctx: Context, superseding: str, superseded: str, root: str = "") -> dict[str, Any]:
    """Record that one ADR supersedes another, writing BOTH sides of the edge."""
    return mutate.supersede(await async_resolve_root(ctx, root), superseding, superseded)


@mcp.tool
async def reconcile_related(ctx: Context, adr: str = "", apply: bool = False, root: str = "") -> dict[str, Any]:
    """Derive frontmatter `related` from body links. Dry-run unless apply=True."""
    return mutate.reconcile_related(await async_resolve_root(ctx, root), adr_id=adr, apply=apply)


@mcp.tool
async def remediate_dark_nodes(ctx: Context, dry_run: bool = True, root: str = "") -> dict[str, Any]:
    """Find plain-text ADR references in markdown bodies and convert them to wikilinks. Dry-run by default."""
    return await mutate.remediate_dark_nodes(await async_resolve_root(ctx, root), ctx=ctx, dry_run=dry_run)


@mcp.tool
async def remediate_drift(ctx: Context, dry_run: bool = True, root: str = "") -> dict[str, Any]:
    """Find nodes where frontmatter typed edges exist but are missing from body links (drift),
    and append them to the body as wikilinks. Dry-run by default."""
    return await mutate.remediate_drift(await async_resolve_root(ctx, root), ctx=ctx, dry_run=dry_run)


@mcp.tool
async def remediate_dead_links(ctx: Context, dry_run: bool = True, root: str = "") -> dict[str, Any]:
    """Find and remove references to non-existent ADRs from both frontmatter and body. Dry-run by default."""
    return await mutate.remediate_dead_links(await async_resolve_root(ctx, root), ctx=ctx, dry_run=dry_run)


@mcp.tool
async def read(ctx: Context, adr: str, root: str = "") -> dict[str, Any]:
    """Read a single ADR by ID, returning its frontmatter details and body text."""
    g = await _graph(ctx, root)
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
async def list_tool(ctx: Context, status: str = "", tag: str = "", limit: int = 100, offset: int = 0, root: str = "") -> list[dict[str, Any]]:
    """List all ADRs, optionally filtered by status and/or tag."""
    g = await _graph(ctx, root)
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
async def search(ctx: Context, query: str, status: str = "", limit: int = 100, offset: int = 0, root: str = "") -> list[dict[str, Any]]:
    """Search for ADRs by title substring match, optionally filtered by status."""
    g = await _graph(ctx, root)
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
async def path(ctx: Context, from_adr: str, to_adr: str, root: str = "") -> dict[str, Any]:
    """Find the BFS shortest path between two ADRs."""
    return await _graph(ctx, root).find_path(from_adr, to_adr)


@mcp.tool
async def set_status(ctx: Context, adr: str, status: str, root: str = "") -> dict[str, Any]:
    """Update the status of a single ADR."""
    return mutate.set_status(await async_resolve_root(ctx, root), adr, status)


@mcp.tool
async def rename(ctx: Context, old: str, new: str, dry_run: bool = True, root: str = "") -> dict[str, Any]:
    """Rename/renumber an ADR and cascade updates to all files referencing it."""
    return mutate.rename(await async_resolve_root(ctx, root), old, new, dry_run=dry_run)


@mcp.tool
async def drift(ctx: Context, root: str = "") -> list[dict[str, Any]]:
    """Nodes where frontmatter typed edges and body links disagree."""
    res = await _graph(ctx, root).drift()
    return [
        {"adr": a, "in_yaml_not_body": f, "in_body_not_yaml": b}
        for a, f, b in res
    ]


@mcp.tool
async def blast_radius(ctx: Context, adr: str, root: str = "") -> dict[str, Any]:
    """Find downstream ADRs that transitively depend on this ADR."""
    return await _graph(ctx, root).blast_radius(adr)


@mcp.tool
async def propose_adr(ctx: Context, title: str, status: str = "proposed", context: str = "", tags: list[str] | None = None, root: str = "") -> dict[str, Any]:
    """Scaffold a new ADR file in the corpus with the next available ID."""
    return mutate.propose(await async_resolve_root(ctx, root), title, status, context, tags)


@mcp.tool
async def migrate_okf(ctx: Context, dry_run: bool = True, root: str = "") -> dict[str, Any]:
    """Migrate the ADR corpus to OKF v0.1 conformance. Ensures type fields, converts
    date→timestamp, synthesizes descriptions, generates index.md. Dry-run by default."""
    return await mutate.migrate_okf(await async_resolve_root(ctx, root), ctx=ctx, dry_run=dry_run)


@mcp.resource("adr://{adr_id}")
async def adr_resource(adr_id: str) -> str:
    """Get the raw markdown text of a specific ADR."""
    g = await _graph(None, None)
    a = canonify(adr_id)
    if a not in g.adrs:
        raise ValueError(f"ADR {a} not found")
    return g.adrs[a].path.read_text(encoding="utf-8", errors="replace")

@mcp.tool
async def read(ctx: Context, adr: str, root: str = "") -> str:
    """Read the structured metadata, content, and navigation options for an ADR, returned as Markdown."""
    g = await _graph(ctx, root)
    a = canonify(adr)
    if a not in g.adrs:
        raise ValueError(f"ADR {a} not found")
    obj = g.adrs[a]
    meta, body = mutate._load(obj.path)
    
    # Build navigation options based on graph topology
    nav_options = []
    
    out_edges = g.out.get(a, set())
    if out_edges:
        nav_options.append("### 🔗 Outgoing References (This ADR depends on / references):")
        for oe in sorted(out_edges):
            if oe in g.adrs:
                nav_options.append(f"- **{oe}**: {g.adrs[oe].title}")
            else:
                nav_options.append(f"- **{oe}** *(Missing/Unresolved)*")
                
    in_edges = g.inn.get(a, set())
    if in_edges:
        nav_options.append("### ⬅️ Incoming References (These ADRs depend on / reference this one):")
        for ie in sorted(in_edges):
            if ie in g.adrs:
                nav_options.append(f"- **{ie}**: {g.adrs[ie].title}")
            else:
                nav_options.append(f"- **{ie}**")

    cross_repo = obj.fm_cross | obj.body_cross
    if cross_repo:
        nav_options.append("### 🌐 Cross-Repo References:")
        for cr in sorted(cross_repo):
            nav_options.append(f"- {cr}")

    nav_section = "\n".join(nav_options) if nav_options else "*No direct neighborhood links found.*"
    tags_str = ", ".join(obj.tags) if obj.tags else "None"

    return f"""# {obj.id}: {obj.title}

**Status:** `{obj.status}` | **Date:** `{obj.timestamp}` | **Tags:** `{tags_str}`

## 📖 Description
{obj.description or "*No description available.*"}

---

## 📝 Content
{body}

---

## 🧭 Navigation Options (Where to go next)
{nav_section}
"""


@mcp.tool
async def hover_context(ctx: Context, file_path: str, root: str = "") -> str:
    """Get architectural context for a file path (for IDE hover tooltips)."""
    g = await _graph(ctx, root)
    adrs = g.get_governing_adrs(file_path)
    if not adrs:
        return "No architectural decisions explicitly govern this path."
    
    lines = ["**Architectural Context**"]
    for a in adrs:
        lines.append(f"- **[{a.id}] {a.title}** (Status: `{a.status}`)")
        if a.fm.get("superseded_by"):
            lines.append(f"  *Warning: Superseded by {', '.join(a.fm['superseded_by'])}*")
    return "\n".join(lines)


@mcp.prompt()
async def draft_adr(ctx: Context, topic: str) -> str:
    """Prompt for an LLM to draft a new Architecture Decision Record based on a topic."""
    g = await _graph(ctx, None)
    adrs = g.list_adrs()
    recent = sorted(adrs, key=lambda a: a.num, reverse=True)[:3]
    recent_titles = "\n".join(f"- {a.id}: {a.title}" for a in recent)
    
    return f"""You are an expert software architect. Draft a new Architecture Decision Record (ADR) about "{topic}".
    
Ensure the ADR uses Google's Open Knowledge Format (OKF) v0.1.
Required YAML frontmatter fields:
- type: adr
- title: "{topic}"
- status: proposed
- timestamp: (current time in ISO 8601)

The body should contain the following sections:
## Context and Problem Statement
## Decision Drivers
## Considered Options
## Decision Outcome

Recent ADRs for context:
{recent_titles}

Please provide the complete markdown text including the YAML frontmatter.
"""

@mcp.prompt()
async def review_adr(ctx: Context, adr_id: str) -> str:
    """Prompt for an LLM to review an existing Architecture Decision Record."""
    g = await _graph(ctx, None)
    from .graph import canonify
    a = canonify(adr_id)
    if a not in g.adrs:
        return f"Error: ADR {a} not found in the graph."
    
    adr = g.adrs[a]
    from .mutate import _load
    meta, body = _load(adr.path)
    
    neighbors = g.neighbors(a, depth=1)
    blast = g.blast_radius(a)
    
    import json
    return f"""You are an expert software architect. Please review the following Architecture Decision Record (ADR): {a}.

### Target ADR Content
```markdown
{body}
```

### Topological Context
- Neighbors (Depth 1): {json.dumps(neighbors, indent=2)}
- Blast Radius (downstream dependents): {json.dumps(blast, indent=2)}

Please evaluate the ADR for:
1. Architectural soundness and tradeoffs.
2. Topological consistency (are we missing any dependencies or relations with its neighbors?).
3. Adherence to the Open Knowledge Format (OKF) guidelines.
"""


@mcp.tool
async def set_root(ctx: Context, path: str = "") -> dict[str, str]:
    """Dynamically set the global ADR root for all subsequent tool calls. Pass an empty string to unset it."""
    from .config import set_global_root
    set_global_root(path if path else None)
    return {"status": "ok", "current_root": path if path else "unset"}
