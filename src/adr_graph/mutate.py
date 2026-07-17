"""Mutating operations. These edit ADR frontmatter on disk.

Kept deliberately small and reciprocity-safe: `supersede` always writes both
sides of the edge, so a reciprocity break can never be introduced by the tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import re
import yaml

from .parser import _FILENUM, canon, parse_dir

_FM_PREFIX = "---\n"


def _load(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith(_FM_PREFIX):
        end = text.find("\n---", len(_FM_PREFIX))
        if end != -1:
            meta = yaml.safe_load(text[len(_FM_PREFIX):end]) or {}
            body = text[end + 4:]
            if body.startswith("\n"):
                body = body[1:]
            return (meta if isinstance(meta, dict) else {}), body
    return {}, text


def _write(path: Path, meta: dict, body: str) -> None:
    fm = yaml.safe_dump(meta, sort_keys=False, default_flow_style=False, allow_unicode=True).strip()
    path.write_text(f"---\n{fm}\n---\n\n{body.lstrip()}", encoding="utf-8")


def _append_unique(meta: dict, key: str, value: str) -> bool:
    cur = meta.get(key)
    items = [] if cur is None else (list(cur) if isinstance(cur, list) else [cur])
    if any(canon(x) == value for x in items):
        return False
    items.append(value)
    meta[key] = items
    return True


def supersede(root: Path, superseding: str, superseded: str) -> dict:
    a, b = canon(superseding), canon(superseded)
    if not a or not b:
        return {"ok": False, "error": "could not parse ADR ids"}
    paths = {adr.id: adr.path for adr in parse_dir(root).values()}
    if a not in paths or b not in paths:
        missing = [x for x in (a, b) if x not in paths]
        return {"ok": False, "error": f"unknown ADR(s): {missing}"}
    changed = []
    ma, ba = _load(paths[a])
    if _append_unique(ma, "supersedes", b):
        _write(paths[a], ma, ba)
        changed.append(f"{a}.supersedes += {b}")
    mb, bb = _load(paths[b])
    if _append_unique(mb, "superseded_by", a):
        _write(paths[b], mb, bb)
        changed.append(f"{b}.superseded_by += {a}")
    return {"ok": True, "changed": changed}


def reconcile_related(root: Path, adr_id: str | None = None, apply: bool = False) -> dict:
    adrs = parse_dir(root)
    nodes = set(adrs)
    targets = [canon(adr_id)] if adr_id else list(adrs)
    proposals = []
    for nid in targets:
        adr = adrs.get(nid)
        if not adr:
            continue
        typed = set(adr.fm.get("supersedes", [])) | set(adr.fm.get("superseded_by", []))
        existing = set(adr.fm.get("related", []))
        body_local = (adr.body_refs & nodes) - typed - {nid}
        additions = sorted(body_local - existing, key=lambda x: int(x.split("-")[-1]))
        if not additions:
            continue
        proposals.append({"adr": nid, "add_to_related": additions})
        if apply:
            meta, body = _load(adr.path)
            for cid in additions:
                _append_unique(meta, "related", cid)
            _write(adr.path, meta, body)
    return {"ok": True, "applied": apply, "proposals": proposals}


def set_status(root: Path, adr_id: str, status: str) -> dict[str, Any]:
    a = canon(adr_id)
    if not a:
        return {"ok": False, "error": "could not parse ADR id"}
    paths = {adr.id: adr.path for adr in parse_dir(root).values()}
    if a not in paths:
        return {"ok": False, "error": f"unknown ADR: {a}"}

    meta, body = _load(paths[a])
    status = status.strip().lower()
    meta["status"] = status
    _write(paths[a], meta, body)
    return {"ok": True, "changed": f"{a}.status = {status}"}


def rename(root: Path, old: str, new: str, dry_run: bool = True) -> dict[str, Any]:
    old_id = canon(old)
    new_id = canon(new)
    if not old_id or not new_id:
        return {"ok": False, "error": "Invalid ADR ID format"}

    adrs = parse_dir(root)
    if old_id not in adrs:
        return {"ok": False, "error": f"ADR {old_id} not found"}
    if new_id in adrs:
        return {"ok": False, "error": f"Target ADR {new_id} already exists"}

    old_adr = adrs[old_id]
    old_path = old_adr.path
    old_num = old_adr.num
    new_num = int(new_id.split("-")[1])

    m = _FILENUM.match(old_path.name)
    if m:
        old_num_str = m.group(0)
        new_num_str = str(new_num).zfill(len(old_num_str))
        new_name = old_path.name.replace(old_num_str, new_num_str, 1)
    else:
        new_name = old_path.name.replace(old_id, new_id)
        if new_name == old_path.name:
            new_name = f"{new_id.lower()}-{old_path.name}"

    new_path = old_path.parent / new_name
    if new_path.exists() and new_path != old_path:
        return {"ok": False, "error": f"Target file {new_name} already exists"}

    changes = []
    pattern = re.compile(rf"\bADR-0*{old_num}\b", re.I)

    def repl(match):
        orig = match.group(0)
        digits = [c for c in orig if c.isdigit()]
        prefix = "ADR-" if orig.startswith("ADR") else "adr-"
        return f"{prefix}{str(new_num).zfill(len(digits))}"

    old_stem = old_path.stem
    new_stem = new_path.stem
    stem_pattern = re.compile(rf"\b{re.escape(old_stem)}\b")

    def replace_id_in_str(s: str) -> str:
        res = pattern.sub(repl, s)
        res = stem_pattern.sub(new_stem, res)
        return res

    for nid, adr in adrs.items():
        meta, body = _load(adr.path)
        file_changed = False

        for key in ["id", "supersedes", "superseded_by", "related", "planned", "forward_refs"]:
            if key in meta:
                val = meta[key]
                if isinstance(val, list):
                    new_list = []
                    changed_list = False
                    for item in val:
                        s_orig = str(item)
                        s_new = replace_id_in_str(s_orig)
                        new_list.append(s_new)
                        if s_new != s_orig:
                            changed_list = True
                    if changed_list:
                        meta[key] = new_list
                        file_changed = True
                else:
                    s_orig = str(val)
                    s_new = replace_id_in_str(s_orig)
                    if s_new != s_orig:
                        meta[key] = s_new
                        file_changed = True

        new_body = pattern.sub(repl, body)
        new_body = stem_pattern.sub(new_stem, new_body)
        if new_body != body:
            file_changed = True

        if nid == old_id:
            changes.append(f"rename file: {adr.path.name} -> {new_name}")
            changes.append(f"update content in {new_name}")
            if not dry_run:
                _write(new_path, meta, new_body)
                if old_path != new_path:
                    old_path.unlink()
        else:
            if file_changed:
                changes.append(f"update references in {adr.path.name}")
                if not dry_run:
                    _write(adr.path, meta, new_body)

    return {"ok": True, "dry_run": dry_run, "changes": changes}


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def propose(root: Path, title: str, status: str = "proposed", context: str = "", tags: list[str] | None = None) -> dict[str, Any]:
    import datetime
    adrs = parse_dir(root)
    max_num = max([adr.num for adr in adrs.values()] + [0])
    next_num = max_num + 1

    slug = slugify(title)
    padding = 3
    for adr in adrs.values():
        m = _FILENUM.match(adr.path.name)
        if m:
            padding = max(padding, len(m.group(0)))

    filename = f"{str(next_num).zfill(padding)}-{slug}.md"
    file_path = root / filename

    if file_path.exists():
        filename = f"{str(next_num).zfill(padding)}-{slug}-{int(datetime.datetime.now().timestamp())}.md"
        file_path = root / filename

    meta = {
        "id": f"ADR-{next_num}",
        "type": "adr",
        "title": title,
        "description": context[:160] + ("..." if len(context) > 160 else "") if context else "",
        "status": status.strip().lower(),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
    }
    if tags:
        meta["tags"] = [t.strip().lower() for t in tags]

    body = f"""# {next_num}. {title}

## Context and Problem Statement
{context or "[Describe the context and problem statement here...]"}

## Decision Drivers
* [Driver 1]
* [Driver 2]

## Considered Options
* [Option 1]
* [Option 2]

## Decision Outcome
Chosen option: "[Option 1]", because [explanation].
"""

    _write_okf(file_path, meta, body)
    return {
        "ok": True,
        "adr_id": f"ADR-{next_num}",
        "filename": filename,
        "path": str(file_path),
    }


_OKF_FIELD_ORDER = ["id", "type", "title", "description", "resource", "status", "tags", "timestamp"]


def _ordered_meta(meta: dict) -> dict:
    """Return meta dict with OKF-recommended field ordering."""
    ordered = {}
    for key in _OKF_FIELD_ORDER:
        if key in meta:
            ordered[key] = meta[key]
    for key, val in meta.items():
        if key not in ordered:
            ordered[key] = val
    return ordered


def _write_okf(path: Path, meta: dict, body: str) -> None:
    """Write frontmatter with OKF field ordering."""
    _write(path, _ordered_meta(meta), body)


def _synthesize_description(body: str) -> str:
    """Extract a one-line description from the first substantive body paragraph.

    Skips headings, list items, table rows, blockquotes, and horizontal rules.
    """
    for line in body.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip headings, list items, blockquotes, table rows/separators, horizontal rules
        if stripped[0] in "#*->+|" or re.match(r'^\d+\.\s', stripped) or re.match(r'^-{3,}$|^\*{3,}$|^_{3,}$', stripped):
            continue
        # Strip markdown links and emphasis
        desc = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', stripped)
        desc = re.sub(r'[*_`]+', '', desc)
        desc = desc.strip()
        if len(desc) > 10:
            return desc[:160] + ("..." if len(desc) > 160 else "")
    return ""


def _generate_index(root: Path, adrs: dict) -> str:
    """Generate an OKF §6 index.md with §11 version declaration.

    Per §11 the root index.md is the one place frontmatter is permitted
    in an index file, specifically to declare okf_version.
    """
    parts = ["---\nokf_version: '0.1'\n---\n"]
    parts.append("# Architecture Decision Records\n")
    by_status: dict[str, list] = {}
    for adr in sorted(adrs.values(), key=lambda a: a.num):
        s = adr.status or "uncategorized"
        by_status.setdefault(s, []).append(adr)
    status_order = ["accepted", "proposed", "draft", "deprecated", "superseded", "rejected"]
    for status in status_order:
        group = by_status.pop(status, [])
        if group:
            parts.append(f"\n## {status.title()}\n")
            for a in group:
                desc = f" - {a.description}" if a.description else ""
                # Convert path to POSIX style for markdown links
                rel_path = a.path.relative_to(root).as_posix()
                parts.append(f"* [{a.title}](./{rel_path}){desc}")
    for status, group in sorted(by_status.items()):
        if group:
            parts.append(f"\n## {status.title()}\n")
            for a in group:
                desc = f" - {a.description}" if a.description else ""
                rel_path = a.path.relative_to(root).as_posix()
                parts.append(f"* [{a.title}](./{rel_path}){desc}")
    parts.append("")
    return "\n".join(parts)


async def migrate_okf(root: Path, dry_run: bool = True, ctx: Any = None) -> dict[str, Any]:
    """Migrate ADR corpus to OKF v0.1 conformance.

    Ensures type fields, converts date→timestamp, synthesizes missing
    descriptions, generates index.md. Dry-run by default.
    """
    adrs = parse_dir(root)
    file_changes: list[dict[str, Any]] = []

    total = len(adrs)
    for i, (nid, adr) in enumerate(sorted(adrs.items(), key=lambda x: x[1].num)):
        if ctx:
            await ctx.report_progress(i, total)
        meta, body = _load(adr.path)
        changes: list[str] = []

        # Ensure type field (don't overwrite existing non-empty types per OKF §4.1)
        if not meta.get("type"):
            meta["type"] = "adr"
            changes.append("added type: adr")

        # Convert legacy date → timestamp
        if "date" in meta and "timestamp" not in meta:
            meta["timestamp"] = meta.pop("date")
            changes.append("converted date → timestamp")

        # Ensure id field
        if "id" not in meta:
            meta["id"] = adr.id
            changes.append(f"added id: {adr.id}")

        # Ensure title field
        if not meta.get("title"):
            meta["title"] = adr.title
            changes.append(f"added title: {adr.title}")

        # Synthesize description if missing
        if not meta.get("description"):
            desc = _synthesize_description(body)
            if desc:
                meta["description"] = desc
                changes.append("synthesized description")

        if changes:
            if ctx:
                ctx.info(f"[{nid}] " + ", ".join(changes))
            if not dry_run:
                _write_okf(adr.path, meta, body)
            file_changes.append({"adr": nid, "file": adr.path.name, "changes": changes})

    if ctx:
        await ctx.report_progress(total, total)

    # Generate index.md
    index_path = root / "index.md"
    index_existed = index_path.exists()
    if not dry_run:
        # Re-parse to pick up any written changes
        adrs = parse_dir(root)
    index_content = _generate_index(root, adrs)
    if not dry_run:
        index_path.write_text(index_content, encoding="utf-8")

    # Build conformance summary
    from .graph import Graph
    g = Graph.build(root)
    conformance = g.okf_conformance()

    return {
        "ok": True,
        "dry_run": dry_run,
        "files_changed": len(file_changes),
        "changes": file_changes,
        "index_md": "would update" if dry_run else ("updated" if index_existed else "created"),
        "conformance": conformance,
    }


async def remediate_dark_nodes(root: Path, dry_run: bool = True, ctx: Any = None) -> dict[str, Any]:
    """Find plain-text ADR references or malformed wikilinks and convert them to valid wikilinks."""
    from .graph import Graph
    g = Graph.build(root)
    dark = g.dark_nodes()
    
    by_adr = {}
    for nid, raw, intended in dark:
        if nid not in by_adr:
            by_adr[nid] = []
        by_adr[nid].append((raw, intended))
        
    changes = []
    
    total = len(by_adr)
    for i, (nid, issues) in enumerate(by_adr.items()):
        if ctx:
            await ctx.report_progress(i, total)
        if nid not in g.adrs:
            continue
        path = g.adrs[nid].path
        meta, body = _load(path)
        
        file_changed = False
        
        for raw, intended in issues:
            if intended != "unresolved" and intended in g.adrs:
                target_adr = g.adrs[intended]
                correct_wiki = f"[[{target_adr.path.stem}|{target_adr.id}]]"
                
                # If it's already a wikilink but malformed (ghost node), replace it directly
                if f"[[{raw}]]" in body:
                    body = body.replace(f"[[{raw}]]", correct_wiki)
                    file_changed = True
                else:
                    # It's likely a plain text mention
                    pattern = r'\b' + re.escape(raw) + r'\b'
                    new_body = re.sub(pattern, correct_wiki, body)
                    if new_body != body:
                        body = new_body
                        file_changed = True
                        
        if file_changed:
            msg = f"Fixed dark nodes in {nid}"
            changes.append(msg)
            if ctx:
                ctx.info(msg)
            if not dry_run:
                _write(path, meta, body)
                
    if ctx:
        await ctx.report_progress(total, total)

    return {"ok": True, "dry_run": dry_run, "changes": changes, "remediated_count": len(changes)}


async def remediate_drift(root: Path, dry_run: bool = True, ctx: Any = None) -> dict[str, Any]:
    """Find nodes where frontmatter typed edges exist but are missing from body links (drift),
    and append them to the body as wikilinks."""
    from .graph import Graph
    g = Graph.build(root)
    drifts = g.drift()
    
    changes = []
    
    total = len(drifts)
    for i, (nid, only_fm, only_body) in enumerate(drifts):
        if ctx:
            await ctx.report_progress(i, total)
        if not only_fm:
            continue
            
        if nid not in g.adrs:
            continue
        path = g.adrs[nid].path
        meta, body = _load(path)
        
        added_links = []
        for c in only_fm:
            target_id = g.adrs[c].id if c in g.adrs else c
            if c in g.adrs:
                stem = g.adrs[c].path.stem
                added_links.append(f"- [[{stem}|{target_id}]]")
            else:
                added_links.append(f"- [[{target_id}]]")
        
        if "## References" in body:
            append_str = "\n" + "\n".join(added_links) + "\n"
        elif "## Related" in body:
            append_str = "\n" + "\n".join(added_links) + "\n"
        else:
            append_str = "\n\n## References\n\n" + "\n".join(added_links) + "\n"
            
        msg = f"Fixed drift in {nid}: added {len(only_fm)} missing body links"
        changes.append(msg)
        if ctx:
            ctx.info(msg)
        if not dry_run:
            _write(path, meta, body + append_str)
            
    if ctx:
        await ctx.report_progress(total, total)

    return {"ok": True, "dry_run": dry_run, "changes": changes, "remediated_count": len(changes)}

async def remediate_dead_links(root: Path, dry_run: bool = True, ctx: Any = None) -> dict[str, Any]:
    """Find and remove references to non-existent ADRs from both frontmatter and body."""
    from .graph import Graph
    g = Graph.build(root)
    rep = g.report()
    dead_links = rep.get("defects", {}).get("broken_dead_links", [])
    
    changes = []
    
    by_source = {}
    for link in dead_links:
        src = link["from"]
        dst = link["to"]
        if src not in by_source:
            by_source[src] = []
        by_source[src].append(dst)
        
    total = len(by_source)
    for i, (src, dead_targets) in enumerate(by_source.items()):
        if ctx:
            await ctx.report_progress(i, total)
        if src not in g.adrs:
            continue
        path = g.adrs[src].path
        meta, body = _load(path)
        
        fm_changed = False
        for key in ["related", "supersedes", "superseded_by"]:
            if key in meta:
                val = meta[key]
                if isinstance(val, list):
                    new_val = []
                    for x in val:
                        target_id = f"ADR-{x}" if str(x).isdigit() else str(x)
                        if target_id not in dead_targets:
                            new_val.append(x)
                    if len(new_val) != len(val):
                        meta[key] = new_val if len(new_val) > 0 else []
                        fm_changed = True
                elif isinstance(val, str):
                    target_id = f"ADR-{val}" if str(val).isdigit() else str(val)
                    if target_id in dead_targets:
                        del meta[key]
                        fm_changed = True
                    
        body_lines = body.split('\n')
        new_lines = []
        body_changed = False
        for line in body_lines:
            line_changed = False
            for target in dead_targets:
                target_num = target.replace("ADR-", "")
                if f"[[{target}]]" in line or f"[{target}]" in line or target in line or f"ADR-{target_num}" in line:
                    line_changed = True
            
            if line_changed and line.strip().startswith("- "):
                body_changed = True
                continue 
            elif line_changed:
                for target in dead_targets:
                    target_num = target.replace("ADR-", "")
                    if f"[[{target}]]" in line:
                        line = line.replace(f"[[{target}]]", f"{target}")
                        body_changed = True
                    import re
                    pattern = r'\[([^\]]+)\]\([^\)]*' + target_num + r'[^\)]*\)'
                    new_line = re.sub(pattern, r'\1', line)
                    if new_line != line:
                        line = new_line
                        body_changed = True
                new_lines.append(line)
            else:
                new_lines.append(line)
                
        if fm_changed or body_changed:
            msg = f"Removed dead links to {dead_targets} from {src}"
            changes.append(msg)
            if ctx:
                ctx.info(msg)
            if not dry_run:
                _write(path, meta, "\n".join(new_lines))
                
    if ctx:
        await ctx.report_progress(total, total)

    return {"ok": True, "dry_run": dry_run, "changes": changes, "remediated_count": len(changes)}
