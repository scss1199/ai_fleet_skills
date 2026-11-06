#!/usr/bin/env python3
"""_projects.py — accessor for the central project link matrix (folder<->git<->role)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import MATRIX, COMMON

def _load():
    return json.loads(open(MATRIX, encoding="utf-8-sig").read()).get("projects", {}) if os.path.exists(MATRIX) else {}

# Legacy component keys (pre-2026-06-19 fracdigi_* seats) -> relative paths under AI_WORKSPACE.
_COMPONENT_ALIASES = {
    "fracdigi_new_messages": "fracdigi/GitHub/new.messages.fracdigi.com",
    "fracdigi_meetings": "fracdigi/meetings",
    "fracdigi_insights": "fracdigi/GitHub/insights.fracdigi.com",
    "fracdigi_messages": "fracdigi/GitHub/messages.fracdigi.com",
}

def _resolve_path(p):
    if not p:
        return p
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(COMMON, p))

def get(name):
    if name in _COMPONENT_ALIASES:
        base = _load().get("fracdigi") or {}
        comp_key = {"fracdigi_new_messages": "psync", "fracdigi_meetings": "meetings",
                    "fracdigi_insights": "insights", "fracdigi_messages": "messages"}.get(name)
        comp = (base.get("components") or {}).get(comp_key) if comp_key else None
        if comp:
            out = dict(comp)
            out["path"] = _resolve_path(out.get("path") or _COMPONENT_ALIASES[name])
            out["hub_seat"] = "fracdigi"
            return out
        return {"path": _resolve_path(_COMPONENT_ALIASES[name]), "hub_seat": "fracdigi"}
    p = _load().get(name)
    if not p:
        return p
    out = dict(p)
    if "path" in out:
        out["path"] = _resolve_path(out["path"])
    return out

def code(name):
    p = _load().get(name) or {}
    return p.get("code")

def by_code(c):
    c = str(c).strip()
    if not c:
        return None
    for n, p in _load().items():
        if str(p.get("code") or "") == c:
            return n
    return None

def path(name):
    if name in _COMPONENT_ALIASES:
        got = get(name)
        return got.get("path") if got else _resolve_path(_COMPONENT_ALIASES[name])
    p = _load().get(name) or {}
    return _resolve_path(p.get("path"))

def remote(name):
    p = _load().get(name) or {}
    return p.get("git_remote")

def find(substr):
    s = substr.lower()
    return [n for n, p in _load().items()
            if s in n.lower() or s in (str(p.get("path", "")) + p.get("role", "")).lower()]

def whoami(cwd):
    if not cwd:
        return ("unknown", None)
    c = os.path.normcase(os.path.abspath(cwd)).rstrip("\\/")
    best = None
    blen = -1
    for n, p in _load().items():
        pp = p.get("path")
        if not pp:
            continue
        pn = os.path.normcase(_resolve_path(pp)).rstrip("\\/")
        if (c == pn or c.startswith(pn + os.sep)) and len(pn) > blen:
            best = (n, p)
            blen = len(pn)
    if best:
        return best
    for alias, rel in _COMPONENT_ALIASES.items():
        pn = os.path.normcase(_resolve_path(rel)).rstrip("\\/")
        if (c == pn or c.startswith(pn + os.sep)) and len(pn) > blen:
            base = _load().get("fracdigi") or {}
            best = ("fracdigi", base)
            blen = len(pn)
    if best:
        return best
    hub = os.path.normcase(os.path.abspath(COMMON)).rstrip("\\/")
    if c == hub:
        try:
            from _local_curator import local_curator
            name = local_curator()
            return (name, _load().get(name))
        except Exception:
            pass
        if os.path.isdir(os.path.join(COMMON, "ai_scar3")):
            return ("ai_scar3", _load().get("ai_scar3"))
        return ("ai_master", _load().get("ai_master"))
    return (os.path.basename(c) or "unknown", None)


def hub_seats():
    """All hub fleet seats — SSOT project-matrix entries with code + on-disk path."""
    out = []
    for name, meta in _load().items():
        if meta.get("status") == "stub":
            continue
        if meta.get("code") in (None, ""):
            continue
        pp = meta.get("path")
        if not pp:
            continue
        if os.path.isdir(_resolve_path(pp)):
            out.append(name)
    return sorted(out)


def is_hub_seat(name: str) -> bool:
    return name in hub_seats()

def list():
    return {n: p.get("role", "") for n, p in _load().items()}

if __name__ == "__main__":
    for n, role in list().items():
        print(f"  {n:24} {role[:70]}")
