"""Helper to render MCP tool responses as rich Markdown containing embedded JSON-LD and self-navigable links."""

from __future__ import annotations

import json
from typing import Any

def render_response(
    *,
    title: str,
    description: str,
    json_ld_type: str,
    json_ld_data: dict[str, Any] | list[Any],
    markdown_body: str,
    navigation_links: list[dict[str, str]] | None = None,
) -> str:
    """Renders a tool response as JSON-LD embedded in Markdown.
    
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
                
    return f"""# {title}

> {description}

```jsonld
{json_ld_str}
```

## 📊 Details
{markdown_body}
{nav_section}"""
