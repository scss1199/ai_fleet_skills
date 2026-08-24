#!/usr/bin/env python3
"""Mechanically verify a project's delegated, fail-closed ZT deploy recipe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ORCHESTRATOR_MARKERS = {
    "hidden_windows_subprocess": "CREATE_NO_WINDOW",
    "local_cpu_build": "run_local_gate",
    "source_push_read_back": "push_and_read_back",
    "version_upload": '"versions", "upload"',
    "version_traffic_deploy": '"versions", "deploy"',
    "old_100_new_0_stage": "@0%",
    "preview_pair_readiness": "wait_for_preview_pair",
    "preview_verification": "preview_url",
    "public_verification": "run_public_verify",
    "authenticated_verification": "run_authenticated_verify",
    "post_cpu_authenticated_verification": '"authenticated_post_cpu"',
    "asset_hash_verification": "verify_asset_samples",
    "cpu_verification": "run_cpu_probe",
    "rollback": "rollback(",
    "failed_candidate_zero_recovery": "failed_candidates_staged_at_zero",
    "ship_receipt_gate": "run_ship_receipt_gate",
    "deployment_read_back": "verify_deployed_pair",
    "recovery_double_read_back": "consecutive_source_matches >= 2",
    "receipt_write": "write_json(receipt_path",
    "prepare_state": '"PREPARE"',
    "apply_state": '"APPLY"',
    "verify_state": '"VERIFY"',
    "commit_state": '"COMMIT"',
    "recover_state": '"RECOVER"',
}


def verify(root: Path, wrapper_name: str, orchestrator_name: str) -> dict[str, object]:
    root = root.resolve()
    wrapper = (root / wrapper_name).resolve()
    orchestrator = (root / orchestrator_name).resolve()
    errors: list[str] = []
    if not wrapper.is_relative_to(root) or not orchestrator.is_relative_to(root):
        errors.append("path_escape")
    if not wrapper.is_file():
        errors.append("wrapper_missing")
    if not orchestrator.is_file():
        errors.append("orchestrator_missing")
    wrapper_text = wrapper.read_text(encoding="utf-8", errors="replace") if wrapper.is_file() else ""
    orchestrator_text = (
        orchestrator.read_text(encoding="utf-8", errors="replace") if orchestrator.is_file() else ""
    )
    wrapper_checks = {
        "delegates_to_orchestrator": Path(orchestrator_name).name in wrapper_text,
        "explicit_deploy_switch": "Deploy" in wrapper_text,
        "no_start_process": "Start-Process" not in wrapper_text,
    }
    for name, ok in wrapper_checks.items():
        if not ok:
            errors.append(f"wrapper:{name}")
    marker_checks = {name: marker in orchestrator_text for name, marker in ORCHESTRATOR_MARKERS.items()}
    for name, ok in marker_checks.items():
        if not ok:
            errors.append(f"orchestrator:{name}")
    forbidden_checks = {
        "shell_true_absent": "shell=True" not in orchestrator_text,
        "password_entry_absent": "agent_password_entry" not in orchestrator_text,
        "unversioned_wrangler_deploy_absent": '"wrangler", "deploy"' not in orchestrator_text,
    }
    for name, ok in forbidden_checks.items():
        if not ok:
            errors.append(f"forbidden:{name}")
    return {
        "schema": 1,
        "ok": not errors,
        "root": str(root),
        "wrapper": str(wrapper),
        "orchestrator": str(orchestrator),
        "wrapper_checks": wrapper_checks,
        "orchestrator_checks": marker_checks,
        "forbidden_checks": forbidden_checks,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--wrapper", default="ship.ps1")
    parser.add_argument("--orchestrator", default="scripts/ztm-cloudflare-ship.py")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(args.project_root, args.wrapper, args.orchestrator)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
