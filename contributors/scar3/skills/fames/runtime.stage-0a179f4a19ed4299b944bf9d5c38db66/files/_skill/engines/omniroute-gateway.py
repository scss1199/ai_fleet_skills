#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
r"""omniroute-gateway.py — run the OmniRoute free-provider gateway headless and report its health.

Operator 2026-10-14 (kyloren_bot 2026-09-09/13/28 reels: 「無限量使用 Claude Code」): when the Anthropic quota is
exhausted, Claude Code keeps working through a local Anthropic-compatible gateway that routes to free
providers (OmniRoute, MIT, github.com/diegosouzapw/OmniRoute; npm global install). This engine is the hub's
only way to start/stop/inspect it: zero foreground (pythonw + CREATE_NO_WINDOW, `--no-open`), state in
_registry/omniroute-gateway.json, no secrets printed (provider keys live in OmniRoute's own AES-256-GCM
store; the hub only holds the gateway access token in the vault, path `omniroute/access-token`).

  python omniroute-gateway.py status [--json]     # pid, port, /health, models count (read-only)
  python omniroute-gateway.py start               # detached hidden daemon on 127.0.0.1:20128 if not running
  python omniroute-gateway.py stop                # terminate the daemon we started (pid file only)
  python omniroute-gateway.py models [--json]     # GET /v1/models through the gateway (names only)
  python omniroute-gateway.py probe [--model M]   # one tiny /v1/messages call: proves a free model answers
  python omniroute-gateway.py setup               # first-run on a new machine: admin pw, local keys, access token
Persistence (autostart / HubClock rider) is proposed, never armed here (operator authority).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace")
STATE = HUB / "_registry" / "omniroute-gateway.json"
HOST, PORT = "127.0.0.1", 20128
BASE = f"http://{HOST}:{PORT}"
NW = 0x08000000 if os.name == "nt" else 0
# scar3 2026-10-15: DETACHED_PROCESS (0x8) makes Windows ignore CREATE_NO_WINDOW, so the .cmd shim's node child
# opened a visible terminal (zero-foreground red line). New process group only; never DETACHED_PROCESS.
NEW_GROUP = 0x00000200


def _launch_argv(cli: str) -> list[str]:
    """node + omniroute.mjs directly (no cmd.exe shim) when the global install is where npm puts it."""
    mjs = Path(cli).resolve().parent / "node_modules" / "omniroute" / "bin" / "omniroute.mjs"
    node = shutil.which("node")
    return [node, str(mjs)] if node and mjs.is_file() else [cli]
VAULT_TOKEN_PATH = "omniroute.access_token"  # dotted vault path (_secrets.get)


def _cli() -> str | None:
    for name in ("omniroute.cmd", "omniroute.CMD", "omniroute"):
        p = shutil.which(name)
        if p:
            return p
    appdata = os.environ.get("APPDATA") or ""
    for cand in (Path(appdata) / "npm" / "omniroute.cmd", Path(appdata) / "npm" / "omniroute"):
        if cand.is_file():
            return str(cand)
    return None


def _token() -> str | None:
    try:
        sys.path.insert(0, str(HUB / "_skill" / "engines"))
        import _secrets  # type: ignore

        v = _secrets.get(VAULT_TOKEN_PATH)
        return str(v) if v else None
    except Exception:  # noqa: BLE001
        return None


def _get(path: str, timeout: float = 8.0, auth: bool = False) -> tuple[int | None, str]:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "omniroute-gateway.py"})
    if auth:
        tok = _token()
        if tok:
            req.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(8_000_000).decode("utf-8", "replace")  # /v1/models is ~1 MB
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, type(exc).__name__


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _save(doc: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, STATE)


def _pid_alive(pid: int) -> bool:
    try:
        import psutil  # type: ignore

        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        try:
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, creationflags=NW, timeout=15)
            return str(pid) in (r.stdout or "")
        except (OSError, subprocess.SubprocessError):
            return False


def status() -> dict:
    st = _state()
    code, body = _get("/api/health")  # OmniRoute 3.8: /health is 404, /api/health answers {"status":"healthy"}
    healthy = code == 200
    models = None
    if healthy:
        mcode, mbody = _get("/v1/models", auth=True)
        if mcode == 200:
            try:
                data = json.loads(mbody)
                items = data.get("data") if isinstance(data, dict) else data
                models = len(items) if isinstance(items, list) else None
            except ValueError:
                models = None
    return {"cli": _cli(), "base_url": BASE, "healthy": healthy, "health_code": code,
            "models": models, "pid": st.get("pid"), "pid_alive": _pid_alive(int(st["pid"])) if st.get("pid") else None,
            "started_at": st.get("started_at"), "token_in_vault": bool(_token()), "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def start() -> dict:
    cur = status()
    if cur["healthy"]:
        return {"ok": True, "already_running": True, **cur}
    cli = _cli()
    if not cli:
        return {"ok": False, "reason": "omniroute_cli_not_found", "hint": "npm install -g omniroute"}
    log_dir = HUB / "_logs"
    log_dir.mkdir(exist_ok=True)
    log = open(log_dir / "omniroute-gateway.log", "ab")
    env = dict(os.environ)
    env.setdefault("OMNIROUTE_SKIP_POSTINSTALL", "1")
    env["PORT"] = str(PORT)
    env["HOST"] = HOST
    env["OMNIROUTE_SERVER_HOST"] = HOST   # 3.8.51 binds 0.0.0.0 without it (scar3 2026-10-15)
    try:
        proc = subprocess.Popen([*_launch_argv(cli), "--no-open", "--port", str(PORT)], cwd=str(HUB), env=env,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=NW | NEW_GROUP, close_fds=True)
    except OSError as exc:
        return {"ok": False, "reason": "spawn_failed:" + type(exc).__name__}
    deadline = time.time() + 90
    while time.time() < deadline:
        code, _ = _get("/api/health", timeout=3)
        if code == 200:
            break
        time.sleep(2)
    doc = {"pid": proc.pid, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cli": cli, "port": PORT}
    _save(doc)
    return {"ok": _get("/api/health", timeout=3)[0] == 200, **status()}


def stop() -> dict:
    st = _state()
    pid = st.get("pid")
    if not pid or not _pid_alive(int(pid)):
        return {"ok": True, "stopped": False, "reason": "no_daemon_of_ours"}
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NW, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "reason": type(exc).__name__}
    st["stopped_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save(st)
    return {"ok": True, "stopped": True, "pid": pid}


def models() -> dict:
    code, body = _get("/v1/models", auth=True)
    if code != 200:
        return {"ok": False, "code": code, "body": body[:200]}
    try:
        data = json.loads(body)
        items = data.get("data") if isinstance(data, dict) else data
        ids = [str(m.get("id")) for m in items if isinstance(m, dict)] if isinstance(items, list) else []
    except ValueError:
        return {"ok": False, "code": code, "body": "not json"}
    return {"ok": True, "count": len(ids), "sample": ids[:40]}


def probe(model: str = "auto/coding") -> dict:
    tok = _token()
    if not tok:
        return {"ok": False, "reason": "no_gateway_token_in_vault", "vault_path": VAULT_TOKEN_PATH}
    payload = json.dumps({"model": model, "max_tokens": 16,
                          "messages": [{"role": "user", "content": "Reply with exactly: OK"}]}).encode("utf-8")
    req = urllib.request.Request(BASE + "/v1/messages", data=payload, method="POST",
                                 headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01",
                                          "x-api-key": tok, "Authorization": "Bearer " + tok})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read(100_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "code": exc.code, "body": exc.read(500).decode("utf-8", "replace")[:300]}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "reason": type(exc).__name__}
    text = "".join(b.get("text", "") for b in body.get("content", []) if isinstance(b, dict))
    # a free model answered at all = the lane works; thinking models echo the instruction instead of "OK"
    return {"ok": bool(text.strip()), "answered_ok": "OK" in text.upper(), "model_requested": model, "model_used": body.get("model"),
            "text": text[:80], "elapsed_s": round(time.time() - t0, 1), "usage": body.get("usage")}


PROVIDER_IDS = {"nvidia-nim": "nvidia"}
SKIP_PROVIDERS = {"ollama", "cursor", "deepgram", "google-maps", "opencode-zen"}
DEAD = {"dead", "revoked", "expired", "invalid", "disabled"}


def _run_cli(cli: str, args: list[str], stdin: str | None = None) -> tuple[int, str]:
    r = subprocess.run([cli, *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=NW, timeout=180)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _find_key(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k.lower() in ("key", "apikey", "api_key", "token", "secret", "value") and isinstance(v, str) and len(v) >= 16:
                return v
            f = _find_key(v)
            if f:
                return f
    if isinstance(o, list):
        for x in o:
            f = _find_key(x)
            if f:
                return f
    return None


def setup(matrix_path: Path | None = None, cli: str | None = None, secrets_mod=None) -> dict:
    """Idempotent first-run setup on THIS machine (darkhero recipe of 2026-10-14, codified 2026-10-15 so a
    follower runs one command): admin password in the vault, the machine's own api-matrix keys connected
    (first live key per provider, then extra keys for groq/gemini/cerebras), a gateway access key minted into
    the vault, then providers test-all. Keys only travel by stdin; nothing secret is returned or printed."""
    cli = cli or _cli()
    if not cli:
        return {"ok": False, "reason": "omniroute_cli_not_found", "hint": "npm install -g omniroute@3.8.51"}
    if secrets_mod is None:
        sys.path.insert(0, str(HUB / "_skill" / "engines"))
        import _secrets as secrets_mod  # type: ignore
    import secrets as _rand
    steps = {}
    pw = secrets_mod.get("omniroute.admin_password")
    if not pw:
        pw = _rand.token_urlsafe(24)
        secrets_mod.set("omniroute.admin_password", pw)
        steps["admin_password"] = "minted"
    else:
        steps["admin_password"] = "present"
    rc, _ = _run_cli(cli, ["setup", "--non-interactive", "--password", str(pw)])
    steps["cli_setup_rc"] = rc
    matrix = json.loads(Path(matrix_path or HUB / "_secrets" / "api-matrix.json").read_text(encoding="utf-8-sig"))
    added, extra, skipped = [], [], []
    count = {}
    for k in matrix.get("keys") or []:
        if not isinstance(k, dict) or not k.get("key"):
            continue
        prov = PROVIDER_IDS.get(k.get("provider"), k.get("provider"))
        if not prov or prov in SKIP_PROVIDERS:
            continue
        if str(k.get("status") or "").lower() in DEAD or str(k.get("health") or "").lower() in DEAD:
            skipped.append(prov)
            continue
        count[prov] = count.get(prov, 0) + 1
        n = count[prov]
        if n == 1:
            rc, _ = _run_cli(cli, ["keys", "add", prov, "--stdin"], stdin=str(k["key"]) + "\n")
            added.append((prov, rc))
        elif prov in ("groq", "gemini", "cerebras"):
            rc, _ = _run_cli(cli, ["providers", "add", prov, "--name", f"{prov}-{n}", "--credential-stdin",
                                   "--priority", str(n), "--json"], stdin=str(k["key"]) + "\n")
            extra.append((f"{prov}-{n}", rc))
    steps.update(providers_added=added, extra_connections=extra, skipped_dead=sorted(set(skipped)))
    if secrets_mod.get(VAULT_TOKEN_PATH):
        steps["access_token"] = "present"
    else:
        rc, out = _run_cli(cli, ["--output", "json", "api", "api-keys", "post-api-keys", "--body",
                                 json.dumps({"name": "claude-free-lane", "description": "hub claude-remote-exec gateway lane"})])
        i = out.find("{")
        try:
            key = _find_key(json.loads(out[i:])) if i >= 0 else None
        except ValueError:
            key = None
        if key:
            secrets_mod.set(VAULT_TOKEN_PATH, key)
            steps["access_token"] = "minted"
        else:
            steps["access_token"] = "mint_failed_rc%d" % rc
    rc, _ = _run_cli(cli, ["providers", "test-all", "--output", "json"])
    steps["test_all_rc"] = rc
    ok = steps["access_token"] in ("present", "minted") and any(r == 0 for _, r in added)
    return {"ok": ok, **steps}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("status", "start", "stop", "models"):
        s = sub.add_parser(name)
        s.add_argument("--json", action="store_true")
    p = sub.add_parser("probe")
    p.add_argument("--model", default="auto/coding")
    p.add_argument("--json", action="store_true")
    sub.add_parser("setup").add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = {"status": status, "start": start, "stop": stop, "models": models, "setup": setup}.get(a.cmd)
    doc = probe(a.model) if a.cmd == "probe" else out()
    print(json.dumps(doc, ensure_ascii=False, indent=None if getattr(a, "json", False) else 1))
    return 0 if doc.get("ok", doc.get("healthy", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
