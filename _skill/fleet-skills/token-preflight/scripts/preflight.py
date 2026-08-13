#!/usr/bin/env python3
"""Create a bounded token-preflight receipt for non-trivial local work."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path


def workspace_root() -> Path:
    return Path(os.environ.get("AI_WORKSPACE", r"C:\ai_workspace"))


def digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    ap.add_argument("--task", required=True)
    args = ap.parse_args()
    root = workspace_root()
    protocol = root / "_registry" / "fames-protocol.json"
    skill = root / "_skill" / "fleet-skills" / "token-preflight" / "SKILL.md"
    task = " ".join(args.task.split())
    fingerprint = hashlib.sha256(
        (args.agent + "\0" + task + "\0" + digest(protocol) + "\0" + digest(skill)).encode("utf-8")
    ).hexdigest()
    receipt_dir = root / "_registry" / "token-preflight"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / f"{args.agent}-{fingerprint[:16]}.json"
    receipt = {
        "schema": "token-preflight.receipt/v1",
        "agent": args.agent,
        "task": task,
        "task_fingerprint": fingerprint,
        "outcome": "complete the requested deliverable with fresh bounded evidence",
        "verification": "task-specific tests plus artifact/status receipts",
        "state": "routed",
        "next_action": "read only the smallest task-specific source and execute",
        "blocker": "none",
        "route": "TR1/TR0 summaries; write detailed results to artifacts",
        "read_budget": {"broad_reads": 0, "targeted_source_groups": 4, "raw_result_in_chat": False},
        "artifact_hashes": {
            "fames_protocol": digest(protocol),
            "token_preflight_skill": digest(skill),
        },
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    print(json.dumps({"receipt": str(path), **{k: receipt[k] for k in ("outcome", "verification", "state", "next_action", "blocker")}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
