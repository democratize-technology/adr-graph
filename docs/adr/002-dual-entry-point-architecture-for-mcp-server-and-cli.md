---
id: ADR-2
type: adr
title: Dual Entry Point Architecture for MCP Server and CLI
description: Maintain a single binary and codebase where adr-graph functions as an interactive FastMCP server over stdio when invoked without arguments, and as a CLI with non-zero exit codes for CI gates when invoked with subcommands.
status: accepted
aliases:
  - ADR-2
  - ADR-002
tags:
  - architecture
  - cli
  - mcp
code_paths:
  - src/adr_graph/__main__.py
  - src/adr_graph/server.py
timestamp: '2026-09-12T04:33:18+00:00'
related:
  - ADR-1
  - ADR-3
  - ADR-7
---

# 2. Dual Entry Point Architecture for MCP Server and CLI

## Context and Problem Statement
Tools designed solely for human terminal use fail to integrate with agentic workflows, while tools designed solely as MCP servers cannot easily run in CI gates, pre-commit hooks, or non-agent pipelines. Developers need graph validation to run both interactively during pair-programming and deterministically in CI.

## Decision Drivers
* Single codebase and package installation (`pip install -e .`) providing both interfaces.
* Non-zero exit code semantics on graph rot (`broken_dead_links`, `reciprocity_breaks`, `orphan_suspects`) for automated CI gates.
* Rich MCP tool capabilities (resources, prompts, tools, JSON-LD) when communicating with LLMs.

## Considered Options
* Two separate packages/binaries (`adr-graph-mcp` and `adr-graph-cli`).
* Pure CLI tool with an MCP wrapper sidecar script.
* Unified entry point (`adr_graph.__main__:main`) dispatching based on argument presence.

## Decision Outcome
Chosen option: Unified entry point.

When invoked without subcommands (`adr-graph`), it starts the FastMCP server over stdio (`mcp.run()`). When invoked with subcommands (`adr-graph validate`, `adr-graph singletons`, etc.), it executes the CLI runner directly, sharing the exact same underlying [[ADR-3]] graph engine and adhering to the [[ADR-1]] OKF standard. Rich interactive outputs for agents and IDEs are formatted via [[ADR-7]].

<!-- adr:requirements -->
```yaml
requirements:
  - id: "ADR-002-CLI-001"
    description: "Server stdio execution must invoke mcp.run()"
    category: architecture
    verification:
      type: grep
      pattern: 'mcp\.run\(\)'
      paths:
        - "src/adr_graph/__main__.py"
      expect: present
  - id: "ADR-002-CLI-002"
    description: "FastMCP instance named adr-graph"
    category: architecture
    verification:
      type: grep
      pattern: 'FastMCP\("adr-graph"'
      paths:
        - "src/adr_graph/server.py"
      expect: present
```
<!-- /adr:requirements -->
