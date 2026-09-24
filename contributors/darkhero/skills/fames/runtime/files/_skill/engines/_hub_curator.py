#!/usr/bin/env python3
# token-class: ZT
"""_hub_curator.py — hub curator seat SSOT (ai_darkhero succeeded ai_master 2026-07-03)."""
from __future__ import annotations

HUB_CURATOR = "ai_darkhero"
HUB_CURATOR_LEGACY = frozenset({"ai_master", "ai_darkhero"})


def is_hub_curator(agent: str | None) -> bool:
    return bool(agent) and agent in HUB_CURATOR_LEGACY
