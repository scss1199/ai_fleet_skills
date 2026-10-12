#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
r"""claude-remote-exec.py — the LOCAL terminal the phone->machine path never had.

The phone dispatch chain already exists end to end and is armed: owner LINE DM -> Drive
folder kyloren_agent_jobs (a cloud inbox, so dispatching while the PC is off is fine) ->
HubClock rider line-cursor-agent-bridge@1m pulls -> executes. Every job terminated in
Cursor Cloud (runtime=cloud_rest), so "remote control Claude on this machine" was 0% true
even though ~75% of the plumbing was built. This engine is the missing terminal, and
nothing else.

Non-negotiables, each one a rule that already exists in this hub:
  * The token never enters argv (any same-user Windows process can read another's command
    line) and never enters a log or an agent context. Vault -> child env only, exactly the
    way token-onboard._exec_with_env does it.
  * The PROMPT also goes by stdin, not argv: job text arrives from a DM, and argv caps out
    near 32k chars.
  * cwd is asserted under exec.cwd_root. The owner allowlist gates WHO dispatches; this
    gates WHERE a malformed seat can point the CLI.
  * Zero foreground: CREATE_NO_WINDOW, never -WindowStyle Hidden.
  * "Not logged in" is reported as a NAMED blocker with its remedy, never as a failed run.
    An unauthenticated CLI is a missing prerequisite, not a broken job.
  * Credential PRESENCE is never reported as authentication. An empty, expired or revoked
    store still satisfies "the file exists", and a run against it dies with Not logged in,
    so auth is THREE-state (absent / present_unverified / verified) and ready requires
    verified. A readiness gate that fails open tells the phone this machine will answer
    when it will not, which is the one direction of error that costs the operator a job.

Usage:
  python claude-remote-exec.py check [--json] [--probe]
  python claude-remote-exec.py run --seat ai_darkhero --prompt-file <path>
  echo "prompt" | python claude-remote-exec.py run --seat ai_darkhero

CITE: _registry/claude-remote-control.json - _registry/line-cursor-agent.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ENG = os.path.dirname(os.path.abspath(__file__))
if ENG not in sys.path:
    sys.path.insert(0, ENG)
from _paths import COMMON as HUB, REGISTRY  # noqa: E402

CFG_PATH = os.path.join(REGISTRY, "claude-remote-control.json")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# The one blocker this engine cannot self-heal: minting the token is an interactive OAuth.
NOT_LOGGED_IN = (
    "claude_not_authenticated: the local Claude CLI resolves but has no credential.\n"
    "  Operator, one time only:\n"
    "    1) claude setup-token                     (browser OAuth, prints a token)\n"
    "    2) python %AI_WORKSPACE%\\_skill\\engines\\token-onboard.py request claude_code\n"
    "    3) paste the token into _secrets/token-inbox.txt, save, then: token-onboard.py ingest\n"
    "  The token never passes through chat and never lands in argv."
)

# The other auth blocker: a credential EXISTS but no run has ever proven it works.
AUTH_UNVERIFIED = (
    "claude_auth_unverified: a credential source exists but nothing has proven it works.\n"
    "  Prove it (spends one small real call, then caches the verdict for probe_ttl_sec):\n"
    "    python %AI_WORKSPACE%\\_skill\\engines\\claude-remote-exec.py check --probe\n"
    "  Presence is not authentication: an empty, expired or revoked store still satisfies\n"
    "  'the file exists', so readiness stays false until a probe succeeds."
)

# Probes cost real quota, so the verdict is cached here instead of being re-spent per tick.
# Auth-state only: no token, no prompt, no result ever lands in this file.
PROBE_STAMP = os.path.join(REGISTRY, "claude-remote-probe.json")
PROBE_TTL_SEC = 43200.0  # 12h — long enough that a @5m rider never probes, short enough
                         # that a revoked token stops reading as verified within a day.


def load_cfg() -> dict:
    try:
        with open(CFG_PATH, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        return {"_load_error": "%s: %s" % (type(exc).__name__, exc)}


def resolve_cli(cfg: dict) -> str | None:
    """shutil.which, then the recorded fallbacks.

    Not a bare ['claude', ...] argv: CreateProcess appends only .exe, so the npm shim
    claude.CMD is invisible to it. which() honours PATHEXT and finds the shim.
    """
    name = ((cfg.get("cli") or {}).get("name")) or "claude"
    found = shutil.which(name)
    if found:
        return found
    for cand in (cfg.get("cli") or {}).get("fallbacks") or []:
        p = os.path.expandvars(cand)
        if os.path.isfile(p):
            return p
    return None


def _cred_file_has_substance(path: str) -> bool:
    """True only if the CLI credential store holds a non-empty document.

    os.path.isfile() was the fail-open hole: `claude` leaves a `{}` store behind after a
    logout, and an unreadable or truncated one is just as empty. Presence still proves
    nothing about validity — that is what the probe is for — but a hollow file must not
    even count as PRESENT. No value from the file is returned, logged, or printed.
    """
    try:
        if os.path.getsize(path) <= 2:
            return False
        with open(path, encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return False
    if isinstance(doc, (dict, list)):
        return bool(doc)
    return bool(str(doc).strip())


def auth_source(cfg: dict) -> tuple[str | None, str | None]:
    """(source_label, vault_path_used). PRESENCE ONLY — no value is ever returned here.

    A non-None label means "there is something to try", NOT "authenticated". Only
    check(..., probe=True) can promote presence to verified.
    """
    auth = cfg.get("auth") or {}
    for var in auth.get("env") or []:
        if os.environ.get(var):
            return "env:" + var, None
    cred = os.path.expandvars(auth.get("credentials_file") or "")
    if cred and _cred_file_has_substance(cred):
        return "cli_credentials_file", None
    for path in auth.get("vault_paths") or []:
        try:
            import _secrets

            if _secrets.get(path):
                return "vault:" + path, path
        except Exception:  # noqa: BLE001  (an unreadable vault is UNKNOWN, not absent)
            return None, None
    return None, None


def _probe_paths(cfg: dict) -> tuple[str, float]:
    auth = cfg.get("auth") or {}
    rel = auth.get("probe_stamp")
    path = os.path.join(HUB, *str(rel).split("/")) if rel else PROBE_STAMP
    try:
        ttl = float(auth.get("probe_ttl_sec") or PROBE_TTL_SEC)
    except (TypeError, ValueError):
        ttl = PROBE_TTL_SEC
    return path, max(0.0, ttl)


def read_probe_stamp(cfg: dict) -> dict:
    """Last probe verdict. Missing/unreadable/stale all mean NOT verified, never verified."""
    path, ttl = _probe_paths(cfg)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {"found": False, "ok": False, "fresh": False, "ttl_sec": ttl}
    if not isinstance(doc, dict):
        return {"found": False, "ok": False, "fresh": False, "ttl_sec": ttl}
    age = None
    try:
        age = max(0.0, time.time() - float(doc.get("epoch") or 0)) if doc.get("epoch") else None
    except (TypeError, ValueError):
        age = None
    return {
        "found": True,
        "ok": bool(doc.get("ok")),
        "auth_source": doc.get("auth_source"),
        "age_sec": None if age is None else round(age, 1),
        "fresh": age is not None and age <= ttl,
        "ttl_sec": ttl,
    }


def write_probe_stamp(ok: bool, src: str | None, err: str | None, cfg: dict) -> str | None:
    """Record the verdict so a @5m rider can trust it without spending another call."""
    path, _ = _probe_paths(cfg)
    err_lines = (err or "").splitlines()
    doc = {
        "schema": 1,
        "ok": bool(ok),
        "auth_source": src,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "epoch": round(time.time(), 3),
        "err": (err_lines[0][:160] if err_lines else None),
        "_doc": "Auth-state only. Written by claude-remote-exec.py check --probe; a failed "
                "probe is recorded too, so a revoked token cannot keep reading as verified.",
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return None
    except OSError as exc:
        return "probe_stamp_unwritable:%s" % type(exc).__name__


def _child_env(cfg: dict) -> tuple[dict, str | None, str | None]:
    """(env, source, err). The vault value lands in the child env and nowhere else."""
    env = dict(os.environ)
    src, vpath = auth_source(cfg)
    if src is None:
        return env, None, NOT_LOGGED_IN
    if vpath:
        try:
            import _secrets

            token = _secrets.get(vpath)
        except Exception as exc:  # noqa: BLE001
            return env, None, "vault_unreadable:%s" % type(exc).__name__
        if not token:
            return env, None, NOT_LOGGED_IN
        var = "CLAUDE_CODE_OAUTH_TOKEN" if "oauth" in vpath else "ANTHROPIC_API_KEY"
        env[var] = str(token)
    return env, src, None


def _seat_cwd(seat: str, cfg: dict) -> tuple[str, str | None]:
    """Seat dir under cwd_root, or an error. Never resolves outside the hub."""
    root = os.path.abspath((cfg.get("exec") or {}).get("cwd_root") or HUB)
    if not seat or not seat.replace("_", "").replace("-", "").isalnum():
        return root, "bad_seat:%s" % str(seat)[:40]
    cand = os.path.abspath(os.path.join(root, seat))
    if os.path.normcase(cand) != os.path.normcase(root) and not os.path.normcase(cand).startswith(
        os.path.normcase(root) + os.sep
    ):
        return root, "seat_escapes_cwd_root"
    return (cand if os.path.isdir(cand) else root), None


def run_local(prompt: str, seat: str = "ai_darkhero", cfg: dict | None = None) -> tuple[str, str | None]:
    """Run the local Claude CLI headlessly. Returns (text, err) like the bridge's _run_agent."""
    cfg = cfg or load_cfg()
    if not cfg.get("enabled", True):
        return "", "claude_local_disabled"
    ex = cfg.get("exec") or {}
    cli = resolve_cli(cfg)
    if not cli:
        return "", "claude_cli_not_found"
    prompt = (prompt or "").strip()
    if not prompt:
        return "", "empty_prompt"
    cap = int(ex.get("max_prompt_chars") or 12000)
    if len(prompt) > cap:
        prompt = prompt[:cap] + "\n[truncated at %d chars]" % cap
    cwd, cwd_err = _seat_cwd(seat, cfg)
    if cwd_err:
        return "", cwd_err
    env, src, auth_err = _child_env(cfg)
    if auth_err:
        return "", auth_err

    argv = [cli, "-p", "--output-format", str(ex.get("output_format") or "text")]
    mode = ex.get("permission_mode")
    if mode:
        argv += ["--permission-mode", str(mode)]
    t0 = time.time()
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(ex.get("timeout_sec") or 900),
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return "", "claude_local_timeout:%ss" % (ex.get("timeout_sec") or 900)
    except OSError as exc:
        return "", "claude_local_spawn:%s" % type(exc).__name__

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0 or not out:
        low = (out + " " + err).lower()
        if "not logged in" in low or "/login" in low or "unauthorized" in low:
            return "", NOT_LOGGED_IN
        return out, "claude_local_rc%d:%s" % (proc.returncode, (err or out)[-300:])
    cap_r = int(ex.get("max_result_chars") or 20000)
    if len(out) > cap_r:
        out = out[:cap_r] + "\n[truncated at %d chars]" % cap_r
    head = "[runtime=claude_local seat=%s cwd=%s auth=%s %.1fs]\n" % (
        seat, os.path.basename(cwd), src, time.time() - t0)
    return head + out, None


def check(cfg: dict, *, probe: bool = False) -> dict:
    """Readiness of the local terminal only. UNKNOWN is never reported as ready.

    auth is THREE-state, and `ready` requires the strongest one:
      absent            - nothing to try
      present_unverified- a credential exists but nothing has ever proven it works
      verified          - a probe succeeded, recently, against THIS credential source

    `auth_ok` therefore means VERIFIED, not "a file exists" — the earlier meaning is what
    let the beacon promise the phone a machine that answers `Not logged in`.

    Blocker values stay SHORT labels: claude-remote-ready.py does list-membership on them
    to pick an operator_action. The human-readable remedy rides in `blocker_detail`.
    """
    cli = resolve_cli(cfg)
    src, _ = auth_source(cfg)
    stamp = read_probe_stamp(cfg)
    # A stamp only speaks for the credential it was minted against: swapping env var for
    # vault path, or re-minting under a different label, invalidates the old verdict.
    verified = bool(
        src and stamp.get("ok") and stamp.get("fresh") and stamp.get("auth_source") == src
    )
    state = "verified" if verified else ("present_unverified" if src else "absent")
    out = {
        "cli": cli or None,
        "cli_ok": bool(cli),
        "auth_source": src,
        "auth_present": bool(src),
        "auth_state": state,
        "auth_ok": verified,
        "enabled": bool(cfg.get("enabled", True)),
        "probe": "skipped",
        "probe_stamp": stamp,
        "ready": False,
    }
    if cfg.get("_load_error"):
        out["blocker"] = "cfg_unreadable"
        out["blocker_detail"] = str(cfg["_load_error"])[:200]
        return out

    if probe and out["cli_ok"] and src:
        # Costs real quota, so it is opt-in. This is the only check that proves the
        # credential works rather than merely existing.
        text, err = run_local("Reply with exactly: REMOTE_OK", "ai_darkhero", cfg)
        ok = bool(not err and "REMOTE_OK" in text)
        out["probe"] = "ok" if ok else "fail"
        out["probe_err"] = (err or "")[:200] or None
        # Written on failure too: a revoked token must LOSE its verified status, not keep
        # coasting on a stale success.
        werr = write_probe_stamp(ok, src, err, cfg)
        if werr:
            out["probe_stamp_error"] = werr
        out["probe_stamp"] = read_probe_stamp(cfg)
        verified = ok and not werr
        out["auth_state"] = "verified" if verified else "present_unverified"
        out["auth_ok"] = verified
    elif probe and out["cli_ok"] and not src:
        # Spending a call against no credential proves nothing it does not already know.
        out["probe"] = "skipped_no_credential"

    out["ready"] = bool(cli) and out["enabled"] and out["auth_ok"]
    if not out["enabled"]:
        out["blocker"] = "claude_local_disabled"
    elif not out["cli_ok"]:
        out["blocker"] = "claude_cli_not_found"
    elif not out["auth_present"]:
        out["blocker"] = "claude_not_authenticated"
        out["blocker_detail"] = NOT_LOGGED_IN
    elif not out["auth_ok"]:
        out["blocker"] = "claude_auth_unverified"
        out["blocker_detail"] = (out.get("probe_err") or AUTH_UNVERIFIED)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--json", action="store_true")
    c.add_argument("--probe", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--seat", default="ai_darkhero")
    r.add_argument("--prompt-file")
    args = ap.parse_args()

    cfg = load_cfg()
    if args.cmd == "check":
        res = check(cfg, probe=args.probe)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print("cli=%s auth=%s(%s) ready=%s probe=%s%s%s" % (
                res["cli_ok"], res["auth_source"], res["auth_state"], res["ready"],
                res["probe"],
                "\nblocker: " + res["blocker"] if res.get("blocker") else "",
                "\n" + res["blocker_detail"] if res.get("blocker_detail") else ""))
        return 0 if res["ready"] else 1

    if args.prompt_file:
        with open(args.prompt_file, encoding="utf-8") as fh:
            prompt = fh.read()
    else:
        prompt = sys.stdin.read()
    text, err = run_local(prompt, args.seat, cfg)
    if err:
        print(err, file=sys.stderr)
        if text:
            print(text)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
