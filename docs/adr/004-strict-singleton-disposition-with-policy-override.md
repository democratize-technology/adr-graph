---
id: ADR-4
type: adr
title: Strict Singleton Disposition with Policy Override
description: "Treat all disconnected ADR singletons as defects by default to enforce graph connectivity, allowing corpus policy to selectively re-enable intentional frontiers via disallow_singletons: false."
status: accepted
aliases:
  - ADR-4
  - ADR-004
tags:
  - architecture
  - policy
  - validation
code_paths:
  - src/adr_graph/graph.py
  - src/adr_graph/config.py
timestamp: '2026-09-12T04:33:24+00:00'
related:
  - ADR-1
  - ADR-6
---

# 4. Strict Singleton Disposition with Policy Override

## Context and Problem Statement
An isolated architectural decision that references nothing and is referenced by nothing provides zero graph context. While early draft seeds may start disconnected, accepting decisions into an architecture repository without wiring them into the graph creates dark knowledge and orphans.

## Decision Drivers
* Enforce rigorous graph integrity: every architectural decision must be anchored in the knowledge graph.
* Allow explicit, reviewable opt-in for projects where nascent drafts or standalone seeds are intentionally isolated.
* Provide unambiguous gate outcomes for automated verification.

## Considered Options
* Allow all proposed/draft/seed ADRs to be disconnected without failing validation.
* Reject all singletons unconditionally with no policy override.
* Enforce strict singleton disallowance by default (`disallow_singletons: true`), failing validation (`ok: false`) on any isolated node, while honoring in-corpus policy declarations ([[ADR-6]]) when intentional frontiers are configured.

## Decision Outcome
Chosen option: Strict singleton disallowance by default with policy override.

In accordance with [[ADR-1]], all disconnected nodes are flagged as orphan defects. If a repository needs to author disconnected frontier drafts, it explicitly states so in its [[ADR-6]] policy node (`disallow_singletons: false`).
