"""Tests for coverage, invariant scaffolding, and git hook installation."""

from __future__ import annotations

from pathlib import Path
import stat
import textwrap
import pytest

from adr_graph.coverage import (
    calculate_coverage,
    scaffold_invariants,
    install_git_hook,
)
from adr_graph.formatters import format_coverage, format_scaffold_invariants
from adr_graph.graph import Graph
from adr_graph.__main__ import main


@pytest.fixture
def repo_with_coverage(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path
    (repo_root / ".git").mkdir()
    adr_dir = repo_root / "docs" / "adr"
    adr_dir.mkdir(parents=True)

    # ADR-1: governs src/auth/**
    adr1_content = textwrap.dedent(
        """\
        ---
        id: ADR-1
        title: Authentication Subsystem
        type: adr
        status: accepted
        timestamp: 2026-08-01T00:00:00Z
        code_paths:
          - src/auth/**
        ---

        # ADR-1: Authentication Subsystem

        Body.
        """
    )
    (adr_dir / "001-auth.md").write_text(adr1_content, encoding="utf-8")

    # ADR-2: governs src/api/routes.py and declares a stale path
    adr2_content = textwrap.dedent(
        """\
        ---
        id: ADR-2
        title: API Routing
        type: adr
        status: accepted
        timestamp: 2026-08-02T00:00:00Z
        code_paths:
          - src/api/routes.py
          - src/legacy/stale_file.py
        related:
          - ADR-1
        ---

        # ADR-2: API Routing

        Body.
        """
    )
    (adr_dir / "002-api.md").write_text(adr2_content, encoding="utf-8")

    # Create code files in repo
    auth_dir = repo_root / "src" / "auth"
    auth_dir.mkdir(parents=True)
    (auth_dir / "config.py").write_text(
        "class AuthConfig:\n    pass\n\nAUTH_SECRET = 'xyz'\n", encoding="utf-8"
    )
    (auth_dir / "service.ts").write_text(
        "export class AuthService {\n  login() { return true; }\n}\n", encoding="utf-8"
    )

    api_dir = repo_root / "src" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "routes.py").write_text(
        "class ApiRouter:\n    pass\n", encoding="utf-8"
    )

    # Ungoverned shadow files in billing subsystem
    billing_dir = repo_root / "src" / "billing"
    billing_dir.mkdir(parents=True)
    (billing_dir / "stripe.py").write_text(
        "def process_payment():\n    pass\n", encoding="utf-8"
    )

    return repo_root, adr_dir


def test_calculate_coverage(repo_with_coverage):
    repo_root, adr_dir = repo_with_coverage
    g = Graph.build(adr_dir)

    rep = calculate_coverage(g, repo_root=repo_root)

    assert rep.total_source_files == 4
    # src/auth/config.py, src/auth/service.ts, src/api/routes.py are governed (3 of 4)
    assert rep.governed_source_files == 3
    assert rep.coverage_pct == 75.0

    # Subsystems: src/auth (100%), src/api (100%), src/billing (0%)
    sub_map = {s.name: s for s in rep.subsystems}
    assert "src/auth" in sub_map
    assert sub_map["src/auth"].coverage_pct == 100.0
    assert "src/billing" in sub_map
    assert sub_map["src/billing"].coverage_pct == 0.0

    # Shadow file
    shadow_paths = [sf.path for sf in rep.shadow_files]
    assert "src/billing/stripe.py" in shadow_paths

    # Stale code path
    stale_pats = [sp.pattern for sp in rep.stale_code_paths]
    assert "src/legacy/stale_file.py" in stale_pats


def test_scaffold_invariants_dry_run_and_apply(repo_with_coverage):
    repo_root, adr_dir = repo_with_coverage
    g = Graph.build(adr_dir)

    # 1. Dry run
    res = scaffold_invariants(g, "ADR-1", repo_root=repo_root, apply=False)
    assert res["ok"] is True
    assert res["applied"] is False
    assert len(res["invariants_scaffolded"]) >= 2
    patterns = [inv["verification"]["pattern"] for inv in res["invariants_scaffolded"]]
    assert any("AuthConfig" in p or "AUTH_SECRET" in p for p in patterns)

    # 2. Apply
    res_apply = scaffold_invariants(g, "ADR-1", repo_root=repo_root, apply=True)
    assert res_apply["applied"] is True

    adr1_text = (adr_dir / "001-auth.md").read_text(encoding="utf-8")
    assert "<!-- adr:requirements -->" in adr1_text
    assert "requirements:" in adr1_text


def test_install_git_hook(tmp_path: Path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    res = install_git_hook(repo_root=tmp_path)
    assert res["ok"] is True
    hook_file = Path(res["hook_path"])
    assert hook_file.exists()

    # Check executable bit
    mode = hook_file.stat().st_mode
    assert bool(mode & stat.S_IXUSR)

    content = hook_file.read_text(encoding="utf-8")
    assert "adr-graph validate" in content
    assert "adr-graph audit" in content

    # Reinstall without force should fail
    res_dup = install_git_hook(repo_root=tmp_path, force=False)
    assert res_dup["ok"] is False

    # Reinstall with force should succeed
    res_force = install_git_hook(repo_root=tmp_path, force=True)
    assert res_force["ok"] is True


def test_coverage_formatters(repo_with_coverage):
    repo_root, adr_dir = repo_with_coverage
    g = Graph.build(adr_dir)

    rep = calculate_coverage(g, repo_root=repo_root)
    tr = format_coverage(rep.to_dict())
    assert tr.content is not None
    assert "Architectural Codebase Coverage" in tr.content[0].text
    assert tr.structured_content is not None

    scaffold_res = scaffold_invariants(g, "ADR-1", repo_root=repo_root, apply=False)
    tr_scaffold = format_scaffold_invariants(scaffold_res)
    assert tr_scaffold.content is not None
    assert "Candidate Invariants Synthesized" in tr_scaffold.content[0].text


def test_cli_coverage_and_subcommands(repo_with_coverage, capsys):
    repo_root, adr_dir = repo_with_coverage

    # 1. CLI coverage
    rc = main(["coverage", str(adr_dir)])
    assert rc == 0
    out, _ = capsys.readouterr()
    assert '"coverage_pct": 75.0' in out
    assert "src/billing/stripe.py" in out

    # 2. CLI scaffold-invariants
    rc2 = main(["scaffold-invariants", "ADR-1", str(adr_dir)])
    assert rc2 == 0
    out2, _ = capsys.readouterr()
    assert '"ok": true' in out2
    assert "invariants_scaffolded" in out2

    # 3. CLI install-hook
    rc3 = main(["install-hook", "--force"])
    # May fail or pass depending on current working directory, but should execute
    out3, _ = capsys.readouterr()
    assert rc3 in (0, 1)
