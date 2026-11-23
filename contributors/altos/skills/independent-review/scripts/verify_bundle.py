#!/usr/bin/env python3
"""Recompute identity and artifact integrity for a supervised-build bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    repo = args.repo_root.resolve()
    request = json.loads((bundle / "request.json").read_text(encoding="utf-8"))
    artifacts_doc = json.loads((bundle / "artifacts.json").read_text(encoding="utf-8"))
    errors: list[str] = []

    identities = {
        "diff_sha256": bundle / "diff.patch",
        "claims_sha256": bundle / "claims.json",
        "artifacts_sha256": bundle / "artifacts.json",
    }
    observed: dict[str, str] = {}
    for field, path in identities.items():
        observed[field] = digest(path)
        if request.get(field) != observed[field]:
            errors.append(f"{field} mismatch")

    artifact_results = []
    for item in artifacts_doc.get("artifacts", []):
        label = str(item.get("path", ""))
        path = bundle / label.removeprefix("bundle:") if label.startswith("bundle:") else repo / label
        exists = path.is_file()
        actual_hash = digest(path) if exists else None
        actual_size = path.stat().st_size if exists else None
        row_errors = []
        if not exists:
            row_errors.append("missing")
        if exists and actual_hash != item.get("sha256"):
            row_errors.append("sha256 mismatch")
        if exists and actual_size != item.get("size_bytes"):
            row_errors.append("size mismatch")
        if "source_inputs" not in item:
            row_errors.append("missing per-artifact source_inputs")
        artifact_results.append({"path": label, "errors": row_errors})
        errors.extend(f"{label}: {error}" for error in row_errors)

    patch_paths = sorted(
        set(re.findall(r"^\+\+\+ b/(.+)$", (bundle / "diff.patch").read_text(encoding="utf-8"), re.M))
    )
    changed_paths = sorted(request.get("changed_paths", []))
    if patch_paths != changed_paths:
        errors.append("diff paths do not equal changed_paths")

    result = {
        "ok": not errors,
        "errors": errors,
        "identity_hashes": observed,
        "patch_paths": patch_paths,
        "artifact_results": artifact_results,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
