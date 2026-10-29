#!/usr/bin/env python3
"""Run a bounded real-Claude A/B and write a privacy-bounded FAMES receipt.

The baseline excludes user settings (and therefore the global Claude hook). The
candidate uses user settings, so the only intended treatment in the isolated
cwd is the registered FAMES UserPromptSubmit lifecycle path. This runner proves
only the declared smoke-suite population; broader task effectiveness remains
UNKNOWN until separately measured.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"UNREADABLE_JSON_{type(exc).__name__.upper()}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("INVALID_JSON_OBJECT")
    return value


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _claude_executable() -> str | None:
    candidates = ["claude.cmd", "claude"] if os.name == "nt" else ["claude"]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _hidden_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= STARTF_USESHOWWINDOW
    info.wShowWindow = SW_HIDE
    return info


def _safe_model_usage(value: object) -> tuple[dict[str, Any], bool]:
    if not isinstance(value, dict):
        return {}, False
    safe: dict[str, Any] = {}
    valid = True
    for name, row in value.items():
        if not isinstance(name, str) or not isinstance(row, dict):
            valid = False
            continue
        cost = _number(row.get("costUSD"))
        fields = {
            "input_tokens": _integer(row.get("inputTokens")),
            "output_tokens": _integer(row.get("outputTokens")),
            "cache_read_input_tokens": _integer(row.get("cacheReadInputTokens")),
            "cache_creation_input_tokens": _integer(row.get("cacheCreationInputTokens")),
            "cost_usd": cost,
            "provider": str(row.get("provider") or "")[:32],
            "canonical_model": str(row.get("canonicalModel") or "")[:96],
        }
        if any(fields[key] is None for key in (
            "input_tokens", "output_tokens", "cache_read_input_tokens",
            "cache_creation_input_tokens", "cost_usd",
        )):
            valid = False
        safe[_sha_text(name)] = fields
    return safe, valid and bool(safe)


def _model_usage_totals(value: dict[str, Any]) -> tuple[int | None, int | None]:
    input_total = 0
    output_total = 0
    if not value:
        return None, None
    for row in value.values():
        if not isinstance(row, dict):
            return None, None
        inputs = [
            row.get("input_tokens"),
            row.get("cache_read_input_tokens"),
            row.get("cache_creation_input_tokens"),
        ]
        output = row.get("output_tokens")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in [*inputs, output]):
            return None, None
        input_total += sum(inputs)
        output_total += output
    return input_total, output_total


def _run_cli(
    executable: str,
    *,
    prompt: str,
    cwd: Path,
    model: str,
    system_prompt: str,
    max_budget_usd: float,
    timeout_seconds: int,
    setting_sources: str,
    settings_path: Path,
) -> tuple[dict[str, Any], int, str]:
    command = [
        executable,
        "-p",
        "--model", model,
        "--output-format", "json",
        "--tools", "",
        "--system-prompt", system_prompt,
        "--setting-sources", setting_sources,
        "--settings", str(settings_path),
        "--permission-mode", "dontAsk",
        "--max-budget-usd", format(max_budget_usd, ".6f"),
        "--no-session-persistence",
    ]
    env = os.environ.copy()
    env.update({"NO_COLOR": "1", "DISABLE_AUTOUPDATER": "1"})
    try:
        proc = subprocess.run(
            command,
            input=prompt,
            cwd=str(cwd),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            shell=False,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=_hidden_startupinfo(),
        )
    except subprocess.TimeoutExpired:
        return {}, -1, "TIMEOUT"
    except OSError as exc:
        return {}, -1, f"SPAWN_{type(exc).__name__.upper()}"
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}, proc.returncode, "INVALID_PROVIDER_JSON"
    if not isinstance(payload, dict):
        return {}, proc.returncode, "INVALID_PROVIDER_OBJECT"
    return payload, proc.returncode, "" if proc.returncode == 0 else "PROVIDER_NONZERO"


def _structured_result(raw: object) -> tuple[dict[str, Any] | None, str, int]:
    if not isinstance(raw, str):
        return None, _sha_text(""), 0
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    return parsed if isinstance(parsed, dict) else None, _sha_text(raw), len(raw)


def _sanitize_call(
    payload: dict[str, Any],
    *,
    returncode: int,
    diagnostic: str,
    prompt: str,
    expected: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    result, result_sha, result_chars = _structured_result(payload.get("result"))
    cost = _number(payload.get("total_cost_usd"))
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    input_tokens = _integer(usage.get("input_tokens"))
    output_tokens = _integer(usage.get("output_tokens"))
    model_usage, model_usage_valid = _safe_model_usage(payload.get("modelUsage"))
    billable_input_tokens, billable_output_tokens = _model_usage_totals(model_usage)
    session_id = str(payload.get("session_id") or "")
    result_uuid = str(payload.get("uuid") or "")
    is_error = payload.get("is_error")
    correct = result == expected
    success = bool(
        returncode == 0
        and is_error is False
        and str(payload.get("subtype") or "") == "success"
        and isinstance(result, dict)
    )
    safe = {
        "state": "PASS" if success else "FAIL",
        "diagnostic": diagnostic or ("" if success else "PROVIDER_RESULT_ERROR"),
        "prompt_sha256": _sha_text(prompt),
        "prompt_chars": len(prompt),
        "result_sha256": result_sha,
        "result_chars": result_chars,
        "correct": correct,
        "false_abort": not success,
        "returncode": returncode,
        "stop_reason": str(payload.get("stop_reason") or "")[:64] or None,
        "terminal_reason": str(payload.get("terminal_reason") or "")[:64] or None,
        "session_identity_sha256": _sha_text(session_id) if session_id else None,
        "result_uuid_sha256": _sha_text(result_uuid) if result_uuid else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_cost_usd": cost,
        "model_usage": model_usage,
        "model_usage_valid": model_usage_valid,
        "billable_input_tokens": billable_input_tokens,
        "billable_output_tokens": billable_output_tokens,
        "raw_prompt_persisted": False,
        "raw_output_persisted": False,
    }
    return safe, session_id or None


def _turn_receipt_path(workspace: Path, session_id: str) -> Path:
    identity = _sha_text(f"claude\0{session_id}")
    return workspace / "_registry" / "fames-turn" / "claude" / f"{identity}.json"


def _verify_candidate_lifecycle(
    workspace: Path,
    *,
    session_id: str | None,
    prompt: str,
    package: dict[str, Any],
) -> dict[str, Any]:
    if not session_id:
        return {"state": "UNKNOWN", "reason": "MISSING_SESSION_ID"}
    path = _turn_receipt_path(workspace, session_id)
    if not path.is_file():
        return {"state": "UNKNOWN", "reason": "MISSING_LIFECYCLE_RECEIPT", "path": str(path)}
    try:
        receipt = _read_json(path)
        identity = _sha_bytes(path.read_bytes())
    except RuntimeError as exc:
        return {"state": "UNKNOWN", "reason": str(exc), "path": str(path)}
    checks = {
        "state": receipt.get("state") == "PASS",
        "agent": receipt.get("agent") == "ai_darkhero",
        "surface": receipt.get("surface_id") == "claude",
        "prompt": receipt.get("prompt_identity") == _sha_text(prompt),
        "package": receipt.get("package_sha") == package.get("package_sha"),
        "generation": receipt.get("skill_gen") == package.get("skill_gen"),
        "runtime_event": receipt.get("runtime_event_observed") is True,
        "activation": receipt.get("activation_evidence") == "lifecycle_hook",
        "read_back": receipt.get("read_back") is True,
        "privacy": receipt.get("raw_prompt_persisted") is False,
    }
    return {
        "state": "PASS" if all(checks.values()) else "UNKNOWN",
        "checks": checks,
        "receipt_sha256": identity,
        "path": str(path),
    }


def _verify_baseline_absence(workspace: Path, session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return {"state": "UNKNOWN", "reason": "MISSING_SESSION_ID"}
    path = _turn_receipt_path(workspace, session_id)
    return {
        "state": "PASS" if not path.exists() else "FAIL",
        "receipt_absent": not path.exists(),
        "path": str(path),
    }


def _sum_known(rows: list[dict[str, Any]], field: str) -> float | int | None:
    values = [row.get(field) for row in rows]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        return None
    return sum(values)


def _summary(cases: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
    baseline = [row["baseline"] for row in cases]
    candidate = [row["candidate"] for row in cases]
    count = len(cases)
    baseline_correctness = sum(row.get("correct") is True for row in baseline) / count if count else 0.0
    candidate_correctness = sum(row.get("correct") is True for row in candidate) / count if count else 0.0
    candidate_false_aborts = sum(row.get("false_abort") is True for row in candidate)
    baseline_cost = _sum_known(baseline, "total_cost_usd")
    candidate_cost = _sum_known(candidate, "total_cost_usd")
    baseline_input = _sum_known(baseline, "billable_input_tokens")
    candidate_input = _sum_known(candidate, "billable_input_tokens")
    cost_overhead = (
        float(candidate_cost) - float(baseline_cost)
        if baseline_cost is not None and candidate_cost is not None else None
    )
    input_overhead = (
        int(candidate_input) - int(baseline_input)
        if baseline_input is not None and candidate_input is not None else None
    )
    checks = {
        "candidate_correctness": candidate_correctness >= float(thresholds["required_candidate_correctness"]),
        "candidate_false_aborts": candidate_false_aborts <= int(thresholds["max_candidate_false_aborts"]),
        "candidate_lifecycle": all(row["candidate_lifecycle"]["state"] == "PASS" for row in cases),
        "baseline_hook_absence": all(row["baseline_hook_absence"]["state"] == "PASS" for row in cases),
        "cost_known": baseline_cost is not None and candidate_cost is not None,
        "candidate_cost_cap": candidate_cost is not None and candidate_cost <= float(thresholds["max_total_candidate_cost_usd"]),
        "cost_overhead_cap": cost_overhead is not None and cost_overhead <= float(thresholds["max_cost_overhead_usd"]),
        "input_overhead_cap": input_overhead is not None and input_overhead <= int(thresholds["max_input_token_overhead"]),
    }
    return {
        "state": "PASS" if all(checks.values()) else "FAIL",
        "scope": "DECLARED_SMOKE_SUITE_ONLY",
        "generalization": "UNKNOWN",
        "case_count": count,
        "baseline_correctness": baseline_correctness,
        "candidate_correctness": candidate_correctness,
        "candidate_false_aborts": candidate_false_aborts,
        "baseline_cost_usd": baseline_cost,
        "candidate_cost_usd": candidate_cost,
        "cost_overhead_usd": cost_overhead,
        "baseline_billable_input_tokens": baseline_input,
        "candidate_billable_input_tokens": candidate_input,
        "billable_input_token_overhead": input_overhead,
        "savings_claim": (
            "MEASURED" if cost_overhead is not None and cost_overhead < 0 else "NOT_OBSERVED"
        ),
        "checks": checks,
    }


def run_live(workspace: Path, suite_path: Path, receipt_dir: Path | None = None) -> dict[str, Any]:
    suite = _read_json(suite_path)
    package_path = workspace / "_skill" / "fleet-skills" / "fames" / "bundle-manifest.json"
    package = _read_json(package_path)
    executable = _claude_executable()
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    if not executable:
        return {"schema": 1, "id": "FAMES-CLAUDE-LIVE-AB", "run_id": run_id, "state": "UNKNOWN", "reason": "CLAUDE_CLI_MISSING"}
    cases = suite.get("cases")
    thresholds = suite.get("thresholds")
    if not isinstance(cases, list) or not cases or not isinstance(thresholds, dict):
        raise RuntimeError("INVALID_EVAL_SUITE")
    temp_parent = workspace / "_temp" / "fames-claude-live-ab"
    temp_parent.mkdir(parents=True, exist_ok=True)
    measured_cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=run_id + "-", dir=temp_parent) as raw_temp:
        seat_root = Path(raw_temp) / "ai_darkhero"
        seat_root.mkdir()
        hook_script = workspace / "_skill" / "fleet-skills" / "token-preflight" / "scripts" / "claude_session_hook.py"
        if not hook_script.is_file():
            raise RuntimeError("MISSING_CLAUDE_FAMES_HOOK")
        baseline_settings = seat_root / "baseline-settings.json"
        candidate_settings = seat_root / "candidate-settings.json"
        baseline_settings.write_text("{}\n", encoding="utf-8")
        hook_command = f'"{sys.executable}" "{hook_script}"'
        candidate_settings.write_text(json.dumps({
            "hooks": {
                "UserPromptSubmit": [{
                    "hooks": [{"type": "command", "command": hook_command, "timeout": 20}]
                }]
            }
        }, separators=(",", ":")) + "\n", encoding="utf-8")
        for index, case in enumerate(cases):
            if not isinstance(case, dict) or not isinstance(case.get("prompt"), str) or not isinstance(case.get("expected"), dict):
                raise RuntimeError("INVALID_EVAL_CASE")
            prompt = case["prompt"]
            common = {
                "executable": executable,
                "prompt": prompt,
                "cwd": seat_root,
                "model": str(suite.get("model") or "fable"),
                "system_prompt": str(suite.get("system_prompt") or ""),
                "max_budget_usd": float(suite.get("max_budget_usd_per_call") or 0.08),
                "timeout_seconds": int(suite.get("timeout_seconds") or 90),
            }
            arms = ["baseline", "candidate"] if index % 2 == 0 else ["candidate", "baseline"]
            results: dict[str, dict[str, Any]] = {}
            sessions: dict[str, str | None] = {}
            for arm in arms:
                sources = "project,local"
                settings_path = baseline_settings if arm == "baseline" else candidate_settings
                raw, rc, diagnostic = _run_cli(
                    **common,
                    setting_sources=sources,
                    settings_path=settings_path,
                )
                safe, session_id = _sanitize_call(
                    raw,
                    returncode=rc,
                    diagnostic=diagnostic,
                    prompt=prompt,
                    expected=case["expected"],
                )
                safe["setting_sources_sha256"] = _sha_text(sources)
                safe["settings_sha256"] = _sha_bytes(settings_path.read_bytes())
                safe["temperature_control"] = "UNSUPPORTED_BY_CLAUDE_CODE_CLI"
                results[arm] = safe
                sessions[arm] = session_id
            measured_cases.append({
                "id": str(case.get("id") or f"CASE-{index + 1}"),
                "expected_sha256": _sha_text(json.dumps(case["expected"], sort_keys=True, separators=(",", ":"))),
                "execution_order": arms,
                "baseline": results["baseline"],
                "candidate": results["candidate"],
                "baseline_hook_absence": _verify_baseline_absence(workspace, sessions["baseline"]),
                "candidate_lifecycle": _verify_candidate_lifecycle(
                    workspace,
                    session_id=sessions["candidate"],
                    prompt=prompt,
                    package=package,
                ),
            })
    summary = _summary(measured_cases, thresholds)
    receipt = {
        "schema": 1,
        "id": "FAMES-CLAUDE-LIVE-AB",
        "run_id": run_id,
        "generated": now.isoformat(),
        "state": summary["state"],
        "suite_id": suite.get("id"),
        "suite_sha256": _sha_bytes(suite_path.read_bytes()),
        "package_sha": package.get("package_sha"),
        "skill_gen": package.get("skill_gen"),
        "provider_surface": "claude-code-cli-first-party",
        "model_requested": suite.get("model"),
        "auth_source": "CLAUDE_CODE_EXISTING_AUTH_NAMES_ONLY",
        "api_key_read": False,
        "raw_prompt_persisted": False,
        "raw_output_persisted": False,
        "cases": measured_cases,
        "summary": summary,
    }
    out_dir = receipt_dir or workspace / "_registry" / "fames-evidence" / "claude-live-ab"
    out_path = out_dir / f"{run_id}.json"
    _atomic_write(out_path, receipt)
    receipt["receipt_path"] = str(out_path)
    receipt["receipt_sha256"] = _sha_bytes(out_path.read_bytes())
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(os.environ.get("AI_WORKSPACE", r"C:\ai_workspace")))
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--receipt-dir", type=Path)
    parser.add_argument("--live", action="store_true", help="Authorize bounded real Claude calls declared by the suite")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    suite = (args.suite or workspace / "_skill" / "fleet-skills" / "fames" / "references" / "claude-live-eval.json").resolve()
    if not args.live:
        result = {
            "schema": 1,
            "id": "FAMES-CLAUDE-LIVE-AB",
            "state": "HANDOFF",
            "reason": "LIVE_FLAG_REQUIRED",
            "suite_sha256": _sha_bytes(suite.read_bytes()) if suite.is_file() else None,
            "metered_calls": 0,
        }
    else:
        result = run_live(workspace, suite, args.receipt_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result.get("state"))
    return 0 if result.get("state") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
