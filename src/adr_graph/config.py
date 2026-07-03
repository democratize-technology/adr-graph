"""Configuration: how the ADR corpus root is resolved.

Resolution order:
  1. explicit argument passed to a tool/CLI call
  2. ADR_GRAPH_ROOT environment variable
  3. ./docs/adr relative to the current working directory
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "ADR_GRAPH_ROOT"

# Statuses that make an unconnected node an *intentional* frontier, not an orphan.
SEED_STATUSES = {
    "proposed", "draft", "idea", "seed", "exploratory",
    "parking-lot", "deferred", "rejected", "spike", "deprecated", "superseded",
}
# Tags that signal the same intent.
SEED_TAGS = {"seed", "parking-lot", "draft", "wip", "forward-ref"}


def resolve_root(explicit: str | None = None) -> Path:
    candidate = explicit or os.environ.get(ENV_VAR) or "docs/adr"
    root = Path(candidate).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"ADR root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"ADR root is not a directory: {root}")
    return root
