"""Codebase Coverage & Governance Intelligence.

Provides:
  - calculate_coverage: Architectural coverage analysis across repository files,
    highlighting subsystems, high-churn shadow architecture, and stale code paths.
  - scaffold_invariants: Synthesizes concrete, verifiable requirements from governing code paths.
  - install_git_hook: Installs zero-config pre-commit guardrail.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from .auditor import get_repo_root, path_matches, extract_requirements
from .graph import Graph, canonify

CODE_EXTENSIONS = {
    ".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".rb", ".php", ".swift", ".scala", ".proto", ".sql", ".sh",
}

IGNORED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__",
    ".pytest_cache", ".ruff_cache", ".next", ".turbo", "coverage", ".gemini",
    "docs", "vendor",
}


@dataclass
class SubsystemCoverage:
    name: str
    total_files: int
    governed_files: int
    coverage_pct: float
    governing_adrs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "total_files": self.total_files,
            "governed_files": self.governed_files,
            "coverage_pct": self.coverage_pct,
            "governing_adrs": self.governing_adrs,
        }


@dataclass
class ShadowFile:
    path: str
    commits: int
    subsystem: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "commits": self.commits,
            "subsystem": self.subsystem,
        }


@dataclass
class StaleCodePath:
    adr_id: str
    adr_title: str
    pattern: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "adr_id": self.adr_id,
            "adr_title": self.adr_title,
            "pattern": self.pattern,
        }


@dataclass
class CoverageReport:
    total_source_files: int
    governed_source_files: int
    coverage_pct: float
    subsystems: list[SubsystemCoverage]
    shadow_files: list[ShadowFile]
    stale_code_paths: list[StaleCodePath]
    adr_coverage_rank: list[dict[str, Any]]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_source_files": self.total_source_files,
            "governed_source_files": self.governed_source_files,
            "coverage_pct": self.coverage_pct,
            "subsystems": [s.to_dict() for s in self.subsystems],
            "shadow_files": [f.to_dict() for f in self.shadow_files],
            "stale_code_paths": [p.to_dict() for p in self.stale_code_paths],
            "adr_coverage_rank": self.adr_coverage_rank,
            "recommendations": self.recommendations,
        }


def list_repo_source_files(root: Path, source_dirs: list[str] | None = None) -> list[str]:
    """List tracked source code files relative to repo root."""
    files: list[str] = []

    # 1. Try git ls-files
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            raw_files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            for rf in raw_files:
                p = Path(rf)
                if p.suffix.lower() in CODE_EXTENSIONS:
                    parts = p.parts
                    if not any(ign in parts for ign in IGNORED_DIRS):
                        if not source_dirs or any(rf.startswith(sd.rstrip("/") + "/") or rf == sd for sd in source_dirs):
                            files.append(rf)
            return sorted(files)
    except (subprocess.SubprocessError, OSError):
        pass

    # 2. Fallback to walking filesystem
    scan_roots = [root / sd for sd in source_dirs] if source_dirs else [root]
    for sr in scan_roots:
        if not sr.exists():
            continue
        for curr_root, dirnames, filenames in os.walk(sr):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")]
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext in CODE_EXTENSIONS:
                    full_p = Path(curr_root) / fn
                    rel_p = str(full_p.relative_to(root))
                    files.append(rel_p)

    return sorted(files)


def get_git_churn(root: Path, churn_days: int = 90) -> dict[str, int]:
    """Count commit occurrences per file in the last N days."""
    churn: Counter[str] = Counter()
    try:
        res = subprocess.run(
            ["git", "log", f"--since={churn_days} days ago", "--name-only", "--format="],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.splitlines():
                f = line.strip()
                if f:
                    churn[f] += 1
    except (subprocess.SubprocessError, OSError):
        pass
    return dict(churn)


def _get_subsystem(rel_path: str) -> str:
    parts = Path(rel_path).parts
    if len(parts) <= 1:
        return "(root)"
    if parts[0] in ("src", "lib", "app", "packages") and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def calculate_coverage(
    g: Graph,
    repo_root: Path | None = None,
    source_dirs: list[str] | None = None,
    churn_days: int = 90,
) -> CoverageReport:
    """Calculate architectural codebase coverage, shadow architecture, and stale paths."""
    root = repo_root or get_repo_root(g.root)
    source_files = list_repo_source_files(root, source_dirs=source_dirs)
    churn = get_git_churn(root, churn_days=churn_days)

    # Index ADR path patterns (from code_paths and requirements)
    all_adr_patterns: dict[str, list[str]] = {}
    for adr in g.adrs.values():
        pats = list(adr.paths)
        for req in extract_requirements(adr):
            v_paths = req.get("verification", {}).get("paths", [])
            for vp in v_paths:
                p_str = str(vp).strip()
                if p_str and p_str not in pats:
                    pats.append(p_str)
        if pats:
            all_adr_patterns[adr.id] = pats

    # Determine governed status for each file
    governed_files: set[str] = set()
    file_governing_adrs: dict[str, list[str]] = {}
    adr_file_matches: dict[str, set[str]] = {aid: set() for aid in g.adrs}

    for f in source_files:
        matched: list[str] = []
        for aid, pats in all_adr_patterns.items():
            if any(path_matches(f, pat) for pat in pats):
                matched.append(aid)
                adr_file_matches[aid].add(f)
        if matched:
            governed_files.add(f)
            file_governing_adrs[f] = sorted(matched, key=g._k)
        else:
            file_governing_adrs[f] = []

    # Check for stale code paths
    stale_paths: list[StaleCodePath] = []
    for aid, pats in all_adr_patterns.items():
        adr = g.adrs[aid]
        for pat in pats:
            if not any(path_matches(f, pat) for f in source_files):
                # Also check disk directly if not matching known source files
                test_path = root / pat
                if not test_path.exists() and not any(root.glob(pat)):
                    stale_paths.append(
                        StaleCodePath(
                            adr_id=adr.id,
                            adr_title=adr.title,
                            pattern=pat,
                        )
                    )

    # Group by subsystem
    subsystem_files: dict[str, list[str]] = {}
    for f in source_files:
        sub = _get_subsystem(f)
        subsystem_files.setdefault(sub, []).append(f)

    subsystems: list[SubsystemCoverage] = []
    for sub, sfiles in sorted(subsystem_files.items()):
        g_count = sum(1 for sf in sfiles if sf in governed_files)
        pct = round((g_count / len(sfiles)) * 100.0, 1) if sfiles else 0.0
        gov_adrs: set[str] = set()
        for sf in sfiles:
            gov_adrs.update(file_governing_adrs.get(sf, []))
        subsystems.append(
            SubsystemCoverage(
                name=sub,
                total_files=len(sfiles),
                governed_files=g_count,
                coverage_pct=pct,
                governing_adrs=sorted(gov_adrs, key=g._k),
            )
        )

    # Identify high-churn shadow files (un-governed files with commits)
    shadow_files: list[ShadowFile] = []
    for f in source_files:
        if f not in governed_files:
            commit_count = churn.get(f, 0)
            shadow_files.append(
                ShadowFile(
                    path=f,
                    commits=commit_count,
                    subsystem=_get_subsystem(f),
                )
            )

    # Sort shadow files by commits descending
    shadow_files.sort(key=lambda sf: sf.commits, reverse=True)

    # Rank ADRs by coverage count
    adr_rank = [
        {
            "id": aid,
            "title": g.adrs[aid].title,
            "status": g.adrs[aid].status,
            "governed_files_count": len(files_set),
        }
        for aid, files_set in sorted(adr_file_matches.items(), key=lambda item: len(item[1]), reverse=True)
        if len(files_set) > 0
    ]

    tot = len(source_files)
    gov = len(governed_files)
    cov_pct = round((gov / tot) * 100.0, 1) if tot > 0 else 0.0

    # Recommendations
    recs: list[str] = []
    if cov_pct < 80.0:
        recs.append(f"Architectural coverage is {cov_pct}%. Prioritize documenting high-churn shadow subsystems.")
    if shadow_files and shadow_files[0].commits > 0:
        top_shadow = shadow_files[0]
        recs.append(
            f"File '{top_shadow.path}' had {top_shadow.commits} commits in {churn_days}d but has no governing ADR. Propose an ADR for subsystem '{top_shadow.subsystem}'."
        )
    if stale_paths:
        recs.append(
            f"Found {len(stale_paths)} stale code path declaration(s) in ADRs that match no files on disk. Prune or update them."
        )

    return CoverageReport(
        total_source_files=tot,
        governed_source_files=gov,
        coverage_pct=cov_pct,
        subsystems=subsystems,
        shadow_files=shadow_files[:20],
        stale_code_paths=stale_paths,
        adr_coverage_rank=adr_rank[:15],
        recommendations=recs,
    )


def scaffold_invariants(
    g: Graph,
    adr_id: str,
    repo_root: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Analyze code paths governed by an ADR and scaffold enforceable invariants."""
    aid = canonify(adr_id)
    if aid not in g.adrs:
        return {"ok": False, "error": f"ADR {adr_id} not found in graph"}

    adr = g.adrs[aid]
    root = repo_root or get_repo_root(g.root)

    source_files = list_repo_source_files(root)
    matched_files: list[Path] = [
        root / f for f in source_files if any(path_matches(f, pat) for pat in adr.paths)
    ]

    existing_reqs = extract_requirements(adr)
    existing_ids = {r.get("id") for r in existing_reqs}
    candidate_invariants: list[dict[str, Any]] = []

    req_counter = len(existing_reqs) + 1

    for file_path in matched_files:
        rel_path = str(file_path.relative_to(root))
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        ext = file_path.suffix.lower()

        # 1. Python symbol extract
        if ext == ".py":
            # Class definitions
            for m in re.finditer(r"^class\s+([A-Za-z0-9_]+)(?:\((.*?)\))?:", content, re.M):
                cls_name = m.group(1)
                req_id = f"{aid}-CLASS-{req_counter:03d}"
                if req_id not in existing_ids:
                    candidate_invariants.append({
                        "id": req_id,
                        "description": f"Preserve core class definition '{cls_name}'",
                        "category": "architecture",
                        "verification": {
                            "type": "grep",
                            "pattern": f"class\\s+{cls_name}\\b",
                            "paths": [rel_path],
                            "expect": "present",
                        },
                    })
                    req_counter += 1

            # Top-level entry point or config definitions
            for m in re.finditer(r"^([A-Z][A-Z0-9_]{3,})\s*=", content, re.M):
                const_name = m.group(1)
                req_id = f"{aid}-CONST-{req_counter:03d}"
                if req_id not in existing_ids:
                    candidate_invariants.append({
                        "id": req_id,
                        "description": f"Preserve architectural configuration constant '{const_name}'",
                        "category": "architecture",
                        "verification": {
                            "type": "grep",
                            "pattern": f"^{const_name}\\s*=",
                            "paths": [rel_path],
                            "expect": "present",
                        },
                    })
                    req_counter += 1

        # 2. TypeScript / JavaScript symbol extract
        elif ext in (".ts", ".tsx", ".js", ".jsx"):
            for m in re.finditer(r"export\s+(?:default\s+)?(?:class|function|const|interface|type)\s+([A-Za-z0-9_]+)", content):
                sym = m.group(1)
                req_id = f"{aid}-EXPORT-{req_counter:03d}"
                if req_id not in existing_ids:
                    candidate_invariants.append({
                        "id": req_id,
                        "description": f"Preserve exported interface/component '{sym}'",
                        "category": "interface",
                        "verification": {
                            "type": "grep",
                            "pattern": f"export\\s+.*\\b{sym}\\b",
                            "paths": [rel_path],
                            "expect": "present",
                        },
                    })
                    req_counter += 1

    # Cap to top 6 most relevant invariants to avoid flooding
    candidate_invariants = candidate_invariants[:6]

    applied = False
    if apply and candidate_invariants:
        import yaml

        # Format requirements block
        all_reqs = existing_reqs + candidate_invariants
        dumped_yaml = yaml.dump({"requirements": all_reqs}, sort_keys=False, default_flow_style=False)
        req_block = f"\n<!-- adr:requirements -->\n```yaml\n{dumped_yaml}```\n<!-- /adr:requirements -->\n"

        adr_text = adr.path.read_text(encoding="utf-8", errors="replace")
        from .auditor import _REQUIREMENTS_BLOCK
        if _REQUIREMENTS_BLOCK.search(adr_text):
            updated_text = _REQUIREMENTS_BLOCK.sub(req_block.strip(), adr_text)
        else:
            updated_text = adr_text.rstrip() + "\n\n" + req_block.strip() + "\n"

        adr.path.write_text(updated_text, encoding="utf-8")
        applied = True

    return {
        "ok": True,
        "adr_id": aid,
        "adr_title": adr.title,
        "governed_files_scanned": [str(p.relative_to(root)) for p in matched_files],
        "invariants_scaffolded": candidate_invariants,
        "applied": applied,
    }


def install_git_hook(repo_root: Path | None = None, hook_type: str = "pre-commit", force: bool = False) -> dict[str, Any]:
    """Install zero-config git pre-commit hook to enforce ADR graph validation and diff audits."""
    root = repo_root or Path.cwd()
    git_dir = root / ".git"
    if not git_dir.exists() or not git_dir.is_dir():
        return {"ok": False, "error": f"No .git directory found in {root}"}

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_file = hooks_dir / hook_type

    if hook_file.exists() and not force:
        return {
            "ok": False,
            "error": f"Hook {hook_file} already exists. Pass force=True to overwrite.",
            "hook_path": str(hook_file),
        }

    script_content = """#!/usr/bin/env sh
# Installed by adr-graph
# Verifies ADR graph integrity and audits staged changes against invariants

set -e

if ! command -v adr-graph >/dev/null 2>&1; then
    # adr-graph not installed in PATH, skip check
    exit 0
fi

echo "🔍 [adr-graph] Validating ADR graph integrity..."
if ! adr-graph validate >/dev/null 2>&1; then
    echo "❌ [adr-graph] Architecture decision graph has defects (broken links, singletons, or reciprocity breaks)!" >&2
    echo "   Run 'adr-graph validate' to inspect and remediate." >&2
    exit 1
fi

echo "🔍 [adr-graph] Auditing staged code changes against governing ADR invariants..."
if ! adr-graph audit >/dev/null 2>&1; then
    echo "❌ [adr-graph] Staged code violates governing ADR invariants!" >&2
    echo "   Run 'adr-graph audit' to inspect violations or propose a superseding ADR." >&2
    exit 1
fi

echo "✅ [adr-graph] Architecture decision verification passed."
exit 0
"""
    hook_file.write_text(script_content, encoding="utf-8")
    try:
        os.chmod(hook_file, 0o755)
    except OSError:
        pass

    return {
        "ok": True,
        "hook_path": str(hook_file),
        "hook_type": hook_type,
        "message": f"Successfully installed executable {hook_type} hook at {hook_file}",
    }
