---
id: ADR-5
type: adr
title: Tri-State Provenance Resolution for Code Path Governance
description: Implement tri-state provenance resolution in hover_context to avoid confident false assertions of absence when no code_paths index is declared in the corpus.
status: accepted
aliases:
  - ADR-5
  - ADR-005
tags:
  - architecture
  - ide
  - provenance
code_paths:
  - src/adr_graph/graph.py
  - src/adr_graph/server.py
timestamp: '2026-09-12T04:33:26+00:00'
related:
  - ADR-1
  - ADR-3
---

# 5. Tri-State Provenance Resolution for Code Path Governance

## Context and Problem Statement
When an agent or IDE requests the governing architecture decisions for a source file (via `hover_context`), tools frequently collapse a missing index into a negative match. In a corpus where zero ADRs declare `code_paths`, claiming *"No architectural decisions govern this path"* is a confident falsehood that papers over an unindexed corpus.

## Decision Drivers
* Epistemic honesty: tools must distinguish between "I looked and found no governing rule" vs "I cannot answer because no index exists".
* IDE hover tooltips must inform developers when `code_paths` frontmatter needs to be populated.
* Glob match disclosure: callers must see which glob pattern matched.

## Considered Options
* Binary lookup: return matching ADRs or an empty list `[]`.
* Tri-state provenance resolution (`matched`, `no_explicit_match`, `no_code_paths_declared`).

## Decision Outcome
Chosen option: Tri-state provenance resolution.

`Graph.governing_adrs_with_provenance()` evaluates `code_paths` declared across [[ADR-1]] frontmatter using [[ADR-3]]'s in-memory index:
1. `matched`: at least one glob matched, reporting the pattern in `matched_via`.
2. `no_explicit_match`: an index exists across the corpus, and this path is unconstrained.
3. `no_code_paths_declared`: zero ADRs declare `code_paths`, and the tool honestly reports that no index exists.
