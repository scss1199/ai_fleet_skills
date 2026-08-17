#!/usr/bin/env python3
"""Negative controls for fames_ship_gate.py."""

from copy import deepcopy

from fames_ship_gate import validate


def valid_receipt() -> dict:
    goal_hash = "a" * 64
    return {
        "risk_class": "R2",
        "goal": {"semantic_goal_hash": goal_hash},
        "result": {"goal_hash": goal_hash},
        "phase_ledger": [
            {"phase": "FP", "state": "PASS"},
            {"phase": "MTM", "state": "PASS"},
            {"phase": "SCF", "state": "PASS"},
            {"phase": "AEX", "state": "NOT_APPLICABLE", "activation_predicate": False},
            {"phase": "SEAL", "state": "PASS"},
        ],
        "transaction": {
            "before_version": "old",
            "new_version": "new",
            "read_back_version": "new",
            "rollback_command": "wrangler versions deploy old@100 new@0",
            "journal": [
                {"state": "PREPARE", "status": "PASS"},
                {"state": "APPLY", "status": "PASS"},
                {"state": "VERIFY", "status": "PASS"},
                {"state": "COMMIT", "status": "PASS"},
                {"state": "RECOVER", "status": "NOT_TRIGGERED"},
            ],
        },
        "ship_evidence": {
            "build": {"exit_status": 0},
            "dry_run": {"exit_status": 0},
            "version_upload": {"exit_status": 0},
            "preview_verify": {"exit_status": 0},
            "public_verify": {"exit_status": 0},
            "git": {"exit_status": 0, "local_sha": "abc", "upstream_sha": "abc"},
            "cpu_probe": {
                "route_count": 25,
                "non_ok_outcomes": 0,
                "exceeded_cpu": 0,
                "p99_ms": 3,
                "budget_ms": 7,
            },
        },
        "evidence": [{"exit_status": 0}],
    }


cases = {
    "valid": lambda r: None,
    "wrong_risk": lambda r: r.update(risk_class="R1"),
    "phase_order": lambda r: r["phase_ledger"].reverse(),
    "missing_rollback": lambda r: r["transaction"].update(rollback_command=""),
    "readback_mismatch": lambda r: r["transaction"].update(read_back_version="old"),
    "build_failed": lambda r: r["ship_evidence"]["build"].update(exit_status=1),
    "cpu_exceeded": lambda r: r["ship_evidence"]["cpu_probe"].update(exceeded_cpu=1),
    "cpu_over_budget": lambda r: r["ship_evidence"]["cpu_probe"].update(p99_ms=8),
    "git_mismatch": lambda r: r["ship_evidence"]["git"].update(upstream_sha="def"),
}


def main() -> int:
    failures = 0
    for name, mutate in cases.items():
        receipt = deepcopy(valid_receipt())
        mutate(receipt)
        errors = validate(receipt)
        expected_ok = name == "valid"
        actual_ok = not errors
        passed = expected_ok == actual_ok
        failures += 0 if passed else 1
        print(f"{'PASS' if passed else 'SELFTEST-FAIL':14} {name:18} errors={errors[:2]}")
    print(f"SELFTEST_RC={1 if failures else 0} ({len(cases)-failures}/{len(cases)} cases)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
