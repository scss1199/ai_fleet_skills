#!/usr/bin/env python3
"""Run Wrangler locally, smoke-test routes, and always terminate its process tree."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def terminate_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--port", type=int, default=18790)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    args = parser.parse_args()

    root = args.project_root.resolve()
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    log_file = tempfile.TemporaryFile()
    process = subprocess.Popen(
        [npx, "wrangler", "dev", "--local", "--port", str(args.port)],
        cwd=root,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        start_new_session=sys.platform != "win32",
    )
    base = f"http://127.0.0.1:{args.port}"
    paths = args.path or ["/"]
    checks: list[dict[str, object]] = []

    try:
        deadline = time.monotonic() + args.startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"wrangler exited with code {process.returncode}")
            try:
                with urllib.request.urlopen(base + "/", timeout=2) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.5)
        else:
            raise TimeoutError("wrangler did not become ready")

        ok = True
        for path in paths:
            try:
                with urllib.request.urlopen(base + path, timeout=20) as response:
                    body = response.read()
                    route_ok = response.status == 200
                    checks.append(
                        {
                            "path": path,
                            "status": response.status,
                            "content_type": response.headers.get("content-type", ""),
                            "bytes": len(body),
                            "ok": route_ok,
                        }
                    )
                    ok = ok and route_ok
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                checks.append({"path": path, "ok": False, "error": str(error)})
                ok = False
        result: dict[str, object] = {"ok": ok, "url": base, "checks": checks}
        if not ok:
            time.sleep(0.25)
            log_file.flush()
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            log_file.seek(max(0, size - 12000))
            result["wrangler_log_tail"] = log_file.read().decode("utf-8", errors="replace")
        print(json.dumps(result, indent=2))
        return 0 if ok else 2
    finally:
        terminate_tree(process)
        log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
