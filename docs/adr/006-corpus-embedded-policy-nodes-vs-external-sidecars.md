---
id: ADR-6
type: adr
title: Corpus-Embedded Policy Nodes vs External Sidecars
description: Store corpus disposition policy inside the markdown knowledge graph as a top-level node with type policy rather than in an untracked external sidecar file.
status: accepted
aliases:
  - ADR-6
  - ADR-006
tags:
  - architecture
  - policy
  - git
code_paths:
  - src/adr_graph/config.py
timestamp: '2026-09-12T04:33:29+00:00'
related:
  - ADR-1
  - ADR-4
---

# 6. Corpus-Embedded Policy Nodes vs External Sidecars

## Context and Problem Statement
Dispositions on what statuses count as frontiers, what subject scopes require observable discharge, and where sibling ADR repositories live are corpus opinions. Putting policy into an external config file (e.g. `.adr-policy.toml`) introduces failure modes where a missing config falls back silently to defaults, weakening verification gates unnoticed.

## Decision Drivers
* Policy must be a function of the git tree SHA: visible to the same verification tooling that audits links.
* Changing policy rules must produce a standard, reviewable git diff within the corpus.
* Multi-repo product architectures need to declare `sibling_roots` to avoid false-positive dead link alerts across repositories.

## Considered Options
* Global CLI command-line flags.
* Repository root sidecar config file (`.adr-graph.json`).
* Top-level OKF document with `type: policy` inside the corpus root.

## Decision Outcome
Chosen option: Top-level OKF policy node (`type: policy`).

The policy node is parsed alongside other [[ADR-1]] documents. It defines rules like `disallow_singletons` ([[ADR-4]]), `scopes_requiring_discharge`, and `sibling_roots`. If omitted, the server reports `policy_source: "defaults"`.
