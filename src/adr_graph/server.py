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
from fastmcp.dependencies import Depends, CurrentContext
from fastmcp.tools.base import ToolResult
from fastmcp.apps.approval import Approval


from . import mutate
from .config import async_resolve_root, get_ctx_callbacks
from .exports import render
from .graph import Graph, canonify
from .markdown_ld_renderer import render_response
from .formatters import (
    format_validate,
    format_okf_conformance,
    format_singletons,
    format_dead_links,
    format_reciprocity,
    format_neighbors,
    format_read,
    format_list,
    format_search,
    format_path,
    format_drift,
    format_blast_radius,
    format_mutation,
)
import json

mcp = FastMCP("adr-graph", list_page_size=50)
mcp.add_provider(Approval())

from fastmcp.server.transforms import ResourcesAsTools, PromptsAsTools

mcp.add_transform(ResourcesAsTools(mcp))
mcp.add_transform(PromptsAsTools(mcp))

class ADRProvider(Provider):
    async def _list_resources(self) -> Sequence[Resource]:
        g = await _graph(None, None)
        resources = []
        for a in g.adrs.values():
            def make_reader(adr_obj=a):
                def reader() -> str:
                    return adr_obj.path.read_text(encoding="utf-8", errors="replace")
                return reader

            resources.append(
                Resource.from_function(
                    make_reader(a),
                    uri=a.resource or f"adr://{a.id}",
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


async def _graph(ctx: Context | None, root_path: str | Path | None) -> Graph:
    root = await async_resolve_root(ctx, str(root_path) if root_path else None)
    current_state = _get_dir_state(root)
    cached = _GRAPH_CACHE.get(root)
    if cached:
        cached_graph, cached_state = cached
        if cached_state == current_state:
            return cached_graph
    
    progress_cb, log_cb = get_ctx_callbacks(ctx)
    g = Graph.build(root, progress_cb=progress_cb, log_cb=log_cb)
    _GRAPH_CACHE[root] = (g, current_state)
    return g


async def get_root(ctx: Context = CurrentContext()) -> Path:
    return await async_resolve_root(ctx, None)


async def get_graph(ctx: Context = CurrentContext()) -> Graph:
    root = await get_root(ctx)
    return await _graph(ctx, root)


@mcp.tool
async def validate(g: Graph = Depends(get_graph)) -> ToolResult:
    """Full topology report. `ok` is False only on genuine rot (undeclared dead
    links or broken reciprocity) — intentional singletons and planned forward
    references are reported under `signals`, never as failures. Returns self-navigable Markdown containing JSON-LD."""
    res = g.report()
    return format_validate(res)


@mcp.tool
async def okf_conformance(g: Graph = Depends(get_graph)) -> ToolResult:
    """OKF v0.1 conformance report: violations (missing required fields),
    warnings (missing recommended fields), and field coverage metrics. Returns self-navigable Markdown containing JSON-LD."""
    res = g.okf_conformance()
    return format_okf_conformance(res)


@mcp.tool
async def find_singletons(g: Graph = Depends(get_graph)) -> ToolResult:
    """Disconnected nodes, split into intentional frontier vs orphan suspects. Returns self-navigable Markdown containing JSON-LD."""
    intentional, suspect = g.singletons()
    res = {"intentional_frontier": intentional, "orphan_suspects": suspect}
    return format_singletons(res)


@mcp.tool
async def find_dead_links(g: Graph = Depends(get_graph)) -> ToolResult:
    """Unresolved references, split into planned (signal) vs broken (defect). Returns self-navigable Markdown containing JSON-LD."""
    planned, broken = g.dead_links()
    res = {
        "planned_forward_refs": [{"from": s, "to": t} for s, t in planned],
        "broken_dead_links": [{"from": s, "to": t} for s, t in broken],
    }
    return format_dead_links(res)


@mcp.tool
async def check_reciprocity(g: Graph = Depends(get_graph)) -> ToolResult:
    """supersede / superseded_by edges that are not mirrored on the other node. Returns self-navigable Markdown containing JSON-LD."""
    breaks = g.reciprocity_breaks()
    res = {"reciprocity_breaks": [{"a": a, "b": b, "detail": d} for a, b, d in breaks]}
    return format_reciprocity(res)


@mcp.tool
async def neighbors(adr: str, depth: int = 1, g: Graph = Depends(get_graph)) -> ToolResult:
    """Authored-link neighbourhood of an ADR — the grounding-context primitive. Returns self-navigable Markdown containing JSON-LD."""
    res = g.neighbors(adr, depth=depth)
    return format_neighbors(res)


@mcp.tool
async def export(fmt: str = "json", g: Graph = Depends(get_graph)) -> Any:
    """Render the graph as 'json', 'mermaid', or 'okf' (bundle summary with typed relationships). Returns self-navigable Markdown containing JSON-LD."""
    res = render(g, fmt)
    if fmt.lower() == "mermaid":
        return f"```mermaid\n{res}\n```"
    return render_response(
        title=f"Graph Export ({fmt.upper()})",
        description=f"Exported topology in {fmt.upper()} format.",
        json_ld_type="ExportAction",
        json_ld_data=res if isinstance(res, dict) else {"content": res},
        markdown_body=f"```json\n{json.dumps(res, indent=2)}\n```" if isinstance(res, dict) else res,
    )


@mcp.tool
async def supersede(superseding: str, superseded: str, root: Path = Depends(get_root)) -> ToolResult:
    """Record that one ADR supersedes another, writing BOTH sides of the edge. Returns self-navigable Markdown containing JSON-LD.

    IMPORTANT: You MUST call the `request_approval` tool to get user confirmation before executing this destructive action.
    """
    res = mutate.supersede(root, superseding, superseded)
    return format_mutation(res, "Supersede Edges Updated", f"Record that {superseding} supersedes {superseded}.")


@mcp.tool
async def reconcile_related(adr: str = "", apply: bool = False, root: Path = Depends(get_root)) -> ToolResult:
    """Derive frontmatter `related` from body links. Dry-run unless apply=True. Returns self-navigable Markdown containing JSON-LD.

    IMPORTANT: If `apply` is True, you MUST call the `request_approval` tool to get user confirmation before executing this action.
    """
    res = mutate.reconcile_related(root, adr_id=adr, apply=apply)
    return format_mutation(res, "Reconcile Related Links", "Derive frontmatter `related` fields from body references.")


@mcp.tool(task=True)
async def remediate_dark_nodes(ctx: Context = CurrentContext(), dry_run: bool = True, root: Path = Depends(get_root)) -> ToolResult:
    """Find plain-text ADR references in markdown bodies and convert them to wikilinks. Dry-run by default. Returns self-navigable Markdown containing JSON-LD.

    IMPORTANT: If `dry_run` is False, you MUST call the `request_approval` tool to get user confirmation before executing this action.
    """
    res = await mutate.remediate_dark_nodes(root, ctx=ctx, dry_run=dry_run)
    return format_mutation(res, "Remediate Dark Nodes", "Convert plaintext references to wikilinks.")


@mcp.tool(task=True)
async def remediate_drift(ctx: Context = CurrentContext(), dry_run: bool = True, root: Path = Depends(get_root)) -> ToolResult:
    """Find nodes where frontmatter typed edges exist but are missing from body links (drift),
    and append them to the body as wikilinks. Dry-run by default. Returns self-navigable Markdown containing JSON-LD.

    IMPORTANT: If `dry_run` is False, you MUST call the `request_approval` tool to get user confirmation before executing this action.
    """
    res = await mutate.remediate_drift(root, ctx=ctx, dry_run=dry_run)
    return format_mutation(res, "Remediate Drift", "Append missing body links from frontmatter definitions.")


@mcp.tool(task=True)
async def remediate_dead_links(ctx: Context = CurrentContext(), dry_run: bool = True, root: Path = Depends(get_root)) -> ToolResult:
    """Find and remove references to non-existent ADRs from both frontmatter and body. Dry-run by default. Returns self-navigable Markdown containing JSON-LD.

    IMPORTANT: If `dry_run` is False, you MUST call the `request_approval` tool to get user confirmation before executing this action.
    """
    res = await mutate.remediate_dead_links(root, ctx=ctx, dry_run=dry_run)
    return format_mutation(res, "Remediate Dead Links", "Remove references to non-existent ADRs from metadata and content.")


@mcp.tool(name="list")
async def list_tool(status: str = "", tag: str = "", limit: int = 100, offset: int = 0, g: Graph = Depends(get_graph)) -> ToolResult:
    """List all ADRs, optionally filtered by status and/or tag. Returns self-navigable Markdown containing JSON-LD."""
    adrs = g.list_adrs(status=status, tag=tag, limit=limit, offset=offset)
    adrs_data = [
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
    query_info = []
    if status:
        query_info.append(f"status='{status}'")
    if tag:
        query_info.append(f"tag='{tag}'")
    
    return format_list(adrs_data, ", ".join(query_info))


@mcp.tool
async def search(query: str, status: str = "", limit: int = 100, offset: int = 0, g: Graph = Depends(get_graph)) -> ToolResult:
    """Search for ADRs by title substring match, optionally filtered by status. Returns self-navigable Markdown containing JSON-LD."""
    adrs = g.search_adrs(query, status=status, limit=limit, offset=offset)
    adrs_data = [
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
    return format_search(adrs_data, query)


@mcp.tool
async def path(from_adr: str, to_adr: str, g: Graph = Depends(get_graph)) -> ToolResult:
    """Find the BFS shortest path between two ADRs. Returns self-navigable Markdown containing JSON-LD."""
    res = g.find_path(from_adr, to_adr)
    return format_path(res, from_adr, to_adr)


@mcp.tool
async def set_status(adr: str, status: str = "", ctx: Context = CurrentContext(), root: Path = Depends(get_root)) -> ToolResult:
    """Update the status of a single ADR. Returns self-navigable Markdown containing JSON-LD.

    IMPORTANT: You MUST call the `request_approval` tool to get user confirmation before executing this action.
    """
    VALID_STATUSES = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
    if not status or status.lower() not in VALID_STATUSES:
        result = await ctx.elicit(
            message=f"Choose a valid status for ADR {adr}:" if status else f"Select new status for ADR {adr}:",
            response_type=VALID_STATUSES,
            response_title="Choose ADR Status",
            response_description=f"Updating status for {adr}."
        )
        if result.action == "accept":
            status = result.data
        elif result.action == "decline":
            return format_mutation({"ok": False, "error": "Status update declined by user."}, "Set ADR Status", "Update status of ADR.")
        else:
            return format_mutation({"ok": False, "error": "Operation cancelled."}, "Set ADR Status", "Update status of ADR.")

    res = mutate.set_status(root, adr, status)
    return format_mutation(res, "Set ADR Status", f"Update status of {adr} to {status}.")


@mcp.tool(task=True)
async def rename(old: str, new: str, dry_run: bool = True, root: Path = Depends(get_root)) -> ToolResult:
    """Rename/renumber an ADR and cascade updates to all files referencing it. Returns self-navigable Markdown containing JSON-LD.

    IMPORTANT: If `dry_run` is False, you MUST call the `request_approval` tool to get user confirmation before executing this action.
    """
    res = mutate.rename(root, old, new, dry_run=dry_run)
    return format_mutation(res, "Rename ADR", f"Rename/renumber ADR {old} to {new}.")


@mcp.tool
async def drift(g: Graph = Depends(get_graph)) -> ToolResult:
    """Nodes where frontmatter typed edges and body links disagree. Returns self-navigable Markdown containing JSON-LD."""
    res = g.drift()
    drift_data = [
        {"adr": a, "in_yaml_not_body": f, "in_body_not_yaml": b}
        for a, f, b in res
    ]
    return format_drift(drift_data)


@mcp.tool
async def blast_radius(adr: str, g: Graph = Depends(get_graph)) -> ToolResult:
    """Find downstream ADRs that transitively depend on this ADR. Returns self-navigable Markdown containing JSON-LD."""
    res = g.blast_radius(adr)
    return format_blast_radius(res)


@mcp.tool
async def propose_adr(
    title: str = "",
    status: str = "proposed",
    context: str = "",
    tags: list[str] | None = None,
    ctx: Context = CurrentContext(),
    g: Graph = Depends(get_graph),
    root: Path = Depends(get_root)
) -> ToolResult:
    """Scaffold a new ADR file in the corpus with the next available ID. Returns self-navigable Markdown containing JSON-LD."""
    if not title:
        result = await ctx.elicit(
            message="Enter the title for the new ADR:",
            response_type=str,
            response_title="ADR Title Required",
            response_description="A descriptive title is required to scaffold a new ADR."
        )
        if result.action == "accept":
            title = result.data
        else:
            return format_mutation({"ok": False, "error": "ADR proposal cancelled."}, "Propose ADR", "Scaffold new ADR.")

    if tags is None:
        existing_tags = sorted(list({t for a in g.adrs.values() for t in a.tags if t}))
        if existing_tags:
            result = await ctx.elicit(
                message="Select tags for the new ADR (optional):",
                response_type=[existing_tags],
                response_title="Select ADR Tags",
                response_description="Choose one or more existing tags, or decline/cancel to skip."
            )
            if result.action == "accept":
                tags = result.data
            elif result.action == "cancel":
                return format_mutation({"ok": False, "error": "ADR proposal cancelled."}, "Propose ADR", "Scaffold new ADR.")

    res = mutate.propose(root, title, status, context, tags)
    return format_mutation(res, "Propose ADR", f"Scaffold new ADR titled '{title}'.")


@mcp.tool(task=True)
async def migrate_okf(ctx: Context = CurrentContext(), dry_run: bool = True, root: Path = Depends(get_root)) -> ToolResult:
    """Migrate the ADR corpus to OKF v0.1 conformance. Ensures type fields, converts
    date→timestamp, synthesizes descriptions, generates index.md. Dry-run by default. Returns self-navigable Markdown containing JSON-LD.

    IMPORTANT: If `dry_run` is False, you MUST call the `request_approval` tool to get user confirmation before executing this action.
    """
    res = await mutate.migrate_okf(root, ctx=ctx, dry_run=dry_run)
    return format_mutation(res, "Migrate OKF Conformance", "Migrate corpus to OKF v0.1 specification.")


@mcp.resource("adr://{adr_id}")
async def adr_resource(adr_id: str) -> str:
    """Get the raw markdown text of a specific ADR."""
    g = await _graph(None, None)
    a = canonify(adr_id)
    if a not in g.adrs:
        raise ValueError(f"ADR {a} not found")
    return g.adrs[a].path.read_text(encoding="utf-8", errors="replace")


@mcp.tool
async def read(adr: str, g: Graph = Depends(get_graph)) -> ToolResult:
    """Read the structured metadata, content, and navigation options for an ADR, returned as Markdown."""
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
                nav_options.append(f"- **[{oe}](adr://{oe})**: {g.adrs[oe].title}")
            else:
                nav_options.append(f"- **{oe}** *(Missing/Unresolved)*")
                
    in_edges = g.inn.get(a, set())
    if in_edges:
        nav_options.append("### ⬅️ Incoming References (These ADRs depend on / reference this one):")
        for ie in sorted(in_edges):
            if ie in g.adrs:
                nav_options.append(f"- **[{ie}](adr://{ie})**: {g.adrs[ie].title}")
            else:
                nav_options.append(f"- **{ie}**")

    cross_repo = obj.fm_cross | obj.body_cross
    if cross_repo:
        nav_options.append("### 🌐 Cross-Repo References:")
        for cr in sorted(cross_repo):
            nav_options.append(f"- {cr}")

    nav_section = "\n".join(nav_options) if nav_options else "*No direct neighborhood links found.*"
    
    adr_data = {
        "id": obj.id,
        "title": obj.title,
        "description": obj.description,
        "resource": obj.resource,
        "type": obj.type,
        "timestamp": obj.timestamp,
        "status": obj.status,
        "tags": obj.tags,
        "metadata": meta,
        "body": body,
    }
    return format_read(adr_data, nav_section)






@mcp.tool
async def hover_context(ctx: Context = CurrentContext(), file_path: str = "", root: str = "", g: Graph = Depends(get_graph)) -> str:
    """Get architectural context for a file path (for IDE hover tooltips)."""
    if root:
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
async def draft_adr(topic: str, g: Graph = Depends(get_graph)) -> str:
    """Prompt for an LLM to draft a new Architecture Decision Record based on a topic."""
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
async def review_adr(adr_id: str, g: Graph = Depends(get_graph)) -> str:
    """Prompt for an LLM to review an existing Architecture Decision Record."""
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
