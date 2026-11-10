#!/usr/bin/env python3
"""Verify a public or local Cloudflare Worker deployment without browser state."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="PATH=STATUS",
        help="Expected HTTP status for a route; may be repeated",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--allow-non-cloudflare", action="store_true")
    args = parser.parse_args()

    base = args.url.rstrip("/") + "/"
    expected: dict[str, int] = {}
    for item in args.expect:
        try:
            path, raw_status = item.rsplit("=", 1)
            expected[path] = int(raw_status)
        except (ValueError, TypeError):
            parser.error(f"Invalid --expect value: {item}")
    paths = list(dict.fromkeys((args.path or ["/"]) + list(expected)))
    checks = []
    ok = True

    for path in paths:
        target = urllib.parse.urljoin(base, path.lstrip("/"))
        request = urllib.request.Request(
            target,
            headers={"User-Agent": "deploy-nextjs-cloudflare-verifier/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                status = response.status
                server = response.headers.get("server", "")
                content_type = response.headers.get("content-type", "")
                body = response.read()
                expected_status = expected.get(path, 200)
                route_ok = status == expected_status and (
                    args.allow_non_cloudflare or "cloudflare" in server.lower() or base.startswith("http://127.0.0.1")
                )
                checks.append(
                    {
                        "path": path,
                        "status": status,
                        "expected_status": expected_status,
                        "server": server,
                        "content_type": content_type,
                        "bytes": len(body),
                        "ok": route_ok,
                    }
                )
                ok = ok and route_ok
        except urllib.error.HTTPError as error:
            status = error.code
            server = error.headers.get("server", "")
            expected_status = expected.get(path, 200)
            route_ok = status == expected_status and (
                args.allow_non_cloudflare or "cloudflare" in server.lower() or base.startswith("http://127.0.0.1")
            )
            checks.append(
                {
                    "path": path,
                    "status": status,
                    "expected_status": expected_status,
                    "server": server,
                    "content_type": error.headers.get("content-type", ""),
                    "bytes": len(error.read()),
                    "ok": route_ok,
                }
            )
            ok = ok and route_ok
        except (urllib.error.URLError, TimeoutError) as error:
            checks.append({"path": path, "ok": False, "error": str(error)})
            ok = False

    print(json.dumps({"ok": ok, "url": base, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
