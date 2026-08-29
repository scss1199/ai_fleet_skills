#!/usr/bin/env python3
"""Provision Cloudflare Worker secrets from existing secure sources — values never printed.

WHY THIS EXISTS
  A Cloudflare Worker name is immutable, so "renaming" a worker means deploying a
  NEW worker — and a new worker starts with ZERO secrets. `wrangler` has no
  cross-worker secret copy and cannot read a secret's value back, so the values
  must be re-sourced from the original secure files and pushed again.

DESIGN RULES (deploy rule 9)
  - Values are only ever held in memory and written to wrangler's stdin.
  - Nothing is written to a temp file, a log, or stdout.
  - Dry-run (the default) prints key names, value lengths, and source file only.
  - Keys requested via --only but not found anywhere are reported as MISSING, so a
    partial provisioning is visible instead of silently shipping a broken worker.

USAGE
  python cf_secret_push.py --worker <name> --env <file> [--env <file> ...]
                           [--only KEY ...] [--set KEY=VALUE ...] [--apply]

  --env    Repeatable. Later files win on key collision.
  --only   Allowlist. Without it, every key survives except DROP_* below.
  --set    Literal, for NON-SECRET values that have no env file (e.g. a public
           Firebase project id). Never pass a real secret on the command line —
           it lands in shell history.
  --apply  Actually run `npx wrangler secret bulk --name <worker>` over stdin.

KNOWN TRAP (measured 2026-08-06)
  `vercel env pull` writes ENCRYPTED variables as KEY="" — the file looks complete
  but every sensitive value is blank. A blank value is dropped here and counted in
  the BLANK report, so an all-blank source file surfaces as "0 usable" instead of
  quietly wiping a worker's secrets. Always compare the count against
  `wrangler secret list --name <old-worker>` before --apply.
"""
import argparse
import json
import subprocess
import sys

# Platform-injected / build-only variables that must never become Worker secrets.
DROP_PREFIXES = ("VERCEL", "TURBO_", "NX_", "NEXT_PUBLIC_")
DROP_EXACT = {"NODE_ENV", "CI", "PORT"}


def parse_env(path):
    """Parse a .env file into {key: value}. Quote-stripped, comment-aware."""
    out = {}
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if not k:
                continue
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", required=True)
    ap.add_argument("--env", action="append", default=[], metavar="FILE")
    ap.add_argument("--only", nargs="*", default=None, metavar="KEY")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    payload, source, blank = {}, {}, []

    for path in args.env:
        for k, v in parse_env(path).items():
            if args.only is not None and k not in args.only:
                continue
            if args.only is None and (k.startswith(DROP_PREFIXES) or k in DROP_EXACT):
                continue
            if v == "":
                blank.append(k)
                continue
            payload[k] = v
            source[k] = path

    for spec in args.set:
        k, _, v = spec.partition("=")
        if k and v:
            payload[k] = v
            source[k] = "--set"

    missing = sorted(set(args.only) - set(payload)) if args.only else []

    report = {
        "worker": args.worker,
        "count": len(payload),
        "keys": {k: {"len": len(payload[k]), "src": source[k]}
                 for k in sorted(payload)},
        "blank_in_source": sorted(set(blank)),
        "missing": missing,
    }
    print(json.dumps(report, indent=1), file=sys.stderr)

    if not args.apply:
        print("DRY-RUN — nothing pushed. Re-run with --apply.", file=sys.stderr)
        return 0
    if not payload:
        print("REFUSING: empty payload.", file=sys.stderr)
        return 2

    proc = subprocess.run(
        ["npx", "wrangler", "secret", "bulk", "--name", args.worker],
        input=json.dumps(payload).encode("utf-8"),
        shell=(sys.platform == "win32"),
    )
    if proc.returncode == 0 and missing:
        print(f"PARTIAL: pushed {len(payload)}, still MISSING {missing}", file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
