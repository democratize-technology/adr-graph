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

# Statuses that make an unconnected node an *intentional* frontier, not an orphan.
SEED_STATUSES = set()
# Tags that signal the same intent.
SEED_TAGS = {"standalone"}


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
