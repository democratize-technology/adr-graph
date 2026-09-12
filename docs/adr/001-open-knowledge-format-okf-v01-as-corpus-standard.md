---
id: ADR-1
type: adr
title: Open Knowledge Format (OKF) v0.1 as Corpus Standard
description: Standardize on Google's Open Knowledge Format (OKF) v0.1 for representing architecture decisions as markdown with typed YAML frontmatter and wikilinks.
status: accepted
aliases:
  - ADR-1
  - ADR-001
tags:
  - architecture
  - okf
  - standard
code_paths:
  - src/adr_graph/parser.py
  - src/adr_graph/exports.py
timestamp: '2026-09-12T04:33:16+00:00'
related:
  - ADR-2
  - ADR-3
  - ADR-4
  - ADR-5
  - ADR-6
  - ADR-7
---

# 1. Open Knowledge Format (OKF) v0.1 as Corpus Standard

## Context and Problem Statement
Architecture Decision Records (ADRs) are often scattered across arbitrary formats (MADR, Nygard, custom templates) with unstandardized metadata and fragile linkage conventions. For AI agents and developers to reliably reason about architectural invariants, dependencies, and rot, decisions must be expressed in an open, typed, machine-traversable format.

## Decision Drivers
* Need for a vendor-neutral, human-readable, agent-verifiable knowledge format.
* Support for three typed reference channels: YAML frontmatter edges (`supersedes`, `superseded_by`, `related`), wikilinks (e.g. `[ADR-001]`), and markdown relative links.
* Ability to export the entire corpus as a unified knowledge graph bundle.

## Considered Options
* Custom JSON schema database for ADRs.
* Freeform Markdown with heuristic regex link parsing.
* Google's Open Knowledge Format (OKF) v0.1 specification.

## Decision Outcome
Chosen option: Google's Open Knowledge Format (OKF) v0.1.

Every decision document is a markdown file with typed YAML frontmatter containing required `type: adr` (or policy/metric/etc.), `id`, `title`, `description`, `timestamp`, `status`, `tags`, and optional `code_paths`.

This foundation enables:
- Seamless dual-entry CLI and MCP tool consumption ([[ADR-2]]).
- In-memory graph traversal with strict edge reciprocity checks ([[ADR-3]]).
- Rigorous singleton and rot dispositioning ([[ADR-4]]).
- Accurate IDE code path governance mapping ([[ADR-5]]).
- In-tree policy declaration ([[ADR-6]]).
- Dual-layer human/agent tool responses with JSON-LD metadata ([[ADR-7]]).
