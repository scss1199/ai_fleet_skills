#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""f1s_live.py — an idle conversation takes an F1S upgrade or a curator order the moment it lands.

operator 2026-10-24: 「目的就是當任何對話一閒置後立刻套用」. An open conversation already gets every upgrade at its
next prompt (UserPromptSubmit) and at its next tool call (PostToolUse mid-turn update); what it could not do is take
one while idle. Claude Code runs `wait` as an asyncRewake Stop hook: it starts when a turn ends and keeps running in
the background while the conversation sits idle. When the F1S contract files or this seat's curator orders change
(claude_session_hook._midturn_sig, the signature the mid-turn update uses) it lets the release finish writing
(SETTLE_S), prints the update text (claude_session_hook.live_update, recorded as delivered) to stderr and exits 2:
Claude Code wakes the model with that text. An upgrade that landed during the turn after its last tool call wakes the
conversation as soon as the turn ends.

It exits 0 without waking when the conversation turns active again (a user or assistant row lands in its transcript;
that turn's own hooks deliver), when a newer waiter for the same conversation takes over, when the kill switch is off,
after MAX_WAKES_PER_DAY wakes, when the Claude process is gone, or after LIFETIME_S. Any error exits 0: a broken
waiter never loops the model.

Capture watch (operator 2026-10-24, after a Google Meet caption scraper in a background tab stalled at 12:03 and nobody
noticed until the meeting ended 55 min later): a conversation that leaves a capture running that cannot be redone
(meeting recording, caption scraping, a stream download) registers it, and the same idle waiter watches it: a file that
stops growing for --stale-s wakes the conversation at once (CAPTURE STALLED), and --check-every-s wakes it on a beat to
re-verify what no file shows (CAPTURE CHECK). Captures are exempt from the daily wake cap until their --hours end.
claude-run-until-done-hook.py refuses to let a turn end on "it keeps recording until the end" without a registration.

  python f1s_live.py wait              # hook entry: the Stop payload on stdin
  python f1s_live.py status [--json]   # one row per conversation: seat, current or behind, waiter, wakes
  python f1s_live.py capture add --name meet-0824 --file <growing file> [--stale-s 90] [--check-every-s 300] [--hours 3]
  python f1s_live.py capture done --name meet-0824 | capture list   (session from CLAUDE_CODE_SESSION_ID or --session)
Kill switch: _registry/run-until-done.json  "live_wake": {"enabled": false}.
State: _registry/fames-hot/wait-<key>.json, capture-<key>.json (key = the conversation's mid-turn record key).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or Path(__file__).resolve().parents[2])
HOOK = HUB / "_skill" / "fleet-skills" / "token-preflight" / "scripts" / "claude_session_hook.py"
CONFIG = HUB / "_registry" / "run-until-done.json"
POLL_S = 5.0
GRACE_S = 10.0         # rows the host appends right after the Stop event (hook summaries) are not activity
SETTLE_S = 15.0        # a release rewrites several watched files; wake once, after the last one
SETTLE_MAX_S = 180.0
LIFETIME_S = 70 * 3600  # wired with timeout 259200 s (72 h); exit cleanly before the host kills the hook
MAX_WAKES_PER_DAY = 24
SHIP_STATE = HUB / "_registry" / "fames-hot" / "ship-state.json"  # written by ship-f1s.py around its steps
SHIP_MAX_S = 3600.0
ACTIVE_TYPES = ("user", "assistant")
# Real Claude / Codex conversations carry a UUID; the FAMES run-cases probes write ids like "claude-session".
SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
HEAD = ("F1S LIVE UPDATE — this conversation was idle when an F1S upgrade or a curator order landed (operator "
        "2026-10-24: apply it the moment a conversation is idle). Answer any open curator order now; otherwise take "
        "the new contract on board, do nothing else, and end the turn with 「沒有下一步」.")


def _now() -> float:
    return time.time()


def _iso(epoch: float | None = None) -> str:
    return datetime.fromtimestamp(epoch if epoch is not None else _now(), timezone.utc).isoformat()


def load_hook():
    spec = importlib.util.spec_from_file_location("f1s_live_session_hook", HOOK)
    if spec is None or spec.loader is None:
        raise ImportError(str(HOOK))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.HUB = HUB
    return mod


def enabled() -> bool:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig")).get("live_wake") or {}
        return cfg.get("enabled", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def wait_path(hook, surface_id: str, session_id: str) -> Path:
    return hook._midturn_path(surface_id, session_id).with_name(
        hook._midturn_path(surface_id, session_id).name.replace("midturn-", "wait-", 1))


def _read(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(path.name + f".{os.getpid()}.tmp")
    stage.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(stage, path)


def turned_active(transcript: Path, offset: int) -> bool:
    """A user or assistant row written after `offset`: the conversation is in a turn again."""
    try:
        with transcript.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except OSError:
        return False
    for raw in data.split(b"\n"):
        try:
            row = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(row, dict) and row.get("type") in ACTIVE_TYPES:
            return True
    return False


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _claude_ancestor() -> int | None:
    try:
        import psutil
        proc = psutil.Process(os.getpid()).parent()
        while proc is not None:
            if proc.name().lower().startswith("claude"):
                return proc.pid
            proc = proc.parent()
    except Exception:
        pass
    return None


def _alive(pid: int | None) -> bool:
    if not pid:
        return True
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        return True


def shipping(now: float | None = None) -> bool:
    """A ship-f1s run is between its first and last step (pid alive, under SHIP_MAX_S): its bump, bundle and
    install rewrite the watched files minutes apart (1.45.81, 2026-10-24), so waking now would wake again later."""
    doc = _read(SHIP_STATE)
    if doc.get("state") != "running":
        return False
    try:
        age = (now if now is not None else _now()) - SHIP_STATE.stat().st_mtime
    except OSError:
        return False
    return age < SHIP_MAX_S and _alive(int(doc.get("pid") or 0) or None)


def capture_path(session_id: str, surface_id: str = "claude") -> Path:
    import hashlib
    scope = f"{surface_id}\0{session_id}"
    return HUB / "_registry" / "fames-hot" / f"capture-{hashlib.sha256(scope.encode('utf-8')).hexdigest()[:24]}.json"


def _captures(session_id: str) -> list[dict]:
    rows = _read(capture_path(session_id)).get("captures")
    return rows if isinstance(rows, list) else []


def active_captures(session_id: str, now: float | None = None) -> list[dict]:
    now = now if now is not None else _now()
    return [c for c in _captures(session_id) if c.get("state") == "active" and float(c.get("until") or 0) > now]


def capture_add(session_id: str, name: str, file: str = "", stale_s: float = 90.0, check_every_s: float = 0.0,
                hours: float = 3.0) -> dict:
    if not session_id:
        raise ValueError("no session id: run inside a Claude conversation (CLAUDE_CODE_SESSION_ID) or pass --session")
    if not file and not check_every_s:
        raise ValueError("a capture watch needs --file (a file that grows while it captures) or --check-every-s")
    if file and not Path(file).exists():
        raise ValueError(f"--file {file} does not exist yet: start the capture first, then register it")
    now = _now()
    size = _size(Path(file)) if file else 0
    entry = {"name": name, "file": file or None, "stale_s": float(stale_s), "check_every_s": float(check_every_s),
             "until": now + hours * 3600, "added": _iso(now), "state": "active", "last_size": size,
             "last_growth": now, "last_check": now, "last_alert": 0.0}
    rows = [c for c in _captures(session_id) if c.get("name") != name] + [entry]
    _write(capture_path(session_id), {"session_id": session_id, "captures": rows})
    return entry


def capture_done(session_id: str, name: str) -> bool:
    rows = _captures(session_id)
    hit = False
    for c in rows:
        if c.get("name") == name and c.get("state") == "active":
            c.update({"state": "done", "ended": _iso()})
            hit = True
    if hit:
        _write(capture_path(session_id), {"session_id": session_id, "captures": rows})
    return hit


def capture_due(session_id: str, now: float | None = None) -> str:
    """The alert text when a registered capture stalled or its check is due ("" when all is well); state written back."""
    now = now if now is not None else _now()
    rows = _captures(session_id)
    alerts, changed = [], False
    for c in rows:
        if c.get("state") != "active":
            continue
        if float(c.get("until") or 0) <= now:
            c.update({"state": "expired", "ended": _iso(now)})
            changed = True
            continue
        name = c.get("name")
        if c.get("file"):
            size = _size(Path(c["file"]))
            if size != c.get("last_size"):
                c.update({"last_size": size, "last_growth": now})
                changed = True
            idle = now - float(c.get("last_growth") or now)
            if idle > float(c.get("stale_s") or 90) and now - float(c.get("last_alert") or 0) > float(c.get("stale_s") or 90):
                alerts.append(f"F1S CAPTURE STALLED — {name}: {c['file']} has not grown for {idle:.0f} s "
                              f"(still {size} bytes). Recover it now (restart the recorder, re-join, switch source), "
                              "confirm the file grows again, and tell the operator in this conversation right away.")
                c["last_alert"] = now
                changed = True
        every = float(c.get("check_every_s") or 0)
        if every and now - float(c.get("last_check") or now) >= every:
            alerts.append(f"F1S CAPTURE CHECK — {name}: verify now that it is still capturing (read its progress: "
                          "line count, file size, the page itself). If it stalled, recover it and tell the operator; "
                          f"then end the turn — you are woken again in {every:.0f} s.")
            c["last_check"] = now
            changed = True
    if changed:
        _write(capture_path(session_id), {"session_id": session_id, "captures": rows})
    return "\n".join(alerts)


def _recent_wakes(state: dict, now: float) -> list[float]:
    return [float(w) for w in state.get("wakes") or [] if now - float(w) < 86400]


def wait(doc: dict, *, hook=None, poll_s: float = POLL_S, grace_s: float = GRACE_S, settle_s: float = SETTLE_S,
         lifetime_s: float = LIFETIME_S, sleep=time.sleep) -> tuple[int, str]:
    """(exit code, wake text). 2 = wake the model with the text; 0 = end quietly."""
    session_id = str(doc.get("session_id") or "")
    if not session_id or doc.get("agent_id") or not enabled():
        return 0, ""
    hook = hook or load_hook()
    surface_id = "open-agent-standard" if str(doc.get("turn_id") or "").strip() else "claude"
    transcript = Path(str(doc.get("transcript_path") or ""))
    record = hook._midturn_record(surface_id, session_id)
    seat, cwd = hook._session_seat(doc, record)
    sig_seat = str(record.get("seat") or "") if record else seat
    if record and not sig_seat and seat and not hook._midturn_pending(surface_id, session_id):
        # A record without the seat (made before the ledger fields, or kept through machine-event turns, which record
        # nothing) watches the F1S files only, so an order would never wake it. Nothing is pending on those files and
        # every prompt carries the seat's orders: re-record with the seat so its orders are watched from here on.
        hook._midturn_changed(surface_id, session_id, record_only=True, seat=seat, cwd=cwd, event="Stop")
        sig_seat = seat
    path = wait_path(hook, surface_id, session_id)
    prior = _read(path)
    token = uuid.uuid4().hex
    start = _now()
    state = {"token": token, "pid": os.getpid(), "session_id": session_id, "seat": seat, "surface": surface_id,
             "started": _iso(start), "state": "waiting", "wakes": _recent_wakes(prior, start),
             "claude_pid": _claude_ancestor(), "transcript": str(transcript)}
    _write(path, state)

    def finish(code: int, why: str, text: str = "") -> tuple[int, str]:
        current = _read(path)
        if current.get("token") == token:
            state.update({"state": why, "ended": _iso()})
            if code == 2:
                state["wakes"] = state["wakes"] + [_now()]
            _write(path, state)
        return code, text

    if len(state["wakes"]) >= MAX_WAKES_PER_DAY and not active_captures(session_id):
        return finish(0, "capped")
    sleep(grace_s)
    offset = _size(transcript) if transcript.is_file() else 0
    while True:
        if _read(path).get("token") != token:
            return 0, ""                                   # a newer waiter owns this conversation now
        if transcript.is_file() and _size(transcript) > offset and turned_active(transcript, offset):
            return finish(0, "active")
        if not _alive(state.get("claude_pid")):
            return finish(0, "host_gone")
        if not enabled():
            return finish(0, "disabled")
        if _now() - start > lifetime_s:
            return finish(0, "expired")
        alert = capture_due(session_id)
        if alert:
            return finish(2, "capture", alert)
        if hook._midturn_pending(surface_id, session_id, seat=sig_seat) and not shipping():
            settled, last, ready = _now(), hook._midturn_sig(sig_seat), True
            while True:
                sleep(settle_s)
                if shipping():
                    ready = False                          # a ship started: the outer loop waits for it to end
                    break
                sig = hook._midturn_sig(sig_seat)
                if sig == last or _now() - settled > SETTLE_MAX_S:
                    break
                last = sig
            if ready:
                if transcript.is_file() and _size(transcript) > offset and turned_active(transcript, offset):
                    return finish(0, "active")
                text = hook.live_update(doc, event="IdleWake", watch_seat=sig_seat)
                if text:
                    return finish(2, "woke", HEAD + "\n" + text)
                # Nothing to say about the change: record it, or the same change re-enters the settle loop forever.
                hook._midturn_changed(surface_id, session_id, record_only=True, seat=sig_seat, cwd=cwd, event="IdleQuiet")
        sleep(poll_s)


def status() -> list[dict]:
    hook = load_hook()
    root = HUB / "_registry" / "fames-hot"
    rows = []
    sigs: dict[str, str] = {}
    for rec_path in sorted(root.glob("midturn-*.json")):
        rec = _read(rec_path)
        session_id = rec.get("session_id")
        if not session_id or rec.get("agent_id") or not SESSION_ID.match(str(session_id)):
            continue                                       # legacy record, a subagent, or a synthetic probe session
        seat = str(rec.get("seat") or "")
        if seat not in sigs:
            sigs[seat] = hook._midturn_sig(seat)
        waiter = _read(rec_path.with_name(rec_path.name.replace("midturn-", "wait-", 1)))
        rows.append({"session_id": session_id, "seat": seat or None, "surface": rec.get("surface"),
                     "delivered_at": rec.get("at"), "current": rec.get("sig") == sigs[seat],
                     "waiter": waiter.get("state"), "waiter_started": waiter.get("started"),
                     "wakes_24h": len(_recent_wakes(waiter, _now()))})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("wait")
    st = sub.add_parser("status")
    st.add_argument("--json", action="store_true")
    cp = sub.add_parser("capture")
    cp.add_argument("action", choices=("add", "done", "list"))
    cp.add_argument("--name", default="")
    cp.add_argument("--file", default="")
    cp.add_argument("--stale-s", type=float, default=90.0)
    cp.add_argument("--check-every-s", type=float, default=0.0)
    cp.add_argument("--hours", type=float, default=3.0)
    cp.add_argument("--session", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    a = ap.parse_args(argv)
    if a.cmd == "capture":
        if a.action == "list":
            print(json.dumps(_captures(a.session), ensure_ascii=False, indent=1))
            return 0
        if not a.name:
            print("capture: --name is required", file=sys.stderr)
            return 2
        try:
            if a.action == "add":
                entry = capture_add(a.session, a.name, a.file, a.stale_s, a.check_every_s, a.hours)
                print(json.dumps({"ok": True, "watching": entry}, ensure_ascii=False))
            else:
                print(json.dumps({"ok": capture_done(a.session, a.name)}, ensure_ascii=False))
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        return 0
    if a.cmd == "status":
        rows = status()
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            behind = [r for r in rows if not r["current"]]
            print(f"f1s_live: {len(rows)} conversations in the ledger, {len(behind)} behind the current contract, "
                  f"{sum(1 for r in rows if r['waiter'] == 'waiting')} waiting idle")
            for r in rows:
                print(f"  {r['session_id'][:8]} {str(r['seat']):<14} {'current' if r['current'] else 'BEHIND':<8} "
                      f"waiter={r['waiter']} wakes_24h={r['wakes_24h']} delivered={r['delivered_at']}")
        return 0
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", "replace") if sys.stdin else ""
        doc = json.loads(raw) if raw.strip() else {}
        code, text = wait(doc if isinstance(doc, dict) else {})
    except Exception:
        return 0
    if code == 2 and text:
        data = text.encode("utf-8", "replace")
        try:
            sys.stderr.buffer.write(data)
            sys.stderr.flush()
        except Exception:
            try:
                os.write(2, data)
            except OSError:
                return 0
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
