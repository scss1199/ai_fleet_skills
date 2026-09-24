#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""hub_python.py — Fleet Python interpreter SSOT (probe, never hardcode 311).

CITE: _registry/python-runtime.json
"""
from __future__ import annotations

import json
import os
import sys

ENG = os.path.dirname(os.path.abspath(__file__))
HUB = os.environ.get("AI_WORKSPACE") or os.path.dirname(os.path.dirname(ENG))
RUNTIME = os.path.join(HUB, "_registry", "python-runtime.json")
PATH_STAMP = os.path.join(ENG, "hooks", ".pythonw.path")


def _load_runtime() -> dict:
    try:
        with open(RUNTIME, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _profile_name() -> str:
    return os.environ.get("FLEET_PYTHON_PROFILE") or _load_runtime().get("default_profile") or "darkhero"


def candidates(*, pythonw: bool = True) -> list[str]:
    rt = _load_runtime()
    prof = (rt.get("machines") or {}).get(_profile_name()) or {}
    key = "pythonw_candidates" if pythonw else "python_candidates"
    out = list(prof.get(key) or [])
    if pythonw:
        out.extend(rt.get("program_files_candidates") or [])
    else:
        out.extend((p.replace("pythonw.exe", "python.exe") for p in (rt.get("program_files_candidates") or [])))
    # sys.executable fallbacks
    exe = sys.executable
    if pythonw:
        if exe.lower().endswith("python.exe"):
            w = exe[:-10] + "pythonw.exe"
            if os.path.isfile(w):
                out.append(w)
        out.append(exe)
    else:
        if exe.lower().endswith("pythonw.exe"):
            out.append(exe[:-11] + "python.exe")
        out.append(exe)
    out.append("pythonw.exe" if pythonw else "python.exe")
    seen: set[str] = set()
    deduped: list[str] = []
    for p in out:
        p = os.path.normpath(p)
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped


def resolve_pythonw() -> str:
    for p in candidates(pythonw=True):
        if p == "pythonw.exe" or os.path.isfile(p):
            return p
    return sys.executable


def resolve_python() -> str:
    for p in candidates(pythonw=False):
        if p == "python.exe" or os.path.isfile(p):
            return p
    return sys.executable


def write_stamp(path: str | None = None) -> str:
    pyw = resolve_pythonw()
    dest = path or PATH_STAMP
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(pyw)
    return pyw


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Resolve fleet pythonw/python paths")
    ap.add_argument("--pythonw", action="store_true", help="print pythonw path only")
    ap.add_argument("--python", action="store_true", help="print python path only")
    ap.add_argument("--write-stamp", action="store_true", help="write hooks/.pythonw.path")
    args = ap.parse_args()
    if args.write_stamp:
        print(write_stamp())
        return 0
    if args.python:
        print(resolve_python())
        return 0
    print(resolve_pythonw())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
