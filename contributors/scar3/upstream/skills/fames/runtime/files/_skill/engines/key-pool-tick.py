#!/usr/bin/env python3
"""key-pool-tick.py — bounded HubClock API-key recovery orchestrator.

This engine does not pretend that minting a second key repairs every failure. It probes
stale credentials, classifies the actual recovery action, writes a names-only queue, and
publishes names-only availability only when state changed.

It never signs up, accepts Terms, bypasses captcha, reads a browser profile, ingests a
plaintext dropfile, or creates provider-side keys without an explicit provider adapter and
local policy. No provider adapter is armed in this version; those cases are queued for the
operator. This is deliberate fail-closed behavior, not a missing success claim.

Usage:
  python key-pool-tick.py status
  python key-pool-tick.py run [--stale-hours 168] [--max-probes 8]
  python key-pool-tick.py run --dry-run
"""
import argparse
import datetime
import json
import os
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _atomicio import atomic_write
from _paths import API_MATRIX, REGISTRY

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
RECIPES = os.path.join(REGISTRY, "token-onboard.json")
STATE_DIR = os.path.join(REGISTRY, "api-key-recovery")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

LIVE = {"ok"}
ROTATE = {"invalid", "expired", "compromised"}
WAIT = {"quota0"}
ACCOUNT = {"restricted"}
INTEGRATION = {"http400", "http404"}
IGNORE = {"disabled"}


def _seat():
    value = os.environ.get("AI_SEAT")
    if value:
        return value
    host = socket.gethostname().lower()
    for tag, seat in (("darkhero", "ai_darkhero"), ("dark-hero", "ai_darkhero"),
                      ("scar3", "ai_scar3"), ("altos", "ai_altos")):
        if tag in host:
            return seat
    return "host:" + host


def _load(path, default):
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _run(argv, timeout=900):
    try:
        result = subprocess.run([PY, *argv], cwd=HERE, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout,
                                creationflags=NO_WINDOW)
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def _public_fingerprint(matrix):
    rows = []
    for key in matrix.get("keys", []):
        health = key.get("health") or {}
        rows.append((key.get("provider"), key.get("status"), bool(key.get("key")),
                     health.get("result"), health.get("evidence"), health.get("checked_at")))
    return rows


def _classify(matrix, recipes):
    by_provider = {}
    for key in matrix.get("keys", []):
        provider = key.get("provider")
        if not provider:
            continue
        row = by_provider.setdefault(provider, {"present": 0, "statuses": {}})
        if key.get("key"):
            row["present"] += 1
        status = key.get("status", "untested")
        row["statuses"][status] = row["statuses"].get(status, 0) + 1
        health = key.get("health") or {}
        result = health.get("result")
        evidence = health.get("evidence")
        if evidence == "inference" and result == "ok":
            row["verified_inference"] = row.get("verified_inference", 0) + 1
        if evidence == "credential" and result == "auth-ok":
            row["auth_valid"] = row.get("auth_valid", 0) + 1
        if result == "ratelimited":
            row["transient"] = row.get("transient", 0) + 1
        if result in ("cf-blocked", "neterr") or (str(result).startswith("http")
                                                   and result not in ("http400", "http404")):
            row["unknown_latest"] = row.get("unknown_latest", 0) + 1

    providers = sorted(set(matrix.get("endpoints", {})) | set(recipes))
    queue = []
    for provider in providers:
        row = by_provider.get(provider, {"present": 0, "statuses": {}})
        statuses = set(row["statuses"])
        recipe = recipes.get(provider) or {}
        kind = recipe.get("kind") or ("llm" if provider in matrix.get("endpoints", {}) else None)
        if kind not in ("llm", "stt"):
            continue
        if row.get("verified_inference"):
            state, action, automatic = "HEALTHY", "none", True
        elif row.get("transient"):
            state = "RETRY_LATER"
            action = "bounded retry after backoff; do not rotate a credential accepted by the provider"
            automatic = True
        elif row.get("unknown_latest"):
            state = "UNKNOWN_LATEST_PROBE"
            action = "repair endpoint/model or network and re-probe; preserve the last-known credential"
            automatic = False
        elif row.get("auth_valid"):
            state = "AUTH_ONLY"
            action = f"run a provider-appropriate inference probe before claiming {provider} callable"
            automatic = False
        elif not row["present"] and statuses:
            state, action, automatic = "RETIRED", "none", True
        elif statuses & ROTATE:
            state = "NEEDS_KEY_ROTATION"
            action = f"token-onboard.py request {provider}"
            automatic = False
        elif statuses & WAIT:
            state = "WAIT_OR_SWITCH_PROVIDER"
            action = "wait for quota reset or route to a healthy provider; do not mint another same-account key"
            automatic = True
        elif statuses & ACCOUNT:
            state = "NEEDS_ACCOUNT_REMEDIATION"
            action = "resolve provider account/org restriction; a replacement key in the same org will not help"
            automatic = False
        elif statuses & INTEGRATION or any(s.startswith("http") for s in statuses):
            state = "NEEDS_INTEGRATION_REPAIR"
            action = "verify current endpoint, model and payload before judging the credential"
            automatic = False
        elif row["present"] or statuses & LIVE:
            state = "NEEDS_VALIDATION"
            action = f"key-health.py probe --provider {provider} --write"
            automatic = True
        else:
            state = "NEEDS_FIRST_KEY"
            action = f"token-onboard.py request {provider}"
            automatic = False
        queue.append({"provider": provider, "state": state, "action": action,
                      "automatic": automatic, "present_count": row["present"],
                      "status_counts": dict(sorted(row["statuses"].items())),
                      "console": recipe.get("token_url")})
    return queue


def _state_path():
    return os.path.join(STATE_DIR, _seat() + ".json")


def cmd_status(_args):
    state = _load(_state_path(), None)
    if not state:
        print("UNKNOWN: no recovery state; run key-pool-tick.py run --dry-run")
        return 3
    print(f"seat={state.get('seat')} generated={state.get('generated')} "
          f"probe_rc={state.get('probe', {}).get('rc')} changed={state.get('matrix_changed')}")
    for row in state.get("queue", []):
        if row.get("state") != "HEALTHY":
            print(f"{row['provider']:14} {row['state']:28} {row['action']}")
    return 0


def cmd_run(args):
    before = _load(API_MATRIX, {})
    if not before:
        print("UNKNOWN: api-matrix missing or unreadable; no probe or publish attempted")
        return 3
    cmd = ["key-health.py", "probe", "--stale-hours", str(args.stale_hours),
           "--max-probes", str(args.max_probes)]
    if not args.dry_run:
        cmd.append("--write")
    probe_rc, probe_output = _run(cmd)
    after = _load(API_MATRIX, {})
    changed = _public_fingerprint(before) != _public_fingerprint(after)
    recipes_doc = _load(RECIPES, {})
    queue = _classify(after, recipes_doc.get("providers", {}))
    tail = [line for line in probe_output.splitlines() if line.strip()][-2:]
    payload = {
        "version": 1,
        "seat": _seat(),
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "mode": "dry-run" if args.dry_run else "apply",
        "contract": "detect -> classify -> recover-safe-or-queue -> publish-names-only",
        "matrix_changed": changed,
        "probe": {"rc": probe_rc, "summary": tail},
        "auto_mint": {"enabled_providers": [],
                      "reason": "no provider adapter plus explicit local policy is armed"},
        "queue": queue,
    }
    os.makedirs(STATE_DIR, exist_ok=True)
    atomic_write(_state_path(), json.dumps(payload, ensure_ascii=False, indent=2))

    publish_rc = None
    if changed and not args.dry_run:
        publish_cmd = ["api_registry.py", "sync", "--apply"]
        if _seat() == "ai_darkhero":
            publish_cmd.append("--publish")
        publish_rc, _ = _run(publish_cmd)
    print(f"seat={_seat()} probe_rc={probe_rc} matrix_changed={changed} publish_rc={publish_rc}")
    counts = {}
    for row in queue:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    print("recovery states: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"names-only state: {_state_path()}")
    return 0 if probe_rc in (0, 3) and publish_rc in (None, 0) else 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    run = sub.add_parser("run")
    run.add_argument("--stale-hours", type=float, default=168.0)
    run.add_argument("--max-probes", type=int, default=8)
    run.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    return cmd_status(args) if args.command == "status" else cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
