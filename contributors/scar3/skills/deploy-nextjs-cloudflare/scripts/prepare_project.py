#!/usr/bin/env python3
"""Prepare an isolated Next.js project for OpenNext Cloudflare deployment."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


WORKER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
NPM = "npm.cmd" if sys.platform == "win32" else "npm"


def version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.search(value)
    if not match:
        raise ValueError(f"Cannot parse version: {value}")
    return tuple(int(part) for part in match.groups())


def constraint_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(part) for part in value.split(".")]
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"Cannot parse constraint version: {value}")
    return tuple((parts + [0, 0])[:3])


def compare(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return (left > right) - (left < right)


def satisfies(version: tuple[int, int, int], expression: str) -> bool:
    for alternative in expression.split("||"):
        ok = True
        for token in alternative.strip().split():
            match = re.fullmatch(r"(>=|<=|>|<|=)?(\d+(?:\.\d+){0,2})", token)
            if not match:
                continue
            operator = match.group(1) or "="
            candidate = constraint_tuple(match.group(2))
            order = compare(version, candidate)
            ok = ok and {
                ">=": order >= 0,
                "<=": order <= 0,
                ">": order > 0,
                "<": order < 0,
                "=": order == 0,
            }[operator]
        if ok:
            return True
    return False


def npm_json(args: list[str], cwd: Path):
    completed = subprocess.run(
        [NPM, *args, "--json"],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return json.loads(completed.stdout)


def run(args: list[str], cwd: Path) -> None:
    completed = subprocess.run(args, cwd=cwd, shell=False, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(args)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--worker-name", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--allow-minor-upgrade", action="store_true")
    args = parser.parse_args()

    root = args.project_root.resolve()
    if not WORKER_RE.fullmatch(args.worker_name):
        raise SystemExit("Worker name must use lowercase letters, digits, and dashes only")
    package_path = root / "package.json"
    if not package_path.is_file():
        raise SystemExit("package.json not found")

    package = json.loads(package_path.read_text(encoding="utf-8"))
    dependencies = package.setdefault("dependencies", {})
    current_spec = dependencies.get("next")
    if not current_spec:
        raise SystemExit("Next.js dependency not found")
    current = version_tuple(str(current_spec))

    open_next = npm_json(["view", "@opennextjs/cloudflare@latest", "version", "peerDependencies"], root)
    open_next_version = open_next["version"]
    peer_range = open_next["peerDependencies"]["next"]
    selected_next = current

    if not satisfies(current, peer_range):
        versions = npm_json(["view", f"next@{current[0]}", "version"], root)
        if isinstance(versions, str):
            versions = [versions]
        parsed = sorted((version_tuple(item), item) for item in versions)
        compatible = [item for item in parsed if satisfies(item[0], peer_range)]
        same_minor = [item for item in compatible if item[0][:2] == current[:2]]
        choice = same_minor[-1] if same_minor else (compatible[-1] if compatible else None)
        if not choice:
            raise SystemExit(f"No compatible Next.js release found for {peer_range}")
        selected_next = choice[0]
        if selected_next[:2] != current[:2] and not args.allow_minor_upgrade:
            raise SystemExit(
                f"OpenNext requires {peer_range}; minor upgrade {current} -> {selected_next} needs --allow-minor-upgrade"
            )
        dependencies["next"] = choice[1]

    plan = {
        "project_root": str(root),
        "worker_name": args.worker_name,
        "open_next": open_next_version,
        "open_next_next_peer": peer_range,
        "next_before": ".".join(map(str, current)),
        "next_after": ".".join(map(str, selected_next)),
        "apply": args.apply,
        "install": args.install,
    }
    print(json.dumps(plan, indent=2))
    if not args.apply:
        return 0

    scripts = package.setdefault("scripts", {})
    scripts.update(
        {
            "cf:build": "opennextjs-cloudflare build",
            "cf:preview": "opennextjs-cloudflare build && opennextjs-cloudflare preview",
            "cf:deploy": "opennextjs-cloudflare build && opennextjs-cloudflare deploy",
            "cf:dry-run": "opennextjs-cloudflare build && wrangler deploy --dry-run",
        }
    )
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")

    compatibility_date = datetime.now(timezone.utc).date().isoformat()
    (root / "open-next.config.ts").write_text(
        'import { defineCloudflareConfig } from "@opennextjs/cloudflare";\n\n'
        "export default defineCloudflareConfig();\n",
        encoding="utf-8",
    )
    wrangler = {
        "$schema": "node_modules/wrangler/config-schema.json",
        "name": args.worker_name,
        "main": ".open-next/worker.js",
        "compatibility_date": compatibility_date,
        "compatibility_flags": ["nodejs_compat", "global_fetch_strictly_public"],
        "assets": {"directory": ".open-next/assets", "binding": "ASSETS"},
        "services": [{"binding": "WORKER_SELF_REFERENCE", "service": args.worker_name}],
        "observability": {"enabled": True},
    }
    (root / "wrangler.jsonc").write_text(json.dumps(wrangler, indent=2) + "\n", encoding="utf-8")

    if args.install:
        if selected_next != current:
            run([NPM, "install", "--save-exact", f"next@{'.'.join(map(str, selected_next))}"], root)
        run(
            [
                NPM,
                "install",
                "--save-dev",
                "--save-exact",
                f"@opennextjs/cloudflare@{open_next_version}",
                "wrangler@latest",
            ],
            root,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
