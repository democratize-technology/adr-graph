"""Formatters to convert raw ADR tool outputs into JSON-LD embedded Markdown + Prefab rich UI."""

from __future__ import annotations

from typing import Any
from .markdown_ld_renderer import render_response
from fastmcp.tools.base import ToolResult

from prefab_ui.app import PrefabApp
import prefab_ui.components as c
from prefab_ui.actions.mcp import CallTool, SendMessage
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.rx import Rx, RESULT

def format_validate(res: dict[str, Any]) -> ToolResult:
    status_emoji = "✅" if res["ok"] else "❌"
    md = f"### Status: {status_emoji} {'ADR Graph is clean' if res['ok'] else 'ADR Graph has defects'}\n\n"
    
    md += "#### 📊 Summary Metrics\n"
    md += f"| Metric | Value |\n| --- | --- |\n"
    md += f"| Total ADRs | {res['meta']['adrs']} |\n"
    md += f"| Total Edges | {res['meta']['edges']} |\n"
    md += f"| Connected Nodes | {res['meta']['connected']} |\n"
    md += f"| Completeness % | {res['meta']['completeness_pct']}% |\n"
    md += f"| Intentional Frontier | {res['meta']['intentional_frontier']} |\n\n"
    
    if not res["ok"]:
        md += "#### ⚠️ Defects Found\n"
        defects = res["defects"]
        if defects.get("broken_dead_links"):
            md += "\n**Broken Dead Links:**\n"
            for x in defects["broken_dead_links"]:
                md += f"- `{x['from']}` references non-existent `{x['to']}`\n"
        if defects.get("reciprocity_breaks"):
            md += "\n**Reciprocity Breaks:**\n"
            for x in defects["reciprocity_breaks"]:
                md += f"- `{x['detail']}`\n"
        if defects.get("okf_violations"):
            md += "\n**OKF Violations:**\n"
            for x in defects["okf_violations"]:
                md += f"- `{x['adr']}`: {x['detail']}\n"
        if defects.get("orphan_suspects"):
            md += "\n**Orphan Suspects:**\n"
            for x in defects["orphan_suspects"]:
                md += f"- `{x}`\n"
        if defects.get("dark_nodes"):
            md += "\n**Dark Nodes:**\n"
            for x in defects["dark_nodes"]:
                md += f"- `{x['adr']}`: Mentions `{x['raw_ref']}` but intended `{x['intended_id']}`\n"
        if defects.get("cross_repo_bleeds"):
            md += "\n**Cross-Repo Bleeds:**\n"
            for x in defects["cross_repo_bleeds"]:
                md += f"- `{x['adr']}`: References `{x['raw_ref']}` external to codebase\n"
                
    signals = res.get("signals", {})
    if signals.get("intentional_singletons") or signals.get("planned_forward_refs"):
        md += "\n#### 🟢 Signals (Intentional Incompleteness)\n"
        if signals.get("intentional_singletons"):
            md += "**Intentional Singletons:** " + ", ".join(f"`{x}`" for x in signals["intentional_singletons"]) + "\n"
        if signals.get("planned_forward_refs"):
            md += "\n**Planned Forward References:**\n"
            for x in signals["planned_forward_refs"]:
                md += f"- `{x['from']}` -> `{x['to']}` (Planned)\n"
                
    nav = [
        {"label": "List all ADRs", "uri": "mcp://adr-graph/list", "description": "View list of ADRs"},
        {"label": "Run OKF conformance", "uri": "mcp://adr-graph/okf_conformance", "description": "View OKF standards report"},
    ]
    
    # UI Component Dashboard
    broken_links = res["defects"].get("broken_dead_links", []) or []
    rec_breaks = res["defects"].get("reciprocity_breaks", []) or []
    okf_viols = res["defects"].get("okf_violations", []) or []
    orphans = res["defects"].get("orphan_suspects", []) or []
    dark_nodes = res["defects"].get("dark_nodes", []) or []
    cross_bleeds = res["defects"].get("cross_repo_bleeds", []) or []
    
    total_defects = len(broken_links) + len(rec_breaks) + len(okf_viols) + len(orphans) + len(dark_nodes) + len(cross_bleeds)
    
    with PrefabApp(title="ADR Validation Dashboard") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading("ADR Graph Validation", level=2)
            with c.Row(gap=4):
                c.Metric(label="Total ADRs", value=str(res["meta"]["adrs"]))
                c.Metric(label="Total Edges", value=str(res["meta"]["edges"]))
                c.Metric(label="Connected Nodes", value=str(res["meta"]["connected"]))
            with c.Row(gap=4):
                c.Metric(label="Intentional Frontier", value=str(res["meta"]["intentional_frontier"]))
                c.Metric(label="Completeness", value=f"{res['meta']['completeness_pct']}%")
                c.Metric(label="Active Defects", value=str(total_defects), variant="error" if total_defects > 0 else "success")
            
            c.Separator()
            
            if total_defects > 0:
                c.Heading("⚠️ Active Defects", level=3)
                with c.Tabs(default_value="broken" if broken_links else "okf"):
                    if broken_links:
                        with c.Tab(value="broken", title=f"Broken Links ({len(broken_links)})"):
                            c.DataTable(
                                columns=[
                                    c.DataTableColumn(key="from", header="From ADR", sortable=True),
                                    c.DataTableColumn(key="to", header="Unresolved Ref", sortable=True),
                                    c.DataTableColumn(key="action", header="Actions"),
                                ],
                                rows=[
                                    {
                                        "from": b["from"],
                                        "to": b["to"],
                                        "action": c.Button("Fix", on_click=CallTool("remediate_dead_links", arguments={"dry_run": False}))
                                    } for b in broken_links
                                ]
                            )
                    if okf_viols:
                        with c.Tab(value="okf", title=f"OKF Violations ({len(okf_viols)})"):
                            c.DataTable(
                                columns=[
                                    c.DataTableColumn(key="adr", header="ADR", sortable=True),
                                    c.DataTableColumn(key="detail", header="Violation Details"),
                                ],
                                rows=okf_viols
                            )
                    if rec_breaks:
                        with c.Tab(value="reciprocity", title=f"Reciprocity ({len(rec_breaks)})"):
                            c.DataTable(
                                columns=[
                                    c.DataTableColumn(key="a", header="ADR A", sortable=True),
                                    c.DataTableColumn(key="b", header="ADR B", sortable=True),
                                    c.DataTableColumn(key="detail", header="Detail"),
                                ],
                                rows=rec_breaks
                            )
                    if orphans:
                        with c.Tab(value="orphans", title=f"Orphans ({len(orphans)})"):
                            c.DataTable(
                                columns=[
                                    c.DataTableColumn(key="adr", header="Orphan ADR", sortable=True),
                                ],
                                rows=[{"adr": o} for o in orphans]
                            )
                    if dark_nodes:
                        with c.Tab(value="dark_nodes", title=f"Dark Nodes ({len(dark_nodes)})"):
                            c.DataTable(
                                columns=[
                                    c.DataTableColumn(key="adr", header="ADR", sortable=True),
                                    c.DataTableColumn(key="raw_ref", header="Raw Reference"),
                                    c.DataTableColumn(key="intended_id", header="Intended ID"),
                                ],
                                rows=dark_nodes
                            )
            else:
                with c.Card(css_class="bg-emerald-50 border-emerald-200 dark:bg-emerald-950 dark:border-emerald-800"):
                    with c.CardContent():
                        c.Text("🎉 ADR graph has no defects! Everything is clean.", css_class="text-emerald-800 dark:text-emerald-200")
            
            with c.Row(gap=2):
                c.Button("Revalidate", on_click=CallTool("validate"))
                c.Button("Remediate Drift", on_click=CallTool("remediate_drift", arguments={"dry_run": False}))
                c.Button("Remediate Dead Links", on_click=CallTool("remediate_dead_links", arguments={"dry_run": False}))
                
    return render_response(
        title="ADR Graph Validation Report",
        description="Full topology validation report analyzing structural health and OKF compliance.",
        json_ld_type="ValidationReport",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_okf_conformance(res: dict[str, Any]) -> ToolResult:
    status = "✅ Conformant" if res["conformant"] else "❌ Non-conformant"
    md = f"### Conformance Status: {status} ({res['conformance_pct']}% of records comply)\n\n"
    
    md += "#### 📊 Field Coverage Metrics\n"
    md += f"| Field | Coverage |\n| --- | --- |\n"
    for field_name, coverage in res["coverage"].items():
        md += f"| {field_name} | {coverage} |\n"
    md += "\n"
    
    if res["violations"]:
        md += "#### 🚨 Violations\n"
        for v in res["violations"]:
            md += f"- **[{v['adr']}](adr://{v['adr']})**: {v['detail']}\n"
        md += "\n"
        
    if res["warnings"]:
        md += "#### ⚠️ Warnings\n"
        for w in res["warnings"]:
            md += f"- **[{w['adr']}](adr://{w['adr']})**: {w['detail']}\n"
        md += "\n"
        
    nav = [
        {"label": "Run full validation", "uri": "mcp://adr-graph/validate", "description": "Run the full graph validation report"},
    ]
    
    # UI Component Conformance
    violations = res.get("violations", []) or []
    warnings = res.get("warnings", []) or []
    coverage = res.get("coverage", {}) or {}
    
    with PrefabApp(title="OKF Conformance Report") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading("OKF Conformance Report", level=2)
            c.Metric(
                label="Conformance Score", 
                value=f"{res['conformance_pct']}%", 
                variant="success" if res["conformant"] else "warning"
            )
            
            c.Separator()
            
            c.Heading("📊 Field Coverage", level=3)
            c.DataTable(
                columns=[
                    c.DataTableColumn(key="field", header="Field Name"),
                    c.DataTableColumn(key="pct", header="Coverage"),
                ],
                rows=[{"field": k, "pct": v} for k, v in coverage.items()]
            )
            
            if violations or warnings:
                with c.Tabs(default_value="violations" if violations else "warnings"):
                    if violations:
                        with c.Tab(value="violations", title=f"Violations ({len(violations)})"):
                            c.DataTable(
                                columns=[
                                    c.DataTableColumn(key="adr", header="ADR", sortable=True),
                                    c.DataTableColumn(key="detail", header="Violation Details"),
                                ],
                                rows=violations
                            )
                    if warnings:
                        with c.Tab(value="warnings", title=f"Warnings ({len(warnings)})"):
                            c.DataTable(
                                columns=[
                                    c.DataTableColumn(key="adr", header="ADR", sortable=True),
                                    c.DataTableColumn(key="detail", header="Warning Details"),
                                ],
                                rows=warnings
                            )
            else:
                with c.Card(css_class="bg-emerald-50 border-emerald-200 dark:bg-emerald-950 dark:border-emerald-800"):
                    with c.CardContent():
                        c.Text("🎉 Perfect OKF conformance! No violations or warnings found.", css_class="text-emerald-800 dark:text-emerald-200")
            
            with c.Row(gap=2):
                c.Button("Recheck Conformance", on_click=CallTool("okf_conformance"))
                c.Button("Migrate to OKF (Apply)", on_click=CallTool("migrate_okf", arguments={"dry_run": False}))
                
    return render_response(
        title="OKF v0.1 Conformance Report",
        description="Detailed review of ADR metadata adherence to the Open Knowledge Format v0.1 specification.",
        json_ld_type="ConformanceReport",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_singletons(res: dict[str, Any]) -> ToolResult:
    intentional = res.get("intentional_frontier", [])
    suspect = res.get("orphan_suspects", [])
    
    md = ""
    if suspect:
        md += "#### ⚠️ Orphan Suspects (Disconnected nodes without status/tags declaring them standalone)\n"
        for s in suspect:
            md += f"- **[{s}](adr://{s})**\n"
        md += "\n"
    else:
        md += "#### ✅ No Orphan Suspects Found\n\n"
        
    if intentional:
        md += "#### 🟢 Intentional Frontier (Disconnected, but flagged as standalone/seed)\n"
        for i in intentional:
            md += f"- **[{i}](adr://{i})**\n"
            
    nav = []
    if suspect:
        nav.append({"label": f"Read first suspect ({suspect[0]})", "uri": f"mcp://adr-graph/read?adr={suspect[0]}"})
        
    # UI Component Singletons
    with PrefabApp(title="Orphans & Singletons") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading("Orphans & Singletons Analysis", level=2)
            
            with c.Tabs(default_value="suspect" if suspect else "intentional"):
                with c.Tab(value="suspect", title=f"Orphan Suspects ({len(suspect)})"):
                    if suspect:
                        c.DataTable(
                            columns=[
                                c.DataTableColumn(key="adr", header="Orphan ADR ID", sortable=True),
                                c.DataTableColumn(key="action", header="Actions"),
                            ],
                            rows=[
                                {
                                    "adr": s,
                                    "action": c.Button("Read", on_click=CallTool("read", arguments={"adr": s}))
                                } for s in suspect
                            ]
                        )
                    else:
                        c.Text("No suspicious orphans. All disconnected nodes are intentionally marked as standalone/seed.")
                with c.Tab(value="intentional", title=f"Intentional Frontier ({len(intentional)})"):
                    if intentional:
                        c.DataTable(
                            columns=[
                                c.DataTableColumn(key="adr", header="Frontier ADR ID", sortable=True),
                                c.DataTableColumn(key="action", header="Actions"),
                            ],
                            rows=[
                                {
                                    "adr": i,
                                    "action": c.Button("Read", on_click=CallTool("read", arguments={"adr": i}))
                                } for i in intentional
                            ]
                        )
                    else:
                        c.Text("No intentional frontiers.")
                        
    return render_response(
        title="Orphans & Singletons Analysis",
        description="Report identifying disconnected nodes split into intentional standalone vs suspicious orphans.",
        json_ld_type="ItemList",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_dead_links(res: dict[str, Any]) -> ToolResult:
    planned = res.get("planned_forward_refs", [])
    broken = res.get("broken_dead_links", [])
    
    md = ""
    if broken:
        md += "#### ❌ Broken Dead Links\n"
        for b in broken:
            md += f"- **[{b['from']}](adr://{b['from']})** references non-existent `{b['to']}`\n"
        md += "\n"
    else:
        md += "#### ✅ No Broken Dead Links Found\n\n"
        
    if planned:
        md += "#### 🟢 Planned Forward References (Declared unresolved links)\n"
        for p in planned:
            md += f"- **[{p['from']}](adr://{p['from']})** -> `{p['to']}` (Planned)\n"
            
    nav = []
    if broken:
        nav.append({"label": "Remediate Dead Links (Dry Run)", "uri": "mcp://adr-graph/remediate_dead_links?dry_run=true"})
        nav.append({"label": "Remediate Dead Links (APPLY)", "uri": "mcp://adr-graph/remediate_dead_links?dry_run=false"})
        
    # UI Component Dead Links
    with PrefabApp(title="Dead Link Analysis") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading("Dead Link Analysis", level=2)
            
            with c.Tabs(default_value="broken" if broken else "planned"):
                with c.Tab(value="broken", title=f"Broken Dead Links ({len(broken)})"):
                    if broken:
                        c.DataTable(
                            columns=[
                                c.DataTableColumn(key="from", header="Source ADR", sortable=True),
                                c.DataTableColumn(key="to", header="Missing Target", sortable=True),
                                c.DataTableColumn(key="action", header="Actions"),
                            ],
                            rows=[
                                {
                                    "from": b["from"],
                                    "to": b["to"],
                                    "action": c.Button("Remediate", on_click=CallTool("remediate_dead_links", arguments={"dry_run": False}))
                                } for b in broken
                            ]
                        )
                    else:
                        c.Text("No broken dead links found!")
                with c.Tab(value="planned", title=f"Planned Forward Refs ({len(planned)})"):
                    if planned:
                        c.DataTable(
                            columns=[
                                c.DataTableColumn(key="from", header="Source ADR", sortable=True),
                                c.DataTableColumn(key="to", header="Planned Target", sortable=True),
                            ],
                            rows=planned
                        )
                    else:
                        c.Text("No planned forward references.")
                        
    return render_response(
        title="Dead Link Analysis",
        description="Report on broken links and planned forward references within the graph.",
        json_ld_type="ItemList",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_reciprocity(res: dict[str, Any]) -> ToolResult:
    breaks = res.get("reciprocity_breaks", [])
    
    md = ""
    if breaks:
        md += "#### ❌ Reciprocity Breaks (Missing backlink matches)\n"
        for b in breaks:
            md += f"- **[{b['a']}](adr://{b['a']})** and **[{b['b']}](adr://{b['b']})**: {b['detail']}\n"
    else:
        md += "#### ✅ All Relationship Edges are Reciprocal\n"
        
    # UI Component Reciprocity
    with PrefabApp(title="Reciprocity Checker") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading("Reciprocity Checker", level=2)
            
            if breaks:
                c.DataTable(
                    columns=[
                        c.DataTableColumn(key="a", header="ADR A", sortable=True),
                        c.DataTableColumn(key="b", header="ADR B", sortable=True),
                        c.DataTableColumn(key="detail", header="Detail"),
                    ],
                    rows=breaks
                )
            else:
                with c.Card(css_class="bg-emerald-50 border-emerald-200 dark:bg-emerald-950 dark:border-emerald-800"):
                    with c.CardContent():
                        c.Text("🎉 All relationships are reciprocal (every supersedes edge has a matching superseded_by).", css_class="text-emerald-800 dark:text-emerald-200")
                        
    return render_response(
        title="Reciprocity Check",
        description="Verifies that superseded and supersedes relationships are properly mirrored on both nodes.",
        json_ld_type="ItemList",
        json_ld_data=res,
        markdown_body=md,
        structured_content=app
    )

def format_neighbors(res: dict[str, Any]) -> ToolResult:
    adr = res.get("adr", "")
    title = res.get("title", "")
    depth = res.get("depth", 1)
    outbound = res.get("outbound", [])
    inbound = res.get("inbound", [])
    reached = res.get("reached", [])
    
    md = f"### Neighbors for [{adr}](adr://{adr}) (Depth: {depth})\n\n"
    md += f"**Title:** {title}\n\n"
    
    if outbound:
        md += "➡️ **Outbound References:** " + ", ".join(f"[{x}](adr://{x})" for x in outbound) + "\n"
    else:
        md += "➡️ **Outbound References:** None\n"
        
    if inbound:
        md += "⬅️ **Inbound References:** " + ", ".join(f"[{x}](adr://{x})" for x in inbound) + "\n"
    else:
        md += "⬅️ **Inbound References:** None\n"
        
    if reached:
        md += f"\n🌐 **Transitively Reached Nodes (at depth <= {depth}):** " + ", ".join(f"[{x}](adr://{x})" for x in reached) + "\n"
        
    nav = []
    for x in outbound + inbound:
        nav.append({"label": f"Read neighboring {x}", "uri": f"mcp://adr-graph/read?adr={x}"})
        
    # UI Neighborhood Mermaid diagram + stats
    mermaid_lines = ["graph LR"]
    mermaid_lines.append(f'  style {adr} fill:#f59e0b,stroke:#d97706,stroke-width:4px')
    mermaid_lines.append(f'  {adr}["{adr}: {title[:20]}..."]')
    
    for node in outbound:
        mermaid_lines.append(f'  {node}["{node}"]')
        mermaid_lines.append(f'  {adr} --> {node}')
        
    for node in inbound:
        mermaid_lines.append(f'  {node}["{node}"]')
        mermaid_lines.append(f'  {node} --> {adr}')
        
    mermaid_chart = "\n".join(mermaid_lines)
    
    with PrefabApp(title=f"Neighbors of {adr}") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading(f"Neighbors for {adr}", level=2)
            c.Text(f"**Title:** {title}", css_class="text-lg font-medium")
            
            c.Separator()
            
            c.Heading("Local Neighborhood Map", level=3)
            c.Mermaid(chart=mermaid_chart)
            
            c.Separator()
            
            with c.Tabs(default_value="outbound"):
                with c.Tab(value="outbound", title=f"Outbound References ({len(outbound)})"):
                    if outbound:
                        c.DataTable(
                            columns=[
                                c.DataTableColumn(key="adr", header="Target ADR", sortable=True),
                                c.DataTableColumn(key="action", header="Actions"),
                            ],
                            rows=[
                                {"adr": x, "action": c.Button("Read", on_click=CallTool("read", arguments={"adr": x}))}
                                for x in outbound
                            ]
                        )
                    else:
                        c.Text("No outbound references from this ADR.")
                with c.Tab(value="inbound", title=f"Inbound References ({len(inbound)})"):
                    if inbound:
                        c.DataTable(
                            columns=[
                                c.DataTableColumn(key="adr", header="Source ADR", sortable=True),
                                c.DataTableColumn(key="action", header="Actions"),
                            ],
                            rows=[
                                {"adr": x, "action": c.Button("Read", on_click=CallTool("read", arguments={"adr": x}))}
                                for x in inbound
                            ]
                        )
                    else:
                        c.Text("No inbound references to this ADR.")
                        
    return render_response(
        title=f"Neighbors of {adr}",
        description=f"Adjacency list neighborhood for {adr} up to depth {depth}.",
        json_ld_type="AdjacencyGraph",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_read(adr_data: dict[str, Any], nav_section: str) -> ToolResult:
    tags_str = ", ".join(adr_data['tags']) if adr_data['tags'] else "None"
    md = f"""### Metadata
- **Status:** `{adr_data['status']}`
- **Date:** `{adr_data['timestamp']}`
- **Tags:** `{tags_str}`
- **Resource URI:** `{adr_data['resource'] or f'adr://{adr_data["id"]}'}`

### 📖 Description
{adr_data['description'] or "*No description available.*"}

---

### 📝 Content
{adr_data['body']}

---

### 🧭 Graph Topology & Neighborhood
{nav_section}
"""
    
    nav = []
    for ref in adr_data.get("metadata", {}).get("related", []):
        ref_id = f"ADR-{ref}" if str(ref).isdigit() else str(ref)
        nav.append({"label": f"Read Related {ref_id}", "uri": f"mcp://adr-graph/read?adr={ref_id}"})
        
    # UI Component Read ADR
    adr_id = adr_data["id"]
    title = adr_data["title"]
    status = adr_data["status"]
    tags = adr_data["tags"] or []
    body = adr_data["body"]
    
    metadata = adr_data.get("metadata", {}) or {}
    supersedes = metadata.get("supersedes", []) or []
    superseded_by = metadata.get("superseded_by", []) or []
    related = metadata.get("related", []) or []
    
    status_variant = "secondary"
    if status == "accepted":
        status_variant = "success"
    elif status in ("deprecated", "superseded"):
        status_variant = "destructive"
    elif status == "proposed":
        status_variant = "warning"
        
    with PrefabApp(title=f"Read {adr_id}") as app:
        with c.Column(gap=4, css_class="p-6"):
            with c.Row(gap=4, align="center"):
                c.Heading(f"{adr_id}: {title}", level=2)
                c.Badge(status, variant=status_variant)
                
            with c.Row(gap=2):
                c.Text(f"Date: {adr_data['timestamp']}", css_class="text-sm text-muted-foreground")
                c.Text(f"Tags: {', '.join(tags) or 'None'}", css_class="text-sm text-muted-foreground")
            
            c.Separator()
            
            with c.Row(gap=6):
                with c.Column(gap=4, css_class="w-2/3"):
                    c.Heading("📖 Decision Record Content", level=3)
                    c.Markdown(content=body)
                    
                with c.Column(gap=4, css_class="w-1/3"):
                    c.Heading("🧭 Navigation & Actions", level=3)
                    
                    with c.Card():
                        with c.CardHeader():
                            c.CardTitle("Lifecycle Actions")
                        with c.CardContent():
                            with c.Row(gap=2):
                                c.Button("Accept", on_click=CallTool("set_status", arguments={"adr": adr_id, "status": "accepted"}))
                                c.Button("Deprecate", on_click=CallTool("set_status", arguments={"adr": adr_id, "status": "deprecated"}))
                                
                    if supersedes or superseded_by or related:
                        with c.Card():
                            with c.CardHeader():
                                c.CardTitle("Relations")
                            with c.CardContent():
                                with c.Column(gap=2):
                                    for s in supersedes:
                                        sid = f"ADR-{s}" if str(s).isdigit() else str(s)
                                        c.Button(f"Supersedes {sid}", on_click=CallTool("read", arguments={"adr": sid}))
                                    for s in superseded_by:
                                        sid = f"ADR-{s}" if str(s).isdigit() else str(s)
                                        c.Button(f"Superseded By {sid}", on_click=CallTool("read", arguments={"adr": sid}))
                                    for r in related:
                                        rid = f"ADR-{r}" if str(r).isdigit() else str(r)
                                        c.Button(f"Related {rid}", on_click=CallTool("read", arguments={"adr": rid}))
                    
                    with c.Row(gap=2):
                        c.Button("Neighborhood Map", on_click=CallTool("neighbors", arguments={"adr": adr_id}))
                        c.Button("Blast Radius", on_click=CallTool("blast_radius", arguments={"adr": adr_id}))
                        
    return render_response(
        title=f"{adr_data['id']}: {adr_data['title']}",
        description="Architectural Decision Record details and relationships.",
        json_ld_type="TechArticle",
        json_ld_data=adr_data,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_list(adrs: list[dict[str, Any]], query_info: str = "") -> ToolResult:
    md = f"Found {len(adrs)} ADR(s){f' matching {query_info}' if query_info else ''}.\n\n"
    if adrs:
        md += "| ID | Title | Status | Date | Tags |\n| --- | --- | --- | --- | --- |\n"
        for a in adrs:
            tags = ", ".join(a.get("tags", [])) if a.get("tags") else "None"
            md += f"| [{a['id']}](adr://{a['id']}) | {a['title']} | `{a['status']}` | `{a['timestamp']}` | `{tags}` |\n"
    else:
        md += "*No ADRs found.*\n"
        
    nav = []
    if adrs:
        first_id = adrs[0]['id']
        nav.append({"label": f"Read {first_id}", "uri": f"mcp://adr-graph/read?adr={first_id}"})
        
    # UI Component List
    with PrefabApp(title="ADR Directory") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading("ADR Directory", level=2)
            if query_info:
                c.Text(f"Filters: {query_info}", css_class="text-muted-foreground mb-2")
                
            c.DataTable(
                columns=[
                    c.DataTableColumn(key="id", header="ID", sortable=True),
                    c.DataTableColumn(key="title", header="Title", sortable=True),
                    c.DataTableColumn(key="status", header="Status", sortable=True),
                    c.DataTableColumn(key="timestamp", header="Date", sortable=True),
                    c.DataTableColumn(key="action", header="Actions"),
                ],
                rows=[
                    {
                        "id": a["id"],
                        "title": a["title"],
                        "status": c.Badge(
                            a["status"], 
                            variant="success" if a["status"] == "accepted" 
                            else "warning" if a["status"] == "proposed" 
                            else "destructive" if a["status"] in ("deprecated", "superseded") 
                            else "secondary"
                        ),
                        "timestamp": a["timestamp"],
                        "action": c.Button("Read", on_click=CallTool("read", arguments={"adr": a["id"]}))
                    }
                    for a in adrs
                ],
                search=True
            )
            
            with c.Row(gap=2):
                c.Button("Propose New ADR", on_click=CallTool("propose_adr"))
                
    return render_response(
        title="ADR List",
        description="Index list of all architectural decision records in the corpus.",
        json_ld_type="ItemList",
        json_ld_data=adrs,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_search(adrs: list[dict[str, Any]], query: str) -> ToolResult:
    md = f"Search query: `{query}`\n"
    md += f"Found {len(adrs)} matching ADR(s).\n\n"
    if adrs:
        md += "| ID | Title | Status | Date | Tags |\n| --- | --- | --- | --- | --- |\n"
        for a in adrs:
            tags = ", ".join(a.get("tags", [])) if a.get("tags") else "None"
            md += f"| [{a['id']}](adr://{a['id']}) | {a['title']} | `{a['status']}` | `{a['timestamp']}` | `{tags}` |\n"
    else:
        md += "*No matching ADRs found.*\n"
        
    nav = []
    if adrs:
        first_id = adrs[0]['id']
        nav.append({"label": f"Read {first_id}", "uri": f"mcp://adr-graph/read?adr={first_id}"})
        
    # UI Component Search Results
    with PrefabApp(title=f"Search: {query}") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading(f"Search Results for '{query}'", level=2)
            
            c.DataTable(
                columns=[
                    c.DataTableColumn(key="id", header="ID", sortable=True),
                    c.DataTableColumn(key="title", header="Title", sortable=True),
                    c.DataTableColumn(key="status", header="Status", sortable=True),
                    c.DataTableColumn(key="action", header="Actions"),
                ],
                rows=[
                    {
                        "id": a["id"],
                        "title": a["title"],
                        "status": c.Badge(
                            a["status"], 
                            variant="success" if a["status"] == "accepted" 
                            else "warning" if a["status"] == "proposed" 
                            else "destructive"
                        ),
                        "action": c.Button("Read", on_click=CallTool("read", arguments={"adr": a["id"]}))
                    }
                    for a in adrs
                ],
                search=True
            )
            
    return render_response(
        title=f"Search Results for '{query}'",
        description="Filtered list of ADRs matching the search substring.",
        json_ld_type="ItemList",
        json_ld_data=adrs,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_path(res: dict[str, Any], from_adr: str, to_adr: str) -> ToolResult:
    path_nodes = res.get("path", [])
    
    md = f"### Path search from **{from_adr}** to **{to_adr}**\n\n"
    if path_nodes is None:
        md += "❌ **No path found** between these two ADRs in the link topology.\n"
    elif not path_nodes:
        md += "❌ **Invalid path query** (one of the ADRs was not found).\n"
    else:
        md += "✅ **Shortest Path Found:**\n\n"
        md += " -> ".join(f"**[{node}](adr://{node})**" for node in path_nodes) + "\n"
        
    nav = []
    if path_nodes:
        for node in path_nodes:
            nav.append({"label": f"Read {node}", "uri": f"mcp://adr-graph/read?adr={node}"})
            
    # UI Component Path
    with PrefabApp(title=f"Path Search: {from_adr} -> {to_adr}") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading(f"Path search from {from_adr} to {to_adr}", level=2)
            
            if not path_nodes:
                with c.Card(css_class="bg-red-50 border-red-200 dark:bg-red-950 dark:border-red-800"):
                    with c.CardContent():
                        c.Text("❌ No path found between these ADRs in the graph.", css_class="text-red-800 dark:text-red-200")
            else:
                c.Heading("✅ Shortest Connection Route Found", level=3)
                
                with c.Row(gap=2, align="center"):
                    for idx, node in enumerate(path_nodes):
                        if idx > 0:
                            c.Text("➔", css_class="text-xl text-muted-foreground font-bold")
                        c.Button(node, on_click=CallTool("read", arguments={"adr": node}))
                        
    return render_response(
        title="BFS Shortest Path Report",
        description=f"Traversal path between {from_adr} and {to_adr}.",
        json_ld_type="ConnectionPath",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_drift(res: list[dict[str, Any]]) -> ToolResult:
    md = ""
    if res:
        md += "#### ⚠️ Drift Detected in Nodes\n"
        md += "| ADR | Missing in Body (only YAML) | Missing in YAML (only Body) |\n| --- | --- | --- |\n"
        for item in res:
            yaml_only = ", ".join(f"`{x}`" for x in item["in_yaml_not_body"]) if item["in_yaml_not_body"] else "-"
            body_only = ", ".join(f"`{x}`" for x in item["in_body_not_yaml"]) if item["in_body_not_yaml"] else "-"
            md += f"| **[{item['adr']}](adr://{item['adr']})** | {yaml_only} | {body_only} |\n"
    else:
        md += "#### ✅ No Drift Detected\n\nAll nodes have matching frontmatter and body links."
        
    nav = [
        {"label": "Remediate Drift (Dry Run)", "uri": "mcp://adr-graph/remediate_drift?dry_run=true"},
        {"label": "Remediate Drift (APPLY)", "uri": "mcp://adr-graph/remediate_drift?dry_run=false"},
    ]
    
    # UI Component Drift
    with PrefabApp(title="Drift Analysis") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading("Drift Analysis", level=2)
            
            if res:
                c.DataTable(
                    columns=[
                        c.DataTableColumn(key="adr", header="ADR", sortable=True),
                        c.DataTableColumn(key="yaml_only", header="Only in YAML"),
                        c.DataTableColumn(key="body_only", header="Only in Body"),
                        c.DataTableColumn(key="action", header="Actions"),
                    ],
                    rows=[
                        {
                            "adr": item["adr"],
                            "yaml_only": ", ".join(f"`{x}`" for x in item["in_yaml_not_body"]) or "-",
                            "body_only": ", ".join(f"`{x}`" for x in item["in_body_not_yaml"]) or "-",
                            "action": c.Button("Sync", on_click=CallTool("remediate_drift", arguments={"dry_run": False}))
                        }
                        for item in res
                    ]
                )
            else:
                with c.Card(css_class="bg-emerald-50 border-emerald-200 dark:bg-emerald-950 dark:border-emerald-800"):
                    with c.CardContent():
                        c.Text("🎉 No drift detected! Frontmatter and body links match perfectly.", css_class="text-emerald-800 dark:text-emerald-200")
                        
    return render_response(
        title="Link-Frontmatter Drift Analysis",
        description="Identifies misalignment between YAML frontmatter references and markdown body links.",
        json_ld_type="ItemList",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_blast_radius(res: dict[str, Any]) -> ToolResult:
    adr = res.get("adr", "")
    radius = res.get("blast_radius", [])
    count = res.get("count", 0)
    
    md = f"### Blast Radius for [{adr}](adr://{adr})\n\n"
    md += f"**Transitive Downstream Dependents Count:** `{count}`\n\n"
    
    if radius:
        md += "💥 **Affected ADRs:**\n"
        for r in radius:
            md += f"- **[{r}](adr://{r})** (Transitively depends on this ADR)\n"
    else:
        md += "✅ **No downstream dependents affected** if this decision changes.\n"
        
    nav = []
    if radius:
        nav.append({"label": f"Read first affected ({radius[0]})", "uri": f"mcp://adr-graph/read?adr={radius[0]}"})
        
    # UI Component Blast Radius
    with PrefabApp(title=f"Blast Radius: {adr}") as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading(f"Blast Radius for {adr}", level=2)
            c.Metric(label="Affected Downstream ADRs", value=str(count), variant="error" if count > 0 else "success")
            
            c.Separator()
            
            if radius:
                c.DataTable(
                    columns=[
                        c.DataTableColumn(key="adr", header="Dependent ADR ID", sortable=True),
                        c.DataTableColumn(key="action", header="Actions"),
                    ],
                    rows=[
                        {"adr": r, "action": c.Button("Read", on_click=CallTool("read", arguments={"adr": r}))}
                        for r in radius
                    ]
                )
            else:
                with c.Card(css_class="bg-emerald-50 border-emerald-200 dark:bg-emerald-950 dark:border-emerald-800"):
                    with c.CardContent():
                        c.Text("🎉 Changing this decision has no downstream impacts on other records.", css_class="text-emerald-800 dark:text-emerald-200")
                        
    return render_response(
        title=f"Blast Radius of {adr}",
        description=f"Identifies downstream ADRs that transitively depend on the chosen decision.",
        json_ld_type="BlastRadiusReport",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )

def format_mutation(res: dict[str, Any], title: str, description: str) -> ToolResult:
    ok = res.get("ok", False)
    changed = res.get("changed", [])
    error = res.get("error", "")
    applied = res.get("applied", None)
    proposals = res.get("proposals", None)
    dry_run = res.get("dry_run", None)
    changes = res.get("changes", None)
    
    status_emoji = "✅" if ok else "❌"
    md = f"### Status: {status_emoji} {'Operation Succeeded' if ok else 'Operation Failed'}\n\n"
    
    if error:
        md += f"**Error:** `{error}`\n\n"
        
    if dry_run is not None:
        md += f"**Mode:** {'Dry Run (no changes made)' if dry_run else 'APPLY (changes written)'}\n\n"
        
    if changed:
        md += "**Changes Made:**\n"
        if isinstance(changed, list):
            for c_val in changed:
                md += f"- {c_val}\n"
        else:
            md += f"- {changed}\n"
            
    if changes:
        md += "**Changes Made:**\n"
        for c_val in changes:
            md += f"- {c_val}\n"
            
    if applied is not None:
        md += f"**Applied:** `{applied}`\n\n"
        
    if proposals:
        md += "**Proposals Details:**\n"
        for p in proposals:
            md += f"- **[{p['adr']}](adr://{p['adr']})**: Add `related` links to {p['add_to_related']}\n"
            
    nav = [
        {"label": "Run Graph Validation", "uri": "mcp://adr-graph/validate", "description": "Validate the graph to verify changes"},
    ]
    
    # UI Component Mutation
    with PrefabApp(title=title) as app:
        with c.Column(gap=4, css_class="p-6"):
            c.Heading(title, level=2)
            c.Text(description, css_class="text-muted-foreground mb-4")
            
            if ok:
                with c.Card(css_class="bg-emerald-50 border-emerald-200 dark:bg-emerald-950 dark:border-emerald-800"):
                    with c.CardContent():
                        c.Text("🎉 Operation succeeded!", css_class="text-emerald-800 dark:text-emerald-200")
            else:
                with c.Card(css_class="bg-red-50 border-red-200 dark:bg-red-950 dark:border-red-800"):
                    with c.CardContent():
                        c.Text(f"❌ Operation failed. {error or 'Unknown error.'}", css_class="text-red-800 dark:text-red-200")
            
            # Map changes list
            all_changes = []
            if isinstance(changed, list):
                all_changes.extend(changed)
            elif changed:
                all_changes.append(changed)
            if changes:
                all_changes.extend(changes)
                
            if all_changes:
                c.Heading("Changes Applied:", level=3)
                c.DataTable(
                    columns=[
                        c.DataTableColumn(key="change", header="File / Operation"),
                    ],
                    rows=[{"change": str(ch)} for ch in all_changes]
                )
                
            with c.Row(gap=2):
                c.Button("Run Validation", on_click=CallTool("validate"))
                
    return render_response(
        title=title,
        description=description,
        json_ld_type="UpdateAction",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav,
        structured_content=app
    )
