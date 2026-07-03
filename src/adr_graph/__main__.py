"""Entry point. With no subcommand, runs the MCP server over stdio.
With a subcommand, acts as a CLI (handy as a CI gate) — same logic, no MCP runtime.

  adr-graph                         # run MCP server (stdio)
  adr-graph validate [ROOT]         # full report as JSON; exit 1 if not ok
  adr-graph singletons [ROOT]
  adr-graph dead-links [ROOT]
  adr-graph reciprocity [ROOT]
  adr-graph neighbors ADR [DEPTH] [ROOT]
  adr-graph export FMT [ROOT]       # FMT = json | mermaid
  adr-graph reconcile [ADR] [--apply] [ROOT]
  adr-graph read ADR [ROOT]
  adr-graph list [--status STATUS] [--tag TAG] [--limit LIMIT] [--offset OFFSET] [ROOT]
  adr-graph search QUERY [--status STATUS] [--limit LIMIT] [--offset OFFSET] [ROOT]
  adr-graph path FROM TO [ROOT]
  adr-graph set-status ADR STATUS [ROOT]
  adr-graph rename OLD NEW [--apply] [ROOT]
  adr-graph drift [ROOT]
  adr-graph propose TITLE [CONTEXT] [--tags tag1,tag2,...] [ROOT]
  adr-graph migrate-okf [ROOT]
  adr-graph okf-conformance [ROOT]                         # OKF v0.1 conformance report
"""

from __future__ import annotations

import json
import sys

from .config import resolve_root
from .graph import Graph, canonify


def _emit(obj: object) -> None:
    print(obj if isinstance(obj, str) else json.dumps(obj, indent=2))


def _cli(argv: list[str]) -> int:
    cmd, rest = argv[0], argv[1:]
    apply = "--apply" in rest
    rest = [a for a in rest if a != "--apply"]

    status = ""
    tag = ""
    limit = 100
    offset = 0
    tags_list = None

    if "--status" in rest:
        idx = rest.index("--status")
        if idx + 1 < len(rest):
            status = rest[idx + 1]
            rest.pop(idx + 1)
        rest.pop(idx)
    if "--tag" in rest:
        idx = rest.index("--tag")
        if idx + 1 < len(rest):
            tag = rest[idx + 1]
            rest.pop(idx + 1)
        rest.pop(idx)
    if "--limit" in rest:
        idx = rest.index("--limit")
        if idx + 1 < len(rest) and rest[idx + 1].isdigit():
            limit = int(rest[idx + 1])
            rest.pop(idx + 1)
        rest.pop(idx)
    if "--offset" in rest:
        idx = rest.index("--offset")
        if idx + 1 < len(rest) and rest[idx + 1].isdigit():
            offset = int(rest[idx + 1])
            rest.pop(idx + 1)
        rest.pop(idx)
    if "--tags" in rest:
        idx = rest.index("--tags")
        if idx + 1 < len(rest):
            tags_list = [t.strip() for t in rest[idx + 1].split(",")]
            rest.pop(idx + 1)
        rest.pop(idx)

    if cmd == "validate":
        rep = Graph.build(resolve_root(rest[0] if rest else None)).report()
        _emit(rep)
        return 0 if rep["ok"] else 1
    if cmd == "singletons":
        intentional, suspect = Graph.build(resolve_root(rest[0] if rest else None)).singletons()
        _emit({"intentional_frontier": intentional, "orphan_suspects": suspect})
        return 0
    if cmd == "dead-links":
        planned, broken = Graph.build(resolve_root(rest[0] if rest else None)).dead_links()
        _emit({"planned": planned, "broken": broken})
        return 0 if not broken else 1
    if cmd == "reciprocity":
        breaks = Graph.build(resolve_root(rest[0] if rest else None)).reciprocity_breaks()
        _emit({"reciprocity_breaks": breaks})
        return 0 if not breaks else 1
    if cmd == "neighbors":
        if not rest:
            sys.stderr.write("Error: missing ADR argument\nUsage: adr-graph neighbors ADR [DEPTH] [ROOT]\n")
            return 2
        adr = rest[0]
        depth = int(rest[1]) if len(rest) > 1 and rest[1].isdigit() else 1
        root = rest[2] if len(rest) > 2 else (rest[1] if len(rest) > 1 and not rest[1].isdigit() else None)
        _emit(Graph.build(resolve_root(root)).neighbors(adr, depth=depth))
        return 0
    if cmd == "export":
        from .exports import render

        fmt = rest[0] if rest else "json"
        _emit(render(Graph.build(resolve_root(rest[1] if len(rest) > 1 else None)), fmt))
        return 0
    if cmd == "reconcile":
        from . import mutate

        adr = rest[0] if rest else None
        root = rest[1] if len(rest) > 1 else None
        _emit(mutate.reconcile_related(resolve_root(root), adr_id=adr, apply=apply))
        return 0
    if cmd == "read":
        if not rest:
            sys.stderr.write("Error: missing ADR argument\nUsage: adr-graph read ADR [ROOT]\n")
            return 2
        adr = rest[0]
        root = rest[1] if len(rest) > 1 else None
        g = Graph.build(resolve_root(root))
        a = canonify(adr)
        if a not in g.adrs:
            sys.stderr.write(f"ADR {a} not found\n")
            return 1
        adr_obj = g.adrs[a]
        from .mutate import _load
        meta, body = _load(adr_obj.path)
        _emit({
            "id": adr_obj.id,
            "title": adr_obj.title,
            "description": adr_obj.description,
            "resource": adr_obj.resource,
            "type": adr_obj.type,
            "timestamp": adr_obj.timestamp,
            "status": adr_obj.status,
            "tags": adr_obj.tags,
            "metadata": meta,
            "body": body,
        })
        return 0
    if cmd == "list":
        root = rest[0] if rest else None
        g = Graph.build(resolve_root(root))
        adrs = g.list_adrs(status=status, tag=tag, limit=limit, offset=offset)
        _emit([
            {"id": a.id, "title": a.title, "description": a.description, "resource": a.resource,
             "type": a.type, "timestamp": a.timestamp, "status": a.status, "tags": a.tags}
            for a in adrs
        ])
        return 0
    if cmd == "search":
        if not rest:
            sys.stderr.write("Error: missing QUERY argument\nUsage: adr-graph search QUERY [--status STATUS] [--limit LIMIT] [--offset OFFSET] [ROOT]\n")
            return 2
        query = rest[0]
        root = rest[1] if len(rest) > 1 else None
        g = Graph.build(resolve_root(root))
        adrs = g.search_adrs(query, status=status, limit=limit, offset=offset)
        _emit([
            {"id": a.id, "title": a.title, "description": a.description, "resource": a.resource,
             "type": a.type, "timestamp": a.timestamp, "status": a.status, "tags": a.tags}
            for a in adrs
        ])
        return 0
    if cmd == "path":
        if len(rest) < 2:
            sys.stderr.write("Error: missing FROM and/or TO arguments\nUsage: adr-graph path FROM TO [ROOT]\n")
            return 2
        from_adr = rest[0]
        to_adr = rest[1]
        root = rest[2] if len(rest) > 2 else None
        g = Graph.build(resolve_root(root))
        _emit(g.find_path(from_adr, to_adr))
        return 0
    if cmd == "set-status":
        if len(rest) < 2:
            sys.stderr.write("Error: missing ADR and/or STATUS arguments\nUsage: adr-graph set-status ADR STATUS [ROOT]\n")
            return 2
        adr = rest[0]
        status_val = rest[1]
        root = rest[2] if len(rest) > 2 else None
        from . import mutate
        _emit(mutate.set_status(resolve_root(root), adr, status_val))
        return 0
    if cmd == "rename":
        if len(rest) < 2:
            sys.stderr.write("Error: missing OLD and/or NEW arguments\nUsage: adr-graph rename OLD NEW [--apply] [ROOT]\n")
            return 2
        old = rest[0]
        new = rest[1]
        root = rest[2] if len(rest) > 2 else None
        from . import mutate
        _emit(mutate.rename(resolve_root(root), old, new, dry_run=not apply))
        return 0
    if cmd == "drift":
        root = rest[0] if rest else None
        g = Graph.build(resolve_root(root))
        _emit([
            {"adr": a, "in_yaml_not_body": f, "in_body_not_yaml": b}
            for a, f, b in g.drift()
        ])
        return 0
    if cmd == "blast-radius":
        if not rest:
            sys.stderr.write("Error: missing ADR argument\nUsage: adr-graph blast-radius ADR [ROOT]\n")
            return 2
        adr = rest[0]
        root = rest[1] if len(rest) > 1 else None
        g = Graph.build(resolve_root(root))
        _emit(g.blast_radius(adr))
        return 0
    if cmd in ("propose", "propose-adr"):
        if not rest:
            sys.stderr.write("Error: missing TITLE argument\nUsage: adr-graph propose TITLE [CONTEXT] [--tags tag1,tag2,...] [ROOT]\n")
            return 2
        title = rest[0]
        context = rest[1] if len(rest) > 1 else ""
        root = rest[2] if len(rest) > 2 else None
        from . import mutate
        _emit(mutate.propose(resolve_root(root), title, status="proposed", context=context, tags=tags_list))
        return 0
    if cmd == "okf-conformance":
        root = rest[0] if rest else None
        g = Graph.build(resolve_root(root))
        _emit(g.okf_conformance())
        return 0
    if cmd == "migrate-okf":
        root = rest[0] if rest else None
        from . import mutate
        _emit(mutate.migrate_okf(resolve_root(root), dry_run=not apply))
        return 0

    sys.stderr.write(f"unknown command: {cmd}\n{__doc__}\n")
    return 2


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] not in {"-h", "--help"}:
        raise SystemExit(_cli(argv))
    if argv:
        print(__doc__)
        raise SystemExit(0)
    from .server import mcp

    mcp.run()


if __name__ == "__main__":
    main()
