"""Formatters to convert raw ADR tool outputs into JSON-LD embedded Markdown."""

from __future__ import annotations

from typing import Any
from .markdown_ld_renderer import render_response

def format_validate(res: dict[str, Any]) -> str:
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
    
    return render_response(
        title="ADR Graph Validation Report",
        description="Full topology validation report analyzing structural health and OKF compliance.",
        json_ld_type="ValidationReport",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav
    )

def format_okf_conformance(res: dict[str, Any]) -> str:
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
    
    return render_response(
        title="OKF v0.1 Conformance Report",
        description="Detailed review of ADR metadata adherence to the Open Knowledge Format v0.1 specification.",
        json_ld_type="ConformanceReport",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav
    )

def format_singletons(res: dict[str, Any]) -> str:
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
        
    return render_response(
        title="Orphans & Singletons Analysis",
        description="Report identifying disconnected nodes split into intentional standalone vs suspicious orphans.",
        json_ld_type="ItemList",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav
    )

def format_dead_links(res: dict[str, Any]) -> str:
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
        
    return render_response(
        title="Dead Link Analysis",
        description="Report on broken links and planned forward references within the graph.",
        json_ld_type="ItemList",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav
    )

def format_reciprocity(res: dict[str, Any]) -> str:
    breaks = res.get("reciprocity_breaks", [])
    
    md = ""
    if breaks:
        md += "#### ❌ Reciprocity Breaks (Missing backlink matches)\n"
        for b in breaks:
            md += f"- **[{b['a']}](adr://{b['a']})** and **[{b['b']}](adr://{b['b']})**: {b['detail']}\n"
    else:
        md += "#### ✅ All Relationship Edges are Reciprocal\n"
        
    return render_response(
        title="Reciprocity Check",
        description="Verifies that superseded and supersedes relationships are properly mirrored on both nodes.",
        json_ld_type="ItemList",
        json_ld_data=res,
        markdown_body=md,
    )

def format_neighbors(res: dict[str, Any]) -> str:
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
        
    return render_response(
        title=f"Neighbors of {adr}",
        description=f"Adjacency list neighborhood for {adr} up to depth {depth}.",
        json_ld_type="AdjacencyGraph",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav
    )

def format_read(adr_data: dict[str, Any], nav_section: str) -> str:
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
    # If there are related references, suggest reading them
    for ref in adr_data.get("metadata", {}).get("related", []):
        ref_id = f"ADR-{ref}" if str(ref).isdigit() else str(ref)
        nav.append({"label": f"Read Related {ref_id}", "uri": f"mcp://adr-graph/read?adr={ref_id}"})
        
    return render_response(
        title=f"{adr_data['id']}: {adr_data['title']}",
        description="Architectural Decision Record details and relationships.",
        json_ld_type="TechArticle",
        json_ld_data=adr_data,
        markdown_body=md,
        navigation_links=nav
    )

def format_list(adrs: list[dict[str, Any]], query_info: str = "") -> str:
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
        
    return render_response(
        title="ADR List",
        description="Index list of all architectural decision records in the corpus.",
        json_ld_type="ItemList",
        json_ld_data=adrs,
        markdown_body=md,
        navigation_links=nav
    )

def format_search(adrs: list[dict[str, Any]], query: str) -> str:
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
        
    return render_response(
        title=f"Search Results for '{query}'",
        description="Filtered list of ADRs matching the search substring.",
        json_ld_type="ItemList",
        json_ld_data=adrs,
        markdown_body=md,
        navigation_links=nav
    )

def format_path(res: dict[str, Any], from_adr: str, to_adr: str) -> str:
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
            
    return render_response(
        title="BFS Shortest Path Report",
        description=f"Traversal path between {from_adr} and {to_adr}.",
        json_ld_type="ConnectionPath",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav
    )

def format_drift(res: list[dict[str, Any]]) -> str:
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
    
    return render_response(
        title="Link-Frontmatter Drift Analysis",
        description="Identifies misalignment between YAML frontmatter references and markdown body links.",
        json_ld_type="ItemList",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav
    )

def format_blast_radius(res: dict[str, Any]) -> str:
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
        
    return render_response(
        title=f"Blast Radius of {adr}",
        description=f"Identifies downstream ADRs that transitively depend on the chosen decision.",
        json_ld_type="BlastRadiusReport",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav
    )

def format_mutation(res: dict[str, Any], title: str, description: str) -> str:
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
            for c in changed:
                md += f"- {c}\n"
        else:
            md += f"- {changed}\n"
            
    if changes:
        md += "**Changes Made:**\n"
        for c in changes:
            md += f"- {c}\n"
            
    if applied is not None:
        md += f"**Applied:** `{applied}`\n\n"
        
    if proposals:
        md += "**Proposals Details:**\n"
        for p in proposals:
            md += f"- **[{p['adr']}](adr://{p['adr']})**: Add `related` links to {p['add_to_related']}\n"
            
    nav = [
        {"label": "Run Graph Validation", "uri": "mcp://adr-graph/validate", "description": "Validate the graph to verify changes"},
    ]
    
    return render_response(
        title=title,
        description=description,
        json_ld_type="UpdateAction",
        json_ld_data=res,
        markdown_body=md,
        navigation_links=nav
    )
