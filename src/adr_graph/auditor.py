"""Auditor module: active architectural verification and context briefing.

Provides:
  - audit_diff: Verifies that code changes / files satisfy invariants declared in governing ADRs.
  - task_briefing: Synthesizes a compact, task-specific architectural briefing from the graph.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .graph import Graph
from .parser import ADR

_REQUIREMENTS_BLOCK = re.compile(
    r"<!--\s*adr:requirements\s*-->\s*```(?:yaml)?\s*(.*?)\s*```\s*<!--\s*/adr:requirements\s*-->",
    re.S | re.I,
)
_DIFF_FILE_HEADER = re.compile(r"^\+\+\+\s+b/(.*)$", re.M)
_DIFF_GIT_HEADER = re.compile(r"^diff --git a/.*? b/(.*?)$", re.M)

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "with",
    "by", "from", "of", "about", "into", "through", "during", "before", "after",
    "above", "below", "is", "are", "was", "were", "be", "been", "being", "have",
    "has", "had", "do", "does", "did", "can", "could", "should", "would", "will",
    "i", "you", "we", "they", "it", "this", "that", "these", "those", "how", "what",
    "where", "when", "why", "which", "who", "all", "any", "both", "each", "few",
}


@dataclass
class InvariantCheck:
    id: str
    adr_id: str
    description: str
    category: str
    target_path: str
    pattern: str
    expect: str
    status: str  # "passed" | "violated" | "skipped"
    detail: str


@dataclass
class AuditResult:
    ok: bool
    files_checked: list[str]
    governing_adrs: list[dict[str, Any]]
    invariants_checked: int
    invariants_passed: int
    invariants_violated: int
    checks: list[InvariantCheck]
    unindexed_files: list[str]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "files_checked": self.files_checked,
            "governing_adrs": self.governing_adrs,
            "invariants_checked": self.invariants_checked,
            "invariants_passed": self.invariants_passed,
            "invariants_violated": self.invariants_violated,
            "checks": [
                {
                    "id": c.id,
                    "adr": c.adr_id,
                    "description": c.description,
                    "category": c.category,
                    "target_path": c.target_path,
                    "pattern": c.pattern,
                    "expect": c.expect,
                    "status": c.status,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
            "unindexed_files": self.unindexed_files,
            "recommendations": self.recommendations,
        }


@dataclass
class TaskBriefingResult:
    task: str
    files: list[str]
    primary_adrs: list[dict[str, Any]]
    invariants: list[dict[str, Any]]
    blast_radius: list[str]
    neighboring_context: list[str]
    recommended_checklist: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "files": self.files,
            "primary_adrs": self.primary_adrs,
            "invariants": self.invariants,
            "blast_radius": self.blast_radius,
            "neighboring_context": self.neighboring_context,
            "recommended_checklist": self.recommended_checklist,
        }


def extract_requirements(adr: ADR) -> list[dict[str, Any]]:
    """Extract requirements from an ADR body comments and/or frontmatter."""
    reqs: list[dict[str, Any]] = []

    # 1. Check frontmatter requirements
    fm_reqs = (getattr(adr, "raw_fm", None) or {}).get("requirements") or adr.fm.get("requirements")
    if isinstance(fm_reqs, list):
        for item in fm_reqs:
            if isinstance(item, dict):
                reqs.append(item)

    # 2. Check HTML comment block in body: <!-- adr:requirements -->
    try:
        text = adr.path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""

    for match in _REQUIREMENTS_BLOCK.finditer(text):
        content = match.group(1).strip()
        parsed = None
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError:
            try:
                sanitized = re.sub(r"\\([^0abtnvfre\"\\_LPxuU\n])", r"\\\\\1", content)
                parsed = yaml.safe_load(sanitized)
            except yaml.YAMLError:
                continue

        if isinstance(parsed, dict) and isinstance(parsed.get("requirements"), list):
            reqs.extend([r for r in parsed["requirements"] if isinstance(r, dict)])
        elif isinstance(parsed, list):
            reqs.extend([r for r in parsed if isinstance(r, dict)])

    return reqs


def extract_files_from_diff(git_diff: str) -> list[str]:
    """Extract changed file paths from a unified diff string."""
    files: set[str] = set()
    for m in _DIFF_FILE_HEADER.finditer(git_diff):
        path = m.group(1).strip()
        if path and path != "/dev/null":
            files.add(path)
    if not files:
        for m in _DIFF_GIT_HEADER.finditer(git_diff):
            path = m.group(1).strip()
            if path and path != "/dev/null":
                files.add(path)
    return sorted(files)


def path_matches(path: str, pattern: str) -> bool:
    """Match a relative path against a glob pattern, supporting standard ** globs."""
    import fnmatch

    if path == pattern:
        return True
    if fnmatch.fnmatch(path, pattern):
        return True
    if "/**/" in pattern:
        alt = pattern.replace("/**/", "/")
        if fnmatch.fnmatch(path, alt):
            return True
    if pattern.endswith("/**"):
        alt = pattern[:-3] + "/*"
        if fnmatch.fnmatch(path, alt):
            return True
    return False


def get_repo_root(corpus_root: Path) -> Path:
    """Find repository root containing corpus_root, or default to corpus_root.parent.parent."""
    cur = corpus_root.resolve()
    for p in [cur, *cur.parents]:
        if (p / ".git").exists():
            return p
    # Fallback to parent of docs/adr
    if cur.name == "adr" and cur.parent.name == "docs":
        return cur.parent.parent
    return cur.parent


def audit_diff(
    g: Graph,
    files: list[str] | None = None,
    git_diff: str | None = None,
    repo_root: Path | None = None,
) -> AuditResult:
    """Audit code changes against invariants declared in governing ADRs."""
    root = repo_root or get_repo_root(g.root)

    # Resolve target files to audit
    target_files: list[str] = []
    if files:
        target_files = [f.strip() for f in files if f.strip()]
    elif git_diff:
        target_files = extract_files_from_diff(git_diff)
    else:
        # Try reading changed files from git
        try:
            res = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                target_files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            else:
                # Try unstaged status
                res_status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if res_status.returncode == 0:
                    for line in res_status.stdout.splitlines():
                        parts = line.strip().split(maxsplit=1)
                        if len(parts) == 2:
                            target_files.append(parts[1].strip())
        except (subprocess.SubprocessError, OSError):
            target_files = []

    # Index ADR requirements and their path patterns
    adr_reqs: dict[str, list[dict[str, Any]]] = {}
    path_pattern_to_adrs: dict[str, set[str]] = {}
    for adr in g.adrs.values():
        reqs = extract_requirements(adr)
        if reqs:
            adr_reqs[adr.id] = reqs
            for r in reqs:
                for p in r.get("verification", {}).get("paths", []):
                    path_pattern_to_adrs.setdefault(str(p).strip(), set()).add(adr.id)

    governing_adrs_map: dict[str, ADR] = {}
    unindexed_files: list[str] = []

    for rel_path in target_files:
        has_governing_adr = False
        prov = g.governing_adrs_with_provenance(rel_path)
        matched_adrs = prov.get("result") or []
        if matched_adrs:
            has_governing_adr = True
            for adr in matched_adrs:
                governing_adrs_map[adr.id] = adr

        for pattern_str, aid_set in path_pattern_to_adrs.items():
            if path_matches(rel_path, pattern_str):
                has_governing_adr = True
                for aid in aid_set:
                    governing_adrs_map[aid] = g.adrs[aid]

        if not has_governing_adr:
            unindexed_files.append(rel_path)

    checks: list[InvariantCheck] = []
    recommendations: list[str] = []

    # Check invariants for all governing ADRs
    for adr in governing_adrs_map.values():
        reqs = adr_reqs.get(adr.id) or extract_requirements(adr)
        for r in reqs:
            req_id = str(r.get("id") or "UNKNOWN")
            desc = str(r.get("description") or "")
            category = str(r.get("category") or "general")
            verification = r.get("verification") or {}
            v_type = str(verification.get("type") or "grep").lower()
            if v_type not in ("grep", "regex"):
                continue
            pattern = str(verification.get("pattern") or "")
            expect = str(verification.get("expect") or "present").lower()
            v_paths = verification.get("paths") or []

            # If paths are specified, test against those matching target_files (or all v_paths if target_files empty)
            target_paths_to_test: list[str] = []
            if v_paths:
                for p in v_paths:
                    p_str = str(p).strip()
                    if target_files:
                        for tf in target_files:
                            if path_matches(tf, p_str) and tf not in target_paths_to_test:
                                target_paths_to_test.append(tf)
                    else:
                        if any(c in p_str for c in "*?["):
                            try:
                                for matched in root.glob(p_str):
                                    if matched.is_file():
                                        rel_matched = str(matched.relative_to(root))
                                        if rel_matched not in target_paths_to_test:
                                            target_paths_to_test.append(rel_matched)
                            except (ValueError, OSError):
                                pass
                        else:
                            if p_str not in target_paths_to_test:
                                target_paths_to_test.append(p_str)
            else:
                for tf in target_files:
                    if any(path_matches(tf, pat) for pat in adr.paths) and tf not in target_paths_to_test:
                        target_paths_to_test.append(tf)

            for path_str in target_paths_to_test:
                file_path = (root / path_str).resolve()
                if not file_path.exists():
                    status = "violated" if expect == "present" else "passed"
                    detail = f"File {path_str} does not exist"
                    checks.append(
                        InvariantCheck(
                            id=req_id,
                            adr_id=adr.id,
                            description=desc,
                            category=category,
                            target_path=path_str,
                            pattern=pattern,
                            expect=expect,
                            status=status,
                            detail=detail,
                        )
                    )
                    continue

                try:
                    file_content = file_path.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    checks.append(
                        InvariantCheck(
                            id=req_id,
                            adr_id=adr.id,
                            description=desc,
                            category=category,
                            target_path=path_str,
                            pattern=pattern,
                            expect=expect,
                            status="violated",
                            detail=f"Could not read {path_str}: {e}",
                        )
                    )
                    continue

                # Evaluate pattern
                found = False
                if pattern:
                    try:
                        found = bool(re.search(pattern, file_content))
                    except re.error:
                        found = pattern in file_content

                if expect == "present":
                    if found:
                        checks.append(
                            InvariantCheck(
                                id=req_id,
                                adr_id=adr.id,
                                description=desc,
                                category=category,
                                target_path=path_str,
                                pattern=pattern,
                                expect=expect,
                                status="passed",
                                detail=f"Pattern matched in {path_str}",
                            )
                        )
                    else:
                        checks.append(
                            InvariantCheck(
                                id=req_id,
                                adr_id=adr.id,
                                description=desc,
                                category=category,
                                target_path=path_str,
                                pattern=pattern,
                                expect=expect,
                                status="violated",
                                detail=f"Required pattern '{pattern}' missing in {path_str}",
                            )
                        )
                elif expect == "absent":
                    if not found:
                        checks.append(
                            InvariantCheck(
                                id=req_id,
                                adr_id=adr.id,
                                description=desc,
                                category=category,
                                target_path=path_str,
                                pattern=pattern,
                                expect=expect,
                                status="passed",
                                detail=f"Forbidden pattern absent from {path_str}",
                            )
                        )
                    else:
                        checks.append(
                            InvariantCheck(
                                id=req_id,
                                adr_id=adr.id,
                                description=desc,
                                category=category,
                                target_path=path_str,
                                pattern=pattern,
                                expect=expect,
                                status="violated",
                                detail=f"Forbidden pattern '{pattern}' found in {path_str}",
                            )
                        )

    passed_count = sum(1 for c in checks if c.status == "passed")
    violated_count = sum(1 for c in checks if c.status == "violated")
    ok = violated_count == 0

    if violated_count > 0:
        recommendations.append(
            f"Found {violated_count} invariant violation(s). Revert or amend changes to satisfy governing ADR requirements."
        )
        recommendations.append(
            "If this change is an intentional architecture evolution, propose a superseding ADR using `supersede` or `propose_adr`."
        )
    elif governing_adrs_map:
        recommendations.append(
            f"All {passed_count} verified invariants passed across {len(governing_adrs_map)} governing ADR(s)."
        )

    if unindexed_files:
        recommendations.append(
            f"{len(unindexed_files)} touched file(s) are not governed by any ADR `code_paths`. Consider declaring them in relevant decisions."
        )

    return AuditResult(
        ok=ok,
        files_checked=target_files,
        governing_adrs=[
            {
                "id": a.id,
                "title": a.title,
                "status": a.status,
                "description": a.description,
                "tags": a.tags,
            }
            for a in sorted(governing_adrs_map.values(), key=lambda x: g._k(x.id))
        ],
        invariants_checked=len(checks),
        invariants_passed=passed_count,
        invariants_violated=violated_count,
        checks=checks,
        unindexed_files=unindexed_files,
        recommendations=recommendations,
    )


def task_briefing(
    g: Graph,
    task: str,
    files: list[str] | None = None,
    max_adrs: int = 5,
) -> TaskBriefingResult:
    """Synthesize an actionable architectural briefing for an agent or developer embarking on a task."""
    relevant_adrs_map: dict[str, ADR] = {}
    touched_files = [f.strip() for f in (files or []) if f.strip()]

    # 1. Match ADRs by files (code_paths)
    for f in touched_files:
        prov = g.governing_adrs_with_provenance(f)
        for adr in prov.get("result") or []:
            relevant_adrs_map[adr.id] = adr

    # 2. Match ADRs by task query tokens
    tokens = [
        re.sub(r"[^\w-]", "", w.lower())
        for w in task.split()
        if len(w) > 2 and w.lower() not in STOP_WORDS
    ]

    scores: dict[str, int] = {}
    for nid, adr in g.adrs.items():
        score = 0
        title_lower = adr.title.lower()
        desc_lower = adr.description.lower()
        tags_lower = [t.lower() for t in adr.tags]

        for tok in tokens:
            if tok in title_lower:
                score += 5
            if tok in tags_lower:
                score += 4
            if tok in desc_lower:
                score += 2

        if score > 0:
            scores[nid] = score

    # Sort scored ADRs and select top
    sorted_scored = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    for nid, _ in sorted_scored:
        if len(relevant_adrs_map) >= max_adrs:
            break
        relevant_adrs_map[nid] = g.adrs[nid]

    # Gather invariants, blast radius, and neighboring context
    invariants: list[dict[str, Any]] = []
    blast_radius: set[str] = set()
    neighbors: set[str] = set()

    for adr in relevant_adrs_map.values():
        reqs = extract_requirements(adr)
        for r in reqs:
            invariants.append(
                {
                    "adr": adr.id,
                    "id": r.get("id"),
                    "description": r.get("description"),
                    "category": r.get("category"),
                    "pattern": r.get("verification", {}).get("pattern"),
                    "expect": r.get("verification", {}).get("expect", "present"),
                }
            )

        # Blast radius
        b_res = g.blast_radius(adr.id)
        for dep in b_res.get("transitive_dependents") or []:
            if dep != adr.id:
                blast_radius.add(dep)

        # 1-hop neighbors
        n_res = g.neighbors(adr.id, depth=1)
        for out in n_res.get("outbound") or []:
            if out not in relevant_adrs_map:
                neighbors.add(out)
        for inn in n_res.get("inbound") or []:
            if inn not in relevant_adrs_map:
                neighbors.add(inn)

    checklist: list[str] = []
    checklist.append("Review governing ADRs before modifying core interfaces or configuration.")
    if invariants:
        checklist.append(
            f"Preserve {len(invariants)} declared architectural invariant(s) during implementation."
        )
    if blast_radius:
        checklist.append(
            f"Be aware of {len(blast_radius)} downstream dependent ADR(s) ({', '.join(sorted(blast_radius)[:5])})."
        )
    checklist.append("Run `audit_diff` on your staged files before committing.")

    return TaskBriefingResult(
        task=task,
        files=touched_files,
        primary_adrs=[
            {
                "id": a.id,
                "title": a.title,
                "status": a.status,
                "description": a.description,
                "tags": a.tags,
                "code_paths": a.paths,
            }
            for a in sorted(relevant_adrs_map.values(), key=lambda x: g._k(x.id))
        ],
        invariants=invariants,
        blast_radius=sorted(blast_radius, key=g._k),
        neighboring_context=sorted(neighbors, key=g._k)[:10],
        recommended_checklist=checklist,
    )
