"""Configuration: how the ADR corpus root is resolved.

Resolution order:
  1. explicit argument passed to a tool/CLI call
  2. ADR_GRAPH_ROOT environment variable
  3. ./docs/adr relative to the current working directory
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

class ADRSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", env_file_encoding="utf-8", extra="ignore")
    
    adr_graph_root: str = "docs/adr"

_GLOBAL_ROOT: str | None = None

def set_global_root(path: str | None) -> None:
    global _GLOBAL_ROOT
    _GLOBAL_ROOT = path

def get_global_root() -> str | None:
    return _GLOBAL_ROOT

# --- Corpus policy ----------------------------------------------------------
# Defaults match the published README contract. A corpus overrides them with a
# policy NODE: a markdown file in the root whose frontmatter carries
# `type: policy`. Deliberately NOT a sidecar outside the corpus — a sidecar that
# goes missing falls back silently, which is a gate weaker than declared and
# unobservable at the tree SHA. A policy node's absence is visible to the same
# tooling that reports dead links.

# Statuses that make an unconnected node an *intentional* frontier, not an orphan.
DEFAULT_SEED_STATUSES = frozenset({"proposed", "draft", "seed"})
# Tags that signal the same intent.
DEFAULT_SEED_TAGS = frozenset({"standalone", "frontier"})
# Subject scopes whose truth does not live in the tree, and so must declare how
# they are discharged. `commit` is the default scope and needs no discharge.
DEFAULT_SCOPES_REQUIRING_DISCHARGE = frozenset({"per-machine", "deployment"})
# Accepted ways to discharge such a scope.
DEFAULT_DISCHARGE_FORMS = frozenset({"heartbeat", "named-unverifiable"})

# By default, singletons are treated as defects (not deliberate).
# A corpus policy node can configure `disallow_singletons: false` (or specify seed_statuses/seed_tags)
# to re-enable intentional singleton frontiers.
DEFAULT_DISALLOW_SINGLETONS = True

# Back-compat module-level names (previously hardcoded; SEED_STATUSES was empty,
# which silently contradicted the README's disposition table).
SEED_STATUSES = DEFAULT_SEED_STATUSES
SEED_TAGS = DEFAULT_SEED_TAGS

_FM_SPLIT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


@dataclass(frozen=True)
class Policy:
    """Corpus disposition policy. Loaded from a policy node, else defaults."""

    disallow_singletons: bool = DEFAULT_DISALLOW_SINGLETONS
    seed_statuses: frozenset[str] = DEFAULT_SEED_STATUSES
    seed_tags: frozenset[str] = DEFAULT_SEED_TAGS
    scopes_requiring_discharge: frozenset[str] = DEFAULT_SCOPES_REQUIRING_DISCHARGE
    discharge_forms: frozenset[str] = DEFAULT_DISCHARGE_FORMS
    # Sibling ADR roots in the same product, relative to this root or absolute.
    # A corpus is per-repo: a reference to a decision living in a sibling root is
    # a documented coverage edge, NOT a dangling link. Without this, one-root
    # validation reports every cross-root reference as broken — a validator that
    # cannot say "outside my root" says "missing" instead.
    sibling_roots: tuple[str, ...] = ()
    source: str = "defaults"

    @property
    def is_declared(self) -> bool:
        """True when a policy node supplied these values."""
        return self.source != "defaults"


def _as_frozenset(val: Any, fallback: frozenset[str]) -> frozenset[str]:
    if val is None:
        return fallback
    items = val if isinstance(val, (list, tuple, set)) else [val]
    out = {str(i).strip().lower() for i in items if str(i).strip()}
    return frozenset(out) if out else fallback


def load_policy(root: Path) -> Policy:
    """Find the corpus policy node in `root` and read its frontmatter.

    A policy node is any top-level markdown file whose frontmatter declares
    `type: policy`. Absent or unreadable, documented defaults apply and
    `Policy.source` stays "defaults" so callers can report which was used.
    """
    try:
        candidates = sorted(p for p in root.glob("*.md") if p.is_file())
    except OSError:
        return Policy()
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _FM_SPLIT.match(text)
        if not m:
            continue
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(meta, dict):
            continue
        if str(meta.get("type", "")).strip().lower() != "policy":
            continue

        disallow_singletons = DEFAULT_DISALLOW_SINGLETONS
        if "disallow_singletons" in meta:
            disallow_singletons = bool(meta.get("disallow_singletons"))
        elif "allow_intentional_singletons" in meta:
            disallow_singletons = not bool(meta.get("allow_intentional_singletons"))
        elif "seed_statuses" in meta or "seed_tags" in meta:
            disallow_singletons = False

        return Policy(
            disallow_singletons=disallow_singletons,
            seed_statuses=_as_frozenset(meta.get("seed_statuses"), DEFAULT_SEED_STATUSES),
            seed_tags=_as_frozenset(meta.get("seed_tags"), DEFAULT_SEED_TAGS),
            scopes_requiring_discharge=_as_frozenset(
                meta.get("scopes_requiring_discharge"), DEFAULT_SCOPES_REQUIRING_DISCHARGE
            ),
            discharge_forms=_as_frozenset(meta.get("discharge_forms"), DEFAULT_DISCHARGE_FORMS),
            sibling_roots=_as_paths(meta.get("sibling_roots")),
            source=path.name,
        )
    return Policy()


def _as_paths(val: Any) -> tuple[str, ...]:
    if val is None:
        return ()
    items = val if isinstance(val, (list, tuple)) else [val]
    return tuple(str(i).strip() for i in items if str(i).strip())


def sibling_root_ids(root: Path, policy: Policy) -> frozenset[str]:
    """Canonical ADR ids present in the declared sibling roots.

    Used to disposition a reference that does not resolve in THIS root: if it
    resolves in a declared sibling, it is a cross-root coverage edge (signal),
    not a dangling reference (defect).
    """
    if not policy.sibling_roots:
        return frozenset()
    found: set[str] = set()
    for spec in policy.sibling_roots:
        p = Path(spec).expanduser()
        if not p.is_absolute():
            p = (root / spec).resolve()
        try:
            entries = list(p.glob("*.md"))
        except OSError:
            continue
        for f in entries:
            m = re.match(r"0*(\d+)", f.name)
            if m:
                found.add(f"ADR-{int(m.group(1))}")
    return frozenset(found)


def resolve_root(explicit: str | None = None) -> Path:
    settings = ADRSettings()
    candidate = explicit or get_global_root() or settings.adr_graph_root
    root = Path(candidate).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"ADR root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"ADR root is not a directory: {root}")
    return root


async def async_resolve_root(ctx: Any | None = None, explicit: str | None = None) -> Path:
    if explicit:
        return resolve_root(explicit)
    if ctx:
        try:
            roots = await ctx.request_roots()
            if roots:
                for r in roots:
                    if r.uri.startswith("file://"):
                        p = Path(r.uri[7:])
                        if (p / "docs/adr").exists():
                            return resolve_root(str(p / "docs/adr"))
                        if (p / "adr").exists():
                            return resolve_root(str(p / "adr"))
                        try:
                            return resolve_root(str(p))
                        except (FileNotFoundError, NotADirectoryError):
                            pass
        except Exception:
            pass
    return resolve_root(None)


def get_ctx_callbacks(ctx: Any | None) -> tuple[Any, Any]:
    """Helper to convert a FastMCP Context into progress and logging callbacks.
    
    Uses asyncio.create_task to invoke the async Context methods from synchronous code safely.
    """
    if not ctx:
        return None, None
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None, None

    def progress_cb(current: int, total: int, filename: str):
        loop.create_task(ctx.report_progress(current, total, message=f"Parsing {filename}"))

    def log_cb(level: str, message: str):
        if level == "warning":
            loop.create_task(ctx.warning(message))
        elif level == "error":
            loop.create_task(ctx.error(message))
        else:
            loop.create_task(ctx.info(message))

    return progress_cb, log_cb
