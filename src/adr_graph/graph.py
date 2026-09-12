"""Graph analyses over a parsed ADR corpus.

Topology-as-signal: every "incomplete" finding is dispositioned as either an
intentional frontier (signal) or genuine rot (defect). `ok` fails only on rot.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import fnmatch
from pathlib import Path

from .config import Policy, load_policy, sibling_root_ids
from .parser import ADR, parse_dir


@dataclass
class Graph:
    adrs: dict[str, ADR]
    root: Path = field(default_factory=Path.cwd)
    out: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    inn: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    policy: Policy = field(default_factory=Policy)
    sibling_ids: frozenset[str] = frozenset()
    _cross_root: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        root: Path,
        progress_cb: callable[[int, int, str], None] | None = None,
        log_cb: callable[[str, str], None] | None = None,
    ) -> "Graph":
        adrs = parse_dir(root, progress_cb=progress_cb, log_cb=log_cb)
        pol = load_policy(root)
        g = cls(adrs=adrs, root=root, policy=pol, sibling_ids=sibling_root_ids(root, pol))
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
            or adr.status in self.policy.seed_statuses
            or bool(set(adr.tags) & self.policy.seed_tags)
        )

    def subject_scopes(self) -> tuple[list[dict], list[dict]]:
        """Returns (discharged_signals, undischarged_defects).

        A node declaring a `subject_scope` whose truth does not live in the tree
        (per policy: per-machine, deployment) must also declare `discharged_by`
        — how that subject becomes observable. Declared-and-discharged is a
        signal; declared-without-discharge is a defect, structurally identical
        to a broken dead link: a claim whose referent cannot be resolved.

        An undeclared scope is treated as `commit`, the sound default, and is
        neither signal nor defect. This is a disposition over a DECLARED field;
        it never evaluates a requirement predicate.
        """
        discharged: list[dict] = []
        undischarged: list[dict] = []
        for nid, adr in self.adrs.items():
            scope = adr.subject_scope
            if not scope or scope not in self.policy.scopes_requiring_discharge:
                continue
            row = {"adr": nid, "scope": scope, "discharged_by": adr.discharged_by}
            if adr.discharged_by in self.policy.discharge_forms:
                discharged.append(row)
            else:
                undischarged.append(row)
        key = lambda r: self._k(r["adr"])  # noqa: E731
        return sorted(discharged, key=key), sorted(undischarged, key=key)

    def singletons(self) -> tuple[list[str], list[str]]:
        """Returns (intentional_frontier, orphan_suspects).

        When policy has disallow_singletons=True (default), all singletons are
        treated as orphan defects and none as intentional frontiers.
        """
        intentional, suspect = [], []
        for nid, adr in self.adrs.items():
            if not self.out[nid] and not self.inn[nid]:
                if not self.policy.disallow_singletons and self._intentional_singleton(adr):
                    intentional.append(nid)
                else:
                    suspect.append(nid)
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
                elif r in self.sibling_ids:
                    # Resolves in a declared sibling root. A corpus is per-repo;
                    # this is a documented coverage edge, not a dangling link.
                    self._cross_root.append((nid, r))
                else:
                    broken.append((nid, r))
        self._cross_root = sorted(set(self._cross_root))
        return sorted(planned), sorted(broken)

    def cross_root_refs(self) -> list[tuple[str, str]]:
        """References resolving in a declared sibling root (signal, not defect).

        Empty until `dead_links()` has run; `report()` calls it after.
        """
        return list(self._cross_root)

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

    def dark_nodes(self) -> list[tuple[str, str, str]]:
        """Returns list of (adr_id, raw_ref, intended_id) for unresolvable references that match a known alias,
        plain text references that are unlinked but map to an ID, or completely unresolved dead links.
        This also flags 'ghost nodes' where a link uses a string that canon() resolves but Obsidian does not
        (e.g., missing alias or wrong filename)."""
        alias_map = {}
        for nid, adr in self.adrs.items():
            for a in adr.aliases:
                alias_map[a] = nid

        dark = []
        from .parser import canon, _FILENUM
        for nid, adr in self.adrs.items():
            # Check raw_refs for any unresolved links
            for raw in adr.raw_refs:
                # Skip absolute links
                if raw.startswith(("http://", "https://", "file://", "mailto:", "#")):
                    continue
                
                # raw might be from a markdown link like 'href' or wikilink 'target|display'
                # parser.py extracts href directly for MD links, and contents for wikilinks
                text_to_check = raw.split("|")[0].strip()
                
                c = canon(raw)
                m = _FILENUM.match(text_to_check)
                
                # Check if it resolves perfectly in Obsidian
                # Obsidian resolves if text_to_check == stem OR text_to_check in aliases
                resolved_in_obsidian = False
                intended_id = None
                
                if c and c in self.adrs:
                    intended_id = c
                elif m and f"ADR-{int(m.group(1))}" in self.adrs:
                    intended_id = f"ADR-{int(m.group(1))}"
                    
                if intended_id:
                    target_adr = self.adrs[intended_id]
                    clean_text = text_to_check.split("/")[-1]
                    if (clean_text == target_adr.path.stem or 
                        clean_text == target_adr.path.name or 
                        text_to_check in target_adr.aliases):
                        resolved_in_obsidian = True
                        
                if not resolved_in_obsidian:
                    if text_to_check in alias_map:
                        dark.append((nid, raw, alias_map[text_to_check]))
                    elif intended_id:
                        dark.append((nid, raw, intended_id))
                    elif "adr" in raw.lower():
                        dark.append((nid, raw, "unresolved"))
            
            # Check unlinked_refs (plain text mentions)
            for raw in adr.unlinked_refs:
                c = canon(raw)
                if c and c != nid:
                    if c in self.adrs:
                        # It's an unlinked reference to a valid ADR
                        dark.append((nid, raw, c))
                    else:
                        # It's an unlinked reference to a non-existent ADR
                        dark.append((nid, raw, "unresolved"))
        return sorted(list(set(dark)))

    def cross_repo_bleeds(self) -> list[tuple[str, str]]:
        """Returns list of (adr_id, raw_ref) where a wikilink points outside the vault, or is nested inside an external markdown link."""
        import re
        bleeds = []
        for nid, adr in self.adrs.items():
            try:
                text = adr.path.read_text(encoding="utf-8", errors="replace")
                
                # 1. Wikilinks containing paths (../)
                for m in re.finditer(r'\[\[(\.\.[^\]]*)\]\]', text):
                    bleeds.append((nid, m.group(0)))
                
                # 2. Markdown links that are external/cross-repo but contain wikilinks inside the text
                for m in re.finditer(r'\[(.*?)\]\(([^)]+)\)', text):
                    link_text, href = m.groups()
                    if href.startswith('../'): # cross repo
                        if '[[' in link_text and ']]' in link_text:
                            bleeds.append((nid, m.group(0)))
            except Exception:
                pass
                        
        return sorted(list(set(bleeds)))

    def report(self) -> dict:
        n = len(self.adrs)
        edges = sum(len(v) for v in self.out.values())
        intentional, suspect = self.singletons()
        planned, broken = self.dead_links()
        recip = self.reciprocity_breaks()
        okf_viol = self.okf_violations()
        dark = self.dark_nodes()
        bleeds = self.cross_repo_bleeds()
        scoped, undischarged = self.subject_scopes()
        connected = sum(1 for nid in self.adrs if self.out[nid] or self.inn[nid])
        ok = (
            not broken
            and not recip
            and not okf_viol
            and not dark
            and not bleeds
            and not undischarged
            and (not self.policy.disallow_singletons or not suspect)
        )
        return {
            "ok": ok,
            "meta": {
                "adrs": n,
                "edges": edges,
                "connected": connected,
                "completeness_pct": round(100 * connected / n, 1) if n else 0.0,
                "intentional_frontier": len(intentional) + len(planned),
                "policy_source": self.policy.source,
            },
            "defects": {
                "broken_dead_links": [{"from": s, "to": t} for s, t in broken],
                "reciprocity_breaks": [{"a": a, "b": b, "detail": d} for a, b, d in recip],
                "okf_violations": [{"adr": a, "detail": d} for a, d in okf_viol],
                "orphan_suspects": suspect,
                "dark_nodes": [{"adr": a, "raw_ref": r, "intended_id": i} for a, r, i in dark],
                "cross_repo_bleeds": [{"adr": a, "raw_ref": r} for a, r in bleeds],
                "undischarged_scopes": undischarged,
            },
            "signals": {
                "intentional_singletons": intentional,
                "planned_forward_refs": [{"from": s, "to": t} for s, t in planned],
                "discharged_scopes": scoped,
                "cross_root_refs": [{"from": s, "to": t} for s, t in self.cross_root_refs()],
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
        """Find all ADRs whose `code_paths` globs match the given file_path.

        Returns [] for BOTH "nothing governs this path" and "no ADR in this
        corpus declares code_paths at all". Callers that report to a human or an
        agent must use `governing_adrs_with_provenance` instead — an empty list
        is not evidence of absence.
        """
        return [m[0] for m in self._match_governing(file_path)]

    def _match_governing(self, file_path: str) -> list[tuple[ADR, str]]:
        matches: list[tuple[ADR, str]] = []
        for adr in self.adrs.values():
            for pat in adr.paths:
                if fnmatch.fnmatch(file_path, pat):
                    matches.append((adr, pat))
                    break
        return sorted(matches, key=lambda m: self._k(m[0].id))

    def governing_adrs_with_provenance(self, file_path: str) -> dict:
        """Resolve a file path to its governing ADRs, with the provenance of the answer.

        `null` is a first-class provenant result. An empty match and an absent
        index are different facts, and a lookup that cannot tell them apart is
        how a confident false statement gets made — "nothing governs this file"
        asserted by a tool with no index to answer from.

        provenance:
          "matched"                -> at least one code_paths glob matched
          "no_explicit_match"      -> an index exists; this path is not in it
          "no_code_paths_declared" -> NO ADR declares code_paths; the tool
                                      cannot answer, and absence of a match
                                      carries no information whatsoever
        `matched_via` reports the pattern that matched each ADR. Patterns are
        fnmatch, where `*` crosses `/` — so `src/*` governs the whole subtree.
        Surfacing the pattern is what makes an over-broad glob visible at the
        call site instead of silently widening a decision's reach.
        """
        declaring = sum(1 for adr in self.adrs.values() if adr.paths)
        pairs = self._match_governing(file_path)
        if not declaring:
            provenance = "no_code_paths_declared"
        elif pairs:
            provenance = "matched"
        else:
            provenance = "no_explicit_match"
        return {
            "query": file_path,
            "provenance": provenance,
            "result": [a for a, _ in pairs] or None,
            "matched_via": {a.id: pat for a, pat in pairs},
            "index_size": declaring,
            "corpus_size": len(self.adrs),
        }

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
