"""Load grant: one owner (ai_darkhero) approves every planned load increase on this box.

Operator 2026-10-24 after two power losses 14 min apart: the trip is a fast load STEP while the box is already
loaded (01:12:54: A770 49 -> 150 W in 1 s on top of ~165 W CPU from four subtitle lanes; 10-05 analysis: the A770 rise
before a crash ranks at the 75.6th percentile, p = 0.0065). The absolute level was lower than loads the box had
carried before. So a job that is about to add load (an A770 batch, one more CPU lane, an Ollama model, a big test run)
asks first, and gets a grant only when:
  1. the last WINDOW_S seconds of CPU + A770 package power were steady: p90 - p10 <= STABLE_SPREAD_W (calibrated
     2026-10-24 on 1,219 quiet seconds: median 21 W, p75 27 W; the 60 s before the 01:12 crash: 31 W),
  2. the step it announces is at most MAX_STEP_W, and now + step stays within BUDGET_W (the 01:12 crash stepped
     from ~230 W to ~313 W; the box carried more before, so this is a margin while the hardware cause is open),
  3. no other grant was given in the last SPACING_S seconds (one increase at a time, each settles before the next),
     and load granted in the last OBSERVE_TO_S seconds that the sensors do not show yet counts against BUDGET_W
     (2026-10-27: a job still loading its model looked steady, so the next +40 W could stack past the budget),
  4. the sensor log is fresh (older than STALE_S = no grant: unknown power is not safe power).
A job that needs more than MAX_STEP_W ramps itself in steps and asks before each one.

Python:  from load_grant import wait_grant; g = wait_grant("ai_theater/stt", 40, timeout_s=900)  # g["ok"]
CLI:     python load_grant.py wait --owner ai_theater/stt --step 40 [--timeout 900]   (exit 0 granted, 2 not)
         python load_grant.py run --owner seat/tests --step 60 -- python -m pytest -q ...
         python load_grant.py status
State: tray/state/load_grant.json (last grant). Log: tray/logs/load_grant.log (one JSON line per decision).
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TRAY = os.path.dirname(HERE)
if TRAY not in sys.path:
    sys.path.insert(0, TRAY)
import load_posture  # noqa: E402  (tray/load_posture.py: awake | nap | sleep)
RING = "D:/__hwlog"
STATE = os.path.join(TRAY, "state", "load_grant.json")
LOCK = os.path.join(TRAY, "state", "load_grant.lock")
LOG = os.path.join(TRAY, "logs", "load_grant.log")
WINDOW_S = 60
STABLE_SPREAD_W = 30.0
BUDGET_W = 250.0
MAX_STEP_W = 40.0
# load posture (operator 2026-11-10, tray/load_posture.py): while the sleep overlay is up a job may step 60 W at a
# time (budget, steadiness window and spacing unchanged); nap and awake keep MAX_STEP_W.
SLEEP_MAX_STEP_W = 60.0
SPACING_S = 20.0
STALE_S = 10.0
TAIL_BYTES = 262144
POWER_COLUMNS = ("cpu.CPU Package [W]", "a770.GPU Package [W]")
# Measured step (operator standing mandate 2026-10-24: darkhero's task allocation). A job is charged what it really
# added, not what it announced: on 2026-10-24 an STT lane asked for +25 W and ran 16 threads, and the box reached 276 W.
# Each grant's rise is measured OBSERVE_FROM_S..OBSERVE_TO_S after it; an owner whose last LEARN_KEEP rises (at least
# two, within LEARN_TTL_S) exceed what it announced by OVERRUN_MARGIN_W is charged their median from then on.
LEARNED = os.path.join(TRAY, "state", "load_grant.learned.json")
OBSERVE_FROM_S, OBSERVE_TO_S = 30.0, 120.0
OVERRUN_MARGIN_W = 15.0
LEARN_KEEP = 3
LEARN_TTL_S = 6 * 3600.0


def _log(row: dict) -> None:
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **row}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def recent_power(window_s: float = WINDOW_S, ring: str = RING) -> dict:
    """Total CPU + A770 package watts over the last `window_s` seconds of the newest hwlog segment."""
    files = sorted(glob.glob(os.path.join(ring, "hwlog-*.csv")), key=os.path.getmtime)
    if not files:
        return {"ok": False, "reason": "no_sensor_log"}
    path = files[-1]
    try:
        age = time.time() - os.path.getmtime(path)
        with open(path, "rb") as fh:
            header = next(csv.reader([fh.readline().decode("utf-8", "replace")]))
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            lines = fh.read().decode("utf-8", "replace").split("\n")[1:-1]
    except (OSError, csv.Error, StopIteration):
        return {"ok": False, "reason": "sensor_log_unreadable"}
    if age > STALE_S:
        return {"ok": False, "reason": f"sensor_log_stale_{age:.0f}s"}
    try:
        idx = [header.index(c) for c in POWER_COLUMNS]
    except ValueError:
        return {"ok": False, "reason": "power_columns_missing"}
    totals = []
    for line in lines[-int(window_s * 2):]:
        row = next(csv.reader([line.rstrip("\r")]), [])
        try:
            totals.append(sum(float(row[i]) for i in idx))
        except (ValueError, IndexError):
            continue
    totals = totals[-int(window_s):]
    if len(totals) < window_s * 0.8:
        return {"ok": False, "reason": f"too_few_samples_{len(totals)}"}
    ordered = sorted(totals)
    spread = ordered[int(0.9 * (len(ordered) - 1))] - ordered[int(0.1 * (len(ordered) - 1))]
    return {"ok": True, "now_w": round(totals[-1], 1), "min_w": round(ordered[0], 1), "max_w": round(ordered[-1], 1),
            "spread_w": round(spread, 1), "n": len(totals)}


def window_mean(t0: float, t1: float, ring: str = RING) -> float | None:
    """Mean CPU + A770 package watts over rows stamped t0..t1 (epoch) in the newest segment; None with < 20 rows."""
    files = sorted(glob.glob(os.path.join(ring, "hwlog-*.csv")), key=os.path.getmtime)
    if not files:
        return None
    try:
        with open(files[-1], "rb") as fh:
            header = next(csv.reader([fh.readline().decode("utf-8", "replace")]))
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - TAIL_BYTES * 4))
            lines = fh.read().decode("utf-8", "replace").split("\n")[1:-1]
        idx = [header.index(c) for c in POWER_COLUMNS]
    except (OSError, csv.Error, StopIteration, ValueError):
        return None
    from datetime import datetime
    totals = []
    for line in lines:
        row = next(csv.reader([line.rstrip("\r")]), [])
        try:
            stamp = datetime.fromisoformat(row[0]).timestamp()
            if t0 <= stamp <= t1:
                totals.append(sum(float(row[i]) for i in idx))
        except (ValueError, IndexError):
            continue
    return sum(totals) / len(totals) if len(totals) >= 20 else None


def _learned() -> dict:
    try:
        with open(LEARNED, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def learned_step(owner: str, now: float, learned: dict | None = None) -> float:
    """The watts this owner is charged: the median of its recent measured rises when they overran, else 0."""
    rows = [r for r in (learned if learned is not None else _learned()).get(owner) or []
            if now - float(r.get("at") or 0) < LEARN_TTL_S][-LEARN_KEEP:]
    over = [float(r["rise"]) for r in rows if float(r["rise"]) > float(r["announced"]) + OVERRUN_MARGIN_W]
    if len(rows) < 2 or len(over) < 2:
        return 0.0
    over.sort()
    return over[len(over) // 2]


def observe_last(last: dict, now: float, ring: str = RING) -> dict | None:
    """Measure the previous grant's real rise once its observation window has passed; record it per owner."""
    epoch = float(last.get("epoch") or 0)
    if not epoch or last.get("observed") is not None or now < epoch + OBSERVE_TO_S:
        return None
    before = float((last.get("power") or {}).get("now_w") or 0)
    after = window_mean(epoch + OBSERVE_FROM_S, epoch + OBSERVE_TO_S, ring)
    rise = None if after is None or not before else round(after - before, 1)
    last["observed"] = "unobservable" if rise is None else rise
    if rise is not None:
        doc = _learned()
        rows = (doc.get(last.get("owner") or "?") or []) + [{"at": epoch, "announced": float(last.get("step_w") or 0),
                                                              "rise": rise}]
        doc[last.get("owner") or "?"] = rows[-LEARN_KEEP * 2:]
        tmp = LEARNED + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        os.replace(tmp, LEARNED)
    return last


def _last_grant() -> dict:
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def unsettled(last: dict, now: float) -> list:
    """Grants younger than OBSERVE_TO_S, oldest first. A state file written before 2026-10-27 has no 'recent' list;
    its single grant stands in for it."""
    rows = last.get("recent")
    if not isinstance(rows, list):
        rows = [{"owner": last.get("owner"), "charged_w": float(last.get("step_w") or 0), "epoch": last.get("epoch"),
                 "before_w": (last.get("power") or {}).get("now_w")}] if last.get("epoch") else []
    keep = []
    for r in rows:
        try:
            if 0 <= now - float(r["epoch"]) < OBSERVE_TO_S:
                keep.append({"owner": r.get("owner"), "charged_w": float(r.get("charged_w") or 0),
                             "epoch": float(r["epoch"]), "before_w": r.get("before_w")})
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(keep, key=lambda r: r["epoch"])


def pending_w(recent: list, now_w: float) -> float:
    """Watts already granted that the live reading does not show yet (2026-10-27: grants 20 s apart could each see a
    steady box while the earlier job was still loading its model, so two +40 W steps stacked past the budget).
    Everything granted since the oldest unsettled grant, minus the rise the sensors already show since then."""
    if not recent:
        return 0.0
    granted = sum(r["charged_w"] for r in recent)
    try:
        shown = max(0.0, now_w - float(recent[0]["before_w"]))
    except (TypeError, ValueError):
        shown = 0.0                       # baseline unknown: charge the whole grant until it settles
    return round(max(0.0, granted - shown), 1)


def max_step_w(posture: str = "awake") -> float:
    return SLEEP_MAX_STEP_W if posture == "sleep" else MAX_STEP_W


def decide(owner: str, step_w: float, power: dict, last: dict, now: float, measured_w: float = 0.0,
           pending: float = 0.0, posture: str = "awake") -> dict:
    """Pure decision (tested without sensors): {'ok': bool, 'reason': str, 'charged_w': float}. `measured_w` is what
    this owner's earlier grants really added (learned_step); it is charged when larger than what it announces.
    `pending` is granted load that has not shown up in the sensors yet (pending_w); it counts against the budget.
    `posture` (load_posture.read()): 'sleep' widens the step to SLEEP_MAX_STEP_W; nap and awake use MAX_STEP_W."""
    limit = max_step_w(posture)
    if measured_w > step_w:
        if measured_w > limit:
            return {"ok": False, "reason": f"step {step_w:.0f} W announced but {owner} measured +{measured_w:.0f} W "
                                           f"> {limit:.0f} W: shrink the job (fewer threads/lanes)"}
        step_w = measured_w
    if step_w > limit:
        return {"ok": False, "reason": f"step {step_w:.0f} W > {limit:.0f} W: ramp in smaller steps"}
    if not power.get("ok"):
        return {"ok": False, "reason": power.get("reason", "power_unknown")}
    level = power["now_w"]
    if power["spread_w"] > STABLE_SPREAD_W:
        # sleep posture (operator 2026-11-11: fill the CPU at night): bursty CPU work never holds a 30 W window, so the
        # gate stayed shut with 100 W of budget unused. There the budget is judged against the window's PEAK instead.
        if posture != "sleep" or float(power.get("max_w") or 1e9) + pending + step_w > BUDGET_W:
            return {"ok": False, "reason": f"unsteady: {power['spread_w']} W spread in {WINDOW_S} s"}
        level = float(power["max_w"])
    if level + pending + step_w > BUDGET_W:
        settling = f" + {pending:.0f} W still settling from earlier grants" if pending else ""
        return {"ok": False, "reason": f"{level} W{settling} + {step_w:.0f} W > budget {BUDGET_W:.0f} W"}
    since = now - float(last.get("epoch") or 0)
    if since < SPACING_S:
        return {"ok": False, "reason": f"last grant {since:.0f} s ago to {last.get('owner')}"}
    return {"ok": True, "charged_w": step_w, "reason": f"steady {power['spread_w']} W spread at {power['now_w']} W"
                                                       + (f" (+{pending:.0f} W settling)" if pending else "")}


def unmetered_host(ring: str = RING, host: str | None = None) -> bool:
    """A follower (scar3, altos) carries this script through the hub repo but has no sensor ring at all: there is
    nothing to meter, so a grant there passes (2026-11-10: f1s_daily never ticked on scar3, every tick deferred with
    no_sensor_log). darkhero itself keeps deferring when its logger is dead: its ring directory exists."""
    host = (host or socket.gethostname()).lower()
    return not os.path.isdir(ring) and not host.startswith("dark-hero")


def try_grant(owner: str, step_w: float) -> dict:
    """One attempt; the grant is recorded under an exclusive file lock so two jobs never step at the same moment."""
    import msvcrt

    if unmetered_host():
        return {"ok": True, "owner": owner, "step_w": step_w, "charged_w": 0.0, "reason": "unmetered_host"}
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, "a+b") as lock:
        lock.seek(0)  # lock and unlock the same byte: "a+b" opens positioned at the end
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return {"ok": False, "reason": "another grant is being decided"}
        try:
            now = time.time()
            last = _last_grant()
            if observe_last(last, now) is not None:     # the previous grant's real rise, measured once
                tmp = STATE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(last, fh)
                os.replace(tmp, STATE)
            power = recent_power()
            recent = unsettled(last, now)
            pending = pending_w(recent, power["now_w"]) if power.get("ok") else 0.0
            posture = load_posture.read(now=now)
            result = decide(owner, step_w, power, last, now, learned_step(owner, now), pending, posture)
            result["posture"] = posture
            if result["ok"]:
                recent.append({"owner": owner, "charged_w": result["charged_w"], "epoch": now,
                               "before_w": power.get("now_w")})
                tmp = STATE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump({"owner": owner, "step_w": step_w, "epoch": now, "power": power,
                               "recent": recent}, fh)
                os.replace(tmp, STATE)
            return {**result, "owner": owner, "step_w": step_w, "power": power}
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def wait_grant(owner: str, step_w: float, timeout_s: float = 900.0, poll_s: float = 2.0) -> dict:
    deadline = time.time() + timeout_s
    while True:
        result = try_grant(owner, step_w)
        if result["ok"] or time.time() >= deadline or result["reason"].startswith("step "):
            _log({k: result[k] for k in ("ok", "owner", "step_w", "reason", "posture") if k in result})
            return result
        time.sleep(poll_s)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("wait", "run"):
        s = sub.add_parser(name)
        s.add_argument("--owner", required=True)
        s.add_argument("--step", type=float, required=True, help="watts this job is about to add")
        s.add_argument("--timeout", type=float, default=900.0)
        if name == "run":
            s.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(json.dumps({"power": recent_power(), "last_grant": _last_grant()}, ensure_ascii=False))
        return 0
    g = wait_grant(a.owner, a.step, a.timeout)
    print(json.dumps({k: g[k] for k in ("ok", "owner", "step_w", "reason")}, ensure_ascii=False))
    if not g["ok"]:
        return 2
    if a.cmd == "run":
        cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
        return subprocess.call(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
