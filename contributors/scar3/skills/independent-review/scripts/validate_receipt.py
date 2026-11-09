#!/usr/bin/env python3
"""Validate the minimal, vendor-neutral independent-review receipt contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED = {
    "reviewer",
    "review_lane",
    "target",
    "commands_rerun",
    "findings",
    "verdict",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    raw = args.receipt.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    missing = sorted(REQUIRED - set(doc))
    errors: list[str] = []
    if missing:
        errors.append(f"missing fields: {missing}")
    allowed_verdicts = {
        "ACCEPTED",
        "REJECTED",
        "REJECTED_FIXABLE",
        "REJECTED_INTEGRITY",
        "UNKNOWN",
    }
    if doc.get("verdict") not in allowed_verdicts:
        errors.append(f"verdict must be one of {sorted(allowed_verdicts)}")
    if not isinstance(doc.get("commands_rerun"), list) or not doc.get("commands_rerun"):
        errors.append("commands_rerun must be a non-empty list")
    if not isinstance(doc.get("findings"), list):
        errors.append("findings must be a list")
    if doc.get("verdict") == "ACCEPTED" and any(
        item.get("blocking", True) for item in doc.get("findings", [])
    ):
        errors.append("ACCEPTED receipt contains a blocking finding")
    result = {
        "ok": not errors,
        "errors": errors,
        "receipt_sha256": hashlib.sha256(raw).hexdigest(),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
