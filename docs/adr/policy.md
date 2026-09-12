---
type: policy
title: ADR-Graph Corpus Disposition Policy
timestamp: '2026-09-12T04:30:00+00:00'
disallow_singletons: true
scopes_requiring_discharge:
  - per-machine
  - deployment
discharge_forms:
  - heartbeat
  - named-unverifiable
---

# ADR-Graph Corpus Disposition Policy

This policy governs the `adr-graph` ADR repository.

- **Singletons**: Treated as defects by default (`disallow_singletons: true`). Every architectural decision must be connected to the graph.
- **Subject Scopes**: Any decision claiming jurisdiction outside the repository commit tree must declare how it is observable (`heartbeat` or `named-unverifiable`).
