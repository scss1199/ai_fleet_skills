#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""fleet-skill-sync.py — fleet-wide Cursor skill registry, inbox broadcast, absorb, deploy.

Lifecycle (0 Cursor token):
  scan      — discover skills under each hub seat + canonical _skill/fleet-skills/
  registry  — write _registry/fleet-skills.json
  absorb    — ingest _inbox/from_projects/*/skill-update-*.md → fleet-skills/incubator/
  deploy    — copy canonical skills → each seat .cursor/skills/
  broadcast — inbox directive to all seats (mandatory ack + skill-submit path)
  verify    — all seats have REQUIRED skills installed
  tick      — absorb → registry → deploy (hub-ztm-tick chain; no broadcast spam)

CITE: skill-registry.py · fleet-inbox-absorb.py · pfkt-fragment.py
usage:
  python fleet-skill-sync.py scan
  python fleet-skill-sync.py registry
  python fleet-skill-sync.py absorb
  python fleet-skill-sync.py deploy [--agent SEAT] [--seats-only]
  python fleet-skill-sync.py broadcast [--dry-run]
  python fleet-skill-sync.py verify
  python fleet-skill-sync.py tick
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

ENG = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENG)
from _paths import COMMON as HUB, REGISTRY, INBOX  # noqa: E402
from _hub_curator import HUB_CURATOR  # noqa: E402

CANON = os.path.join(HUB, "_skill", "fleet-skills")
INCUBATOR = os.path.join(CANON, "incubator")
REG_PATH = os.path.join(REGISTRY, "fleet-skills.json")
FLEET_META_PATH = os.path.join(REGISTRY, "fleet-skill-metadata.json")
LANES_PATH = os.path.join(REGISTRY, "fleet-skill-lanes.json")
ROUTING_PATH = os.path.join(REGISTRY, "fleet-skill-routing.json")
SUBMIT_INBOX = os.path.join(INBOX, "from_projects")
THREAD = "fleet-skill-sync-20260704"
REQUIRED = (
    "fames",
    "independent-review",
    "aex-agent-evolution",
    "ztm-fleet-inbox-absorb",
    "ztm-skill-submit",
    "ztm-git-ship",
    "ztm-web-auth-ops",
    "agc-auto-goal-compact",
    "ztm-verify-before-done",
    "mtm-mto-first",
    "adus-auto-deploy-upgrading-skill",
    "ztm-fleet-intelligence",
    "token-preflight",
)
# Fail-closed fallback only. The SSOT is _registry/agent-surfaces.json (loaded below).
DISCOVERY_ENTRYPOINTS = ("fames", "token-preflight")
SKILL_ALIAS_DEPLOY: dict[str, tuple[str, ...]] = {
    # 2026-09-05: the last alias (adus -> auto-skill-upgrade-deploy) was retired. The alias dir
    # had drifted from the ADUS skill (two authorities under one name) and is quarantined in
    # _delete/2026-09-05-skill-consolidation/fleet-skills/. Spoken aliases live in
    # _registry/fleet-lexicon.json legacy_aliases; nothing is deployed under a retired name.
}
SEAT_EXTRA = {
    "fracdigi": ("ztm-fracdigi-psync", "ztm-meta-oauth-console"),
    "ai_ziyaoastro": ("ztm-ziyaoastro-vercel",),
    "ai_darkhero": (
        "accountability-unblock",
        "ztm-portal-google-sso-edge",
        "mtm-claude-remnant-cleanup",
        "mtm-fleet-skill-github",
        "mtm-obsidian-wiki",
        "hubpulse-ops",
        "aware-dual-field",
    ),
}
ROUTING_PATH = os.path.join(REGISTRY, "fleet-skill-routing.json")
WEB_VERIFY_SKILL = "ztm-webapp-verify"
FLEET_OPTIONAL = (
    "aware-dual-field",
    "hubpulse-ops",
    "mtd-judgment-escalation",
    "mtm-fleet-audit",
    "mtm-github-ops",
    "mtm-converge-loop",
    "pfkt-parallel-wave",
    "pfkt-auto-unblock",
    "mtm-claude-remnant-cleanup",
    "ztm-meta-oauth-console",
    "mtm-mte-mint",
    "ztm-cursor-edge-auth",
    "mtm-api-pool-offload",
    "ztm-portal-google-sso-edge",
    "ztm-web-stack",  # website + OAuth/webhook/LLM kit orchestrator
)
EXTRA_PATH_PREFIX = {
    # fracdigi/meetings dropped 2026-08-13: it has no AGENTS.md, so it is no longer a
    # deploy root (see _is_agent_cwd) and the mapping could never fire. psync stays —
    # new.messages.fracdigi.com carries its own charter + git remote.
    "fracdigi/GitHub/new.messages.fracdigi.com": ("ztm-fracdigi-psync", "ztm-meta-oauth-console"),
}
# Canon skills that must NOT go fleet-wide. Everything else in CANON is fleet-wide by default
# (see _skills_for_root), so a newly promoted skill is reachable without editing a list —
# measured 2026-08-12: mtm-token-ladder (an alias skill, itself retired 2026-09-05) was in canon
# and cited by AGENTS.md yet appeared in no list, so it reached zero .claude surfaces. Curated
# allowlists were a copy-cost defence; with link_mode=junction a skill costs one directory entry,
# so only real scoping stays.
SEAT_SCOPED_ONLY = frozenset({
    "ztm-fracdigi-psync",     # fracdigi vault isolation (seat red line)
    "ztm-ziyaoastro-vercel",  # ai_ziyaoastro domain deploy
    WEB_VERIFY_SKILL,         # gated on package.json below
})
SKIP_SEATS = frozenset({"ai_master", "ai_portal", "ai_darkhero_integration", "ai_fintrend"})
AGENT_SURFACES_PATH = os.path.join(REGISTRY, "agent-surfaces.json")
AGENT_SURFACES_FALLBACK = (
    {"key": "cursor", "path": (".cursor", "skills"), "subset": "full",
     "aliases": True, "link_mode": "junction"},
    {"key": "claude", "path": (".claude", "skills"), "subset": "full",
     "aliases": False, "link_mode": "junction"},
)


def _load_agent_surfaces() -> tuple[tuple[dict, ...], tuple[str, ...]]:
    """Agent discovery surfaces: path + subset + aliases + link_mode per vendor.

    Each vendor reads only its own path, so subset IS reachability. This table used to be
    hardcoded at three separate call sites (deploy-to-root, deploy-named, verify), which is
    how .claude/.agents stayed at 3 skills while .cursor grew to 38: widening one site did
    not widen the others. One table, read once.
    """
    try:
        with open(AGENT_SURFACES_PATH, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        rows = []
        for row in data.get("surfaces") or ():
            parts = tuple(row.get("path") or ())
            if not row.get("key") or len(parts) != 2:
                continue
            rows.append({
                "key": row["key"],
                "path": parts,
                "subset": row.get("subset") or "entrypoints",
                "aliases": bool(row.get("aliases")),
                "link_mode": row.get("link_mode") or "copy",
            })
        entrypoints = tuple(data.get("entrypoints") or ())
        # fames is the portable contract carrier; a table that drops it is corrupt, not new.
        if rows and "fames" in entrypoints:
            return tuple(rows), entrypoints
    except Exception:
        pass
    return AGENT_SURFACES_FALLBACK, DISCOVERY_ENTRYPOINTS


AGENT_SURFACES, ENTRYPOINTS = _load_agent_surfaces()
SKILL_DIRS = tuple(surface["path"] for surface in AGENT_SURFACES)
from lane_taxonomy import LANE_ZTM, norm_lane, display_lane  # noqa: E402

LANE_ZERO = LANE_ZTM


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _seats():
    import _projects
    return [s for s in _projects.hub_seats() if s not in SKIP_SEATS]


def _seat_root(seat: str) -> str | None:
    import _projects
    meta = _projects.get(seat) or {}
    rel = meta.get("path")
    if not rel:
        return None
    root = os.path.join(HUB, rel) if not os.path.isabs(rel) else rel
    return root if os.path.isdir(root) else None


def _rel_path(abs_path: str) -> str:
    return os.path.relpath(abs_path, HUB).replace("\\", "/")


def _is_agent_cwd(root: str) -> bool:
    """Does this path earn its own .claude/.cursor surface?

    2026-08-13 (operator: 一個 cwd 一個 surface). The old test was _has_project_marker —
    any sub-folder holding package.json / pyproject.toml / .git got a full skill farm.
    That minted 12 surplus surfaces (ai_busker|ai_eatery|ai_search|ai_trader|ai_ut /web,
    ai_ziyaoastro/{backend,frontend}, ai_career/match-app-web,
    ai_trader/sinopac-trading-system, fracdigi/meetings, jci_taipei/jci_taipei_website),
    none of which is a cwd: each is worked on FROM its seat root, and
    workspace-seat-contract.json forbids opening anything but a seat folder for agent work.
    A path now needs its own AGENTS.md identity — the same artifact
    required_at_create demands of a real seat.
    """
    return os.path.isfile(os.path.join(root, "AGENTS.md"))


def _all_deploy_roots() -> list[str]:
    import _projects
    roots: set[str] = set()
    matrix = _projects._load() or {}
    for _name, meta in matrix.items():
        # SKIP_SEATS is the SSOT for "never deploy skills here". _seats() honoured it but
        # this walk did not, so `deploy` (all-folders, the mode cmd_tick uses) and `verify`
        # kept re-creating / demanding skills under ai_master — reversing the 2026-08-08
        # claude-remnant quarantine within one 15m fleet-skill-pulse tick.
        if _name in SKIP_SEATS:
            continue
        rel = meta.get("path")
        if rel:
            ap = os.path.join(HUB, rel) if not os.path.isabs(rel) else rel
            if os.path.isdir(ap):
                roots.add(os.path.normpath(ap))
        # Sub-roots are declared, never discovered: the old marker-walk over listdir(ap)
        # is what re-created the surplus surfaces (see _is_agent_cwd).
        for comp in (meta.get("components") or {}).values():
            cp = comp.get("path")
            if cp:
                ap = os.path.join(HUB, cp) if not os.path.isabs(cp) else cp
                if os.path.isdir(ap) and _is_agent_cwd(ap):
                    roots.add(os.path.normpath(ap))
    clean = []
    for r in sorted(roots):
        rp = _rel_path(r) + "/"
        if ".secrets/" in rp:
            continue
        # A stub seat whose matrix path points into quarantine (ai_news ->
        # _delete/2026-07-14-ai_news-fertilizer) was still getting skills deployed,
        # re-populating the very zone the operator drains.
        if rp.startswith("_delete/") or "/_delete/" in rp:
            continue
        # second gate: a skipped seat can also be reached as a component/sub-root of
        # another matrix entry, where the key name no longer identifies it.
        if rp.split("/", 1)[0] in SKIP_SEATS:
            continue
        clean.append(r)
    return clean


def _routing_optional(seat: str) -> tuple[str, ...]:
    try:
        doc = json.load(open(ROUTING_PATH, encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return ()
    out: list[str] = []
    for item in doc.get("optional_canonical") or []:
        if seat in (item.get("seats") or []):
            out.append(str(item.get("name") or ""))
    return tuple(n for n in out if n)


def _skills_for_root(root: str) -> tuple[str, ...]:
    rel = _rel_path(root)
    extra: list[str] = list(REQUIRED)
    for prefix, names in EXTRA_PATH_PREFIX.items():
        if rel == prefix or rel.startswith(prefix + "/"):
            extra.extend(names)
    import _projects
    name, _ = _projects.whoami(root)
    if name in SEAT_EXTRA:
        extra.extend(SEAT_EXTRA[name])
    extra.extend(_routing_optional(name))
    for opt in FLEET_OPTIONAL:
        if opt not in extra and os.path.isfile(os.path.join(CANON, opt, "SKILL.md")):
            extra.append(opt)
    # Then every remaining canon skill: fleet-wide is the default, scoping is the exception.
    # REQUIRED/FLEET_OPTIONAL above are kept because they fix ORDER and because
    # Keep entrypoints explicit for static consumers and bootstrap readability.
    alias_dirs = {a for aliases in SKILL_ALIAS_DEPLOY.values() for a in aliases}
    for cand in sorted(os.listdir(CANON) if os.path.isdir(CANON) else ()):
        if cand in extra or cand in SEAT_SCOPED_ONLY or cand in alias_dirs:
            continue  # alias dirs ship through SKILL_ALIAS_DEPLOY, never as a second skill
        if os.path.isfile(os.path.join(CANON, cand, "SKILL.md")):
            extra.append(cand)
    if os.path.isfile(os.path.join(root, "package.json")) and WEB_VERIFY_SKILL not in extra:
        if WEB_VERIFY_SKILL in {c["name"] for c in _list_skill_folder(CANON)}:
            extra.append(WEB_VERIFY_SKILL)
    # dedupe preserve order
    seen = set()
    out = []
    for n in extra:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return tuple(out)


def _sha(path: str) -> str:
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]
    except OSError:
        return ""


def _parse_skill_tags(md_path: str) -> dict:
    """Read central fleet tags, with legacy frontmatter as a compatibility fallback."""
    tags = {"lane": None, "secrets": None, "scheduler": None, "token_budget": None}
    name = os.path.basename(os.path.dirname(md_path))
    try:
        doc = json.load(open(FLEET_META_PATH, encoding="utf-8-sig"))
        central = ((doc.get("skills") or {}).get(name) or {}) if isinstance(doc, dict) else {}
        for key in tags:
            value = central.get(key)
            if value:
                tags[key] = norm_lane(value) if key == "lane" else str(value)
        if _tags_complete(tags):
            return tags
    except (OSError, json.JSONDecodeError):
        pass
    try:
        text = open(md_path, encoding="utf-8", errors="replace").read(4096)
    except OSError:
        return tags
    if not text.startswith("---"):
        if name.startswith(("zct-", "ztm-")):
            tags["lane"] = LANE_ZERO
            tags["secrets"] = "none"
            tags["scheduler"] = "session"
            tags["token_budget"] = "zero" if name.startswith("ztm-") and "verify" not in name else "low"
        return tags
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return tags
    block = m.group(1)
    fleet_block = ""
    if "metadata:" in block:
        fm = re.search(
            r"fleet:\s*\n((?:\s+[a-z_]+:\s*.+(?:\n|$))+)",
            block,
        )
        if fm:
            fleet_block = fm.group(1)
    for line in (fleet_block or block).splitlines():
        line = line.strip()
        if line.startswith("lane:"):
            tags["lane"] = norm_lane(line.split(":", 1)[1])
        elif line.startswith("secrets:"):
            tags["secrets"] = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("scheduler:"):
            tags["scheduler"] = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("token_budget:"):
            tags["token_budget"] = line.split(":", 1)[1].strip().strip('"')
    if not tags["lane"]:
        if name.startswith(("zct-", "ztm-")):
            budget = "low" if "verify" in name or "webapp" in name else "zero"
            tags.update({"lane": LANE_ZERO, "secrets": "none", "scheduler": "session", "token_budget": budget})
        elif name.startswith("mtd-"):
            tags.update({"lane": "MTD", "secrets": "none", "scheduler": "session", "token_budget": "judgment"})
    return tags


def _tags_complete(tags: dict) -> bool:
    return all(tags.get(k) for k in ("lane", "secrets", "scheduler", "token_budget"))


def _list_skill_folder(base: str) -> list[dict]:
    out = []
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        md = os.path.join(base, name, "SKILL.md")
        if os.path.isfile(md):
            out.append({
                "name": name,
                "path": md,
                "bytes": os.path.getsize(md),
                "sha": _sha(md),
            })
    return out


def _scan_canonical() -> list[dict]:
    rows = []
    for name in sorted(os.listdir(CANON)) if os.path.isdir(CANON) else []:
        if name == "incubator":
            continue
        md = os.path.join(CANON, name, "SKILL.md")
        if os.path.isfile(md):
            tags = _parse_skill_tags(md)
            rows.append({
                "name": name,
                "source": "canonical",
                "path": md,
                "required": name in REQUIRED,
                "sha": _sha(md),
                "fleet": tags,
                "tags_ok": _tags_complete(tags),
            })
    return rows


def cmd_scan() -> dict:
    doc = {"generated": _iso(), "canonical": _scan_canonical(), "seats": {}}
    for seat in _seats():
        root = _seat_root(seat)
        if not root:
            continue
        found = []
        for parts in SKILL_DIRS:
            base = os.path.join(root, *parts)
            for s in _list_skill_folder(base):
                s["seat"] = seat
                s["rel"] = os.path.relpath(s["path"], root).replace("\\", "/")
                found.append(s)
        doc["seats"][seat] = found
    return doc


def _group_by_lane(canonical: list[dict]) -> dict:
    out: dict[str, list[str]] = {LANE_ZERO: [], "MTD": []}
    for row in canonical:
        lane = norm_lane((row.get("fleet") or {}).get("lane")) or "?"
        out.setdefault(lane, []).append(row["name"])
    return out


def cmd_registry() -> dict:
    scan = cmd_scan()
    subs = []
    if os.path.isdir(SUBMIT_INBOX):
        for proj in os.listdir(SUBMIT_INBOX):
            d = os.path.join(SUBMIT_INBOX, proj)
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if f.startswith("skill-update") and f.endswith(".md"):
                    p = os.path.join(d, f)
                    subs.append({"project": proj, "file": f, "path": p, "mtime": os.path.getmtime(p)})
    reg = {
        "schema": 2,
        "updated": _iso(),
        "thread": THREAD,
        "lanes_ssot": "fleet-skill-lanes.json",
        "routing_ssot": "fleet-skill-routing.json",
        "required": list(REQUIRED),
        "canonical_dir": CANON,
        "canonical": scan["canonical"],
        "by_lane": _group_by_lane(scan["canonical"]),
        "by_seat": scan["seats"],
        "submissions_pending": subs,
        "incubator": sorted(os.listdir(INCUBATOR)) if os.path.isdir(INCUBATOR) else [],
    }
    os.makedirs(REGISTRY, exist_ok=True)
    json.dump(reg, open(REG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("registry: %s  canonical=%d seats=%d submissions=%d" % (
        REG_PATH, len(reg["canonical"]), len(reg["by_seat"]), len(subs)))
    return reg


def _parse_submit(path: str) -> dict | None:
    try:
        body = open(path, encoding="utf-8").read()
    except OSError:
        return None
    name_m = re.search(r"^\s*[-*]\s*\*\*name:\*\*\s*(.+)$", body, re.M | re.I)
    if not name_m:
        name_m = re.search(r"^#\s*skill-update[^·]*·[^·]*·\s*(\S+)", body, re.M)
    name = (name_m.group(1).strip() if name_m else os.path.basename(path)).lower()
    name = re.sub(r"[^a-z0-9\-]+", "-", name).strip("-") or "unnamed"
    return {"name": name, "body": body, "source_path": path}


def cmd_absorb() -> dict:
    os.makedirs(INCUBATOR, exist_ok=True)
    absorbed = []
    if not os.path.isdir(SUBMIT_INBOX):
        return {"absorbed": absorbed}
    for proj in sorted(os.listdir(SUBMIT_INBOX)):
        d = os.path.join(SUBMIT_INBOX, proj)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not (f.startswith("skill-update") and f.endswith(".md")):
                continue
            src = os.path.join(d, f)
            parsed = _parse_submit(src)
            if not parsed:
                continue
            dest_name = "%s-%s" % (proj, parsed["name"])[:80]
            dest_dir = os.path.join(INCUBATOR, dest_name)
            os.makedirs(dest_dir, exist_ok=True)
            dest_md = os.path.join(dest_dir, "SKILL.md")
            header = "<!-- absorbed from %s/%s @ %s -->\n\n" % (proj, f, _iso())
            open(dest_md, "w", encoding="utf-8").write(header + parsed["body"])
            meta = {"project": proj, "file": f, "absorbed_at": _iso(), "incubator": dest_name}
            json.dump(meta, open(os.path.join(dest_dir, "meta.json"), "w", encoding="utf-8"), indent=2)
            absorbed.append(meta)
    print("absorb: %d submission(s) → %s/incubator/" % (len(absorbed), CANON))
    return {"absorbed": absorbed}


LEGACY_SKILL_DIRS = (
    # Retired folder names only — NEVER list a current REQUIRED skill here.
    # Pre-ZTM rename names:
    "zct-fleet-inbox-absorb",
    "zct-git-ship",
    "zct-skill-submit",
    "zct-webapp-verify",
    "zct-fracdigi-psync",
    "zct-ziyaoastro-vercel",
    # 2026-09-05 skill consolidation — canon dirs quarantined in
    # _delete/2026-09-05-skill-consolidation/fleet-skills/ (see its README.md):
    "ztm-goal-compact-enforce",   # absorbed into agc-auto-goal-compact
    "mtm-token-ladder",           # was a SUPERSEDED pointer to aex-agent-evolution
    "auto-skill-upgrade-deploy",  # drifted alias of adus-auto-deploy-upgrading-skill
)


def _copy_skill_tree(src_dir: str, dest_dir: str) -> None:
    """Copy a skill and its resources without deleting unrelated local files."""
    for walk_root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git"}]
        rel = os.path.relpath(walk_root, src_dir)
        out_dir = dest_dir if rel == "." else os.path.join(dest_dir, rel)
        os.makedirs(out_dir, exist_ok=True)
        for filename in files:
            if filename.endswith((".pyc", ".pyo")):
                continue
            shutil.copy2(os.path.join(walk_root, filename), os.path.join(out_dir, filename))


try:
    import _winapi  # Windows only; CreateJunction needs no admin right and no subprocess
except ImportError:  # pragma: no cover - non-Windows node
    _winapi = None

JUNCTION_QUARANTINE = os.path.join(HUB, "_delete", "surface-junction-20260812")


def _skill_tree_hash(root: str) -> str:
    """Content identity of a skill dir: relative paths + bytes, build artefacts ignored."""
    digest = hashlib.sha256()
    for walk_root, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {"__pycache__", ".git"})
        for filename in sorted(files):
            if filename.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(walk_root, filename)
            digest.update(os.path.relpath(full, root).replace("\\", "/").encode())
            try:
                with open(full, "rb") as fh:
                    digest.update(fh.read())
            except OSError:
                digest.update(b"<unreadable>")
    return digest.hexdigest()


def _junction_skill(src_dir: str, dest_dir: str) -> str:
    """Point dest_dir at the canonical skill through a directory junction.

    Measured 2026-08-12 (see _registry/agent-surfaces.json → junction_facts_measured):
    shutil.rmtree, git clean -xdf, rd /s /q and Remove-Item -Recurse -Force all delete the
    LINK and leave canon intact, so a surface wipe can never reach the canonical skill.
    os.path.islink() is False for a junction — isjunction() is the only correct probe.
    """
    if os.path.isjunction(dest_dir):
        if os.path.realpath(dest_dir).lower() == os.path.realpath(src_dir).lower():
            return "ok"
        os.rmdir(dest_dir)  # a junction is one dir entry; rmdir drops the reparse point
    elif os.path.isdir(dest_dir):
        # A physical dir may hold an un-promoted local edit, so it is quarantined rather
        # than deleted when it differs from canon. Identical trees are pure duplicates.
        if _skill_tree_hash(dest_dir) == _skill_tree_hash(src_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)
        else:
            flat = _rel_path(dest_dir).replace("/", "__")
            keep = os.path.join(JUNCTION_QUARANTINE, flat)
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            if os.path.exists(keep):
                shutil.rmtree(keep, ignore_errors=True)
            shutil.move(dest_dir, keep)
    elif os.path.exists(dest_dir):
        os.remove(dest_dir)
    if os.path.isdir(dest_dir):  # quarantine/rmtree failed — never leave a half state
        return "blocked"
    os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
    _winapi.CreateJunction(src_dir, dest_dir)
    return "linked"


def _place_skill(src_dir: str, dest_dir: str, link_mode: str) -> str:
    if link_mode == "junction" and _winapi is not None and os.name == "nt":
        try:
            return _junction_skill(src_dir, dest_dir)
        except OSError:
            pass  # e.g. non-NTFS target — a copy is still a correct deploy
    _copy_skill_tree(src_dir, dest_dir)
    return "copied"


def _deploy_surface(root: str, surface: dict, names: tuple[str, ...]) -> dict:
    dest_base = os.path.join(root, *surface["path"])
    os.makedirs(dest_base, exist_ok=True)
    link_mode = surface.get("link_mode") or "copy"
    copied, actions = [], {}
    for name in names:
        src_dir = os.path.join(CANON, name)
        if not os.path.isfile(os.path.join(src_dir, "SKILL.md")):
            continue
        actions[name] = _place_skill(src_dir, os.path.join(dest_base, name), link_mode)
        copied.append(name)
        if surface.get("aliases"):
            for alias in SKILL_ALIAS_DEPLOY.get(name, ()):
                actions[alias] = _place_skill(src_dir, os.path.join(dest_base, alias), link_mode)
                copied.append(alias)
    blocked = sorted(n for n, act in actions.items() if act == "blocked")
    return {"dest": dest_base, "copied": copied, "link_mode": link_mode, "blocked": blocked}


def _deploy_named(root: str, names: tuple[str, ...]) -> dict:
    """Deploy only named skills to every discovery surface; never touch other skills."""
    if not os.path.isdir(root):
        return {"root": _rel_path(root), "ok": False, "error": "missing"}
    gitignored = _ensure_surface_gitignore(root)
    surfaces = {}
    copied = []
    for surface in AGENT_SURFACES:
        result = _deploy_surface(root, surface, names)
        surfaces[surface["key"]] = result["dest"]
        copied.extend(result["copied"])
    return {
        "root": _rel_path(root),
        "ok": True,
        "copied": sorted(set(copied)),
        "surfaces": surfaces,
        "gitignored": gitignored,
    }


def _named_deploy_roots() -> list[str]:
    """Active workspace roots for bounded named deploys, including the hub itself."""
    return [HUB, *(root for root in _all_deploy_roots()
                   if not _rel_path(root).startswith("_delete/"))]


GITIGNORE_MARK = "# Agent skill surfaces — junctions into _skill/fleet-skills (agent-surfaces.json)"


def _ensure_surface_gitignore(root: str) -> list[str]:
    """Ignore the surface dirs in any repo that carries them.

    Measured 2026-08-12: `git status -uall` traverses a junction and reports the linked canon
    files as untracked, so a junctioned surface inside a git repo pulls the whole canonical
    skill tree into that repo (6607 untracked paths on the pilot seat). This runs on every
    deploy rather than once, because the footgun must not depend on anyone remembering it for
    the next machine. Text-only and idempotent — it never runs a git command.
    """
    if not os.path.isdir(os.path.join(root, ".git")):
        return []
    path = os.path.join(root, ".gitignore")
    try:
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
    except OSError:
        body = ""
    wanted = ["/".join(s["path"]) + "/" for s in AGENT_SURFACES]
    lines = {ln.strip() for ln in body.splitlines()}
    # An existing broader rule (e.g. ".claude/") already ignores the surface under it.
    missing = [w for w in wanted
               if w not in lines and w.split("/")[0] + "/" not in lines]
    if not missing:
        return []
    block = ("" if body.endswith("\n") or not body else "\n") + \
        "\n" + GITIGNORE_MARK + "\n" + "\n".join(missing) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(block)
    return missing


def _deploy_to_root(root: str, names: tuple[str, ...] | None = None) -> dict:
    if not os.path.isdir(root):
        return {"root": _rel_path(root), "ok": False, "error": "missing"}
    want = names or _skills_for_root(root)
    gitignored = _ensure_surface_gitignore(root)
    results = {}
    for surface in AGENT_SURFACES:
        subset = want if surface.get("subset") == "full" else ENTRYPOINTS
        results[surface["key"]] = _deploy_surface(root, surface, subset)
    primary = results.get("cursor") or next(iter(results.values()))
    copied = primary["copied"]
    dest_base = primary["dest"]
    removed = []
    copied_set = set(copied)
    if names is None:
        for legacy in LEGACY_SKILL_DIRS:
            if legacy in copied_set or legacy in REQUIRED:
                continue
            # Every declared surface, not only the primary one: a retired skill was junctioned
            # on all of them. Once canon is quarantined the junction dangles and isdir() is
            # False, so probe the reparse point itself (measured 2026-09-05: 161 dangling links).
            for res in results.values():
                leg = os.path.join(res["dest"], legacy)
                if os.path.isjunction(leg):
                    os.rmdir(leg)
                    removed.append(legacy)
                elif os.path.isdir(leg):
                    shutil.rmtree(leg, ignore_errors=True)
                    removed.append(legacy)
    return {
        "root": _rel_path(root), "ok": True, "copied": copied,
        "entrypoints": list(ENTRYPOINTS), "removed_legacy": removed,
        "dest": dest_base,
        "surfaces": {key: res["dest"] for key, res in results.items()},
        "link_modes": {key: res["link_mode"] for key, res in results.items()},
        "blocked": sorted({n for res in results.values() for n in res["blocked"]}),
        "gitignored": gitignored,
    }


def _deploy_one(seat: str, names: tuple[str, ...] | None = None) -> dict:
    root = _seat_root(seat)
    if not root:
        return {"seat": seat, "ok": False, "error": "no root"}
    r = _deploy_to_root(root, names or _skills_for_root(root))
    r["seat"] = seat
    return r


def cmd_deploy(only: str | None = None, *, all_folders: bool = True, seats_only: bool = False,
               entrypoints_only: bool = False, skill: str | None = None) -> dict:
    if skill:
        if not os.path.isfile(os.path.join(CANON, skill, "SKILL.md")):
            raise ValueError("unknown canonical skill: %s" % skill)
        names = (skill,)
        if only:
            root = _seat_root(only)
            results = [_deploy_named(root, names)] if root else []
            mode = "agent-named"
        elif seats_only:
            results = [_deploy_named(_seat_root(s), names) for s in _seats() if _seat_root(s)]
            mode = "seats-named"
        else:
            results = [_deploy_named(root, names) for root in _named_deploy_roots()]
            mode = "all-folders-named"
        ok = sum(1 for r in results if r.get("ok"))
        print("deploy-skill: %s %d/%d roots" % (skill, ok, len(results)))
        return {"results": results, "mode": mode, "count": len(results), "skill": skill}
    if only:
        root = _seat_root(only)
        names = ENTRYPOINTS if entrypoints_only else None
        results = [_deploy_to_root(root, names)] if root else [_deploy_one(only, names)]
        ok = sum(1 for r in results if r.get("ok"))
        print("deploy: %d/%d  agent=%s" % (ok, len(results), only))
        return {"results": results, "mode": "agent", "count": len(results)}
    if seats_only:
        results = [_deploy_one(s) for s in _seats()]
        ok = sum(1 for r in results if r.get("ok"))
        print("deploy: %d/%d seats" % (ok, len(results)))
        return {"results": results, "mode": "seats", "count": len(results)}
    roots = _all_deploy_roots()
    results = [_deploy_to_root(r) for r in roots]
    ok = sum(1 for r in results if r.get("ok"))
    print("deploy-all: %d/%d roots" % (ok, len(results)))
    return {"results": results, "mode": "all_folders", "count": len(results)}


def _digest(reg: dict | None = None) -> str:
    if reg is None and os.path.isfile(REG_PATH):
        reg = json.load(open(REG_PATH, encoding="utf-8-sig"))
    if not reg:
        reg = cmd_registry()
    lines = ["### 全艦必裝 (curator canonical)", ""]
    for c in reg.get("canonical") or []:
        tag = " **required**" if c.get("required") else ""
        lines.append("- `%s`%s" % (c["name"], tag))
    lines.append("")
    lines.append("### 各 seat 自有 skill（可 SUBMIT 推廣）")
    lines.append("")
    any_local = False
    for seat, skills in sorted((reg.get("by_seat") or {}).items()):
        local = [s for s in skills if s["name"] not in REQUIRED]
        if not local:
            continue
        any_local = True
        lines.append("- **%s:** %s" % (seat, ", ".join("`" + s["name"] + "`" for s in local)))
    if not any_local:
        lines.append("- (scan 未發現額外 skill — 歡迎第一個 SUBMIT)")
    if reg.get("incubator"):
        lines.append("")
        lines.append("### 待策展 incubator")
        for n in reg["incubator"]:
            lines.append("- `%s`" % n)
    return "\n".join(lines)


def cmd_broadcast(dry_run: bool = False) -> dict:
    reg = cmd_registry()
    digest = _digest(reg)
    body = "\n".join([
        "# [MANDATORY] Fleet skill sync · Wave 1",
        "",
        "**From:** %s curator  **Thread:** %s" % (HUB_CURATOR, THREAD),
        "",
        "## 必做（違反 = inbox 積壓 + accountability）",
        "",
        "1. HubClock 已代 pickup → 讀 `_registry/fleet-pickup/<seat>.md`",
        "2. 確認 `.cursor/skills/` 有三支：`ztm-fleet-inbox-absorb` · `ztm-skill-submit` · `ztm-git-ship`",
        "3. 路由 SSOT：`_registry/fleet-skill-routing.json`（何時用哪支 skill）",
        "4. 執行本 directive 後：**ack**",
        "   `python %AI_WORKSPACE%\\_skill\\engines\\fleet-inbox-absorb.py ack <this-id>`",
        "5. 有可推廣 workflow → SUBMIT（格式見 ztm-skill-submit skill）",
        "",
        digest,
        "",
        "## PFKT",
        "多步 skill 移植 / 跨 repo → `pfkt-fragment.py split` 再逐段 verify-done。",
        "",
    ])
    import inbox

    sent = []
    for seat in _seats():
        if dry_run:
            sent.append({"seat": seat, "dry_run": True})
            continue
        mid = inbox.send(seat, HUB_CURATOR, body, kind="directive", thread=THREAD)
        sent.append({"seat": seat, "id": mid})
    try:
        inbox.portal()
    except Exception:
        pass
    print("broadcast: %d seat(s)%s" % (len(sent), " [dry-run]" if dry_run else ""))
    for row in sent:
        if row.get("id"):
            print("  %s → %s" % (row["seat"], row["id"]))
    return {"sent": sent, "thread": THREAD}


def cmd_verify(all_folders: bool = False, only: str | None = None) -> int:
    missing = []
    if only:
        one = _seat_root(only)
        roots = [one] if one else []
    elif all_folders:
        roots = _all_deploy_roots()
    else:
        # --seats-only: assert only what `deploy --seats-only` actually writes.
        # The parameter existed but was ignored, so both modes returned the same rows.
        roots = [r for r in (_seat_root(s) for s in _seats()) if r]
    for root in roots:
        want = _skills_for_root(root)
        # Verify each surface against ITS OWN declared subset. Asserting entrypoints-only on
        # .claude/.agents is what let the executor seat sit at 4/40 canon skills while the
        # gate reported OK, so the subset now comes from the same table deploy writes from.
        for surface in AGENT_SURFACES:
            base = os.path.join(root, *surface["path"])
            subset = want if surface.get("subset") == "full" else ENTRYPOINTS
            for name in subset:
                if not os.path.isfile(os.path.join(base, name, "SKILL.md")):
                    missing.append((_rel_path(root), "/".join(surface["path"] + (name,))))
    if missing:
        print("VERIFY FAIL missing=%d" % len(missing))
        for root, skill in missing[:25]:
            print("  %s  %s" % (root, skill))
        return 1
    print("VERIFY OK %d root(s)%s" % (len(roots), " agent=" + only if only else ""))
    return 0


def cmd_tags() -> int:
    rows = _scan_canonical()
    bad = [r for r in rows if not r.get("tags_ok")]
    for r in rows:
        f = r.get("fleet") or {}
        lane = f.get("lane") or "?"
        lane_disp = display_lane(lane) if lane != "?" else "?"
        print("%s  lane=%-22s secrets=%-14s sched=%-10s budget=%s" % (
            r["name"],
            lane_disp,
            f.get("secrets") or "?",
            f.get("scheduler") or "?",
            f.get("token_budget") or "?",
        ))
    if bad:
        print("TAGS FAIL incomplete=%d" % len(bad))
        return 1
    print("TAGS OK canonical=%d" % len(rows))
    return 0


def cmd_tick() -> int:
    cmd_absorb()
    cmd_registry()
    cmd_deploy(all_folders=True)
    return cmd_verify(all_folders=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "registry", "absorb", "deploy", "broadcast", "verify", "tick", "tags"])
    ap.add_argument("--agent", default="")
    ap.add_argument("--seats-only", action="store_true", help="deploy hub seats only, not all folders")
    ap.add_argument("--entrypoints-only", action="store_true", help="with --agent, deploy only cross-tool discovery entrypoints")
    ap.add_argument("--skill", default="", help="deploy only one canonical skill to all discovery surfaces")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    if args.cmd == "scan":
        out = cmd_scan()
    elif args.cmd == "registry":
        out = cmd_registry()
    elif args.cmd == "absorb":
        out = cmd_absorb()
    elif args.cmd == "deploy":
        if args.agent:
            out = cmd_deploy(args.agent, all_folders=False, seats_only=False,
                             entrypoints_only=args.entrypoints_only, skill=args.skill or None)
        elif args.seats_only:
            out = cmd_deploy(seats_only=True, all_folders=False, skill=args.skill or None)
        else:
            out = cmd_deploy(all_folders=True, skill=args.skill or None)
    elif args.cmd == "broadcast":
        out = cmd_broadcast(dry_run=args.dry_run)
    elif args.cmd == "verify":
        return cmd_verify(all_folders=not args.seats_only, only=args.agent or None)
    elif args.cmd == "tick":
        return cmd_tick()
    elif args.cmd == "tags":
        return cmd_tags()
    else:
        return 2

    if args.json_only:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
