"""Tests over a small synthetic ADR corpus written to a tmp dir.

Corpus shape:
  ADR-1  accepted, related:[ADR-2], body wikilink [[ADR-2]] + md link [ADR-3](./003-c.md)
  ADR-2  accepted, superseded_by:[ADR-3]            (reciprocal w/ 3 -> no break)
  ADR-3  accepted, supersedes:[ADR-2]
  ADR-4  accepted, supersedes:[ADR-1]               (ADR-1 lacks superseded_by -> break)
  ADR-5  proposed, isolated                          -> intentional singleton (status)
  ADR-6  accepted, isolated                          -> orphan suspect
  ADR-7  standalone:true, isolated                   -> intentional singleton (marker)
  ADR-8  accepted, body [[ADR-1]] + [[ADR-99]] + [[ADR-100]], planned:[ADR-100]
                                                      -> ADR-99 broken, ADR-100 planned signal
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from adr_graph import mutate
from adr_graph.graph import Graph
from adr_graph.parser import canon

FILES = {
    "001-a.md": ("ADR-001", "accepted", "related:\n  - ADR-002\n",
                 "# [[001-a|ADR-001]]\n\nSee [[ADR-002]] and [ADR-003](./003-c.md).\n"),
    "002-b.md": ("ADR-002", "accepted", "superseded_by:\n  - ADR-003\n", "# ADR-002\n\nBody.\n"),
    "003-c.md": ("ADR-003", "accepted", "supersedes:\n  - ADR-002\n", "# ADR-003\n\nBody.\n"),
    "004-d.md": ("ADR-004", "accepted", "supersedes:\n  - ADR-001\n", "# ADR-004\n\nBody.\n"),
    "005-e.md": ("ADR-005", "proposed", "", "# ADR-005\n\nNascent, nothing linked yet.\n"),
    "006-f.md": ("ADR-006", "accepted", "", "# ADR-006\n\nAccepted but linked to nothing.\n"),
    "007-g.md": ("ADR-007", "accepted", "standalone: true\n", "# ADR-007\n\nDeliberately standalone.\n"),
    "008-h.md": ("ADR-008", "accepted", "planned:\n  - ADR-100\n",
                 "# ADR-008\n\nRefs [[ADR-1]], [[ADR-99]], and planned [[ADR-100]].\n"),
}


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    for name, (adr_id, status, extra, body) in FILES.items():
        fm = f"---\nid: {adr_id}\ntitle: {name}\ntype: adr\ntimestamp: 2026-07-01T00:00:00Z\nstatus: {status}\n{extra}---\n\n{body}"
        (tmp_path / name).write_text(textwrap.dedent(fm), encoding="utf-8")
    return tmp_path


def test_canon_normalizes_padding():
    assert canon("ADR-007") == "ADR-7"
    assert canon("infrastructure/ADR-402") == "ADR-402"
    assert canon("nope") is None


def test_parses_both_link_channels(corpus):
    g = Graph.build(corpus)
    # ADR-1 reaches ADR-3 only via a markdown link (not a wikilink)
    assert "ADR-3" in g.out["ADR-1"]
    assert "ADR-2" in g.out["ADR-1"]


def test_singleton_classification(corpus):
    intentional, suspect = Graph.build(corpus).singletons()
    assert set(intentional) == {"ADR-7"}   # standalone
    assert "ADR-5" in suspect and "ADR-6" in suspect  # proposed + accepted are orphan suspects


def test_dead_link_disposition(corpus):
    planned, broken = Graph.build(corpus).dead_links()
    assert ("ADR-8", "ADR-100") in planned
    assert ("ADR-8", "ADR-99") in broken
    assert ("ADR-8", "ADR-100") not in broken


def test_reciprocity_breaks(corpus):
    breaks = Graph.build(corpus).reciprocity_breaks()
    pairs = {(a, b) for a, b, _ in breaks}
    assert ("ADR-4", "ADR-1") in pairs          # 1 lacks superseded_by
    assert ("ADR-3", "ADR-2") not in pairs       # reciprocal, fine


def test_drift_detects_body_only_link(corpus):
    drift = {a: (f, b) for a, f, b in Graph.build(corpus).drift()}
    assert "ADR-3" in drift["ADR-1"][1]          # ADR-3 in body, not in YAML related


def test_validate_fails_only_on_rot(corpus):
    rep = Graph.build(corpus).report()
    assert rep["ok"] is False                     # broken link + reciprocity exist
    assert rep["meta"]["adrs"] == 8
    assert len(rep["signals"]["intentional_singletons"]) == 1


def test_neighbors(corpus):
    n = Graph.build(corpus).neighbors("ADR-1", depth=1)
    assert set(n["outbound"]) == {"ADR-2", "ADR-3"}
    assert "ADR-4" in n["inbound"]


def test_reconcile_proposes_body_only_links(corpus):
    res = mutate.reconcile_related(corpus, adr_id="ADR-1", apply=False)
    adds = res["proposals"][0]["add_to_related"]
    assert "ADR-3" in adds and "ADR-2" not in adds  # ADR-2 already in related


def test_supersede_writes_both_sides(corpus):
    mutate.supersede(corpus, superseding="ADR-1", superseded="ADR-6")
    g = Graph.build(corpus)
    assert "ADR-6" in g.out["ADR-1"]
    assert not any((a, b) == ("ADR-1", "ADR-6") for a, b, _ in g.reciprocity_breaks())


def test_list_adrs_filtering(corpus):
    g = Graph.build(corpus)
    proposed = g.list_adrs(status="proposed")
    assert [a.id for a in proposed] == ["ADR-5"]
    accepted = g.list_adrs(status="accepted")
    assert len(accepted) == 7


def test_search_adrs(corpus):
    g = Graph.build(corpus)
    results = g.search_adrs("005-e")
    assert [a.id for a in results] == ["ADR-5"]


def test_find_path(corpus):
    g = Graph.build(corpus)
    p = g.find_path("ADR-4", "ADR-3")
    assert p["path"] == ["ADR-4", "ADR-1", "ADR-3"]
    p2 = g.find_path("ADR-5", "ADR-3")
    assert p2["path"] is None


def test_set_status(corpus):
    res = mutate.set_status(corpus, "ADR-6", "deprecated")
    assert res["ok"] is True
    g = Graph.build(corpus)
    assert g.adrs["ADR-6"].status == "deprecated"


def test_cascade_rename(corpus):
    (corpus / "004-d.md").write_text(
        "---\nid: ADR-004\ntitle: 004-d.md\nstatus: accepted\nsupersedes:\n  - ../other-repo/001-a.md\n---\n\nBody.\n",
        encoding="utf-8"
    )
    res = mutate.rename(corpus, "ADR-1", "ADR-10", dry_run=False)
    assert res["ok"] is True
    assert not (corpus / "001-a.md").exists()
    assert (corpus / "010-a.md").exists()
    g = Graph.build(corpus)
    assert "ADR-10" in g.adrs
    assert "ADR-1" not in g.adrs
    adr10_path = g.adrs["ADR-10"].path
    content10 = adr10_path.read_text(encoding="utf-8")
    assert "# [[010-a|ADR-010]]" in content10
    adr4_path = g.adrs["ADR-4"].path
    content4 = adr4_path.read_text(encoding="utf-8")
    assert "../other-repo/010-a.md" in content4


def test_list_adrs_pagination(corpus):
    g = Graph.build(corpus)
    accepted = g.list_adrs(status="accepted", limit=3, offset=1)
    assert len(accepted) == 3
    # First sorted is ADR-1, second is ADR-2, etc. With offset=1, limit=3: we expect ADR-2, ADR-3, ADR-4
    assert [a.id for a in accepted] == ["ADR-2", "ADR-3", "ADR-4"]


def test_propose_adr(corpus):
    res = mutate.propose(corpus, title="Use SQLite for configuration", tags=["db", "config"])
    assert res["ok"] is True
    assert res["adr_id"] == "ADR-9"
    assert (corpus / "009-use-sqlite-for-configuration.md").exists()
    
    g = Graph.build(corpus)
    assert "ADR-9" in g.adrs
    assert g.adrs["ADR-9"].title == "Use SQLite for configuration"
    assert g.adrs["ADR-9"].tags == ["db", "config"]


def test_blast_radius(corpus):
    g = Graph.build(corpus)
    # ADR-4 supersedes ADR-1
    # ADR-1 relates to ADR-2
    # So B referencing A -> A is dependencies, B is dependents.
    # ADR-1 is referenced by ADR-4 (supersedes: ADR-1) and ADR-8 (body refs [[ADR-1]])
    # ADR-2 is referenced by ADR-1 (related: ADR-2) and ADR-3 (supersedes: ADR-2)
    # Let's test blast radius of ADR-2: should include ADR-1 and ADR-3, and since ADR-1 is in it, it also includes ADR-4 and ADR-8!
    br = g.blast_radius("ADR-2")
    # All nodes that transitive-depend on ADR-2:
    assert "ADR-1" in br["blast_radius"]
    assert "ADR-3" in br["blast_radius"]
    assert "ADR-4" in br["blast_radius"]
    assert "ADR-8" in br["blast_radius"]


def test_graph_caching(corpus):
    from adr_graph.server import _graph
    g1 = _graph(str(corpus))
    g2 = _graph(str(corpus))
    assert g1 is g2  # Should return cached instance

    # Modify a file to invalidate cache
    import time
    time.sleep(0.1)  # ensure mtime updates
    (corpus / "006-f.md").write_text("# ADR-006\n\nModified.\n", encoding="utf-8")
    
    g3 = _graph(str(corpus))
    assert g1 is not g3  # Cache should have invalidated and rebuilt


def test_cli_missing_args():
    from adr_graph.__main__ import _cli
    assert _cli(["neighbors"]) == 2
    assert _cli(["read"]) == 2
    assert _cli(["search"]) == 2
    assert _cli(["path", "ADR-1"]) == 2
    assert _cli(["set-status", "ADR-1"]) == 2
    assert _cli(["rename", "ADR-1"]) == 2
    assert _cli(["blast-radius"]) == 2
    assert _cli(["propose"]) == 2


def test_hover_context(corpus):
    # Add code_paths to an ADR
    (corpus / "011-lsp.md").write_text(
        "---\nid: ADR-11\ntitle: Use LSP\nstatus: accepted\ncode_paths:\n  - src/api/**/*.py\n  - src/middleware.py\n---\n\nBody.\n",
        encoding="utf-8"
    )
    
    from adr_graph.server import hover_context
    
    # Test file that matches
    ctx = hover_context("src/api/auth/login.py", root=str(corpus))
    assert "**[ADR-11] Use LSP**" in ctx
    assert "Status: `accepted`" in ctx
    
    # Test file that does not match
    ctx_miss = hover_context("src/frontend/app.ts", root=str(corpus))
    assert "No architectural decisions explicitly govern this path." in ctx_miss


# ---------------------------------------------------------------------------
#  OKF v0.1 Standardization Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def okf_corpus(tmp_path: Path) -> Path:
    """Corpus designed to exercise OKF-specific features."""
    # ADR with all OKF fields present
    (tmp_path / "001-full.md").write_text(textwrap.dedent("""\
        ---
        id: ADR-1
        type: adr
        title: Use PostgreSQL
        description: We chose PostgreSQL as our primary relational database.
        resource: https://postgresql.org
        status: accepted
        tags: [database, infrastructure]
        timestamp: 2026-06-01T00:00:00Z
        ---

        # 1. Use PostgreSQL

        PostgreSQL offers mature JSONB support and strong community backing.
    """), encoding="utf-8")

    # ADR missing description, resource — migration target
    (tmp_path / "002-partial.md").write_text(textwrap.dedent("""\
        ---
        id: ADR-2
        type: adr
        title: Use Redis for caching
        status: proposed
        timestamp: 2026-06-15T00:00:00Z
        related:
          - ADR-1
        ---

        # 2. Use Redis for caching

        Redis provides sub-millisecond latency for hot-path queries.

        ## Decision Drivers
        * Performance requirements
    """), encoding="utf-8")

    # ADR with legacy 'date' field instead of 'timestamp'
    (tmp_path / "003-legacy.md").write_text(textwrap.dedent("""\
        ---
        id: ADR-3
        title: Adopt microservices
        status: accepted
        date: 2025-12-01
        ---

        # 3. Adopt microservices

        Breaking the monolith into domain-bounded services improves scalability.
    """), encoding="utf-8")

    # ADR with non-standard type (should be tolerated per OKF §4.1)
    (tmp_path / "004-playbook.md").write_text(textwrap.dedent("""\
        ---
        id: ADR-4
        type: playbook
        title: Incident Response Runbook
        description: Steps for handling production incidents.
        status: accepted
        timestamp: 2026-05-01T00:00:00Z
        ---

        # Incident Response

        Follow these steps when paged for a production incident.
    """), encoding="utf-8")

    # ADR missing everything (no type, no id, no title in frontmatter)
    (tmp_path / "005-bare.md").write_text(textwrap.dedent("""\
        ---
        status: draft
        ---

        # 5. Bare minimum ADR

        This ADR has almost no frontmatter metadata at all.
    """), encoding="utf-8")

    return tmp_path


def test_okf_relaxed_type_validation(okf_corpus):
    """OKF §4.1: type values are freeform. Only MISSING type is a violation."""
    g = Graph.build(okf_corpus)
    violations = g.okf_violations()
    violation_ids = {v[0] for v in violations}
    # ADR-3 (no type) and ADR-5 (no type) should be violations
    assert "ADR-3" in violation_ids
    assert "ADR-5" in violation_ids
    # ADR-4 has type: playbook — NOT a violation per OKF §4.1
    assert "ADR-4" not in violation_ids
    # ADR-1 and ADR-2 have type: adr — fine
    assert "ADR-1" not in violation_ids
    assert "ADR-2" not in violation_ids


def test_okf_description_and_resource_parsing(okf_corpus):
    """New OKF fields are parsed from frontmatter."""
    g = Graph.build(okf_corpus)
    adr1 = g.adrs["ADR-1"]
    assert adr1.description == "We chose PostgreSQL as our primary relational database."
    assert adr1.resource == "https://postgresql.org"
    # ADR-2 has no description or resource
    adr2 = g.adrs["ADR-2"]
    assert adr2.description == ""
    assert adr2.resource == ""


def test_okf_conformance_report(okf_corpus):
    """okf_conformance() returns violations, warnings, and coverage."""
    g = Graph.build(okf_corpus)
    report = g.okf_conformance()
    assert report["okf_version"] == "0.1"
    # ADR-3 and ADR-5 lack type → not conformant
    assert report["conformant"] is False
    assert len(report["violations"]) == 2
    # Warnings for missing description
    warning_adrs = {w["adr"] for w in report["warnings"]}
    assert "ADR-2" in warning_adrs  # no description
    assert "ADR-3" in warning_adrs  # no description
    assert "ADR-5" in warning_adrs  # no description
    # Coverage metrics
    assert report["coverage"]["type"] == "3/5"
    assert report["coverage"]["description"].startswith("2/")


def test_okf_validate_includes_violations(okf_corpus):
    """validate report includes OKF violations as defects."""
    report = Graph.build(okf_corpus).report()
    assert report["ok"] is False
    assert len(report["defects"]["okf_violations"]) == 2


def test_migrate_okf_dry_run(okf_corpus):
    """migrate_okf dry_run=True reports changes without writing."""
    result = mutate.migrate_okf(okf_corpus, dry_run=True)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["files_changed"] >= 2  # at least ADR-3 and ADR-5 need changes
    assert result["index_md"] == "would update"
    # Verify files were NOT modified
    text = (okf_corpus / "003-legacy.md").read_text()
    assert "date:" in text  # original 'date' field still there
    assert "index.md" not in [f.name for f in okf_corpus.iterdir()]


def test_migrate_okf_apply(okf_corpus):
    """migrate_okf dry_run=False actually writes changes."""
    result = mutate.migrate_okf(okf_corpus, dry_run=False)
    assert result["ok"] is True
    assert result["dry_run"] is False
    assert result["files_changed"] >= 2

    # ADR-3: date should be converted to timestamp
    text = (okf_corpus / "003-legacy.md").read_text()
    assert "date:" not in text
    assert "timestamp:" in text

    # ADR-3: type should be added
    assert "type:" in text

    # ADR-5: should now have id, title, type
    text5 = (okf_corpus / "005-bare.md").read_text()
    assert "type:" in text5
    assert "id:" in text5

    # index.md should be generated
    index_path = okf_corpus / "index.md"
    assert index_path.exists()
    index_text = index_path.read_text()
    assert "# Architecture Decision Records" in index_text
    assert "## Accepted" in index_text

    # Conformance should improve
    assert result["conformance"]["okf_version"] == "0.1"


def test_migrate_okf_description_synthesis(okf_corpus):
    """Migration synthesizes description from body text when missing."""
    mutate.migrate_okf(okf_corpus, dry_run=False)
    # ADR-2 had no description but has body text
    g = Graph.build(okf_corpus)
    adr2 = g.adrs["ADR-2"]
    assert adr2.description != ""
    assert "Redis" in adr2.description or "sub-millisecond" in adr2.description


def test_migrate_okf_index_generation(okf_corpus):
    """Migration generates OKF §6 index.md with progressive disclosure."""
    mutate.migrate_okf(okf_corpus, dry_run=False)
    index_text = (okf_corpus / "index.md").read_text()
    # Should group by status
    assert "## Accepted" in index_text
    assert "## Proposed" in index_text or "## Draft" in index_text
    # Should have links to ADR files
    assert ".md)" in index_text  # markdown links to files


def test_migrate_okf_field_ordering(okf_corpus):
    """OKF migration writes frontmatter with spec-recommended field order."""
    mutate.migrate_okf(okf_corpus, dry_run=False)
    text = (okf_corpus / "003-legacy.md").read_text()
    # Extract frontmatter
    import yaml
    lines = text.split("---")
    meta = yaml.safe_load(lines[1])
    keys = list(meta.keys())
    # OKF field order: id, type, title, description, resource, status, tags, timestamp
    # 'id' should come before 'status', 'type' should come before 'timestamp'
    if "id" in keys and "status" in keys:
        assert keys.index("id") < keys.index("status")
    if "type" in keys and "timestamp" in keys:
        assert keys.index("type") < keys.index("timestamp")


def test_okf_export_format(okf_corpus):
    """export(fmt='okf') returns OKF bundle metadata summary."""
    from adr_graph.exports import render
    g = Graph.build(okf_corpus)
    bundle = render(g, "okf")
    assert bundle["okf_version"] == "0.1"
    assert bundle["bundle"]["concepts"] == 5
    assert len(bundle["concepts"]) == 5
    # Each concept should have the full OKF shape
    concept = bundle["concepts"][0]
    assert "concept_id" in concept
    assert "type" in concept
    assert "title" in concept
    assert "description" in concept
    assert "resource" in concept
    assert "links" in concept


def test_mermaid_export_includes_titles(okf_corpus):
    """Mermaid export now includes titles in node labels."""
    from adr_graph.exports import render
    g = Graph.build(okf_corpus)
    mermaid = render(g, "mermaid")
    assert "Use PostgreSQL" in mermaid


def test_okf_conformance_cli(okf_corpus):
    """okf-conformance CLI command runs without error."""
    from adr_graph.__main__ import _cli
    # Should return 0 (always succeeds, it's a report)
    assert _cli(["okf-conformance", str(okf_corpus)]) == 0
