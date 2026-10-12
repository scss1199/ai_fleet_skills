#!/usr/bin/env python3
"""Arm and verify one real Claude ai_* task without retaining task text.

`arm` freezes the active FAMES package and both Claude hook identities.
`verify` accepts only a later main Stop receipt whose completion claim, current
turn lifecycle, package generation, and privacy boundaries all pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _commands(settings: dict[str, Any], event: str) -> list[str]:
    result: list[str] = []
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    for group in hooks.get(event) or []:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks") or []:
            if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                result.append(hook["command"])
    return result


def _paths(workspace: Path, agent: str, settings_path: Path | None = None) -> dict[str, Path]:
    base = workspace / "_registry" / "fames-evidence" / "claude-task-acceptance"
    return {
        "manifest": workspace / "_skill" / "fleet-skills" / "fames" / "bundle-manifest.json",
        "prompt_hook": workspace / "_skill" / "fleet-skills" / "token-preflight" / "scripts" / "claude_session_hook.py",
        "stop_hook": workspace / "_skill" / "engines" / "claude-claim-integrity-hook.py",
        "settings": settings_path or Path.home() / ".claude" / "settings.json",
        "claims": workspace / "_registry" / "fames-evidence" / "claude-claim-integrity",
        "marker": base / f"{agent}-armed.json",
        "result": base / f"{agent}-result.json",
    }


def arm(workspace: Path, agent: str, settings_path: Path | None = None) -> dict[str, Any]:
    paths = _paths(workspace, agent, settings_path)
    manifest = _read(paths["manifest"])
    settings = _read(paths["settings"])
    prompt_commands = _commands(settings, "UserPromptSubmit")
    stop_commands = _commands(settings, "Stop")
    checks = {
        "manifest": bool(manifest.get("package_sha") and manifest.get("skill_gen")),
        "prompt_hook": paths["prompt_hook"].is_file()
        and any(str(paths["prompt_hook"]) in command for command in prompt_commands),
        "stop_hook": paths["stop_hook"].is_file()
        and any(str(paths["stop_hook"]) in command for command in stop_commands),
    }
    now = datetime.now(timezone.utc)
    state = "ARMED" if all(checks.values()) else "UNKNOWN"
    receipt = {
        "schema": 1,
        "id": "FAMES-CLAUDE-TASK-ACCEPTANCE-ARM",
        "state": state,
        "armed_at": now.isoformat(),
        "armed_epoch": now.timestamp(),
        "agent": agent,
        "package_sha": manifest.get("package_sha"),
        "skill_gen": manifest.get("skill_gen"),
        "prompt_hook_sha256": _sha(paths["prompt_hook"]),
        "stop_hook_sha256": _sha(paths["stop_hook"]),
        "checks": checks,
        "failed_checks": sorted(name for name, ok in checks.items() if not ok),
        "raw_prompt_persisted": False,
        "raw_message_persisted": False,
    }
    _write(paths["marker"], receipt)
    receipt["receipt_path"] = str(paths["marker"])
    return receipt


def verify(workspace: Path, agent: str, settings_path: Path | None = None) -> dict[str, Any]:
    paths = _paths(workspace, agent, settings_path)
    marker = _read(paths["marker"])
    current_prompt_sha = _sha(paths["prompt_hook"])
    current_stop_sha = _sha(paths["stop_hook"])
    candidates: list[tuple[float, Path, dict[str, Any]]] = []
    armed_epoch = marker.get("armed_epoch")
    if isinstance(armed_epoch, (int, float)) and paths["claims"].is_dir():
        for path in paths["claims"].glob("*.json"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime + 1 < float(armed_epoch):
                continue
            receipt = _read(path)
            lifecycle = receipt.get("fames_turn_lifecycle")
            if not isinstance(lifecycle, dict):
                lifecycle = {}
            checks = {
                "main_stop": receipt.get("event") == "Stop",
                "claim_allowed": receipt.get("state") == "PASS"
                and receipt.get("action") == "allow"
                and isinstance(receipt.get("claim_count"), int)
                and receipt.get("claim_count") > 0
                and receipt.get("violation_count") == 0,
                "turn_lifecycle": lifecycle.get("state") == "PASS"
                and bool(lifecycle.get("turn_receipt_sha256")),
                "package_identity": lifecycle.get("package_sha") == marker.get("package_sha"),
                "generation_identity": lifecycle.get("skill_gen") == marker.get("skill_gen"),
                "prompt_hook_identity": marker.get("prompt_hook_sha256") == current_prompt_sha,
                "stop_hook_identity": marker.get("stop_hook_sha256") == current_stop_sha
                and receipt.get("implementation_identity_sha") == current_stop_sha,
                "privacy_boundary": receipt.get("raw_message_persisted") is False
                and lifecycle.get("raw_prompt_persisted") is False,
            }
            if all(checks.values()):
                candidates.append((mtime, path, receipt))
    candidates.sort(key=lambda row: row[0], reverse=True)
    selected = candidates[0] if candidates else None
    state = "PASS" if marker.get("state") == "ARMED" and selected else "UNKNOWN"
    receipt = {
        "schema": 1,
        "id": "FAMES-CLAUDE-TASK-ACCEPTANCE",
        "state": state,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "armed_receipt_sha256": _sha(paths["marker"]),
        "package_sha": marker.get("package_sha"),
        "skill_gen": marker.get("skill_gen"),
        "selected_claim_receipt_sha256": _sha(selected[1]) if selected else None,
        "session_identity_sha": selected[2].get("session_identity_sha") if selected else None,
        "message_sha": selected[2].get("message_sha") if selected else None,
        "candidate_count": len(candidates),
        "diagnostic": "" if state == "PASS" else "no post-arm real Claude completion receipt satisfies every gate",
        "raw_prompt_persisted": False,
        "raw_message_persisted": False,
    }
    _write(paths["result"], receipt)
    receipt["receipt_path"] = str(paths["result"])
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("arm", "verify"))
    parser.add_argument("--workspace", type=Path, default=Path(os.environ.get("AI_WORKSPACE", r"C:\ai_workspace")))
    parser.add_argument("--agent", default="ai_darkhero")
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = arm(args.workspace.resolve(), args.agent, args.settings) if args.action == "arm" else verify(
        args.workspace.resolve(), args.agent, args.settings
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"{result['state']} {result['receipt_path']}")
    return 0 if result["state"] in {"ARMED", "PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
