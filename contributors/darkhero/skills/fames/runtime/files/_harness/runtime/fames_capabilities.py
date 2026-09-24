"""One FAMES capability contract; no provider calls, proof execution or authority."""
from __future__ import annotations

import hashlib
import json
import re

COMPONENTS = {"intent_to_skill", "jev", "lean"}
FACETS = {"goal", "authority", "capabilities", "acceptance", "evidence", "budgets", "pending_obligations"}


def policy_snapshot(value):
    """Resolve the canonical policy without creating another policy authority."""
    if value is None:
        return {"state": "NOT_CONFIGURED", "reason": "legacy_contract_without_unified_entrypoint"}
    try:
        if (not isinstance(value, dict) or type(value.get("schema")) is not int
                or value["schema"] != 1 or value.get("id") != "FAMES-UNIFIED-ENTRYPOINT"
                or value.get("public_trigger") != "FAMES"):
            raise ValueError
        components = value["components"]
        scope = value["self_similar_contract"]
        if (not isinstance(components, dict) or set(components) != COMPONENTS
                or any(not isinstance(c, dict) or c.get("execution_authority") is not False
                       or not c.get("activation") for c in components.values())
                or not isinstance(scope, dict) or set(scope.get("facets", [])) != FACETS
                or scope.get("runtime") != "_harness/runtime/skill_scope.py"
                or not scope.get("unsupported")):
            raise ValueError
        directive = value["hot_directive"]
        if not isinstance(directive, str) or not 100 <= len(directive) <= 1400:
            raise ValueError
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return {**value, "state": "PASS", "policy_sha256": hashlib.sha256(raw).hexdigest()}
    except (KeyError, ValueError, TypeError):
        return {"state": "UNKNOWN", "reason": "invalid_unified_entrypoint"}


def _candidate(row):
    if not isinstance(row, dict):
        raise ValueError
    sid, path, digest = (row.get(k) for k in ("id", "path", "body_sha256"))
    if (not isinstance(sid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,99}", sid)
            or not isinstance(path, str) or not path or len(path) > 1024
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError
    return {"id": sid, "path": path, "body_sha256": digest}


def route_receipt(policy, *, prompt_identity, intake_state, local, advice):
    """Compose already-admitted candidates; skill loading rechecks body identity.

    Component observations remain separate. Missing Jev never grants a new
    provider permission, and a deferred Lean decision is never NOT_APPLICABLE.
    """
    result = {
        "schema": 1, "public_entrypoint": "FAMES", "state": "UNKNOWN",
        "policy_sha256": policy.get("policy_sha256"), "prompt_identity": prompt_identity,
        "components": {
            "intent_to_skill": {"state": "MODEL_JUDGMENT_REQUIRED", "local_state": local.get("state", "UNKNOWN"),
                                "decision_owner": "current_conversation_model"},
            "jev": {"state": advice.get("state", "UNAVAILABLE"), "reason": advice.get("reason", "unknown"),
                    "role": "advisory", "api_calls": advice.get("api_calls", 0)},
            "lean": {"state": "APPLICABILITY_UNASSESSED", "proof_state": "NOT_RUN",
                     "rule": "Require bound proof for an applicable formal obligation; absence is not a proof"},
        },
        "self_similar_contract": policy.get("self_similar_contract", {}),
        "candidates": [], "mandatory_skill_ids": advice.get("mandatory_skill_ids", []),
        "unresolved_capabilities": local.get("unresolved_capabilities", []),
        "candidate_overflow": local.get("candidate_overflow", 0),
        "read_only_hint": local.get("read_only_hint", False),
        "skill_loaded": False, "skill_executed": False, "execution_authorized": False,
        "new_api_calls": 0, "raw_prompt_persisted": False,
    }
    if (policy.get("state") != "PASS" or intake_state != "PASS"
            or not isinstance(prompt_identity, str) or not re.fullmatch(r"[0-9a-f]{64}", prompt_identity)):
        result["reason"] = "policy_or_intake_unverified"
        return result
    try:
        sources = []
        if local.get("state") == "CANDIDATES":
            rows = local.get("candidates")
            if not isinstance(rows, list) or len(rows) > 3:
                raise ValueError
            sources.extend((row, "local") for row in rows)
        # Shadow advice is intentionally not shown as a recommendation.
        if advice.get("state") == "SUGGESTION" and advice.get("mode") == "advisory":
            sources.append((advice.get("selected_skill"), "jev"))
        merged = {}
        for row, source in sources:
            item = _candidate(row)
            previous = merged.get(item["id"])
            if previous:
                if any(previous[k] != item[k] for k in ("path", "body_sha256")):
                    raise ValueError
                if source not in previous["sources"]:
                    previous["sources"].append(source)
            else:
                merged[item["id"]] = {**item, "sources": [source]}
        result.update(state="BOUND_NOT_EXECUTION_PROOF", reason="model_judgment_required",
                      candidates=list(merged.values()))
    except (ValueError, TypeError, KeyError):
        result.update(reason="invalid_or_conflicting_candidate_bindings", candidates=[])
    return result


def render_route(receipt):
    """Compact per-turn facts; the canonical core owns the policy prose."""
    components = receipt["components"]
    lines = [f"FAMES ROUTE — {receipt['state']} — local={components['intent_to_skill']['local_state']}; "
             f"Jev={components['jev']['state']}; Lean=APPLICABILITY_UNASSESSED."]
    if receipt["state"] == "UNKNOWN":
        lines.append("No verified unified candidates; preserve unresolved intake and authority boundaries.")
    else:
        for item in receipt["candidates"]:
            lines.append(f"- {item['id']} [{'+'.join(item['sources'])}]: {item['path']} | sha256={item['body_sha256']}")
        lines.append("Select by current intent and actual skill descriptions; recheck bodies before loading. Advice is not execution.")
    if receipt["mandatory_skill_ids"]:
        lines.append("Preserve explicit/mandatory skills: " + ", ".join(receipt["mandatory_skill_ids"]) + ".")
    if receipt["unresolved_capabilities"]:
        lines.append("Host catalog discovery: " + ", ".join(receipt["unresolved_capabilities"]) + ".")
    if receipt["candidate_overflow"]:
        lines.append(f"Additional local candidates omitted: {receipt['candidate_overflow']}; retain all requested stages.")
    if receipt["read_only_hint"]:
        lines.append("Read-only intent hint: preserve the user's actual authority and negation.")
    text = "\n".join(lines)
    if len(text) > 2400:
        return "FAMES ROUTE — UNKNOWN (context budget); retain candidate identities in the turn receipt and load a bounded slice."
    return text
