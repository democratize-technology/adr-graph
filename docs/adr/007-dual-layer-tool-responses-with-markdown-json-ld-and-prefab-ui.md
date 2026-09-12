---
id: ADR-7
type: adr
title: Dual-Layer Tool Responses with Markdown, JSON-LD, and Prefab UI
description: Return composite MCP tool results containing human-readable Markdown with actionable tool links, machine-readable JSON-LD metadata resources, and interactive Prefab UI components.
status: accepted
aliases:
  - ADR-7
  - ADR-007
tags:
  - architecture
  - mcp
  - ui
  - json-ld
code_paths:
  - src/adr_graph/markdown_ld_renderer.py
  - src/adr_graph/formatters.py
  - src/adr_graph/server.py
timestamp: '2026-09-12T04:33:31+00:00'
related:
  - ADR-1
  - ADR-2
---

# 7. Dual-Layer Tool Responses with Markdown, JSON-LD, and Prefab UI

## Context and Problem Statement
When an agent or developer invokes an MCP tool, plain text or raw JSON forces a compromise: plain text is difficult for downstream systems to parse reliably, while raw JSON is cumbersome for humans and conversational LLMs to inspect. Furthermore, rich client interfaces (like Antigravity and Claude Desktop) support interactive buttons and tables.

## Decision Drivers
* Humans and LLMs need high-signal, self-navigable Markdown with executable action links (`mcp://adr-graph/...`).
* External tooling and automated graph verifiers need typed Schema.org JSON-LD data payloads.
* Interactive UI clients benefit from declarative Prefab UI component rendering.

## Considered Options
* Return raw JSON only.
* Return plain Markdown only.
* Return composite `ToolResult` containing `TextContent` (Markdown), `EmbeddedResource` (JSON-LD), and `structured_content` (Prefab UI).

## Decision Outcome
Chosen option: Composite dual-layer ToolResult.

Every query tool in [[ADR-2]] renders:
1. Formatted Markdown with navigation links.
2. An embedded `application/ld+json` resource adhering to Schema.org types (`ItemList`, `TechArticle`, `Report`).
3. An interactive Prefab UI component for desktop rendering, fully conforming to [[ADR-1]].
