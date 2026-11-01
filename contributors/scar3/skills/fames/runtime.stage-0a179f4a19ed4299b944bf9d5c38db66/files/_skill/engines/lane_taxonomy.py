#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""lane_taxonomy.py — MTM/ZTM / MTO / MTD / PFKT lane SSOT for engines.

CITE: _registry/fleet-skill-lanes.json · _registry/mtm-protocol.json
"""
from __future__ import annotations

import json
import os

LANE_ZTM = "zero-token-mechanism"  # lane id; spoken upgrade = MTM (minimal-token-mechanism)
LANE_MTD = "MTD"
UNIT_ZAT = "ZAT"  # MTO deliverable unit; legacy engine name zat-verify-gate
ABBREV_ZTM = "ZTM"
ABBREV_MTM = "MTM"
UNIT_MTO = "MTO"  # minimal-token-operation (replaces spoken ZCT)
LEGACY_ZCT = "ZCT"
PROTO_PFKT = "PFKT"

_LANES_PATH = os.path.join(
    os.environ.get("AI_WORKSPACE", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "_registry",
    "fleet-skill-lanes.json",
)

_LEGACY_TO_ZTM = frozenset({LEGACY_ZCT, "ZAT", ABBREV_ZTM, ABBREV_MTM, "minimal-token-mechanism"})


def norm_lane(raw: str | None) -> str | None:
    if not raw:
        return None
    v = raw.strip().strip('"')
    if v.upper() == PROTO_PFKT:
        return PROTO_PFKT
    if v.upper() == UNIT_MTO:
        return LANE_ZTM
    if v.lower() == LANE_ZTM or v.upper() in _LEGACY_TO_ZTM:
        return LANE_ZTM
    if v.upper() == LANE_MTD:
        return LANE_MTD
    return v


def display_lane(lane: str | None, prefer_mtm: bool = False) -> str:
    if lane == LANE_ZTM:
        return ABBREV_MTM if prefer_mtm else ABBREV_ZTM
    if lane == PROTO_PFKT:
        return PROTO_PFKT
    return lane or "?"


def is_mtm(lane: str | None) -> bool:
    return is_ztm(lane)


def is_ztm(lane: str | None) -> bool:
    return norm_lane(lane) == LANE_ZTM


def is_mtd(lane: str | None) -> bool:
    return norm_lane(lane) == LANE_MTD


def load_glossary() -> dict:
    try:
        with open(_LANES_PATH, encoding="utf-8-sig") as fh:
            return json.load(fh).get("operator_glossary") or {}
    except (OSError, json.JSONDecodeError):
        return {}
