#!/usr/bin/env python3
"""Read saved LINE OA events from a Drive inbox without exposing credentials."""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DRIVE_API = "https://www.googleapis.com/drive/v3/files"
TOKEN_URI = "https://oauth2.googleapis.com/token"
LINE_INFO_URI = "https://api.line.me/v2/bot/info"
MANIFEST = "inbox_manifest.json"
URL_RE = re.compile(r"https?://[^\s<>\"'\]\[(){}]+", re.IGNORECASE)


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
) -> Any:
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read())


def google_access_token(env: dict[str, str]) -> str:
    refresh = env.get("GOOGLE_DRIVE_REFRESH_TOKEN", "")
    client_id = env.get("GOOGLE_DRIVE_CLIENT_ID") or env.get("GOOGLE_CLIENT_ID", "")
    secret = env.get("GOOGLE_DRIVE_CLIENT_SECRET") or env.get("GOOGLE_CLIENT_SECRET", "")
    if not refresh or not client_id or not secret:
        raise RuntimeError("drive_credentials_missing")
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
    ).encode()
    return str(request_json(TOKEN_URI, data=body, method="POST")["access_token"])


def drive_json(token: str, url: str) -> Any:
    return request_json(url, headers={"Authorization": f"Bearer {token}"})


def drive_query(token: str, query: str, fields: str, *, page_size: int = 1000) -> list[dict[str, Any]]:
    params = {
        "q": query,
        "fields": f"nextPageToken,files({fields})",
        "pageSize": str(page_size),
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    files: list[dict[str, Any]] = []
    page_token = ""
    while True:
        if page_token:
            params["pageToken"] = page_token
        url = f"{DRIVE_API}?{urllib.parse.urlencode(params)}"
        doc = drive_json(token, url)
        files.extend(doc.get("files", []))
        page_token = str(doc.get("nextPageToken") or "")
        if not page_token:
            return files


def resolve_inbox_folder(token: str, env: dict[str, str], folder_name: str) -> str:
    direct = env.get("LINE_INBOX_DRIVE_FOLDER_ID", "").strip()
    if direct:
        return direct
    parent = (env.get("LINE_INBOX_DRIVE_PARENT_ID") or env.get("REGISTRY_DRIVE_FOLDER_ID") or "").strip()
    if not parent:
        raise RuntimeError("inbox_parent_missing")
    escaped = folder_name.replace("'", "\\'")
    query = (
        f"'{parent}' in parents and name='{escaped}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    found = drive_query(token, query, "id,name", page_size=1)
    if not found:
        raise RuntimeError("inbox_folder_missing")
    return str(found[0]["id"])


def read_drive_file(token: str, file_id: str) -> Any:
    url = f"{DRIVE_API}/{file_id}?alt=media&supportsAllDrives=true"
    return drive_json(token, url)


def read_manifest(token: str, folder_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    query = f"'{folder_id}' in parents and name='{MANIFEST}' and trashed=false"
    found = drive_query(token, query, "id,name,modifiedTime", page_size=1)
    if not found:
        return [], {"present": False, "updated_at": None}
    doc = read_drive_file(token, str(found[0]["id"]))
    return list(doc.get("messages", [])), {
        "present": True,
        "updated_at": doc.get("updated_at"),
        "modified_time": found[0].get("modifiedTime"),
    }


def read_raw_events(token: str, folder_id: str, max_files: int) -> tuple[list[dict[str, Any]], int]:
    query = f"'{folder_id}' in parents and name!='{MANIFEST}' and trashed=false"
    found = drive_query(token, query, "id,name,modifiedTime")
    candidates = [item for item in found if str(item.get("name", "")).lower().endswith(".json")]
    candidates.sort(key=lambda item: str(item.get("modifiedTime", "")), reverse=True)
    selected = candidates[:max_files]
    rows: list[dict[str, Any]] = []
    for item in selected:
        try:
            doc = read_drive_file(token, str(item["id"]))
        except Exception:
            continue
        if isinstance(doc, dict):
            rows.append(doc)
    return rows, len(candidates)


def parse_since(value: str) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def row_time(row: dict[str, Any]) -> dt.datetime | None:
    try:
        return parse_since(str(row.get("ts") or ""))
    except ValueError:
        return None


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(URL_RE.findall(text or "")))


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        message_id = str(row.get("message_id") or "")
        key = ("id", message_id) if message_id else (
            "row",
            str(row.get("ts") or ""),
            str(row.get("source_type") or ""),
            str(row.get("group_name") or ""),
            str(row.get("text") or ""),
        )
        if key not in seen:
            seen.add(key)
            output.append(row)
    return output


def matches(row: dict[str, Any], args: argparse.Namespace, since: dt.datetime | None) -> bool:
    if args.group_name and str(row.get("group_name") or "").casefold() != args.group_name.casefold():
        return False
    if args.source_type and str(row.get("source_type") or "").casefold() != args.source_type:
        return False
    if since:
        stamp = row_time(row)
        if stamp is None or stamp < since:
            return False
    return True


def safe_row(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ts": row.get("ts"),
        "source_type": row.get("source_type"),
        "channel_label": row.get("channel_label"),
        "group_name": row.get("group_name"),
        "message_type": row.get("message_type") or row.get("type") or "text",
    }
    if args.include_sender:
        result["display_name"] = row.get("display_name") or row.get("sender_label")
    text = str(row.get("text") or "")
    if args.include_text:
        result["text"] = text
    if args.include_urls:
        result["urls"] = extract_urls(text)
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_types = collections.Counter(str(row.get("source_type") or "unknown") for row in rows)
    groups = collections.Counter(str(row.get("group_name") or "") for row in rows if row.get("group_name"))
    timestamps = [str(row.get("ts")) for row in rows if row.get("ts")]
    return {
        "total": len(rows),
        "source_types": dict(sorted(source_types.items())),
        "groups": dict(sorted(groups.items())),
        "newest_ts": max(timestamps) if timestamps else None,
        "oldest_ts": min(timestamps) if timestamps else None,
    }


def probe_bot(env: dict[str, str]) -> dict[str, Any]:
    token = env.get("LINE_BOT_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return {"ok": False, "error": "line_access_token_missing"}
    try:
        doc = request_json(LINE_INFO_URI, headers={"Authorization": f"Bearer {token}"})
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": "HTTPError", "status": exc.code}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    return {
        "ok": True,
        "display_name": doc.get("displayName"),
        "basic_id": doc.get("basicId"),
        "chat_mode": doc.get("chatMode"),
        "mark_as_read_mode": doc.get("markAsReadMode"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True, help="LINE/Drive .env path")
    parser.add_argument("--folder-name", default="kyloren_inbox")
    parser.add_argument("--group-name", default="", help="exact, case-insensitive group name")
    parser.add_argument("--source-type", choices=("user", "group", "room"), default="")
    parser.add_argument("--since", default="", help="inclusive ISO-8601 lower bound")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--scan-raw", action="store_true")
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--include-text", action="store_true")
    parser.add_argument("--include-urls", action="store_true")
    parser.add_argument("--include-sender", action="store_true")
    parser.add_argument("--probe-bot", action="store_true")
    parser.add_argument("--out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit < 0 or args.max_files < 1:
        raise SystemExit("limit must be >= 0 and max-files must be >= 1")
    if args.scan_raw and not args.group_name and not args.source_type:
        raise SystemExit("--scan-raw requires --group-name or --source-type")
    env = load_env(args.env)
    result: dict[str, Any] = {"schema": 1, "env": str(args.env), "secret_values_emitted": False}
    if args.probe_bot:
        result["bot_probe"] = probe_bot(env)
    try:
        drive_token = google_access_token(env)
        folder_id = resolve_inbox_folder(drive_token, env, args.folder_name)
        manifest_rows, manifest_meta = read_manifest(drive_token, folder_id)
        rows = manifest_rows
        result["manifest"] = manifest_meta
        if args.scan_raw:
            rows, raw_available = read_raw_events(drive_token, folder_id, args.max_files)
            result["raw_scan"] = {"scanned": min(raw_available, args.max_files), "available": raw_available}
    except Exception as exc:
        result["drive"] = {"ok": False, "error": str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 2

    rows = dedupe(rows)
    result["drive"] = {"ok": True}
    result["summary"] = summarize(rows)
    try:
        since = parse_since(args.since)
    except ValueError:
        raise SystemExit("--since must be ISO-8601")
    filtered = [row for row in rows if matches(row, args, since)]
    filtered.sort(key=lambda row: str(row.get("ts") or ""), reverse=True)
    result["filter"] = {
        "group_name": args.group_name or None,
        "source_type": args.source_type or None,
        "since": args.since or None,
    }
    result["matched_count"] = len(filtered)
    result["records"] = [safe_row(row, args) for row in filtered[: args.limit]]
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
