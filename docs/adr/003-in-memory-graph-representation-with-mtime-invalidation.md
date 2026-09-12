---
id: ADR-3
type: adr
title: In-Memory Graph Representation with MTime Invalidation
description: Construct an in-memory directed graph of the ADR corpus with bidirectional edge indexes and cache it across MCP calls, invalidating on directory mtime changes.
status: accepted
aliases:
  - ADR-3
  - ADR-003
tags:
  - architecture
  - graph
  - performance
code_paths:
  - src/adr_graph/graph.py
  - src/adr_graph/server.py
timestamp: '2026-09-12T04:33:21+00:00'
related:
  - ADR-1
  - ADR-2
  - ADR-5
---

# 3. In-Memory Graph Representation with MTime Invalidation

## Context and Problem Statement
Repeatedly re-parsing hundreds of markdown files on every MCP tool invocation (e.g. `read`, `neighbors`, `path`, `hover_context`) degrades responsiveness and increases latency during agent multi-step reasoning loops.

## Decision Drivers
* Instantaneous response times for BFS shortest path, blast radius traversal, and neighborhood queries.
* Accurate graph state reflection immediately after mutations (`propose_adr`, `set_status`, `supersede`).
* Zero external database dependencies (e.g. no SQLite or Neo4j requirement).

## Considered Options
* Persistent local SQLite / DuckDB cache.
* Full disk re-read and parse on every tool call.
* In-memory directed graph instance cached by root directory path, invalidated by checking `max(mtime)` of markdown files.

## Decision Outcome
Chosen option: In-memory directed graph with directory mtime invalidation.

`Graph.build(root)` constructs the adjacency lists `out` and `inn` from [[ADR-1]] markdown files. The server caches `(Graph, mtime_state)` per root. If files change, the cache misses and re-parses transparently. This gives sub-millisecond graph queries for [[ADR-2]] CLI commands and feeds provenance data to [[ADR-5]].
