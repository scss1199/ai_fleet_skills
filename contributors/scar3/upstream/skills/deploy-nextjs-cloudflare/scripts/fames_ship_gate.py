#!/usr/bin/env python3
"""Fail-closed validator for an R2 FAMES Cloudflare ship receipt."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PHASES = ["FP", "MTM", "SCF", "AEX", "SEAL"]
JOURNAL = ["PREPARE", "APPLY", "VERIFY", "COMMIT", "RECOVER"]


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("risk_class") != "R2":
        errors.append("risk_class_must_be_R2")
    goal_hash = data.get("goal", {}).get("semantic_goal_hash", "")
    if not re.fullmatch(r"[0-9a-f]{64}", goal_hash):
        errors.append("semantic_goal_hash_invalid")

    phases = data.get("phase_ledger", [])
    if [item.get("phase") for item in phases] != PHASES:
        errors.append("phase_order_invalid")
    for item in phases:
        phase, state = item.get("phase"), item.get("state")
        if state not in {"PASS", "NOT_APPLICABLE"}:
            errors.append(f"phase_not_terminal:{phase}")
        if state == "NOT_APPLICABLE" and item.get("activation_predicate") is not False:
            errors.append(f"not_applicable_without_false_predicate:{phase}")

    transaction = data.get("transaction", {})
    journal = transaction.get("journal", [])
    if [item.get("state") for item in journal] != JOURNAL:
        errors.append("transaction_journal_order_invalid")
    for item in journal:
        state, status = item.get("state"), item.get("status")
        allowed = {"PASS"} if state != "RECOVER" else {"PASS", "NOT_TRIGGERED"}
        if status not in allowed:
            errors.append(f"journal_not_terminal:{state}")
    for field in ("before_version", "new_version", "rollback_command", "read_back_version"):
        if not str(transaction.get(field, "")).strip():
            errors.append(f"transaction_field_missing:{field}")
    if transaction.get("read_back_version") != transaction.get("new_version"):
        errors.append("deployment_read_back_mismatch")

    evidence = data.get("ship_evidence", {})
    for name in ("build", "dry_run", "version_upload", "preview_verify", "public_verify", "git"):
        item = evidence.get(name, {})
        if item.get("exit_status") != 0:
            errors.append(f"evidence_failed:{name}")
    git = evidence.get("git", {})
    if not git.get("local_sha") or git.get("local_sha") != git.get("upstream_sha"):
        errors.append("git_read_back_mismatch")

    cpu = evidence.get("cpu_probe", {})
    if cpu.get("route_count", 0) < 1:
        errors.append("cpu_probe_empty")
    if cpu.get("non_ok_outcomes") != 0:
        errors.append("cpu_non_ok_outcomes")
    if cpu.get("exceeded_cpu") != 0:
        errors.append("cpu_limit_exceeded")
    p99, budget = cpu.get("p99_ms"), cpu.get("budget_ms")
    if not isinstance(p99, (int, float)) or not isinstance(budget, (int, float)) or p99 > budget:
        errors.append("cpu_p99_budget_failed")

    if data.get("result", {}).get("goal_hash") != goal_hash:
        errors.append("goal_result_identity_mismatch")
    if not data.get("evidence"):
        errors.append("canonical_fames_evidence_missing")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    path = Path(args.input).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        errors = validate(data)
    except Exception as exc:  # fail closed on malformed/missing receipt
        errors = [f"receipt_read_failed:{type(exc).__name__}"]
    result = {"ok": not errors, "input": str(path), "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else (
        "FAMES_SHIP_GATE=PASS" if not errors else "FAMES_SHIP_GATE=FAIL " + ",".join(errors)
    ))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
