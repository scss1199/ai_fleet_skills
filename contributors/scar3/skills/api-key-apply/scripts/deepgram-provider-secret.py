#!/usr/bin/env python3
"""Mint, validate, and install a Deepgram key without persisting its value.

The management credential is read from the local API matrix.  The newly minted
value exists only in this process and Wrangler stdin.  The durable receipt is
names-only and can later drive create-before-delete rotation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Any


CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _workspace() -> Path:
    configured = os.environ.get("AI_WORKSPACE")
    if configured:
        return Path(configured).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "_registry").is_dir() and (parent / "_skill").is_dir():
            return parent
    return Path(r"C:\ai_workspace")


def _json_request(
    url: str,
    token: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Token {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "fleet-api-key-apply/1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        return exc.code, body


def _silence_wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(struct.pack("<h", 0) * 1_600)
    return output.getvalue()


def _probe_asr(token: str) -> bool:
    query = urllib.parse.urlencode({"model": "whisper-medium", "language": "zh-TW"})
    req = urllib.request.Request(
        f"https://api.deepgram.com/v1/listen?{query}",
        data=_silence_wav(),
        method="POST",
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "audio/wav",
            "User-Agent": "fleet-api-key-apply/1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and isinstance(body.get("results"), dict)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False


def _matrix_tokens(path: Path) -> list[str]:
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    return [
        str(row["key"])
        for row in doc.get("keys", [])
        if row.get("provider") == "deepgram"
        and row.get("key")
        and row.get("status") in {"ok", "untested"}
    ]


def _wrangler() -> str:
    command = shutil.which("npx.cmd") or shutil.which("npx")
    if not command:
        raise RuntimeError("npx is unavailable")
    return command


def _secret_names(worker: str, cwd: Path) -> set[str]:
    proc = subprocess.run(
        [_wrangler(), "-y", "wrangler", "secret", "list", "--name", worker],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        creationflags=CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise RuntimeError("wrangler secret inventory failed")
    start = proc.stdout.find("[")
    if start < 0:
        raise RuntimeError("wrangler secret inventory was not JSON")
    rows = json.loads(proc.stdout[start:])
    return {str(row.get("name")) for row in rows if row.get("name")}


def _put_secret(worker: str, binding: str, value: str, cwd: Path) -> bool:
    proc = subprocess.run(
        [_wrangler(), "-y", "wrangler", "secret", "put", binding, "--name", worker],
        cwd=cwd,
        input=value + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=CREATE_NO_WINDOW,
    )
    return proc.returncode == 0


def _load_receipt(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _delete_key(management_token: str, project_id: str, key_id: str) -> bool:
    status, _ = _json_request(
        f"https://api.deepgram.com/v1/projects/{project_id}/keys/{key_id}",
        management_token,
        method="DELETE",
        payload={},
    )
    return status == 200


def provision(args: argparse.Namespace) -> int:
    workspace = _workspace()
    matrix = Path(args.matrix or workspace / "_secrets" / "api-matrix.json")
    receipt_path = Path(
        args.receipt
        or workspace / "_registry" / "provider-secrets" / f"deepgram-{args.worker}.json"
    )
    cwd = Path(args.cwd).resolve()

    present = args.binding in _secret_names(args.worker, cwd)
    if present and not args.rotate:
        print(f"PASS worker={args.worker} binding={args.binding} state=already-present")
        return 0

    old_receipt = _load_receipt(receipt_path)
    management_tokens = _matrix_tokens(matrix)
    if not management_tokens:
        print("UNKNOWN no eligible Deepgram management credential", file=sys.stderr)
        return 2

    created: tuple[str, str, str, str] | None = None
    for management_token in management_tokens:
        status, projects_doc = _json_request(
            "https://api.deepgram.com/v1/projects", management_token
        )
        if status != 200:
            continue
        for project in projects_doc.get("projects", []):
            project_id = str(project.get("project_id") or "")
            if not project_id:
                continue
            now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            status, created_doc = _json_request(
                f"https://api.deepgram.com/v1/projects/{project_id}/keys",
                management_token,
                method="POST",
                payload={
                    "comment": f"{args.worker}-production-{now}",
                    "scopes": ["member"],
                    "tags": [args.worker, "production"],
                },
            )
            key_value = str(created_doc.get("key") or "")
            key_id = str(created_doc.get("api_key_id") or "")
            if status == 200 and key_value and key_id:
                created = (management_token, project_id, key_id, key_value)
                break
        if created:
            break

    if not created:
        print("UNKNOWN no Deepgram key with keys:write could mint the production key", file=sys.stderr)
        return 3

    management_token, project_id, key_id, key_value = created
    if not _probe_asr(key_value):
        _delete_key(management_token, project_id, key_id)
        print("FAIL new Deepgram key did not pass the live ASR probe; revoked", file=sys.stderr)
        return 4
    if not _put_secret(args.worker, args.binding, key_value, cwd):
        _delete_key(management_token, project_id, key_id)
        print("FAIL provider secret upload failed; new Deepgram key revoked", file=sys.stderr)
        return 5

    previous_deleted = None
    old_key_id = str(old_receipt.get("key_id") or "")
    old_project_id = str(old_receipt.get("project_id") or "")
    if args.rotate and old_key_id and old_project_id:
        previous_deleted = _delete_key(management_token, old_project_id, old_key_id)

    generated = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    receipt = {
        "schema": 1,
        "provider": "deepgram",
        "worker": args.worker,
        "binding": args.binding,
        "project_id": project_id,
        "key_id": key_id,
        "generated": generated,
        "value_persisted_locally": False,
        "provider_store": "cloudflare_workers_secret",
        "live_probe": {"state": "PASS", "kind": "asr", "model": "whisper-medium"},
        "previous_key_deleted": previous_deleted,
    }
    _write_receipt(receipt_path, receipt)
    print(
        f"PASS worker={args.worker} binding={args.binding} "
        f"live_probe=asr provider_store=cloudflare previous_deleted={previous_deleted}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--binding", default="DEEPGRAM_API_KEY")
    parser.add_argument("--cwd", required=True, help="Wrangler working directory")
    parser.add_argument("--matrix")
    parser.add_argument("--receipt")
    parser.add_argument("--rotate", action="store_true")
    return provision(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
