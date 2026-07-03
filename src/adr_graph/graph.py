"""Graph analyses over a parsed ADR corpus.

Topology-as-signal: every "incomplete" finding is dispositioned as either an
intentional frontier (signal) or genuine rot (defect). `ok` fails only on rot.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import fnmatch
from pathlib import Path

from .config import SEED_STATUSES, SEED_TAGS
from .parser import ADR, parse_dir


@dataclass
class Graph:
    adrs: dict[str, ADR]
    out: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    inn: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @classmethod
    def build(cls, root: Path) -> "Graph":
        adrs = parse_dir(root)
        g = cls(adrs=adrs)
        nodes = set(adrs)
        for nid, adr in adrs.items():
            refs = set(adr.body_refs)
            for key in ("supersedes", "superseded_by", "related"):
                refs.update(adr.fm.get(key, []))
            for r in refs:
                if r in nodes and r != nid:
                    g.out[nid].add(r)
                    g.inn[r].add(nid)
        return g

    # -- dispositioning ---------------------------------------------------
    def _intentional_singleton(self, adr: ADR) -> bool:
        return (
            adr.standalone
            or adr.status in SEED_STATUSES
            or bool(set(adr.tags) & SEED_TAGS)
        )

    def singletons(self) -> tuple[list[str], list[str]]:
        """Returns (intentional_frontier, orphan_suspects)."""
        intentional, suspect = [], []
        for nid, adr in self.adrs.items():
            if not self.out[nid] and not self.inn[nid]:
                (intentional if self._intentional_singleton(adr) else suspect).append(nid)
        return sorted(intentional, key=self._k), sorted(suspect, key=self._k)

    def dead_links(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Returns (planned_signals, broken_defects). Cross-repo refs are excluded."""
        nodes = set(self.adrs)
        planned, broken = [], []
        for nid, adr in self.adrs.items():
            refs: set[str] = set(adr.body_refs)
            for key in ("supersedes", "superseded_by", "related"):
                refs.update(adr.fm.get(key, []))
            cross = adr.fm_cross | adr.body_cross
            for r in refs:
                if r in nodes or r in cross:
                    continue
                if r in adr.planned:
                    planned.append((nid, r))
                else:
                    broken.append((nid, r))
        return sorted(planned), sorted(broken)

    def reciprocity_breaks(self) -> list[tuple[str, str, str]]:
        nodes = set(self.adrs)
        breaks = []
        for a, adr in self.adrs.items():
            for b in adr.fm.get("supersedes", []):
                if b in nodes and a not in self.adrs[b].fm.get("superseded_by", []):
                    breaks.append((a, b, f"{b}.superseded_by missing {a}"))
            for b in adr.fm.get("superseded_by", []):
                if b in nodes and a not in self.adrs[b].fm.get("supersedes", []):
                    breaks.append((a, b, f"{b}.supersedes missing {a}"))
        return sorted(breaks)

    def drift(self) -> list[tuple[str, list[str], list[str]]]:
        """Nodes where frontmatter typed edges and body links disagree."""
        nodes = set(self.adrs)
        result = []
        for nid, adr in self.adrs.items():
            fm_local = set()
            for key in ("supersedes", "superseded_by", "related"):
                fm_local.update(adr.fm.get(key, []))
            fm_local &= nodes
            body_local = adr.body_refs & nodes
            only_fm = sorted(fm_local - body_local, key=self._k)
            only_body = sorted(body_local - fm_local, key=self._k)
            if only_fm or only_body:
                result.append((nid, only_fm, only_body))
        return result

    def neighbors(self, adr_id: str, depth: int = 1) -> dict:
        start = canonify(adr_id)
        if start not in self.adrs:
            return {"error": f"{start} not found"}
        seen = {start: 0}
        q = deque([(start, 0)])
        while q:
            node, d = q.popleft()
            if d >= depth:
                continue
            for nbr in self.out[node] | self.inn[node]:
                if nbr not in seen:
                    seen[nbr] = d + 1
                    q.append((nbr, d + 1))
        seen.pop(start, None)
        return {
            "adr": start,
            "title": self.adrs[start].title,
            "depth": depth,
            "outbound": sorted(self.out[start], key=self._k),
            "inbound": sorted(self.inn[start], key=self._k),
            "reached": sorted(seen, key=self._k),
        }

    def okf_violations(self) -> list[tuple[str, str]]:
        """OKF v0.1 §9 conformance: every non-reserved file MUST have a non-empty `type`."""
        violations = []
        for nid, adr in self.adrs.items():
            if getattr(adr, "unparseable_yaml", False):
                violations.append((nid, "Unparseable YAML frontmatter (OKF §9 Rule 1)"))
            if not adr.type:
                violations.append((nid, "Missing required 'type' field in frontmatter (OKF §4.1)"))
        return violations

    def okf_conformance(self) -> dict:
        """OKF v0.1 conformance report per §9: violations, warnings, and field coverage."""
        violations = self.okf_violations()
        warnings = []
        for nid, adr in self.adrs.items():
            if not adr.title or adr.title == adr.path.stem:
                warnings.append((nid, "Missing or defaulted 'title' field (OKF §4.1)"))
            if not adr.description:
                warnings.append((nid, "Missing recommended 'description' field (OKF §4.1)"))
            if not adr.timestamp:
                warnings.append((nid, "Missing recommended 'timestamp' field (OKF §4.1)"))
        n = len(self.adrs)
        has_type = sum(1 for a in self.adrs.values() if a.type)
        has_title = sum(1 for a in self.adrs.values() if a.title and a.title != a.path.stem)
        has_desc = sum(1 for a in self.adrs.values() if a.description)
        has_ts = sum(1 for a in self.adrs.values() if a.timestamp)
        has_resource = sum(1 for a in self.adrs.values() if a.resource)
        pct = round(100 * has_type / n, 1) if n else 0.0
        return {
            "okf_version": "0.1",
            "conformant": not violations,
            "conformance_pct": pct,
            "violations": [{"adr": a, "detail": d} for a, d in violations],
            "warnings": [{"adr": a, "detail": d} for a, d in warnings],
            "coverage": {
                "type": f"{has_type}/{n}",
                "title": f"{has_title}/{n}",
                "description": f"{has_desc}/{n}",
                "timestamp": f"{has_ts}/{n}",
                "resource": f"{has_resource}/{n}",
            },
        }

    def report(self) -> dict:
        n = len(self.adrs)
        edges = sum(len(v) for v in self.out.values())
        intentional, suspect = self.singletons()
        planned, broken = self.dead_links()
        recip = self.reciprocity_breaks()
        okf_viol = self.okf_violations()
        connected = sum(1 for nid in self.adrs if self.out[nid] or self.inn[nid])
        ok = not broken and not recip and not okf_viol
        return {
            "ok": ok,
            "meta": {
                "adrs": n,
                "edges": edges,
                "connected": connected,
                "completeness_pct": round(100 * connected / n, 1) if n else 0.0,
                "intentional_frontier": len(intentional) + len(planned),
            },
            "defects": {
                "broken_dead_links": [{"from": s, "to": t} for s, t in broken],
                "reciprocity_breaks": [{"a": a, "b": b, "detail": d} for a, b, d in recip],
                "okf_violations": [{"adr": a, "detail": d} for a, d in okf_viol],
                "orphan_suspects": suspect,
            },
            "signals": {
                "intentional_singletons": intentional,
                "planned_forward_refs": [{"from": s, "to": t} for s, t in planned],
            },
        }

    def list_adrs(self, status: str = "", tag: str = "", limit: int = 100, offset: int = 0) -> list[ADR]:
        res = list(self.adrs.values())
        if status:
            s_val = status.strip().lower()
            res = [a for a in res if a.status == s_val]
        if tag:
            t_val = tag.strip().lower()
            res = [a for a in res if t_val in a.tags]
        sorted_res = sorted(res, key=lambda a: self._k(a.id))
        return sorted_res[offset : offset + limit]

    def search_adrs(self, query: str, status: str = "", limit: int = 100, offset: int = 0) -> list[ADR]:
        q_val = query.lower()
        res = [a for a in self.adrs.values() if q_val in a.title.lower()]
        if status:
            s_val = status.strip().lower()
            res = [a for a in res if a.status == s_val]
        sorted_res = sorted(res, key=lambda a: self._k(a.id))
        return sorted_res[offset : offset + limit]

    def get_governing_adrs(self, file_path: str) -> list[ADR]:
        """Find all ADRs whose `code_paths` globs match the given file_path."""
        matches = []
        for adr in self.adrs.values():
            for pat in adr.paths:
                if fnmatch.fnmatch(file_path, pat):
                    matches.append(adr)
                    break
        return sorted(matches, key=lambda a: self._k(a.id))

    def find_path(self, from_adr: str, to_adr: str) -> dict:
        start = canonify(from_adr)
        end = canonify(to_adr)
        if start not in self.adrs:
            return {"error": f"Start ADR {start} not found"}
        if end not in self.adrs:
            return {"error": f"End ADR {end} not found"}
        if start == end:
            return {"path": [start]}

        q = deque([[start]])
        visited = {start}
        while q:
            path = q.popleft()
            node = path[-1]
            for nbr in sorted(self.out[node], key=self._k):
                if nbr == end:
                    return {"path": path + [end]}
                if nbr not in visited:
                    visited.add(nbr)
                    q.append(path + [nbr])
        return {"path": None}

    def blast_radius(self, adr_id: str) -> dict:
        start = canonify(adr_id)
        if start not in self.adrs:
            return {"error": f"ADR {start} not found"}

        visited = set()
        q = deque([start])
        while q:
            curr = q.popleft()
            for parent in self.inn[curr]:
                if parent not in visited:
                    visited.add(parent)
                    q.append(parent)

        return {
            "adr": start,
            "blast_radius": sorted(visited, key=self._k),
            "count": len(visited)
        }

    @staticmethod
    def _k(nid: str) -> int:
        part = nid.split("-")[-1]
        return int(part) if part.isdigit() else 0


def canonify(adr_id: str) -> str:
    from .parser import canon

    return canon(adr_id) or adr_id
