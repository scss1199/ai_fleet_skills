#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""hubclock.py -- the hub's single clock-aligned metronome (HubClock). LIVE since 2026-06-13, dispatching the
armed riders (hub-selfbeat, keypool-tick, metadata-autosave, metadata-watchdog, wallpaper-health, fintrend-feed).
Arming a NEW rider stays operator-gated.

AUTOSTART: ai_darkhero/tray/logon_autostart.py::run_hubclock_ensure (HKCU Run -> ai_darkhero_hub_tray), armed by
the operator 2026-08-14. It starts this daemon when the heartbeat is stale/missing. NOTE the earlier claim here of
"ClaudeHubClock.vbs in the Startup folder" was false -- that file does not exist and no scheduled task started this
daemon, which is why it died at 2026-08-10T00:32 and stayed dead ~9h. The self-heal riders cannot cover this gap:
this daemon is what dispatches them, so the ensure MUST come from outside. Do not re-delete that external ensure.

ONE ultralight, always-on daemon that dispatches every registered job at its own cadence -- frequency band
(1s..60s) AND period band (minutes..hours..@daily) on the SAME fabric -- perfectly aligned to the Windows wall
clock, and NEVER blocking on any job. It replaces the proliferation of one-OS-scheduled-task-per-cadence (which
Win11 24H2 won't even let us grow) with a single 1x pythonw daemon.

HOW IT MEETS THE FOUR HARD REQUIREMENTS:
  1. CLOCK-ALIGNED: sleeps to the next wall-clock boundary (next = (now//tick + 1)*tick), never sleep(interval),
     so zero drift. Due = floor(now/C) != floor(last/C): a pure function of the wall clock, identical across
     restarts, and all jobs of cadence C fire on the SAME boundary grid (:00/:05/:10...).
  2. ALWAYS-ON + ULTRALIGHT: one process, sleeps between ticks (idle CPU ~ 0). Adaptive tick = 1s only if a
     sub-minute (frequency) job exists, else 60s -- footprint scales to the finest real need.
  3. CONTENTION-FREE: never runs a job inline -- detached Popen, no wait, so a slow job can't delay the tick.
     Per-job stale-tolerant lock => a still-running job's next fire is SKIPPED (no pile-up). A concurrency cap
     prevents a same-boundary thundering herd. The job registry is READ-ONLY here (register-rider owns writes),
     so registering a job never contends with the daemon.
  4. PER-AGENT CADENCE, ONE REGISTRY: reads hosts.json["hosts"]["HubClock"]["riders"]; each carries its own
     cadence + gate. Hot-reload on mtime change (no restart to add/remove a job).

ZERO write contention by design: the daemon only READS hosts.json (mtime-gated) and only WRITES its own
hubclock-heartbeat.json. last_boundary is restored from that heartbeat on startup => a restart does NOT
re-fire an @daily/@weekly job whose boundary already passed today (interval jobs fire once on the next
bucket, harmless), and re-aligns to the clock instantly. A pid+freshness singleton lock prevents a 2nd
daemon from running while one is alive, yet still permits an intentional kill-and-restart.

CITE: 50-techniques/auto-effect-doctrine.md, 50-techniques/piggyback-timer-grade-execution.md,
       50-techniques/zero-foreground-execution.md (KB 2026.06.09-18)

usage:
  hubclock.py run        # the daemon loop. Run hidden via a Startup .vbs ONCE the operator authorizes (Phase 1).
  hubclock.py once       # do exactly one clock-aligned tick now, dispatch what's due, exit (test / cron-fallback)
  hubclock.py tick-test  # DRY: print which jobs WOULD dispatch at the current boundary; dispatch nothing
  hubclock.py status     # print the heartbeat + each job's cadence / next-due
"""
import os
import re
import sys
import json
import math
import time
import subprocess
import shlex
import shutil
import datetime

HUB = os.environ.get("AI_WORKSPACE", r"C:\ai_workspace")
REG = os.path.join(HUB, "_registry", "hosts.json")
BEAT = os.path.join(HUB, "_registry", "hubclock-heartbeat.json")
RESULTS = os.path.join(HUB, "_registry", "hubclock-rider-results.json")
RESULTS_SCHEMA = 1
RESULTS_RING = 5                    # per-rider recent completions kept
RESULTS_RETENTION_S = 14 * 86400    # keep a de-registered rider this long after its last run
POLICY = os.path.join(HUB, "_registry", "hubclock-policy.json")   # {"stagger": bool}; missing file = all off
PROTECTED_PRIORITY = 95             # the operator's must-not-stop riders and their liveness guards
DRIVE_STREAK = 3                    # FAMES DRIVE: three stagnant attempts end in a handoff, not silent retries
BACKOFF_EVERY = 4                   # a failing non-protected interval rider then fires on every 4th boundary
STAGGER_MAX_MIN = 15                # a staggered rider fires at most this many minutes after its nominal boundary
LOCKDIR = os.path.join(HUB, "_temp")
HOST = "HubClock"
MIN_TICK, MAX_TICK = 1, 60          # base-tick floor/ceiling (seconds)
# same-boundary herd guard: at most N detached dispatches in flight.
# 2026-07-18 (not this audit): raised 6 -> 8 because late riders (tray-ensure/policy) were starved.
MAX_CONCURRENT = 8
DEFAULT_MAX_RUNTIME = 600           # a lock older than this is considered stale (the job died)
LOCAL_COMPUTE = os.path.join(HUB, "_registry", "fames-local-compute.json")
_LOCAL_CAP_CACHE = {"mtime": None, "value": MAX_CONCURRENT}
# Per-run telemetry (operator 2026-10-28: HubClock 可視化 + f1s 自適應排程). One JSON line per completed run; the board
# (hubclock_board.py) and the learner (hubclock_learn.py) read this exact schema -- add keys only with a schema bump.
RUNS_LEDGER = os.path.join(HUB, "_registry", "hubclock-runs.jsonl")
RUNS_LEDGER_MAX = 20 * 1024 * 1024  # rotate to .1 past this size
RUNS_SCHEMA = 1
LOAD_GUARD = os.path.join(HUB, "ai_darkhero", "tray", "state", "load_guard.json")  # rewritten every ~2 s
LOAD_GUARD_STALE_S = 120            # an older sample says nothing about this run -> null, not a stale number
CTX_KEYS = ("cpu_w", "a770_w", "combined_w", "other_cpu_pct")
METER_KEYS = ("cpu_tree_s", "peak_mb", "io_read_mb", "io_write_mb", "procs")
_CTX_CACHE = {"key": None, "value": None}
_JOBMETER = {"tried": False, "mod": None}
# HubClock v2 adaptive scheduling (operator 2026-10-28): the learner (hubclock_learn.py) writes a per-rider proposal
# into POLICY; the `adaptive` block there switches each part on. Missing block or enabled != true = the v1 scheduler.
ADAPTIVE_FLAGS = ("fast_reap", "offsets", "backoff", "holds", "class_caps")
CLASS_CAPS_DEFAULT = {"heavy": 1, "medium": 3}
HOLD_A770_BUSY_W = 50.0             # learner default; load_guard's own a770 idle sample is ~38 W
HOLD_COMBINED_W_MAX = 250.0         # load_grant.BUDGET_W
HOLD_DAILY_MAX_S = 3600
POLL_S = 1                          # fast_reap poll period while a rider runs or waits
SCHED_EVENTS_RING = 60


def _iso_epoch(stamp):
    """Local-clock ISO string -> epoch, or None.

    Every stamp this parses was written by this same daemon with
    datetime.datetime.now(), so naive local time is the correct reading of it.
    """
    try:
        return datetime.datetime.fromisoformat(str(stamp)).timestamp()
    except (TypeError, ValueError):
        return None


def max_concurrent():
    """Hot-reload the FAMES host cap; retain the safe compiled fallback on drift."""
    try:
        mtime = os.path.getmtime(LOCAL_COMPUTE)
        if _LOCAL_CAP_CACHE["mtime"] != mtime:
            profile = json.load(open(LOCAL_COMPUTE, encoding="utf-8-sig"))
            value = int((profile.get("global_caps") or {}).get("hubclock_max_concurrent"))
            if not 1 <= value <= MAX_CONCURRENT:
                raise ValueError("HubClock cap outside 1..8")
            _LOCAL_CAP_CACHE.update(mtime=mtime, value=value)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        if _LOCAL_CAP_CACHE["mtime"] is None:
            _LOCAL_CAP_CACHE["value"] = MAX_CONCURRENT
    return int(_LOCAL_CAP_CACHE["value"])


# --------------------------------------------------------------------------- cadence
_DOW = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _parse_days(sel):
    """Day selector -> a frozenset of weekday ints (Mon=0..Sun=6), or None for 'every day'. Accepts a
    comma-list of: single days (mon..sun), ranges (mon-fri), and the keywords weekday/weekend/daily.
    Returns False on an unrecognised token so the caller can reject the whole cadence."""
    if not sel:
        return None
    days = set()
    for tok in sel.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok in ("weekday", "wd"):
            days |= {0, 1, 2, 3, 4}
        elif tok in ("weekend", "we"):
            days |= {5, 6}
        elif tok == "daily":
            return None                                    # whole week == no filter
        elif "-" in tok:
            a, b = tok.split("-", 1)
            if a not in _DOW or b not in _DOW:
                return False
            i, j = _DOW[a], _DOW[b]
            days |= set(range(i, j + 1) if i <= j else list(range(i, 7)) + list(range(0, j + 1)))
        elif tok in _DOW:
            days.add(_DOW[tok])
        else:
            return False
    return frozenset(days) if days else None


def parse_cadence(c):
    """'30s'/'5m'/'2h'/'1d' -> ('interval', seconds).
    '@HH:MM[:SS]' -> ('daily', sec_of_day, None).
    '@<days>HH:MM[:SS]' -> ('daily', sec_of_day, frozenset_of_weekdays); <days> is a selector such as
       @sat10:00, @weekday15:35, @mon-fri09:00, @mon,wed,fri07:30. None on bad input.
    The weekday filter lets a weekly/weekday job fire ONLY on matching days, so a heavy job no longer fires
    every day and self-gates to a no-op the rest of the week (KB 2026.06.09-18 audit fix E)."""
    c = (c or "").strip().lower()
    if not c:
        return None
    if c.startswith("@"):
        body = c[1:]
        i = 0
        while i < len(body) and not body[i].isdigit():
            i += 1
        sel, timestr = body[:i], body[i:]
        days = _parse_days(sel)
        if days is False:                                  # unrecognised day selector
            return None
        parts = timestr.split(":")
        try:
            h = int(parts[0]); m = int(parts[1]) if len(parts) > 1 else 0; s = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            return None
        return ("daily", h * 3600 + m * 60 + s, days)
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(c[-1])
    if mult is None:
        return None
    try:
        return ("interval", max(1, int(float(c[:-1]) * mult)))
    except ValueError:
        return None


def _interval_secs(job):
    p = parse_cadence(job.get("cadence"))
    return p[1] if p and p[0] == "interval" else None


# --------------------------------------------------------------------------- registry (READ-ONLY here)
class RegistryUnreadable(RuntimeError):
    """hosts.json is PRESENT but cannot be trusted (truncated, unparseable, wrong shape).

    Distinct from absent-on-purpose. The old code collapsed both into `return []`, which is the single most
    dangerous line this daemon could contain: a registry damaged mid-write turns the whole fleet fabric into
    an empty job list, the metronome keeps ticking and reporting alive:true with n_jobs:0, and nothing --
    no log, no heartbeat field, no exit code -- says the 65 armed riders just stopped."""


def load_jobs():
    """Riders for this host. [] iff the registry is genuinely absent; RegistryUnreadable if it is damaged."""
    try:
        raw = open(REG, encoding="utf-8-sig").read()
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RegistryUnreadable("cannot read %s: %s" % (REG, e))
    try:
        d = json.loads(raw)
    except ValueError as e:
        raise RegistryUnreadable("%s is not valid JSON: %s" % (REG, e))
    if not isinstance(d, dict) or not isinstance(d.get("hosts"), dict):
        raise RegistryUnreadable("%s has no hosts object" % REG)
    riders = (d.get("hosts", {}).get(HOST, {}) or {}).get("riders", []) or []
    return [j for j in riders if _job_enabled(j)]


def _job_enabled(job):
    """False only for an EXPLICIT off switch; a rider without the key stays armed.

    Until 2026-09-22 nothing here read `enabled`, so setting it to false was a silent
    no-op and the only way to stop a rider was to delete its registry entry -- which
    the standing rules reserve for the operator, so retired riders accumulated instead
    (portal-ensure kept firing 288x/day for 78 days after its own module was reduced to
    a stub that prints "RETIRED"). Honouring the flag here, at the single point where
    riders enter the daemon, makes retirement reversible and keeps a disabled rider out
    of the due test, the dispatch race and the heartbeat alike. Default-on is deliberate:
    a typo in the key name must not disarm the fleet.
    """
    flag = job.get("enabled", True)
    if isinstance(flag, str):
        return flag.strip().lower() not in ("false", "0", "no", "off")
    return bool(flag)


def _job_priority(job):
    """Optional stable dispatch priority; malformed legacy values remain priority zero."""
    try:
        return int(job.get("priority") or 0)
    except (TypeError, ValueError):
        return 0


def base_tick(jobs):
    """1s only if a sub-minute interval job exists; else 60s. Daily/period jobs don't force a fast tick."""
    for j in jobs:
        s = _interval_secs(j)
        if s is not None and s < 60:
            return MIN_TICK
    return MAX_TICK


def is_due(job, now, last_boundary):
    """Clock-aligned. interval C: a new floor(now/C) boundary since last. daily: crossed today's wall-time
    AND (if the cadence carries a weekday filter) today is a matching weekday."""
    p = parse_cadence(job.get("cadence"))
    if not p:
        return False
    if p[0] == "interval":
        C = p[1]
        cur = int((now - (job.get("_offset_s") or 0)) // C)
        return last_boundary is None or cur != last_boundary
    # daily (optionally weekday-filtered)
    lt = time.localtime(now)
    target = p[1]
    days = p[2] if len(p) > 2 else None
    if days is not None and lt.tm_wday not in days:
        return False
    sec_of_day = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
    today = time.strftime("%Y-%m-%d", lt)
    return sec_of_day >= target and last_boundary != today


def boundary_key(job, now):
    """The value to store as last_boundary after dispatch (interval -> bucket index; daily -> date string)."""
    p = parse_cadence(job.get("cadence"))
    if p and p[0] == "interval":
        return int((now - (job.get("_offset_s") or 0)) // p[1])
    return time.strftime("%Y-%m-%d", time.localtime(now))


def boundary_start(job, now):
    """Epoch of the boundary that made `job` due at `now`, so dispatch delay = now - this (None if unknown)."""
    p = parse_cadence(job.get("cadence"))
    if not p:
        return None
    if p[0] == "interval":
        off = job.get("_offset_s") or 0
        return int((now - off) // p[1]) * p[1] + off
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) + p[1]


def compute_offsets(jobs):
    """Stable minute offsets that spread whole-minute interval riders over the clock.

    On 2026-10-05, 47 riders fell due at minute 0 against a cap of 8. Riders are placed greedily -- priority
    first, then shorter period, then id -- each at the offset (0 .. min(period, STAGGER_MAX_MIN) - 1 minutes)
    whose busiest minute is least loaded, so the first protected rider keeps its boundary. A pure function of
    the registry: every restart computes the same offsets. Returns {rider id: offset seconds}.
    """
    periods = {}
    for j in jobs:
        s = _interval_secs(j)
        if j.get("id") and s and s >= 120 and s % 60 == 0:
            periods[j["id"]] = s // 60
    if not periods:
        return {}
    hyper = 1
    for m in sorted(set(periods.values())):
        hyper = min(1440, hyper * m // math.gcd(hyper, m))
    load = [0] * hyper
    out = {}
    for j in sorted((j for j in jobs if j.get("id") in periods),
                    key=lambda j: (-_job_priority(j), periods[j["id"]], j["id"])):
        period = periods[j["id"]]
        best = None
        for k in range(min(period, STAGGER_MAX_MIN)):
            mins = [(k + i * period) % hyper for i in range(max(1, hyper // period))]
            score = (max(load[m] for m in mins), sum(load[m] for m in mins), k)
            if best is None or score < best[0]:
                best = (score, k, mins)
        for m in best[2]:
            load[m] += 1
        out[j["id"]] = best[1] * 60
    return out


def load_policy():
    try:
        with open(POLICY, encoding="utf-8-sig") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _int_in(value, lo, hi):
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and lo <= value <= hi else None


def parse_adaptive(doc):
    """hubclock-policy.json -> (flags, plan).

    flags is {} unless `adaptive.enabled` is literally true; then each of ADAPTIVE_FLAGS is on only when it is
    literally true too. plan = {"caps": {class: n}, "riders": {id: {...}}} from the learner's `proposal` (+ its
    `profiles` for load_grant self-gating). Anything malformed is dropped per field, never guessed."""
    if not isinstance(doc, dict):
        return {}, {}
    block = doc.get("adaptive")
    if not isinstance(block, dict) or block.get("enabled") is not True:
        return {}, {}
    flags = {k: block.get(k) is True for k in ADAPTIVE_FLAGS}
    prop = doc.get("proposal") if isinstance(doc.get("proposal"), dict) else {}
    profiles = doc.get("profiles") if isinstance(doc.get("profiles"), dict) else {}
    caps = dict(CLASS_CAPS_DEFAULT)
    for cls, value in (prop.get("concurrency_caps") or {}).items() if isinstance(prop.get("concurrency_caps"),
                                                                                    dict) else ():
        if cls in caps and _int_in(value, 1, MAX_CONCURRENT):
            caps[cls] = value
    glob = prop.get("hold_thresholds") if isinstance(prop.get("hold_thresholds"), dict) else {}
    riders = {}
    for jid, r in (prop.get("riders") or {}).items() if isinstance(prop.get("riders"), dict) else ():
        if not isinstance(r, dict):
            continue
        holds = r.get("holds") if isinstance(r.get("holds"), dict) else {}
        grant = (profiles.get(jid) or {}).get("load_grant") if isinstance(profiles.get(jid), dict) else None
        cls = r.get("concurrency_class") or r.get("class")
        riders[jid] = {
            "offset_s": _int_in(r.get("phase_offset_s"), 0, 10 ** 7),
            "k": _int_in((r.get("backoff") or {}).get("multiplier") if isinstance(r.get("backoff"), dict) else None,
                         1, 4) or 1,
            "class": cls if cls in ("heavy", "medium", "light") else None,
            "protected": r.get("protected") is True,
            "rise_w": _num((r.get("compute") or {}).get("est_rise_w") if isinstance(r.get("compute"), dict)
                           else None) or 0.0,
            "self_gated": bool(holds.get("self_gated")) or bool(isinstance(grant, dict) and grant.get("owners")),
            "a770_busy_w": _num(holds.get("a770_busy_w")) or _num(glob.get("a770_busy_w")) or HOLD_A770_BUSY_W,
            "combined_w_max": (_num(holds.get("combined_w_max")) or _num(glob.get("combined_w_max"))
                               or HOLD_COMBINED_W_MAX),
            "max_hold_s": _num(holds.get("max_hold_s")),
        }
    return flags, {"caps": caps, "riders": riders}


def _open_handoff(inbox_root, owner, sender):
    """Id of an unacked message from `sender` still in `owner`'s inbox, else None (acking deletes the file)."""
    import glob as _glob
    for path in sorted(_glob.glob(os.path.join(inbox_root, owner, "*.json")), reverse=True):
        try:
            with open(path, encoding="utf-8") as fh:
                msg = json.load(fh)
        except (OSError, ValueError):
            continue
        if msg.get("from") == sender:
            return msg.get("id") or os.path.splitext(os.path.basename(path))[0]
    return None


def _owner_of(job):
    """The seat whose files a rider runs; hub engines and anything unmatched belong to the curator."""
    for m in re.finditer(r"[\\/](ai_[A-Za-z0-9_]+|fracdigi|jci_taipei|sdnext_a770)(?=[\\/])", job.get("command") or ""):
        if m.group(1).lower() != "ai_workspace":
            return m.group(1)
    return "ai_darkhero"


# --------------------------------------------------------------------------- dispatch (detached, hidden, locked)
def _lock_path(jid):
    return os.path.join(LOCKDIR, "hubclock-%s.lock" % jid)


def _boot_epoch():
    """Wall-clock time of the last boot, or None. A rider lock older than this was left behind by a reset."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetTickCount64.restype = ctypes.c_ulonglong
        return time.time() - k.GetTickCount64() / 1000.0
    except Exception:  # noqa: BLE001
        return None


def _lock_owner(path):
    """The rider pid a lock records (`<epoch> <pid>`), or None for a lock written before 2026-10-06."""
    try:
        parts = open(path, encoding="utf-8").read().split()
        return int(parts[1]) if len(parts) > 1 else None
    except (OSError, ValueError):
        return None


def _locked(jid, max_runtime):
    """A rider lock holds while it is younger than max_runtime -- unless it was written before the last boot or
    names a rider process that has exited. Age used to be the only test, so the lock the 2026-10-05 17:2x reset
    left behind kept metadata-acq-tick (max_runtime 21600 s) from firing again until 23:10."""
    p = _lock_path(jid)
    try:
        if not os.path.exists(p):
            return False
        written = os.path.getmtime(p)
    except OSError:
        return False
    if time.time() - written >= max_runtime:
        return False
    boot = _boot_epoch()
    if boot is not None and written < boot:
        return False
    owner = _lock_owner(p)
    return owner is None or _pid_alive(owner)


def _proc_times(proc):
    """(wall seconds from creation to exit, user + kernel CPU seconds) of a finished rider's own process -- not its
    children -- or (None, None). Reap runs once per tick, so the reap time alone would round every run up to 60 s."""
    if os.name != "nt":
        return None, None
    try:
        import ctypes
        from ctypes import wintypes
        times = [wintypes.FILETIME() for _ in range(4)]
        if not ctypes.windll.kernel32.GetProcessTimes(wintypes.HANDLE(int(proc._handle)),
                                                      *[ctypes.byref(t) for t in times]):
            return None, None
        created, exited, kernel, user = (((t.dwHighDateTime << 32) | t.dwLowDateTime) / 1e7 for t in times)
        return (round(exited - created, 1) if exited > created else None), round(kernel + user, 3)
    except Exception:  # noqa: BLE001
        return None, None


# --------------------------------------------------------------------------- per-run telemetry (fail-open)
def _jobmeter():
    """hubclock_jobmeter (Windows job-object accounting of the rider's whole process tree), or None."""
    if not _JOBMETER["tried"]:
        _JOBMETER["tried"] = True
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            if here not in sys.path:
                sys.path.insert(0, here)
            import hubclock_jobmeter
            _JOBMETER["mod"] = hubclock_jobmeter
        except Exception:  # noqa: BLE001 -- a missing meter means no tree telemetry, never no dispatch
            _JOBMETER["mod"] = None
    return _JOBMETER["mod"]


def _attach_meter(proc):
    """Called right after Popen: the rider and everything it starts from now on are accounted in one job."""
    try:
        meter = _jobmeter()
        if meter is not None:
            proc.hubclock_meter = meter.open_meter(proc)
    except Exception:  # noqa: BLE001
        pass


def _collect_meter(proc):
    """Read and close the rider's job: {cpu_tree_s, peak_mb, io_read_mb, io_write_mb, procs}, or {}."""
    handle = getattr(proc, "hubclock_meter", None)
    if not handle:
        return {}
    try:
        meter = _jobmeter()
        if meter is None:
            return {}
        try:
            data = meter.read_meter(handle) or {}
        finally:
            meter.close_meter(handle)
            proc.hubclock_meter = None
        return {k: data[k] for k in METER_KEYS if data.get(k) is not None}
    except Exception:  # noqa: BLE001
        return {}


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _machine_ctx(now=None):
    """Machine load at this instant from load_guard.json: {cpu_w, a770_w, combined_w, other_cpu_pct}; each key is
    null when the file is missing, unreadable or older than LOAD_GUARD_STALE_S. Re-parsed only when it changed."""
    out = dict.fromkeys(CTX_KEYS)
    try:
        st = os.stat(LOAD_GUARD)
        if (now if now is not None else time.time()) - st.st_mtime > LOAD_GUARD_STALE_S:
            return out
        key = (st.st_mtime_ns, st.st_size)
        if _CTX_CACHE["key"] != key:
            with open(LOAD_GUARD, encoding="utf-8-sig") as fh:
                doc = json.load(fh) or {}
            sample = doc.get("sample") or {}
            yld = doc.get("yield") or {}
            _CTX_CACHE["value"] = {"cpu_w": _num(sample.get("cpu_w")), "a770_w": _num(sample.get("a770_w")),
                                   "combined_w": _num(doc.get("combined_w")),
                                   "other_cpu_pct": _num(yld.get("other_cpu_pct"))}
            _CTX_CACHE["key"] = key
        out.update(_CTX_CACHE["value"] or {})
    except Exception:  # noqa: BLE001
        pass
    return out


def _append_run(jid, rc, finished, info, cadence):
    """One JSON line per completed run into RUNS_LEDGER (schema RUNS_SCHEMA); rotate to .1 past RUNS_LEDGER_MAX.
    A failed write loses this line only -- it never reaches dispatch, reap or the results file."""
    try:
        info = info or {}
        line = {"id": jid, "dispatched": info.get("dispatched"), "finished": finished, "rc": rc,
                "delay_s": info.get("delay_s"), "duration_s": info.get("duration_s"), "cpu_s": info.get("cpu_s")}
        line.update({k: info.get(k) for k in METER_KEYS})
        line["ctx_start"] = info.get("ctx_start") or dict.fromkeys(CTX_KEYS)
        line["ctx_end"] = _machine_ctx()
        line["cadence"] = cadence
        line["schema"] = RUNS_SCHEMA
        line["sched"] = info.get("sched")   # additive (v2): the scheduler decisions behind this run, or null
        data = (json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            if os.path.getsize(RUNS_LEDGER) + len(data) > RUNS_LEDGER_MAX:
                os.replace(RUNS_LEDGER, RUNS_LEDGER + ".1")
        except OSError:
            pass  # no ledger yet, or a reader holds it open: rotate on a later run
        with open(RUNS_LEDGER, "ab") as fh:
            fh.write(data)
    except Exception:  # noqa: BLE001 -- telemetry must never stop the clock
        pass


def _parse_rider_argv(cmd):
    """Return (argv, use_shell). shell=False avoids cmd.exe flash on pythonw riders.

    Measured 2026-08-10 over the live 65-rider registry: 4 riders reached the shell=True fallback, all of the
    form `wscript.exe <absolute .vbs>` -- rejected only because the launcher is a bare name, not because the
    command needed a shell. Resolving that name through PATH here is strictly safer than handing the whole
    string to cmd.exe: it is the same PATH lookup cmd.exe would do, minus cmd.exe's parsing of & | > and
    %VAR% inside the registry string. shell=True now survives only for commands nothing can resolve."""
    raw = (cmd or "").strip()
    if not raw:
        return None, True
    try:
        parts = shlex.split(raw, posix=False)
    except ValueError:
        return None, True
    if not parts:
        return None, True
    # posix=False keeps the quotes; argv items go to CreateProcess, which re-quotes, so a surviving quote is a
    # literal (altos 2026-10-15: a quoted script path made every rider exit rc=2). Unwrap only whole-token quotes.
    parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]
    exe = parts[0].strip('"')
    if os.path.isabs(exe):
        # argv[0] must be the bare path -- a surviving quote is a literal character to CreateProcess.
        return ([exe] + parts[1:], False) if os.path.isfile(exe) else (None, True)
    found = shutil.which(exe)
    if found:
        return [found] + parts[1:], False
    return None, True


def _log_refusal(jid, cmd, rule, viols):
    """One refusal = one stderr line + one jsonl record. stderr goes to a hidden window, so the file is the
    only durable evidence; a fail-CLOSED gate that leaves no trace is indistinguishable from a dead fleet."""
    sys.stderr.write("hubclock REFUSE %s: %s (%d violations)\n" % (jid, rule, len(viols)))
    try:
        logp = os.path.join(HUB, "_logs", "fleet", "hubclock-refused.jsonl")
        os.makedirs(os.path.dirname(logp), exist_ok=True)
        open(logp, "a", encoding="utf-8").write(json.dumps(
            {"at": datetime.datetime.now().isoformat(timespec="seconds"),
             "id": jid, "command": cmd, "rule": rule, "violations": viols}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def dispatch(job):
    """Fire-and-forget: spawn the command with NO console window, do NOT wait. Returns the Popen (or None)."""
    jid = job.get("id", "?")
    cmd = job.get("command", "")
    # Zero-foreground lint gate: refuse dispatch (not just report) on violation.
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from zero_foreground_lint import lint_hubclock_job  # noqa: WPS433
        ok, viols = lint_hubclock_job(job)
    except Exception as e:
        # FAIL CLOSED. The old branch here wrote "(proceeding)" and dispatched anyway -- so a linter that was
        # missing, renamed or raising turned the zero-foreground contract off for EVERY rider at once, in the
        # exact silence the contract exists to prevent. A lint exception is not a clean bill of health: it is
        # "unknown", and UNKNOWN is not clear. The refusal is logged like any other so the state is diagnosable
        # instead of merely absent -- if this ever fires fleet-wide, hubclock-refused.jsonl says why.
        _log_refusal(jid, cmd, "lint_error", [{"rule": "lint_error", "detail": repr(e)}])
        return None
    if not ok:
        _log_refusal(jid, cmd, (viols[0].get("rule", "?") if viols else "?"), viols)
        return None
    argv, use_shell = _parse_rider_argv(cmd)
    flags, si = 0, None
    if os.name == "nt":
        # Riders inherit this process error mode: a rider that dies with an unhandled native exception ends with
        # its NTSTATUS exit code instead of a modal "python.exe - 應用程式錯誤" box that steals focus and waits
        # for a click (operator zero-popup rule; measured 2026-09-15..17: pythonw crash dialogs 4x/day from a
        # 6h rider plus sim_tick children).  SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX.
        try:
            import ctypes
            ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
        except Exception:  # noqa: BLE001
            pass
        flags = 0x08000000  # CREATE_NO_WINDOW
        flags |= 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
    try:
        open(_lock_path(jid), "w").write(str(int(time.time())))
        # stdout+stderr go to a per-rider file, rewritten each run, so a failed run's last lines survive for
        # _stderr_tail(); with DEVNULL the 2026-10-16 rider audit could not root-cause a single rc 1.
        err = _open_stderr(jid)
        kw = dict(creationflags=flags, startupinfo=si, stdout=err or subprocess.DEVNULL,
                  stderr=subprocess.STDOUT if err else subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        try:
            if use_shell or argv is None:
                proc = subprocess.Popen(cmd, shell=True, **kw)
            else:
                proc = subprocess.Popen(argv, shell=False, **kw)
            _attach_meter(proc)  # before the rider can start children; fail-open, counts only
        finally:
            if err:
                err.close()  # the child holds its own handle
        pid = getattr(proc, "pid", None)
        if isinstance(pid, int):  # record the owner, so a successor can tell a live rider from one a reset killed
            try:
                open(_lock_path(jid), "w").write("%d %d" % (int(time.time()), pid))
            except OSError:
                pass
        return proc
    except Exception as e:
        sys.stderr.write("hubclock dispatch error %s: %s\n" % (jid, e))
        return None


# Failure classification before a DRIVE handoff (HubClock._classify, F1S 當下閉環 item 3).
STALL_RIDERS = 3
STALL_WINDOW_S = 1800
PINNED_RIDERS = {"fames-converge", "fleet-skill-pulse"}
CURATOR_OWNER = "ai_darkhero"

STDERR_DIR = os.path.join(LOCKDIR, "hubclock-stderr")


def _stderr_path(jid):
    return os.path.join(STDERR_DIR, "%s.err" % re.sub(r"[^A-Za-z0-9_.-]", "_", str(jid)))


def _open_stderr(jid):
    try:
        os.makedirs(STDERR_DIR, exist_ok=True)
        return open(_stderr_path(jid), "wb")
    except OSError:
        return None


def _stderr_tail(jid, limit=600):
    """Last `limit` characters of the rider's latest stdout+stderr, '' when it wrote none."""
    try:
        with open(_stderr_path(jid), "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - limit * 4))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return " ".join(text.split())[-limit:]


def _release(jid):
    try:
        os.remove(_lock_path(jid))
    except OSError:
        pass


SINGLETON = os.path.join(LOCKDIR, "hubclock-daemon.lock")
# The OS-enforced half of the singleton: a byte-range lock the kernel drops when its holder exits, whatever
# the holder's session or token. SINGLETON above stays the pid file that the tray's ensure reads.
DAEMON_FLOCK = os.path.join(LOCKDIR, "hubclock-daemon.flock")
# An interactive-session ensure writes {"pid": N} here to ask daemon N to step down (see _yield_requested).
YIELD_REQUEST = os.path.join(LOCKDIR, "hubclock-yield.json")
_daemon_flock_fd = None   # the open descriptor IS the lock; held for the life of the daemon


def _pid_alive(pid):
    """True iff a process with this pid is currently running (Windows: OpenProcess + STILL_ACTIVE)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_ACCESS_DENIED = 5
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            # Access denied means the pid IS running, under a token this process may not open. Until
            # 2026-09-29 that read as dead: the boot task's S4U daemon (session 0) looked dead to the one the
            # logon started, which then took the pid file over while both kept running. A missing process
            # fails with ERROR_INVALID_PARAMETER instead.
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259      # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _hold_daemon_flock():
    """Take the OS-enforced daemon lock and keep it for the life of this process.

    True = held (no other process can take it until this one exits), False = another live daemon holds it,
    None = the lock file cannot be opened (UNKNOWN; the caller falls back to the pid file alone).

    Why: from 2026-09-26 14:03 to 2026-09-29 02:16 several daemons ran at once and every rider fired up to 14
    times per boundary. The boot task's S4U daemon could not be opened from the logon session, so the pid file
    check called it dead; the logon-started daemon took the pid file over, both kept ticking, and each later
    ensure that read their pid files mid-race started one more. A byte-range lock needs no right to open the
    other process, is released by the kernel when its holder exits, and descriptors from os.open are not
    inherited by riders (PEP 446), so no child can keep it alive after the daemon is gone."""
    global _daemon_flock_fd
    if _daemon_flock_fd is not None:
        return True
    try:
        os.makedirs(LOCKDIR, exist_ok=True)
        fd = os.open(DAEMON_FLOCK, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    _daemon_flock_fd = fd
    return True


def _release_daemon_flock():
    global _daemon_flock_fd
    if _daemon_flock_fd is None:
        return
    try:
        os.close(_daemon_flock_fd)     # closing the descriptor drops the lock
    except OSError:
        pass
    _daemon_flock_fd = None


def _yield_requested(started):
    """True when an ensure asked THIS daemon, by pid, to step down after it started.

    The boot task starts HubClock under an S4U token in session 0 so riders run before anyone logs in
    (ai_darkhero/tray/scripts/hubclock_boot_ensure.py). After logon the tray's ensure can neither inspect nor
    stop that process, so it writes this request naming the pid; the daemon exits at its next wake-up (the
    kernel drops its lock) and the ensure's next pass starts the logon session's daemon in its place.
    A request written before this daemon started names an earlier process whose pid was reused: ignored."""
    try:
        with open(YIELD_REQUEST, encoding="utf-8") as fh:
            req = json.load(fh)
    except (OSError, ValueError):
        return False
    if not isinstance(req, dict) or str(req.get("pid")) != str(os.getpid()):
        return False
    try:
        return float(req.get("requested_at")) > started
    except (TypeError, ValueError):
        return False


def _acquire_singleton():
    """Refuse to start a 2nd daemon while one is genuinely alive. The lock carries the holder's pid and is
    mtime-refreshed every tick: a holder is 'live' only if its pid is still running AND it ticked recently
    (<180s). This both prevents an accidental double-daemon (logon autostart firing while a watchdog-spawned
    one runs) AND permits an intentional restart (kill old -> its pid is dead -> the new one takes over).
    The per-job locks remain the final backstop against double-dispatch. KB 2026.06.09-18 audit fix F.

    Since 2026-09-29 the OS-enforced lock (_hold_daemon_flock) is checked first, so a live daemon this process
    cannot open still blocks it. The pid file check stays: it is the fallback when the lock file cannot be
    opened, and it still respects a daemon started before the OS lock existed (which holds none)."""
    if _hold_daemon_flock() is False:
        return False
    try:
        if os.path.exists(SINGLETON):
            age = time.time() - os.path.getmtime(SINGLETON)
            pid = open(SINGLETON, encoding="utf-8").read().strip() or "0"
            # A file naming this very process is a predecessor whose pid was reused (a handover restarts the
            # daemon inside the 180 s window), not a rival.
            if age < 180 and pid != str(os.getpid()) and _pid_alive(pid):
                _release_daemon_flock()
                return False
    except OSError:
        pass
    try:
        open(SINGLETON, "w", encoding="utf-8").write(str(os.getpid()))
    except OSError:
        pass
    return True


def _refresh_singleton():
    try:
        open(SINGLETON, "w", encoding="utf-8").write(str(os.getpid()))
    except OSError:
        pass


# --------------------------------------------------------------------------- the daemon
class HubClock:
    def __init__(self):
        self.last = {}        # job id -> last_boundary (in memory; restart re-fires once, harmless)
        self.running = {}     # job id -> (Popen, started_epoch)
        self.started = time.time()
        self.reg_mtime = 0
        self.jobs = []
        # Per-job aging debt.  A due rider that loses the global concurrency
        # race gains one point; dispatched riders reset to zero.  This turns
        # the old fixed registry-order scan into a bounded round-robin while
        # retaining priority as the tie-breaker for newly-due work.
        self.deferred = {}
        self.fires = []       # recent fires for the heartbeat
        self.reg_error = None  # last RegistryUnreadable text, surfaced in the heartbeat (None = registry healthy)
        # Per-rider DURABLE outcomes. recent_fires above is a 30-slot ring SHARED by every
        # rider, so with 67 riders most return codes rotate out within half a minute: on
        # 2026-09-22 that left 47 of 67 riders' rc unprovable, which is not the same thing
        # as passing. This map holds one row per rider and is written next to the heartbeat,
        # so an outcome survives both rotation and a daemon restart. It is the daemon's OWN
        # state -- hosts.json stays read-only, so this adds no write contention.
        self.results = {}
        self.results_dirty = False
        self.dispatch_info = {}  # job id -> {"dispatched", "delay_s"} for the run in flight (results v2)
        self.policy_mtime = None
        self.stagger = False
        # v2 adaptive state (all inert while self.adaptive == {}).
        self.adaptive = {}        # ADAPTIVE_FLAGS -> bool, only when adaptive.enabled is true
        self.plan = {}            # parse_adaptive() plan: caps + per-rider learner values
        self.queued = set()       # due riders the last round could not start (cap / class cap / hold)
        self.refused = {}         # job id -> boundary key of a refused dispatch: polls do not retry it
        self.hold_since = {}      # job id -> epoch its current hold began
        self.hold_long = set()    # job ids whose current hold already logged held_too_long
        self.skip_seen = {}       # job id -> boundary key already counted as a backoff skip
        self.pending = {}         # job id -> decision counts since its last dispatch (-> the run's `sched`)
        self.sched_counts = {}    # decision -> count since daemon start (heartbeat)
        self.sched_events = []    # recent decisions, oldest first (heartbeat)
        self.offsets_in_use = {}  # job id -> offset its stored last_boundary was computed with
        self.offset_src = {}      # job id -> "learner" | "stagger" | None
        self.last_dispatch = {}   # job id -> epoch of its last dispatch (phase re-anchoring)
        self.not_before = {}      # job id -> epoch: a re-anchored rider waits for this boundary

    def _reload_policy(self):
        try:
            m = os.path.getmtime(POLICY)
        except OSError:
            m = 0
        if m == self.policy_mtime:
            return
        self.policy_mtime = m
        doc = load_policy()
        stagger = bool(doc.get("stagger"))
        adaptive, plan = parse_adaptive(doc)
        before = (self.stagger, self.adaptive.get("offsets"), self._learned_offsets())
        self.adaptive, self.plan = adaptive, plan
        self.stagger = stagger
        if (stagger, self.adaptive.get("offsets"), self._learned_offsets()) != before:
            self._apply_offsets()

    def _rider(self, jid):
        """The learner's plan for one rider ({} when adaptive is off or the learner does not know it)."""
        return (self.plan.get("riders") or {}).get(jid) or {}

    def _learned_offsets(self):
        if not self.adaptive.get("offsets"):
            return {}
        return {jid: r["offset_s"] for jid, r in (self.plan.get("riders") or {}).items()
                if r.get("offset_s") is not None}

    def _protected(self, job):
        return _job_priority(job) >= PROTECTED_PRIORITY or self._rider(job.get("id")).get("protected") is True

    def _apply_offsets(self):
        offsets = compute_offsets(self.jobs) if self.stagger else {}
        learned = self._learned_offsets()
        for job in self.jobs:
            jid = job.get("id")
            period = _interval_secs(job)
            off, src = offsets.get(jid) or 0, ("stagger" if offsets.get(jid) else None)
            if jid in learned and period and learned[jid] < period:
                off, src = learned[jid], "learner"       # v2 offsets: the learner's phase, always < cadence
            if jid and period:
                old = self.offsets_in_use.get(jid)
                if old is not None and old != off and "learner" in (src, self.offset_src.get(jid)):
                    self._reanchor(jid, period, old, off)
                self.offsets_in_use[jid] = off
                self.offset_src[jid] = src
            if off:
                job["_offset_s"] = off
            else:
                job.pop("_offset_s", None)

    def _reanchor(self, jid, period, old, new):
        """Re-express a rider's last boundary in a new phase, so switching to (or away from) the learner's offsets
        neither re-fires every rider at once nor squeezes two runs into less than half a period.

        A new-phase boundary that already passed while the old phase still ruled is not run late at the reload: the
        learner retunes hourly, and every rider it moved would start at the same tick (2026-10-28 14:02:00, four at
        once, up to 236 s 'late'). Such a rider keeps the old boundary it was waiting for, one period after its last
        run; the new phase's next boundary is then at least half a period later (it is >= last + 1.5 periods)."""
        last = self.last.get(jid)
        if not isinstance(last, int) or isinstance(last, bool):
            return
        start_old = last * period + old
        fired = self.last_dispatch.get(jid)
        if fired is None or not start_old <= fired < start_old + period:
            fired = start_old
        key = int((fired - new) // period)            # the new-phase bucket that holds the last run
        self.last[jid] = key
        nxt = (key + 1) * period + new
        if nxt - fired < period / 2.0:
            nxt += period                             # too close to the last run: wait for the boundary after
        old_next = start_old + period                 # what the rider was waiting for under the old phase
        if nxt < time.time() < old_next:
            self.not_before[jid] = old_next
        elif nxt > (key + 1) * period + new:
            self.not_before[jid] = nxt
        else:
            self.not_before.pop(jid, None)

    def reload(self):
        self._reload_policy()
        try:
            m = os.path.getmtime(REG)
        except OSError:
            m = 0
        if m == self.reg_mtime:
            return
        try:
            jobs = load_jobs()
        except RegistryUnreadable as e:
            # KEEP the last known-good job list and do NOT adopt the new mtime: a damaged registry must not be
            # able to disarm the fleet, and the next tick has to retry (register-rider's os.replace means the
            # damage is most likely a reader catching a torn third-party write, i.e. transient).
            if self.reg_error != str(e):
                sys.stderr.write("hubclock REGISTRY UNREADABLE: %s -- keeping %d job(s) from the last good "
                                 "read\n" % (e, len(self.jobs)))
            self.reg_error = str(e)
            return
        self.reg_mtime = m
        self.reg_error = None
        # Stable sort preserves registry order among equal-priority legacy jobs,
        # while critical lightweight riders cannot be starved forever by the
        # global concurrency cap merely because they were registered later.
        self.jobs = sorted(jobs, key=_job_priority, reverse=True)
        self._apply_offsets()
        self.last = {j["id"]: self.last.get(j["id"]) for j in self.jobs if j.get("id")}
        self.deferred = {
            j["id"]: self.deferred.get(j["id"], 0)
            for j in self.jobs if j.get("id")
        }

    def reap(self):
        jobs_by_id = {job.get("id"): job for job in self.jobs}
        now = time.time()
        for jid in list(self.running):
            proc, started = self.running[jid]
            rc = proc.poll()
            max_runtime = int((jobs_by_id.get(jid) or {}).get("max_runtime") or DEFAULT_MAX_RUNTIME)
            if rc is None and now - started > max_runtime:
                # A stale lock was previously ignored whenever the daemon's
                # in-memory `running` entry survived, so one hung job could
                # occupy a global slot forever. Enforce the documented bound
                # and only release after the child is confirmed terminated.
                try:
                    proc.kill()
                    rc = proc.wait(timeout=10)
                except (OSError, subprocess.SubprocessError):
                    continue
                rc = 124
            if rc is not None:
                info = dict(self.dispatch_info.pop(jid, None) or {})
                wall, info["cpu_s"] = _proc_times(proc)
                info["duration_s"] = wall if wall is not None else round(now - started, 1)
                info.update(_collect_meter(proc))
                fired = self._record(jid, rc, info)
                self.running.pop(jid, None)
                _release(jid)
                _append_run(jid, rc, fired, info,
                            info.get("cadence") or (jobs_by_id.get(jid) or {}).get("cadence"))

    def _record(self, jid, rc, info=None):
        fired = datetime.datetime.now().isoformat(timespec="seconds")
        self.fires.append({"id": jid, "fired": fired, "rc": rc})
        self.fires = self.fires[-30:]
        self._record_result(jid, rc, fired, time.time(), info)
        return fired

    def _handoff(self, jid, row):
        """FAMES DRIVE: the third failure in a row ends in one handoff to the rider's owner, not silent retries."""
        job = next((j for j in self.jobs if j.get("id") == jid), {})
        owner = _owner_of(job)
        tail = ("It is protected, so it keeps its cadence." if _job_priority(job) >= PROTECTED_PRIORITY else
                "Until one run succeeds it fires on every %dth boundary only." % BACKOFF_EVERY)
        text = ("HubClock DRIVE handoff: rider `%s` failed %d runs in a row (last rc %s, finished %s; %s of %s runs "
                "failed in the results file). Fix it or retire it. %s"
                % (jid, row.get("consecutive_failures"), row.get("last_rc"), row.get("last_fired"),
                   row.get("failures"), row.get("runs"), tail))
        stderr = (row.get("last_failure") or {}).get("output_tail")
        if stderr:
            text += " Last output: " + stderr
        kind, sender, extra = self._classify(jid, row)
        if kind == "signal":
            return  # rc 75 = EX_TEMPFAIL, "not executed, prior work still active": by design, not a fault
        if extra:
            text = extra + " " + text
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import _bus
            # 2026-10-16: 110 handoffs for 19 riders piled up in the curator inbox (one rider sent 16), each a
            # repeat of an open one. While an unacked handoff from this rider is still in the owner's inbox,
            # point at it instead of sending another.
            inbox_root = getattr(_bus, "INBOX", None)
            canon = getattr(_bus, "_canon_to", lambda name: name)
            if kind != "rider":
                owner = CURATOR_OWNER  # a machine-wide incident has no single rider owner
            open_id = _open_handoff(inbox_root, canon(owner), sender) if inbox_root else None
            if open_id:
                row["last_handoff"] = {"to": owner, "id": open_id, "deduped": True, "kind": kind,
                                       "at": row.get("last_fired")}
                return
            row["last_handoff"] = {"to": owner, "id": _bus.send(owner, sender, text, kind="task"), "kind": kind,
                                   "at": row.get("last_fired")}
        except Exception as e:  # noqa: BLE001 -- a bus fault must never stop the clock
            row["last_handoff"] = {"to": owner, "error": repr(e)[:160], "at": row.get("last_fired")}

    def _classify(self, jid, row):
        """Classify a failure streak at the source (F1S 當下閉環 item 3, 2026-10-18) -> (kind, sender, extra text).

        signal       rc 75 (EX_TEMPFAIL): the rider declined to run because prior work is still active.
        stall        rc 124 while >= STALL_RIDERS other riders also timed out within STALL_WINDOW_S: the machine
                     stalled (2026-10-16 02:00-05:45, load_guard other_cpu 87.6%), one incident for all of them.
        pinned-drift fames-converge / fleet-skill-pulse red while a FAMES-release-pinned file differs from the
                     shipped runtime: one handoff naming the file and the ship command, shared by both riders.
        rider        anything else: the rider's own handoff, as before.
        """
        rc = row.get("last_rc")
        if rc == 75:
            return "signal", None, ""
        if rc == 124:
            peers = self._recent_timeouts(jid, row.get("last_fired_epoch"))
            if len(peers) >= STALL_RIDERS:
                return "stall", "hubclock-stall", (
                    "HubClock STALL incident: %d other riders also hit their runtime cap within %d min (%s). "
                    "Treat it as one machine-wide stall (check load_guard.log other_cpu_pct and the riders that "
                    "started together), not per-rider bugs." % (len(peers), STALL_WINDOW_S // 60, ", ".join(peers[:8])))
        if jid in PINNED_RIDERS:
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import pinned_drift
                rows = pinned_drift.drifted()
            except Exception:  # noqa: BLE001 -- the classifier must never stop the clock
                rows = []
            if rows:
                paths = [r["path"] for r in rows]
                return "pinned-drift", "hubclock-pinned-drift", (
                    "HubClock PINNED-DRIFT: FAMES-release-pinned file(s) %s differ from the shipped runtime, which is "
                    "why %s fail. Ship the edit from the session that made it, or here: %s"
                    % (", ".join(paths), " and ".join(sorted(PINNED_RIDERS)), pinned_drift.ship_command(paths)))
        return "rider", "hubclock-" + jid, ""

    def _recent_timeouts(self, jid, epoch):
        """Other riders whose recent results hold an rc 124 finished within STALL_WINDOW_S of `epoch`."""
        try:
            ref = float(epoch)
        except (TypeError, ValueError):
            return []
        out = []
        for other, row in self.results.items():
            if other == jid or not isinstance(row, dict):
                continue
            for item in row.get("recent") or []:
                if not isinstance(item, dict) or item.get("rc") != 124:
                    continue
                try:
                    when = datetime.datetime.fromisoformat(str(item.get("fired"))).timestamp()
                except ValueError:
                    continue
                if abs(ref - when) <= STALL_WINDOW_S:
                    out.append(other)
                    break
        return sorted(out)

    def _backed_off(self, job, now):
        """A non-protected interval rider in a failure streak fires on every BACKOFF_EVERY-th boundary only."""
        row = self.results.get(job.get("id")) or {}
        if int(row.get("consecutive_failures") or 0) < DRIVE_STREAK or _job_priority(job) >= PROTECTED_PRIORITY:
            return False
        p = parse_cadence(job.get("cadence"))
        return bool(p and p[0] == "interval" and boundary_key(job, now) % BACKOFF_EVERY != 0)

    def _record_result(self, jid, rc, fired, epoch, info=None, handoff=True):
        """Fold one observed completion into the rider's durable row.

        Only reap() reaches this, and only with an rc the OS actually returned, so a row
        here always means "this daemon watched this rider's child exit". Nothing writes a
        row at dispatch time: a started job is not a finished one, and a record that could
        not tell those apart would be exactly the false green this file is meant to remove.
        """
        row = self.results.get(jid)
        if not isinstance(row, dict):
            row = {"runs": 0, "failures": 0, "consecutive_failures": 0,
                   "last_failure": None, "recent": []}
        row["last_rc"] = rc
        row["last_fired"] = fired
        row["last_fired_epoch"] = round(epoch, 3)
        row["runs"] = int(row.get("runs") or 0) + 1
        # Results v2 (2026-10-06): `fired` is when the run FINISHED (reap time); dispatch time, the delay behind
        # its boundary, wall duration and the rider process's own CPU seconds make queueing and cost measurable.
        # 2026-10-28: + the job-object totals of the rider's whole process tree (hubclock_jobmeter). A run without a
        # meter omits them, and drops the previous run's last_* copies so last_* never mixes two runs.
        extra = {k: v for k, v in (info or {}).items()
                 if k in ("dispatched", "delay_s", "duration_s", "cpu_s") + METER_KEYS + ("sched",)}
        for key, value in extra.items():
            row["last_" + key] = value
        for key in METER_KEYS + ("sched",):
            if key not in extra:
                row.pop("last_" + key, None)
        if rc == 0:
            row["consecutive_failures"] = 0
            row.pop("last_handoff", None)  # the streak ended; the next one gets its own handoff
        else:
            row["failures"] = int(row.get("failures") or 0) + 1
            row["consecutive_failures"] = int(row.get("consecutive_failures") or 0) + 1
            row["last_failure"] = {"rc": rc, "fired": fired}
            stderr = _stderr_tail(jid)
            if stderr:
                row["last_failure"]["output_tail"] = stderr
        recent = [r for r in (row.get("recent") or []) if isinstance(r, dict)]
        recent.append({"rc": rc, "fired": fired, **extra})
        row["recent"] = recent[-RESULTS_RING:]
        self.results[jid] = row
        self.results_dirty = True
        # One handoff per streak, also for a streak older than this rule (it hands off at its next failure).
        if handoff and rc != 0 and row["consecutive_failures"] >= DRIVE_STREAK and "last_handoff" not in row:
            self._handoff(jid, row)

    def _load_results(self):
        """Read the durable rows, then backfill any rider that has none from the ring.

        The backfill invents nothing: recent_fires holds real completions this daemon
        observed and persisted, and on the first start after this feature ships it is the
        only surviving record of them. It fills ONLY riders with no durable row, so it can
        never overwrite a newer outcome with an older ring entry.
        """
        try:
            with open(RESULTS, encoding="utf-8-sig") as fh:
                rows = (json.load(fh) or {}).get("riders")
            if isinstance(rows, dict):
                self.results = {str(k): v for k, v in rows.items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            self.results = {}
        for jid, row in self.results.items():   # v2 phase re-anchoring needs each rider's last dispatch time
            epoch = _iso_epoch(row.get("last_dispatched"))
            if epoch is not None:
                self.last_dispatch[jid] = epoch
        try:
            with open(BEAT, encoding="utf-8-sig") as fh:
                fires = (json.load(fh) or {}).get("recent_fires") or []
        except (OSError, ValueError, AttributeError):
            return
        for fire in reversed(fires):          # ring is newest-first; replay oldest-first
            if not isinstance(fire, dict):
                continue
            jid = str(fire.get("id") or "")
            epoch = _iso_epoch(fire.get("fired"))
            if not jid or jid in self.results or epoch is None:
                continue
            self._record_result(jid, fire.get("rc"), fire.get("fired"), epoch, handoff=False)

    def _write_results(self, now):
        """Persist the rows atomically. A failed write stays dirty and retries next tick."""
        if not self.results_dirty:
            return
        live = {j.get("id") for j in self.jobs if j.get("id")}
        keep = {}
        for jid, row in self.results.items():
            if jid in live or self.reg_error is not None:
                # reg_error => the job list is the last good read, not the current one: a
                # registry the daemon cannot parse must not be able to prune rider history.
                keep[jid] = row
                continue
            last = row.get("last_fired_epoch")
            if isinstance(last, (int, float)) and now - float(last) <= RESULTS_RETENTION_S:
                keep[jid] = row
        self.results = keep
        doc = {"schema": RESULTS_SCHEMA,
               "generated": datetime.datetime.fromtimestamp(now).isoformat(timespec="seconds"),
               "generated_epoch": round(now, 3),
               "daemon_pid": os.getpid(),
               "ring_per_rider": RESULTS_RING,
               "retention_s": RESULTS_RETENTION_S,
               "n_riders": len(keep),
               "riders": keep}
        try:
            tmp = RESULTS + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, RESULTS)
            self.results_dirty = False
        except OSError:
            pass

    def tick(self, now, dry=False):
        self.reload()
        self.reap()
        dispatched = self._dispatch_round(now, dry=dry, full=True)
        if not dry:
            self.write_beat(now, dispatched)
            self._write_results(now)
        return dispatched

    def poll(self, now):
        """v2: a wake-up between minute ticks. fast_reap frees the slots of finished riders at once; every flag that
        wakes the daemon then dispatches what is due now (a learner phase boundary, a rider that lost the cap race
        at this minute's tick). The results file stays on the minute tick; the heartbeat is written only when this
        poll dispatched, because it is what a restart restores last_boundary from (2026-10-28 14:14: a restart
        before the next tick re-ran every rider a poll had started since the last one)."""
        if self.adaptive.get("fast_reap"):
            self.reap()
        dispatched = self._dispatch_round(now, full=False)
        if dispatched:
            self.write_beat(now, dispatched)
        return dispatched

    def _dispatch_round(self, now, dry=False, full=True):
        """The v1 dispatch pass (due -> backoff -> lock -> aging+priority sort -> cap), plus the v2 gates, each
        inert unless its adaptive flag is on. `full` = the minute tick: only it adds aging debt and retries a
        refused dispatch, exactly as v1 did once per tick; a poll never does either."""
        ad = self.adaptive
        dispatched = 0
        candidates = []
        for job in self.jobs:
            jid = job.get("id")
            if not jid:
                continue
            if not is_due(job, now, self.last.get(jid)):
                continue
            if self.not_before and self.not_before.get(jid, 0) > now:
                continue  # re-anchored after a phase change: never two runs within half a period
            if self._backed_off(job, now):
                continue  # failure streak: wait for the next BACKOFF_EVERY-th boundary (owner already handed off)
            if ad.get("backoff") and self._learned_skip(job, now):
                continue  # v2 backoff: the learner's every-k-th boundary
            mr = int(job.get("max_runtime") or DEFAULT_MAX_RUNTIME)
            if _locked(jid, mr) or jid in self.running:
                continue  # still running from a prior boundary -> skip (no pile-up)
            if not full and self.refused.get(jid) == boundary_key(job, now):
                continue  # refused at this boundary already: only the minute tick retries (one log line a minute)
            candidates.append(job)

        # Aging is the primary key: after losing one capacity race even a
        # legacy priority-0 rider runs before a freshly-due high-priority one.
        # Priority remains useful for the first race and equal-age peers.
        candidates.sort(
            key=lambda j: (self.deferred.get(j.get("id"), 0), _job_priority(j)),
            reverse=True,
        )
        capacity = max(0, max_concurrent() - len(self.running))
        queued = set()
        for job in candidates:
            jid = job["id"]
            if capacity <= 0:
                if not dry:
                    queued.add(jid)
                    if full:
                        self.deferred[jid] = self.deferred.get(jid, 0) + 1
                        self._note(jid, "capped", now, "cap %d" % max_concurrent())
                continue
            if dry:
                print("  WOULD dispatch %-20s cadence=%s :: %s" % (jid, job.get("cadence"), job.get("command")))
                dispatched += 1
                capacity -= 1
                continue
            if ad.get("class_caps"):
                full_class = self._class_full(job)
                if full_class:
                    queued.add(jid)
                    if full:
                        self.deferred[jid] = self.deferred.get(jid, 0) + 1
                        self._note(jid, "capped", now, full_class)
                    continue
            if ad.get("holds") and self._held(job, now):
                queued.add(jid)
                continue
            # optional cheap inline gate: a job may set "gate":false-result to skip; we keep gate INSIDE the
            # dispatched command (self-gating) to never block the clock -- so here we just fire.
            proc = dispatch(job)
            if proc is not None:
                start = boundary_start(job, now)
                nb = self.not_before.get(jid)
                if start is not None and nb is not None and start < nb <= now:
                    start = nb                        # a re-anchored run was due at its carried-over boundary
                self.dispatch_info[jid] = {
                    "dispatched": datetime.datetime.fromtimestamp(now).isoformat(timespec="seconds"),
                    "delay_s": round(now - start, 1) if start is not None else None,
                    "cadence": job.get("cadence"), "ctx_start": _machine_ctx(),
                    "sched": self._sched_summary(job, now)}
                self.last[jid] = boundary_key(job, now)
                self.deferred[jid] = 0
                self.running[jid] = (proc, now)
                self.last_dispatch[jid] = now
                self.refused.pop(jid, None)
                self.not_before.pop(jid, None)
                dispatched += 1
                capacity -= 1
            else:
                # A fail-closed lint/launch refusal is still outstanding work.
                self.deferred[jid] = self.deferred.get(jid, 0) + 1
                self.refused[jid] = boundary_key(job, now)
        if not dry:
            self.queued = queued
        return dispatched

    # ------------------------------------------------------------------ v2 gates
    def _learned_skip(self, job, now):
        """v2 backoff: run only every k-th boundary (k = learner multiplier 1..4, never faster than armed).
        Never for protected riders, daily/@ cadences or periods of a day or more."""
        jid = job["id"]
        k = self._rider(jid).get("k") or 1
        if k <= 1 or self._protected(job):
            return False
        p = parse_cadence(job.get("cadence"))
        if not p or p[0] != "interval" or p[1] >= 86400:
            return False
        key = boundary_key(job, now)
        if key % k == 0:
            return False
        if self.skip_seen.get(jid) != key:
            self.skip_seen[jid] = key
            self._note(jid, "backoff-skip", now, "every %dth boundary" % k)
        return True

    def _class_full(self, job):
        """v2 class caps: '' when the rider may start, else the reason (e.g. 'class heavy 1/1')."""
        if self._protected(job):
            return ""
        cls = self._rider(job["id"]).get("class")
        cap = (self.plan.get("caps") or {}).get(cls)
        if not cap:
            return ""
        by_id = {j.get("id"): j for j in self.jobs}
        n = sum(1 for rid in self.running
                if self._rider(rid).get("class") == cls and not self._protected(by_id.get(rid) or {"id": rid}))
        return "class %s %d/%d" % (cls, n, cap) if n >= cap else ""

    def _held(self, job, now):
        """v2 holds for heavy riders: defer while the A770 is busy, or while box W + the rider's rise > the cap.
        Protected and load_grant self-gated riders are exempt; an unknown or stale load_guard sample never holds.
        After one full cadence a watts-only hold is released (starvation bound, logged held_too_long); an A770 hold
        is never force-run -- A770 load is the power-loss red line."""
        jid = job["id"]
        plan = self._rider(jid)
        if plan.get("class") != "heavy" or plan.get("self_gated") or self._protected(job):
            return False
        ctx = _machine_ctx(now)
        a770, box = ctx.get("a770_w"), ctx.get("combined_w")
        busy = a770 is not None and a770 >= plan.get("a770_busy_w", HOLD_A770_BUSY_W)
        over = box is not None and box + plan.get("rise_w", 0.0) > plan.get("combined_w_max", HOLD_COMBINED_W_MAX)
        if not busy and not over:
            return False
        why = ("a770 %.0fW>=%.0f" % (a770, plan.get("a770_busy_w", HOLD_A770_BUSY_W)) if busy else
               "box %.0fW+%.1f>%.0f" % (box, plan.get("rise_w", 0.0), plan.get("combined_w_max", HOLD_COMBINED_W_MAX)))
        since = self.hold_since.get(jid)
        if since is None:
            since = self.hold_since[jid] = now
            self._note(jid, "held", now, why)
        period = _interval_secs(job) or plan.get("max_hold_s") or HOLD_DAILY_MAX_S
        if now - since >= period:
            if jid not in self.hold_long:
                self.hold_long.add(jid)
                self._note(jid, "held_too_long", now, why)
            if not busy:
                return False
        return True

    def _note(self, jid, decision, now, why=None):
        """One scheduler decision: counted for the rider's next run (`sched`), since start, and in the event ring."""
        self.pending.setdefault(jid, {})
        self.pending[jid][decision] = self.pending[jid].get(decision, 0) + 1
        self.sched_counts[decision] = self.sched_counts.get(decision, 0) + 1
        self.sched_events.append({"at": datetime.datetime.fromtimestamp(now).isoformat(timespec="seconds"),
                                  "id": jid, "decision": decision, "why": why})
        del self.sched_events[:-SCHED_EVENTS_RING]

    def _sched_summary(self, job, now):
        """The decisions behind this run, for the results ring and the ledger line (`sched`)."""
        jid = job["id"]
        notes = self.pending.pop(jid, {})
        out = {"mode": "adaptive" if self.adaptive else "v1"}
        for decision in ("capped", "backoff-skip"):
            if notes.get(decision):
                out[decision] = notes[decision]
        since = self.hold_since.pop(jid, None)
        if since is not None:
            out["held_s"] = round(now - since, 1)
        if jid in self.hold_long:
            self.hold_long.discard(jid)
            out["held_too_long"] = True
        if job.get("_offset_s"):
            out["offset_s"] = job["_offset_s"]
            out["offset_src"] = self.offset_src.get(jid)
        plan = self._rider(jid)
        if self.adaptive.get("backoff") and (plan.get("k") or 1) > 1:
            out["k"] = plan["k"]
        if (self.adaptive.get("class_caps") or self.adaptive.get("holds")) and plan.get("class"):
            out["class"] = plan["class"]
        return out

    # ------------------------------------------------------------------ the loop
    def _wakes(self):
        return bool(self.adaptive.get("fast_reap") or self.adaptive.get("offsets"))

    def _next_wake(self, now, nxt):
        """Earliest v2 wake-up before the minute tick `nxt`: the next whole second while a rider runs or waits
        (fast_reap), the next learner phase boundary (offsets). Always > now, so the loop cannot spin."""
        wake = nxt
        if self.adaptive.get("fast_reap") and (self.running or self.queued):
            wake = min(wake, math.floor(now) + POLL_S)
        if self.adaptive.get("offsets"):
            for job in self.jobs:
                period = _interval_secs(job)
                if period:
                    off = job.get("_offset_s") or 0
                    wake = min(wake, (math.floor((now - off) / period) + 1) * period + off)
        return wake

    def _loop(self, clock=None, sleep=None, until=None):
        """v1: sleep to each whole-tick boundary and tick(). v2 adds wake-ups between ticks (poll()); the minute
        tick, its heartbeat and its results write stay where they were."""
        clock = clock or time.time
        sleep = sleep or time.sleep
        while until is None or clock() < until:
            tick = base_tick(self.jobs)
            nxt = (int(clock() // tick) + 1) * tick      # the next clock-aligned boundary
            while self._wakes():
                now = clock()
                wake = self._next_wake(now, nxt)
                if wake >= nxt:
                    break
                sleep(max(0.0, wake - now))
                self.poll(max(clock(), wake))
            sleep(max(0.0, nxt - clock()))
            if _yield_requested(self.started):
                # Hand over before dispatching: the successor restores last_boundary from the heartbeat.
                print("HubClock: pid %d was asked to step down; exiting." % os.getpid())
                _release_daemon_flock()
                return
            self.tick(clock())
            _refresh_singleton()

    def write_beat(self, now, dispatched):
        beat = {
            "alive": True,
            "last_tick": datetime.datetime.fromtimestamp(now).isoformat(timespec="seconds"),
            "last_tick_epoch": round(now, 3),
            "drift_ms": round((now - int(now)) * 1000),   # how far off the integer-second boundary we woke
            "tick_seconds": base_tick(self.jobs),
            "n_jobs": len(self.jobs),
            "registry_error": self.reg_error,   # non-null => the job list below is the LAST GOOD read, not current
            "n_running": len(self.running),
            "max_concurrent": max_concurrent(),
            "dispatched_last_tick": dispatched,
            "started": datetime.datetime.fromtimestamp(self.started).isoformat(timespec="seconds"),
            "pid": os.getpid(),
            "os_lock": _daemon_flock_fd is not None,   # False only for `once` or a lock file that cannot open
            "stagger": self.stagger,
            "jobs": [{"id": j.get("id"), "agent": j.get("agent", ""), "cadence": j.get("cadence"),
                      "offset_s": j.get("_offset_s", 0),
                      "offset_src": self.offset_src.get(j.get("id")),
                      "last_boundary": self.last.get(j.get("id")),
                      "not_before": self.not_before.get(j.get("id")),   # v2: a re-anchored wait survives a restart
                      "deferred": self.deferred.get(j.get("id"), 0)} for j in self.jobs],
            "recent_fires": list(reversed(self.fires)),
            # v2 (additive): flags in force, decisions since start, the latest decisions and current holds.
            "adaptive": {"flags": self.adaptive or None,
                         "n_queued": len(self.queued),
                         "counts": self.sched_counts,
                         "held": {jid: datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds")
                                  for jid, t in self.hold_since.items()},
                         "events": list(reversed(self.sched_events))},
        }
        try:
            tmp = BEAT + ".tmp"
            json.dump(beat, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(tmp, BEAT)
        except OSError:
            pass

    def _restore_last(self):
        """Seed last_boundary from the persisted heartbeat so a restart does NOT re-fire a job whose boundary
        already passed today -- in particular a heavy @daily/@weekly job won't re-run just because the daemon
        bounced. Interval jobs still fire once on the first new bucket (harmless). KB 2026.06.09-18 audit fix F.
        v2: also the phase each last_boundary was computed with, so a phase change can be re-anchored, and any
        re-anchored wait (not_before) still pending."""
        try:
            b = json.load(open(BEAT, encoding="utf-8-sig"))
            for j in b.get("jobs", []):
                jid, lb = j.get("id"), j.get("last_boundary")
                if jid and lb is not None:
                    self.last[jid] = lb
                if jid and isinstance(j.get("offset_s"), int):
                    self.offsets_in_use[jid] = j["offset_s"]
                    self.offset_src[jid] = j.get("offset_src")
                nb = j.get("not_before")
                if jid and isinstance(nb, (int, float)) and not isinstance(nb, bool):
                    self.not_before[jid] = nb    # 2026-10-28 14:11: dropping it re-ran a 6h rider twice in 7 s
        except Exception:
            pass

    def run(self):
        if not _acquire_singleton():
            print("HubClock: another live daemon holds the singleton lock (pid alive + fresh tick); "
                  "refusing to double-run.")
            return
        self._restore_last()
        self._load_results()
        print("HubClock daemon up. registry=%s" % REG)
        self.reload()
        self._loop()


# --------------------------------------------------------------------------- CLI
def status():
    try:
        b = json.load(open(BEAT, encoding="utf-8-sig"))
    except Exception:
        b = None
    # A HubClock rider's RUN HISTORY lives in the heartbeat (recent_fires + per-job last_boundary),
    # NOT in hosts.json: the daemon keeps the registry READ-ONLY by design (zero write contention),
    # so hosts.json["hosts"]["HubClock"]["riders"][].last_run is ALWAYS null for HubClock jobs and is
    # NOT evidence of non-firing. (The ClaudeHubDeploy path DOES write last_run -- that contrast is
    # what misleads.) This view overlays each rider's last fire so liveness is unambiguous.
    last_fire, last_bound = {}, {}
    if b:
        for f in b.get("recent_fires", []):              # newest-first; first seen per id = most recent
            last_fire.setdefault(f.get("id"), (f.get("fired"), f.get("rc")))
        for j in b.get("jobs", []):
            last_bound[j.get("id")] = j.get("last_boundary")
        age = time.time() - b.get("last_tick_epoch", 0)
        print("HubClock: last tick %s (%.0fs ago) · tick=%ss · %d jobs · %d running · drift=%sms"
              % (b.get("last_tick"), age, b.get("tick_seconds"), b.get("n_jobs"), b.get("n_running"), b.get("drift_ms")))
    else:
        print("HubClock: no heartbeat yet (daemon not run). jobs registered:")
    if b and b.get("registry_error"):
        print("  !! REGISTRY UNREADABLE: %s -- the daemon is running on its last good read" % b["registry_error"])
    try:
        jobs = load_jobs()
    except RegistryUnreadable as e:
        sys.stderr.write("hubclock status: REGISTRY UNREADABLE -- %s\n" % e)
        return 4
    for j in jobs:
        jid = j.get("id")
        lf = last_fire.get(jid)
        if lf:
            fired = "last_fire=%s rc=%s" % (lf[0], lf[1])
        elif last_bound.get(jid) is not None:
            fired = "fired (boundary=%s; older than recent_fires window)" % last_bound[jid]
        else:
            fired = "NEVER FIRED"
        print("  job %-20s cadence=%-8s %-46s :: %s"
              % (jid, j.get("cadence"), fired, j.get("command")))
    return 0


def main(argv):
    verb = argv[0] if argv else "status"
    if verb == "run":
        HubClock().run()
    elif verb in ("once", "tick-test"):
        # A one-shot has no next tick to recover on, so an unreadable registry here is a hard failure rather
        # than the daemon's keep-last-good: "dispatched 0 job(s)" must never be the whole story.
        clock = HubClock()
        n = clock.tick(time.time(), dry=(verb == "tick-test"))
        print("hubclock %s: %d job(s) %s" % (verb, n, "would dispatch at this boundary"
                                             if verb == "tick-test" else "dispatched"))
        if clock.reg_error:
            sys.stderr.write("hubclock %s: REGISTRY UNREADABLE -- %s\n" % (verb, clock.reg_error))
            return 4
    elif verb == "status":
        return status()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
