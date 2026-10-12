#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""_local_curator.py — per-machine hub curator seat name (scar3=ai_scar3, darkhero=ai_darkhero)."""
from __future__ import annotations

import json
import os
from functools import lru_cache

from _hub_curator import HUB_CURATOR, HUB_CURATOR_LEGACY, is_hub_curator
from _paths import COMMON as HUB, REGISTRY


def _this_host() -> str:
    try:
        import socket
        return socket.gethostname().strip().lower()
    except Exception:
        return ""


@lru_cache(maxsize=1)
def local_curator() -> str:
    # machine.json is a TRACKED hub file, so every checkout carries the same copy (it names
    # scar3). Its local_curator applies only on the machine it names; elsewhere it would turn
    # the hub-root seat into another machine's curator (seen 2026-10-12: darkhero intake
    # stamped ai_scar3). A missing hostname field keeps the legacy behaviour.
    flag = os.path.join(REGISTRY, "machine.json")
    try:
        doc = json.loads(open(flag, encoding="utf-8-sig").read())
        name = (doc.get("local_curator") or "").strip()
        declared = (doc.get("hostname") or "").strip().lower()
        if name and (not declared or declared == _this_host()):
            return name
    except (OSError, json.JSONDecodeError):
        pass
    if os.path.isdir(os.path.join(HUB, HUB_CURATOR)):
        return HUB_CURATOR
    if os.path.isdir(os.path.join(HUB, "ai_scar3")):
        return "ai_scar3"
    return "ai_master"


def is_curator(agent: str) -> bool:
    return is_hub_curator(agent) or agent == local_curator()


def hub_exempt() -> frozenset[str]:
    """PFKT / A2A / accountability HARD DENY exemptions (fleet + per-machine edge hub)."""
    return frozenset(HUB_CURATOR_LEGACY) | frozenset({local_curator()})
