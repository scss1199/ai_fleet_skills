#!/usr/bin/env python3
"""Select an authentication surface by capability, never by host identity."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


VALID_STATES = {"available", "unavailable", "unknown"}
HARD_FORBIDDEN = {
    "agent_password_entry",
    "captcha_bypass",
    "cookie_extraction",
    "profile_extraction",
    "secret_to_chat",
    "secret_to_argv",
    "secret_to_log",
}


def _string_set(value: object, field: str, errors: list[str]) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        errors.append(f"{field} must be a list of non-empty strings")
        return set()
    return set(value)


def resolve(document: object) -> dict:
    errors: list[str] = []
    if not isinstance(document, dict) or document.get("schema") != 1:
        return {"ok": False, "state": "UNKNOWN", "reason": "INVALID_INVENTORY", "errors": ["schema must be 1"]}
    requirements = document.get("requirements")
    adapters = document.get("adapters")
    if not isinstance(requirements, dict) or not isinstance(adapters, list):
        return {"ok": False, "state": "UNKNOWN", "reason": "INVALID_INVENTORY", "errors": ["requirements object and adapters list are required"]}

    required = _string_set(requirements.get("capabilities", []), "requirements.capabilities", errors)
    forbidden = _string_set(requirements.get("forbidden_capabilities", []), "requirements.forbidden_capabilities", errors) | HARD_FORBIDDEN
    max_risk = requirements.get("max_risk", 3)
    if not isinstance(max_risk, int) or isinstance(max_risk, bool) or max_risk < 0:
        errors.append("requirements.max_risk must be a non-negative integer")

    eligible: list[tuple[tuple[int, int, int, int], dict]] = []
    rejected: list[dict] = []
    saw_unknown = False
    for position, raw in enumerate(adapters):
        if not isinstance(raw, dict):
            errors.append(f"adapters[{position}] must be an object")
            continue
        adapter_id = raw.get("id")
        state = raw.get("state")
        if not isinstance(adapter_id, str) or not adapter_id:
            errors.append(f"adapters[{position}].id must be a non-empty string")
            continue
        if state not in VALID_STATES:
            errors.append(f"adapters[{position}].state is invalid")
            continue
        capabilities = _string_set(raw.get("capabilities", []), f"adapters[{position}].capabilities", errors)
        risk = raw.get("risk", 3)
        cost = raw.get("interaction_cost", 100)
        priority = raw.get("priority", 0)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in (risk, cost, priority)) or risk < 0 or cost < 0:
            errors.append(f"adapters[{position}] has invalid risk, interaction_cost, or priority")
            continue
        evidence = raw.get("evidence_refs")
        if not isinstance(evidence, list) or not evidence or any(not isinstance(item, str) or not item for item in evidence):
            errors.append(f"adapters[{position}].evidence_refs must be a non-empty string list")
            continue
        if state == "unknown":
            saw_unknown = True
            rejected.append({"id": adapter_id, "reason": "UNKNOWN_AVAILABILITY"})
            continue
        missing = sorted(required - capabilities)
        unsafe = sorted(forbidden & capabilities)
        reasons = []
        if state != "available":
            reasons.append("UNAVAILABLE")
        if missing:
            reasons.append("MISSING_CAPABILITIES")
        if unsafe:
            reasons.append("FORBIDDEN_CAPABILITY")
        if risk > max_risk:
            reasons.append("RISK_CEILING")
        if reasons:
            rejected.append({"id": adapter_id, "reason": "+".join(reasons), "missing": missing, "forbidden": unsafe})
            continue
        eligible.append(((risk, cost, -priority, position), {"id": adapter_id, "capabilities": sorted(capabilities), "evidence_refs": evidence}))

    if errors:
        return {"ok": False, "state": "UNKNOWN", "reason": "INVALID_INVENTORY", "errors": errors}
    if eligible:
        score, selected = min(eligible, key=lambda item: item[0])
        return {"ok": True, "state": "PASS", "reason": "CAPABILITY_MATCH", "selected": selected, "score": {"risk": score[0], "interaction_cost": score[1], "priority": -score[2]}, "rejected": rejected}
    if saw_unknown:
        return {"ok": False, "state": "UNKNOWN", "reason": "ADAPTER_AVAILABILITY_UNKNOWN", "rejected": rejected, "errors": []}
    capability_union: set[str] = set()
    for item in adapters:
        if isinstance(item, dict) and isinstance(item.get("capabilities"), list):
            capability_union.update(value for value in item["capabilities"] if isinstance(value, str))
    return {"ok": False, "state": "HANDOFF", "reason": "NO_CAPABLE_ADAPTER", "missing_capabilities": sorted(required - capability_union), "rejected": rejected, "errors": []}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="names-only JSON input; stdin when omitted")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        document = json.loads(args.input.read_text(encoding="utf-8-sig") if args.input else sys.stdin.read())
        result = resolve(document)
    except (OSError, json.JSONDecodeError) as exc:
        result = {"ok": False, "state": "UNKNOWN", "reason": "INVALID_INVENTORY", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
