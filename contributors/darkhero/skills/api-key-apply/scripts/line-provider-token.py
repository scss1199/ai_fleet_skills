#!/usr/bin/env python3
"""Issue, validate, and install a provider-only LINE Messaging API token.

The access token exists only in process memory and Fly's encrypted secret store.
It is never printed, written to dotenv, passed in argv, or persisted in receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


WORKSPACE = Path(os.environ.get("AI_WORKSPACE", r"C:\ai_workspace"))
ENV_PATH = WORKSPACE / "ai_darkhero" / "line" / ".env"
RECEIPT = WORKSPACE / "_registry" / "provider-secrets" / "line-kyloren-bot.json"
LOCK = WORKSPACE / "_temp" / "line-provider-token.lock"
FLYCTL = Path(os.environ.get("USERPROFILE", "")) / ".fly" / "bin" / "flyctl.exe"
FLY_CONFIG = Path(os.environ.get("USERPROFILE", "")) / ".fly" / "config.yml"
APP = "fleet-line-hooks"
SECRET_NAME = "LINE_BOT_CHANNEL_ACCESS_TOKEN"
ISSUE_URL = "https://api.line.me/v2/oauth/accessToken"
VERIFY_URL = "https://api.line.me/v2/oauth/verify"
BOT_INFO_URL = "https://api.line.me/v2/bot/info"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_PATH.is_file():
        return out
    for line in ENV_PATH.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _fly_token() -> str:
    direct = os.environ.get("FLY_API_TOKEN", "").strip()
    if direct:
        return direct
    if not FLY_CONFIG.is_file():
        return ""
    match = re.search(
        r"(?m)^access_token:\s*(\S+)",
        FLY_CONFIG.read_text(encoding="utf-8", errors="replace"),
    )
    return match.group(1) if match else ""


def _load_receipt() -> dict:
    try:
        return json.loads(RECEIPT.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _needs_renewal(doc: dict, *, margin_hours: int = 48) -> bool:
    if doc.get("status") != "installed":
        return True
    try:
        expires = datetime.fromisoformat(str(doc["expires_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return True
    return expires <= _now() + timedelta(hours=margin_hours)


def _post_form(url: str, fields: dict[str, str], *, timeout: int = 30) -> tuple[int, dict]:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def _issue(channel_id: str, channel_secret: str) -> tuple[str, int]:
    status, doc = _post_form(
        ISSUE_URL,
        {
            "grant_type": "client_credentials",
            "client_id": channel_id,
            "client_secret": channel_secret,
        },
    )
    token = str(doc.get("access_token") or "")
    expires = int(doc.get("expires_in") or 0)
    if status != 200 or len(token) < 80 or expires <= 0:
        raise RuntimeError(f"line_issue_failed:{status}")
    return token, expires


def _validate(token: str, channel_id: str, expected_basic_id: str) -> dict:
    verify_status, verify = _post_form(VERIFY_URL, {"access_token": token})
    req = urllib.request.Request(BOT_INFO_URL, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            info_status = resp.status
            info = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        info_status, info = exc.code, {}
    client_ok = str(verify.get("client_id") or "") == str(channel_id)
    bot_ok = not expected_basic_id or str(info.get("basicId") or "") == expected_basic_id
    if verify_status != 200 or info_status != 200 or not client_ok or not bot_ok:
        raise RuntimeError(
            f"line_candidate_validation_failed:verify={verify_status}:bot={info_status}"
        )
    return {
        "oauth_verify": verify_status,
        "bot_info": info_status,
        "client_match": client_ok,
        "bot_match": bot_ok,
    }


def _install(token: str) -> None:
    fly_token = _fly_token()
    if not fly_token or not FLYCTL.is_file():
        raise RuntimeError("fly_provider_store_unavailable")
    env = {**os.environ, "FLY_API_TOKEN": fly_token}
    proc = subprocess.run(
        [str(FLYCTL), "secrets", "import", "-a", APP],
        input=f"{SECRET_NAME}={token}\n",
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"fly_secret_import_failed:{proc.returncode}")


def _revoke(token: str) -> None:
    try:
        _post_form("https://api.line.me/v2/oauth/revoke", {"access_token": token})
    except Exception:
        pass


def _write_receipt(doc: dict) -> None:
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    temp = RECEIPT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, RECEIPT)


def _acquire_lock() -> int:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            if time.time() - LOCK.stat().st_mtime > 900:
                LOCK.unlink(missing_ok=True)
                return os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            pass
        raise RuntimeError("line_token_recovery_locked")


def recover(*, force: bool = False) -> dict:
    current = _load_receipt()
    if not force and not _needs_renewal(current):
        return {"ok": True, "changed": False, "status": "current", "expires_at": current.get("expires_at")}
    fd = _acquire_lock()
    token = ""
    try:
        cfg = _env()
        channel_id = cfg.get("LINE_BOT_CHANNEL_ID", "")
        channel_secret = cfg.get("LINE_BOT_CHANNEL_SECRET", "")
        expected_basic_id = cfg.get("LINE_BOT_BASIC_ID", "")
        if not channel_id or not channel_secret:
            raise RuntimeError("line_management_credentials_missing")
        token, expires_in = _issue(channel_id, channel_secret)
        validation = _validate(token, channel_id, expected_basic_id)
        _install(token)
        issued = _now()
        receipt = {
            "schema": 1,
            "provider": "line-messaging-api",
            "bot": "kyloren_bot",
            "status": "installed",
            "store": "fly-provider-only",
            "fly_app": APP,
            "secret_name": SECRET_NAME,
            "token_type": "short-lived",
            "issued_at": _iso(issued),
            "expires_at": _iso(issued + timedelta(seconds=expires_in)),
            "fingerprint": hashlib.sha256(token.encode("utf-8")).hexdigest()[:16],
            "validation": validation,
            "value_persisted_locally": False,
        }
        _write_receipt(receipt)
        token = ""
        return {"ok": True, "changed": True, "status": "installed", "expires_at": receipt["expires_at"]}
    except Exception:
        if token:
            _revoke(token)
        raise
    finally:
        os.close(fd)
        LOCK.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "ensure", "renew"))
    args = parser.parse_args()
    if args.command == "status":
        doc = _load_receipt()
        print(json.dumps({
            "ok": bool(doc),
            "status": doc.get("status") or "missing",
            "expires_at": doc.get("expires_at"),
            "renewal_due": _needs_renewal(doc),
        }))
        return 0 if doc else 2
    try:
        result = recover(force=args.command == "renew")
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:160]}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
