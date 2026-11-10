"""load_posture — one word for how much background load this box may carry right now (operator 2026-11-10).

    awake     operator at the desk (default; also whenever the tray is dead or this file is stale)
    nap       nap overlay up, or a remote session (Chrome Remote Desktop / RDP) is active: normal limits,
              never the sleep boost (operator: 「被 chrome 遠端 … 不能完全進去 sleep mode 但是可以處於 nap mode」)
    sleep     sleep overlay up, operator away: allocators may carry more background load
    cooldown  sleep just ended (phone back on USB, or input at the desk): RAMP_S of stepping the load
              down before the operator takes the box over; nothing new starts in this window

The tray publishes state/load_posture.json every POLL_S from sleep_mode / nap_mode / remote_detect (tick()).
load_guard (yield policy) and load_grant (step size) read it with read(): a document older than STALE_S is
'awake', so a dead tray can never leave a boost behind. Nap as the buffer: phone_presence calls phone_back()
on the BACK transition while the posture is 'sleep'; nap is armed for the cooldown (black pixels, panels on)
and released again when the cooldown ends, so the operator's own nap choice survives.

The hard rails are untouched by any posture: load_guard's 250 W CPU / 280 W combined ladder, load_grant's
250 W budget and 30 W steadiness window, and the A770-busy hold on every lane.

CITE: sleep_mode.py · nap_mode.py · remote_detect.py · phone_presence.py · scripts/load_guard.py ·
      scripts/load_grant.py · tests/test_load_posture.py
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable

_TRAY_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(_TRAY_DIR, "state", "load_posture.json")
POSTURES = ("awake", "nap", "sleep", "cooldown")
RAMP_S = 120.0     # cooldown length: lanes pause staggered at once, grants stop; after it the normal rules resume
STALE_S = 30.0     # a document older than this reads as 'awake'
POLL_S = 5.0

_LOCK = threading.RLock()
_log_fn: Callable[[str], None] | None = None


def set_log_fn(fn: Callable[[str], None] | None) -> None:
    global _log_fn
    _log_fn = fn


def _log(msg: str) -> None:
    if _log_fn:
        try:
            _log_fn(msg)
        except Exception:
            pass


# ------------------------------------------------------------------ pure decision
def decide(doc: dict | None, sleep_on: bool, nap_on: bool, remote: bool, now: float) -> tuple[dict, list[str]]:
    """One posture step. Returns the new document and the events it produced ('enter:<posture>',
    'release_nap_buffer'). Pure: tested without overlays or sensors.

    sleep needs the sleep overlay AND no remote session. Leaving sleep for any reason opens a cooldown of RAMP_S;
    sleep coming back inside the window cancels it. A remote session or the nap overlay is 'nap'.
    """
    doc = dict(doc or {})
    prev = doc.get("posture") if doc.get("posture") in POSTURES else "awake"
    until = float(doc.get("cooldown_until") or 0.0)
    sleeping = bool(sleep_on) and not remote
    if prev == "sleep" and not sleeping:
        until = now + RAMP_S
    if sleeping:
        cur, until = "sleep", 0.0
    elif now < until:
        cur = "cooldown"
    else:
        until = 0.0
        cur = "nap" if (remote or nap_on) else "awake"
    events: list[str] = []
    if cur != prev:
        doc["since"] = now
        events.append(f"enter:{cur}")
    release = bool(doc.get("nap_buffer")) and cur not in ("sleep", "cooldown")
    if release:
        doc["nap_buffer"] = False
        events.append("release_nap_buffer")
    doc.update(posture=cur, cooldown_until=until, at=now, since=float(doc.get("since") or now),
               inputs={"sleep": bool(sleep_on), "nap": bool(nap_on), "remote": bool(remote)})
    return doc, events


def posture_from_doc(doc: dict | None, now: float, stale_s: float = STALE_S) -> str:
    """The posture a consumer acts on: the document's word while it is fresh, else 'awake'."""
    try:
        if not isinstance(doc, dict) or now - float(doc.get("at") or 0.0) > stale_s:
            return "awake"
        p = doc.get("posture")
        return p if p in POSTURES else "awake"
    except (TypeError, ValueError):
        return "awake"


def cooldown_remaining(doc: dict | None, now: float) -> float:
    try:
        return max(0.0, float((doc or {}).get("cooldown_until") or 0.0) - now)
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------------ state file
def load_doc(path: str = STATE_FILE) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def save_doc(doc: dict, path: str = STATE_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, path)


def read(path: str = STATE_FILE, now: float | None = None) -> str:
    """For load_guard / load_grant (other processes): the current posture, 'awake' when missing or stale."""
    return posture_from_doc(load_doc(path), time.time() if now is None else now)


def current() -> str:
    return read()


# ------------------------------------------------------------------ tray surface
def _nap():
    import nap_mode
    return nap_mode


def phone_back(nap=None, *, now: float | None = None) -> bool:
    """phone_presence BACK while sleeping: arm nap as the ramp-down buffer (only if the operator had it off) and
    remember that so the cooldown's end releases it. Returns True when nap was armed here."""
    nap = nap or _nap()
    with _LOCK:
        doc = load_doc()
        if posture_from_doc(doc, time.time() if now is None else now) != "sleep":
            return False
        if nap.enabled():
            return False
        nap.set_all_screens(True)
        doc["nap_buffer"] = True
        save_doc(doc)
    _log("load_posture nap armed as the sleep->awake buffer")
    return True


def tick(_event: str | None = None) -> str:
    """Tray tick (every POLL_S): publish the posture from the live overlay and remote state."""
    import remote_detect
    import sleep_mode

    nap = _nap()
    sleep_on = bool(sleep_mode.overlay_active())
    nap_on = bool(nap.overlay_active())
    remote = bool(remote_detect.refresh().get("active"))
    now = time.time()
    with _LOCK:
        doc, events = decide(load_doc(), sleep_on, nap_on, remote, now)
        save_doc(doc)
    for ev in events:
        if ev == "release_nap_buffer":
            try:
                nap.set_all_screens(False)
            except Exception as exc:  # the buffer must never wedge the posture tick
                _log(f"load_posture nap buffer release ERR {type(exc).__name__}: {exc}")
        _log(f"load_posture {ev} sleep={sleep_on} nap={nap_on} remote={remote}"
             + (f" cooldown={cooldown_remaining(doc, now):.0f}s" if doc["posture"] == "cooldown" else ""))
    return doc["posture"]


def status_line(now: float | None = None) -> str:
    doc = load_doc()
    now = time.time() if now is None else now
    p = posture_from_doc(doc, now)
    extra = f" ({cooldown_remaining(doc, now):.0f} s left)" if p == "cooldown" else ""
    return f"load posture: {p}{extra}"
