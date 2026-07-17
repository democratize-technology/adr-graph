"""Configuration: how the ADR corpus root is resolved.

Resolution order:
  1. explicit argument passed to a tool/CLI call
  2. ADR_GRAPH_ROOT environment variable
  3. ./docs/adr relative to the current working directory
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

ENV_VAR = "ADR_GRAPH_ROOT"

_GLOBAL_ROOT: str | None = None

def set_global_root(path: str | None) -> None:
    global _GLOBAL_ROOT
    _GLOBAL_ROOT = path

def get_global_root() -> str | None:
    return _GLOBAL_ROOT

# Statuses that make an unconnected node an *intentional* frontier, not an orphan.
SEED_STATUSES = set()
# Tags that signal the same intent.
SEED_TAGS = {"standalone"}


def resolve_root(explicit: str | None = None) -> Path:
    candidate = explicit or get_global_root() or os.environ.get(ENV_VAR) or "docs/adr"
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
