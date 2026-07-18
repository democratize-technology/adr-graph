"""Helper to render MCP tool responses as rich Markdown with structured JSON-LD separated into tool content blocks."""

from __future__ import annotations

import json
from typing import Any
from mcp.types import TextContent, EmbeddedResource, TextResourceContents
from fastmcp.tools.base import ToolResult

def render_response(
    *,
    title: str,
    description: str,
    json_ld_type: str,
    json_ld_data: dict[str, Any] | list[Any],
    markdown_body: str,
    navigation_links: list[dict[str, str]] | None = None,
) -> ToolResult:
    """Renders a tool response separating human-readable Markdown from machine-readable JSON-LD.
    
    Args:
        title: The display title of the report/tool output.
        description: Brief description of the result.
        json_ld_type: The Schema.org / custom type for the JSON-LD payload (e.g. "Report", "ItemList", "TechArticle").
        json_ld_data: The structured Python dictionary/list to encode as JSON-LD.
        markdown_body: The main human-readable representation of the data.
        navigation_links: List of dictionaries with 'label' and 'uri' (or command tip) for self-navigation.
    """
    # Build standard JSON-LD wrapper
    json_ld = {
        "@context": "https://schema.org",
        "@type": json_ld_type,
        "name": title,
        "description": description,
        "mainEntity": json_ld_data,
    }
    
    json_ld_str = json.dumps(json_ld, indent=2)
    
    # Build navigation section
    nav_section = ""
    if navigation_links:
        nav_section = "\n## 🧭 Navigation & Actions\n"
        for link in navigation_links:
            label = link.get("label", "Action")
            uri = link.get("uri", "")
            desc = link.get("description", "")
            if desc:
                nav_section += f"- **[{label}]({uri})** - {desc}\n"
            else:
                nav_section += f"- **[{label}]({uri})**\n"
                
    markdown_text = f"""# {title}

> {description}

## 📊 Details
{markdown_body}
{nav_section}"""

    # We return a ToolResult with the Markdown as a TextContent,
    # and the JSON-LD as a separate EmbeddedResource.
    return ToolResult(
        content=[
            TextContent(type="text", text=markdown_text),
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri=f"metadata://adr-graph/{json_ld_type.lower()}",
                    mimeType="application/ld+json",
                    text=json_ld_str
                )
            )
        ]
    )
