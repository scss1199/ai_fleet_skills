#!/usr/bin/env python3
"""Append a sanitized, reproducible deployment failure to the skill knowledge base."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path


def clean(value: str) -> str:
    value = re.sub(r"(?i)(token|secret|password|api[_-]?key)\s*[:=]\s*\S+", r"\1=[REDACTED]", value)
    return " ".join(value.strip().split())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--symptom", required=True)
    parser.add_argument("--cause", required=True)
    parser.add_argument("--fix", required=True)
    parser.add_argument("--verify", required=True)
    args = parser.parse_args()

    reference = Path(__file__).resolve().parents[1] / "references" / "known-failures.md"
    entry = (
        f"\n## {date.today().isoformat()} — {clean(args.stage)}\n\n"
        f"- Symptom: {clean(args.symptom)}\n"
        f"- Cause: {clean(args.cause)}\n"
        f"- Fix: {clean(args.fix)}\n"
        f"- Verify: `{clean(args.verify)}`\n"
    )
    with reference.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    print(reference)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
