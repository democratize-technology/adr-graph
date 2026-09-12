"""Tests for the auditor module: audit_diff and task_briefing."""

from __future__ import annotations

import textwrap
from pathlib import Path
import pytest

from adr_graph.auditor import (
    extract_requirements,
    extract_files_from_diff,
    audit_diff,
    task_briefing,
)
from adr_graph.graph import Graph
from adr_graph.formatters import format_audit_diff, format_task_briefing
from adr_graph.__main__ import main


@pytest.fixture
def project_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path
    adr_dir = repo_root / "docs" / "adr"
    adr_dir.mkdir(parents=True)

    # 1. ADR-1 with body requirements block
    adr1_content = textwrap.dedent(
        """\
        ---
        id: ADR-1
        title: JWT Authentication Architecture
        type: adr
        timestamp: 2026-08-01T00:00:00Z
        status: accepted
        code_paths:
          - src/auth/**
          - src/middleware/auth.ts
        tags:
          - auth
          - security
          - jwt
        ---

        # ADR-1: JWT Authentication Architecture

        <!-- adr:requirements -->
        ```yaml
        requirements:
          - id: AUTH-01
            description: Must use RS256 algorithm for JWT signing
            category: security
            verification:
              type: grep
              pattern: "RS256"
              paths:
                - src/auth/config.ts
              expect: present
          - id: AUTH-02
            description: Never log raw bearer token
            category: privacy
            verification:
              type: grep
              pattern: "console\\.log.*token"
              paths:
                - src/auth/**/*.ts
              expect: absent
        ```
        <!-- /adr:requirements -->

        We decide to use RS256 for all JWT signatures.
        """
    )
    (adr_dir / "001-jwt-auth.md").write_text(adr1_content, encoding="utf-8")

    # 2. ADR-2 with frontmatter requirements referencing ADR-1
    adr2_content = textwrap.dedent(
        """\
        ---
        id: ADR-2
        title: Database Connection Pooling
        type: adr
        timestamp: 2026-08-02T00:00:00Z
        status: accepted
        code_paths:
          - src/db/**
        tags:
          - database
          - performance
        requirements:
          - id: DB-01
            description: Max connections pool limit is 20
            category: performance
            verification:
              type: grep
              pattern: "max_connections.*20"
              paths:
                - src/db/pool.py
              expect: present
        related:
          - ADR-1
        ---

        # ADR-2: Database Connection Pooling

        Connects to auth services [[ADR-1]].
        """
    )
    (adr_dir / "002-db-pooling.md").write_text(adr2_content, encoding="utf-8")

    # Create code files in repo
    auth_dir = repo_root / "src" / "auth"
    auth_dir.mkdir(parents=True)
    (auth_dir / "config.ts").write_text(
        "export const config = { algorithm: 'RS256', secret: 'abc' };\n", encoding="utf-8"
    )
    (auth_dir / "service.ts").write_text(
        "export function verifyToken() { return true; }\n", encoding="utf-8"
    )

    db_dir = repo_root / "src" / "db"
    db_dir.mkdir(parents=True)
    (db_dir / "pool.py").write_text(
        "config = {'max_connections': 20}\n", encoding="utf-8"
    )

    utils_dir = repo_root / "src" / "utils"
    utils_dir.mkdir(parents=True)
    (utils_dir / "math.py").write_text(
        "def add(a, b): return a + b\n", encoding="utf-8"
    )

    return repo_root, adr_dir


def test_extract_requirements_both_sources(project_repo):
    repo_root, adr_dir = project_repo
    g = Graph.build(adr_dir)

    adr1 = g.adrs["ADR-1"]
    reqs1 = extract_requirements(adr1)
    assert len(reqs1) == 2
    assert reqs1[0]["id"] == "AUTH-01"
    assert reqs1[1]["id"] == "AUTH-02"

    adr2 = g.adrs["ADR-2"]
    reqs2 = extract_requirements(adr2)
    assert len(reqs2) == 1
    assert reqs2[0]["id"] == "DB-01"


def test_extract_files_from_diff():
    diff_text = textwrap.dedent(
        """\
        diff --git a/src/auth/config.ts b/src/auth/config.ts
        --- a/src/auth/config.ts
        +++ b/src/auth/config.ts
        @@ -1,2 +1,2 @@
        -export const old = 1;
        +export const config = { algorithm: 'RS256' };
        diff --git a/deleted.txt b//dev/null
        --- a/deleted.txt
        +++ /dev/null
        """
    )
    files = extract_files_from_diff(diff_text)
    assert "src/auth/config.ts" in files
    assert "/dev/null" not in files


def test_audit_diff_clean(project_repo):
    repo_root, adr_dir = project_repo
    g = Graph.build(adr_dir)

    res = audit_diff(
        g,
        files=["src/auth/config.ts", "src/db/pool.py"],
        repo_root=repo_root,
    )

    assert res.ok is True
    assert res.invariants_violated == 0
    assert res.invariants_passed == 3
    assert len(res.governing_adrs) == 2
    assert len(res.unindexed_files) == 0


def test_audit_diff_violation_expect_present(project_repo):
    repo_root, adr_dir = project_repo
    # Break RS256 invariant
    (repo_root / "src" / "auth" / "config.ts").write_text(
        "export const config = { algorithm: 'HS256' };\n", encoding="utf-8"
    )

    g = Graph.build(adr_dir)
    res = audit_diff(g, files=["src/auth/config.ts"], repo_root=repo_root)

    assert res.ok is False
    assert res.invariants_violated == 1
    violation = [c for c in res.checks if c.status == "violated"][0]
    assert violation.id == "AUTH-01"
    assert "missing" in violation.detail


def test_audit_diff_violation_expect_absent(project_repo):
    repo_root, adr_dir = project_repo
    # Add forbidden console.log(token)
    (repo_root / "src" / "auth" / "service.ts").write_text(
        "export function login(token: string) { console.log('token is', token); }\n",
        encoding="utf-8",
    )

    g = Graph.build(adr_dir)
    res = audit_diff(g, files=["src/auth/service.ts"], repo_root=repo_root)

    assert res.ok is False
    assert res.invariants_violated == 1
    violation = [c for c in res.checks if c.status == "violated"][0]
    assert violation.id == "AUTH-02"
    assert "found" in violation.detail


def test_audit_diff_unindexed_file(project_repo):
    repo_root, adr_dir = project_repo
    g = Graph.build(adr_dir)

    res = audit_diff(g, files=["src/utils/math.py"], repo_root=repo_root)
    assert res.ok is True
    assert "src/utils/math.py" in res.unindexed_files


def test_audit_diff_with_diff_input(project_repo):
    repo_root, adr_dir = project_repo
    g = Graph.build(adr_dir)

    diff = "+++ b/src/auth/config.ts\n@@ -1,1 +1,1 @@\n+change\n"
    res = audit_diff(g, git_diff=diff, repo_root=repo_root)
    assert res.ok is True
    assert "src/auth/config.ts" in res.files_checked


def test_task_briefing_by_keywords_and_files(project_repo):
    repo_root, adr_dir = project_repo
    g = Graph.build(adr_dir)

    res = task_briefing(
        g,
        task="Refactor JWT token parsing and authentication headers",
        files=["src/auth/service.ts"],
    )

    assert res.task == "Refactor JWT token parsing and authentication headers"
    adr_ids = [a["id"] for a in res.primary_adrs]
    assert "ADR-1" in adr_ids

    # Should include invariants from ADR-1
    req_ids = [inv["id"] for inv in res.invariants]
    assert "AUTH-01" in req_ids
    assert "AUTH-02" in req_ids

    # Should contain checklist
    assert len(res.recommended_checklist) > 0


def test_formatters_render_valid_results(project_repo):
    repo_root, adr_dir = project_repo
    g = Graph.build(adr_dir)

    audit_res = audit_diff(
        g, files=["src/auth/config.ts", "src/db/pool.py"], repo_root=repo_root
    )
    tr_audit = format_audit_diff(audit_res.to_dict())
    assert tr_audit.content is not None
    assert "Satisfied Invariants" in tr_audit.content[0].text
    assert tr_audit.structured_content is not None

    brief_res = task_briefing(
        g, task="Update JWT verification logic", files=["src/auth/config.ts"]
    )
    tr_brief = format_task_briefing(brief_res.to_dict())
    assert tr_brief.content is not None
    assert "Governing Decisions" in tr_brief.content[0].text
    assert tr_brief.structured_content is not None


def test_cli_subcommands(project_repo, capsys):
    repo_root, adr_dir = project_repo

    # 1. CLI audit
    rc = main(["audit", "--root", str(adr_dir), "--files", "src/auth/config.ts"])
    assert rc == 0
    out, _ = capsys.readouterr()
    assert '"ok": true' in out
    assert "AUTH-01" in out

    # 2. CLI briefing
    rc2 = main(["briefing", "--root", str(adr_dir), "Refactor JWT security", "--files", "src/auth/config.ts"])
    assert rc2 == 0
    out2, _ = capsys.readouterr()
    assert "ADR-1" in out2
    assert "AUTH-01" in out2
