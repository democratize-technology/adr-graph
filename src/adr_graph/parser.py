"""Parse a directory of ADR markdown files into a typed, in-memory graph model.

Captures three reference channels:
  * frontmatter typed edges: supersedes / superseded_by / related
  * body wikilinks:  [[ADR-123]] or [[123-slug|ADR-123]]
  * body markdown links: [ADR-123](./123-slug.md) or [text](./123-slug.md)

And intent markers that turn "incomplete" into "intentional":
  * status (see config.SEED_STATUSES)
  * tags (see config.SEED_TAGS)
  * standalone: true            -> deliberate singleton
  * planned / forward_refs: []  -> intentional dead links (planned ADRs)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_NUM = re.compile(r"ADR-0*(\d+)", re.I)
_FILENUM = re.compile(r"^0*(\d+)\b")
_WIKI = re.compile(r"\[\[([^\]]+)\]\]")
_MDLINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_FM_SPLIT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def canon(text: object) -> str | None:
    """Normalise any reference to a canonical 'ADR-<int>' id (drops zero padding)."""
    if text is None:
        return None
    s = str(text).strip()
    if s.isdigit():
        return f"ADR-{int(s)}"
    m = _NUM.search(s)
    return f"ADR-{int(m.group(1))}" if m else None


def _canon_from_href(href: str) -> tuple[str | None, bool]:
    """Resolve a markdown link href to an ADR id. Returns (id, is_cross_repo)."""
    cross = href.startswith("../")
    direct = canon(href)
    if direct:
        return direct, cross
    base = href.split("/")[-1]
    m = _FILENUM.match(base)
    return (f"ADR-{int(m.group(1))}", cross) if m else (None, cross)


@dataclass
class ADR:
    id: str
    num: int
    path: Path
    title: str = ""
    type: str = ""
    description: str = ""
    timestamp: str = ""
    status: str = ""
    tags: list[str] = field(default_factory=list)
    resource: str = ""
    paths: list[str] = field(default_factory=list)
    fm: dict[str, list[str]] = field(default_factory=dict)  # typed edges -> [ids]
    fm_cross: set[str] = field(default_factory=set)
    body_refs: set[str] = field(default_factory=set)
    body_cross: set[str] = field(default_factory=set)
    planned: set[str] = field(default_factory=set)
    standalone: bool = False
    unparseable_yaml: bool = False


def _fm_refs(val: object) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    if val is None:
        return out
    items = val if isinstance(val, list) else [val]
    for it in items:
        s = str(it).strip()
        cid = canon(s)
        if cid:
            out.append((cid, "/" in s.split("ADR-")[0] or s.startswith("../")))
    return out


def parse_file(path: Path) -> ADR:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict = {}
    m = _FM_SPLIT.match(text)
    body = text
    unparseable = False
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
            unparseable = True
        body = text[m.end():]
    if not isinstance(meta, dict):
        meta = {}

    nid = canon(meta.get("id"))
    fnum = _FILENUM.match(path.name)
    if not nid and fnum:
        nid = f"ADR-{int(fnum.group(1))}"
    nid = nid or path.stem
    num = int(nid.split("-")[1]) if nid.startswith("ADR-") and nid.split("-")[1].isdigit() else -1

    adr = ADR(id=nid, num=num, path=path)
    adr.unparseable_yaml = unparseable
    adr.title = str(meta.get("title") or path.stem)
    adr.type = str(meta.get("type") or "").strip()
    adr.description = str(meta.get("description") or "").strip()
    adr.timestamp = str(meta.get("timestamp") or meta.get("date") or "").strip()
    adr.status = str(meta.get("status") or "").strip().lower()
    tags = meta.get("tags") or []
    adr.tags = [str(t).strip().lower() for t in (tags if isinstance(tags, list) else [tags])]
    paths = meta.get("code_paths") or []
    adr.paths = [str(p).strip() for p in (paths if isinstance(paths, list) else [paths])]
    adr.resource = str(meta.get("resource") or "").strip()
    adr.standalone = bool(meta.get("standalone", False))

    for key in ("supersedes", "superseded_by", "related"):
        ids: list[str] = []
        for cid, cross in _fm_refs(meta.get(key)):
            ids.append(cid)
            if cross:
                adr.fm_cross.add(cid)
        adr.fm[key] = ids

    for key in ("planned", "forward_refs"):
        for cid, _ in _fm_refs(meta.get(key)):
            adr.planned.add(cid)

    for raw in _WIKI.findall(body):
        cid = canon(raw)
        if not cid:
            fn = _FILENUM.match(raw.split("|")[0].strip())
            cid = f"ADR-{int(fn.group(1))}" if fn else None
        if cid and cid != nid:
            adr.body_refs.add(cid)
            if "/" in raw.split("ADR-")[0]:
                adr.body_cross.add(cid)
    for href in _MDLINK.findall(body):
        if href.startswith(("http://", "https://", "#", "mailto:")):
            continue
        cid, cross = _canon_from_href(href)
        if cid and cid != nid:
            adr.body_refs.add(cid)
            if cross:
                adr.body_cross.add(cid)
    return adr


def parse_dir(root: Path) -> dict[str, ADR]:
    adrs: dict[str, ADR] = {}
    for path in sorted(root.rglob("*.md")):
        if path.name.lower() in {"readme.md", "index.md", "log.md"}:
            continue
        adr = parse_file(path)
        adrs[adr.id] = adr
    return adrs
