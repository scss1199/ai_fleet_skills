"""load_posture — one word for how much background load this box may carry right now (operator 2026-11-10;
three states since 2026-11-11, ai_trader chat 「照這組送出」: sleep < nap < awake, cooldown is no longer a state).

    awake     operator at the desk: any input inside NAP_IDLE_S, or nothing says away (default; also whenever the
              tray is dead, this file is stale, or the phone scan failed / its state file is stale)
    nap       no input for NAP_IDLE_S AND (a known phone on USB, or a remote session, or the nap overlay up):
              the operator can come back any moment -- automatic, not tied to the manual Nap toggle. Allocators
              may carry the nap tier (f1s_posture: NAP_MAX_JOBS after NAP_HOLD_S of continuous nap)
    sleep     sleep overlay up and no remote session (phones away): allocators may carry more background load

The tray publishes state/load_posture.json every POLL_S from sleep_mode / nap_mode / remote_detect / phone_presence
(tick()). load_guard (yield policy) and load_grant (step size) read it with read(): a document older than STALE_S is
'awake', so a dead tray can never leave a boost behind. Leaving sleep steps down to nap when the box is still idle
(phone back on USB, nobody typing) and to awake on input -- the nap tier is the buffer the cooldown used to be.
phone_presence calls phone_back() on the BACK transition while the posture is 'sleep': the nap overlay is armed
(black pixels, panels on) and released again when the posture reaches awake, so the operator's own nap choice
survives. Accepted uncovered case (operator): a phone left charging overnight keeps the box in nap, not sleep.

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
POSTURES = ("awake", "nap", "sleep")
NAP_IDLE_S = 30.0  # input idle this long (with a phone on USB / remote / nap overlay) = nap; any input = awake
PHONE_STALE_S = 120.0  # phone_presence saves every 30 s tick; older (or a failed scan, which saves nothing) = unknown
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
def decide(doc: dict | None, sleep_on: bool, nap_on: bool, remote: bool, now: float,
           phone: bool | None = None, idle_s: float | None = None) -> tuple[dict, list[str]]:
    """One posture step. Returns the new document and the events it produced ('enter:<posture>',
    'release_nap_buffer'). Pure: tested without overlays or sensors.

    sleep needs the sleep overlay AND no remote session. Otherwise nap needs input idle >= NAP_IDLE_S and one
    away sign: a known phone on USB (`phone` True; None = scan failed or stale, never a sign), a remote session,
    or the nap overlay. Everything else -- and any input -- is awake. The nap buffer is released on awake.
    """
    doc = dict(doc or {})
    prev = doc.get("posture") if doc.get("posture") in POSTURES else "awake"
    idle = idle_s is not None and float(idle_s) >= NAP_IDLE_S
    if bool(sleep_on) and not remote:
        cur = "sleep"
    elif idle and (phone is True or remote or nap_on):
        cur = "nap"
    else:
        cur = "awake"
    events: list[str] = []
    if cur != prev:
        doc["since"] = now
        events.append(f"enter:{cur}")
    release = bool(doc.get("nap_buffer")) and cur == "awake"
    if release:
        doc["nap_buffer"] = False
        events.append("release_nap_buffer")
    doc.pop("cooldown_until", None)
    doc.update(posture=cur, at=now, since=float(doc.get("since") or now),
               inputs={"sleep": bool(sleep_on), "nap": bool(nap_on), "remote": bool(remote), "phone": phone,
                       "idle_s": None if idle_s is None else round(float(idle_s), 1)})
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


def phone_present(path: str | None = None, now: float | None = None) -> bool | None:
    """Any known phone on USB per phone_presence's state file; None when it is missing, stale or the policy is off."""
    import phone_presence
    path = path or phone_presence.STATE_FILE
    try:
        if (time.time() if now is None else now) - os.path.getmtime(path) > PHONE_STALE_S:
            return None
        doc = phone_presence.load_state()
    except (OSError, ValueError):
        return None
    if not doc.get("enabled", True) or not doc.get("present"):
        return None
    return any(doc["present"].values())


def phone_back(nap=None, *, now: float | None = None) -> bool:
    """phone_presence BACK while sleeping: arm nap as the ramp-down buffer (only if the operator had it off) and
    remember that so reaching awake releases it. Returns True when nap was armed here."""
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
    """Tray tick (every POLL_S): publish the posture from the live overlays, remote, phone and input-idle state."""
    import remote_detect
    import sleep_mode

    nap = _nap()
    sleep_on = bool(sleep_mode.overlay_active())
    nap_on = bool(nap.overlay_active())
    remote = bool(remote_detect.refresh().get("active"))
    try:
        idle_s = float(nap.idle_seconds())
    except Exception:
        idle_s = None          # unknown input = awake
    now = time.time()
    phone = phone_present(now=now)
    with _LOCK:
        doc, events = decide(load_doc(), sleep_on, nap_on, remote, now, phone=phone, idle_s=idle_s)
        save_doc(doc)
    for ev in events:
        if ev == "release_nap_buffer":
            try:
                nap.set_all_screens(False)
            except Exception as exc:  # the buffer must never wedge the posture tick
                _log(f"load_posture nap buffer release ERR {type(exc).__name__}: {exc}")
        _log(f"load_posture {ev} sleep={sleep_on} nap={nap_on} remote={remote} phone={phone} idle={idle_s}")
    return doc["posture"]


def status_line(now: float | None = None) -> str:
    doc = load_doc()
    now = time.time() if now is None else now
    return f"load posture: {posture_from_doc(doc, now)}"
