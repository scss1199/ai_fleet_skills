#!/usr/bin/env python3
"""Read-only preflight for a Next.js to Cloudflare Workers deployment."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


WORKER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
ENV_RE = re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)")


def run(command: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def env_keys(root: Path) -> list[str]:
    keys: set[str] = set()
    for pattern in ("*.js", "*.jsx", "*.mjs", "*.ts", "*.tsx"):
        for path in root.rglob(pattern):
            ignored = {"node_modules", ".next", ".open-next", ".wrangler", ".git"}
            if any(part.casefold() in ignored for part in path.relative_to(root).parts):
                continue
            try:
                keys.update(ENV_RE.findall(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                continue
    return sorted(keys)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--worker-name", required=True)
    parser.add_argument("--account-subdomain", required=True)
    parser.add_argument("--check-auth", action="store_true")
    args = parser.parse_args()

    root = args.project_root.resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not WORKER_RE.fullmatch(args.worker_name):
        errors.append("invalid_worker_name")
    if not WORKER_RE.fullmatch(args.account_subdomain):
        errors.append("invalid_account_subdomain")

    package_path = root / "package.json"
    package: dict[str, object] = {}
    if not package_path.is_file():
        errors.append("missing_package_json")
    else:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        dependencies = {
            **package.get("dependencies", {}),
            **package.get("devDependencies", {}),
        }
        if "next" not in dependencies:
            errors.append("missing_next_dependency")

    git_code, git_root = run(["git", "rev-parse", "--show-toplevel"], root)
    dirty = None
    if git_code == 0:
        status_code, status = run(["git", "status", "--porcelain"], root)
        dirty = status_code == 0 and bool(status)
        if dirty:
            warnings.append("dirty_worktree_use_isolated_copy")

    auth: str | None = None
    if args.check_auth:
        auth_code, auth_output = run(["npx.cmd" if sys.platform == "win32" else "npx", "wrangler", "whoami"], root)
        auth = "authenticated" if auth_code == 0 and "not authenticated" not in auth_output.lower() else "unauthenticated"
        if auth != "authenticated":
            warnings.append("cloudflare_login_required")

    result = {
        "ok": not errors,
        "project_root": str(root),
        "package": package.get("name"),
        "worker_name": args.worker_name,
        "account_subdomain": args.account_subdomain,
        "expected_url": f"https://{args.worker_name}.{args.account_subdomain}.workers.dev/",
        "git_root": git_root if git_code == 0 else None,
        "dirty": dirty,
        "environment_keys": env_keys(root),
        "auth": auth,
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
