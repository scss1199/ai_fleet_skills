#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""register-rider.py -- productized piggyback (0 Claude token). Register a script as an idempotent RIDER on an
existing recurring HOST, so it auto-runs with NO new scheduled task, NO console window, NO typed command. The
skill/script stays the BRAIN; the host is its HEARTBEAT. This is the executable half of auto-effect-doctrine.md.

WHY: skills/plugins are pull/in-turn and cannot self-run (auto-effect-doctrine.md). The hub's recurring hosts
(the ClaudeHubDeploy watcher, the lifecycle hooks) CAN run out-of-turn at 0 token. A rider attaches a brain to a
heartbeat without editing the host's code: state lives in _registry/hosts.json, the host calls `run <host>` each
cycle, and only DUE + work-having riders fire, each under a per-rider lock, spawned hidden.

AUTHORIZATION: building/wiring this primitive is free infrastructure, but ARMING a specific rider (`add`) turns on
new recurring out-of-turn execution = the same class of act as a new scheduled task => needs the operator's
explicit OK. The auto-mode classifier enforces this. `run`/`list`/`rm` are not arming and are unrestricted.

CITE: 50-techniques/piggyback-timer-grade-execution.md, 50-techniques/auto-effect-doctrine.md (KB 2026.06.09-18)

usage:
  register-rider.py add   <host> <id> "<command>" [--gate "<sentinel-cmd>"] [--every <min> | --cadence <spec>] [--priority <int>] [--desc "..."]
  register-rider.py rm    <host> <id>
  register-rider.py list
  register-rider.py audit           # flag duplicate commands armed on >1 host (zombie double-mounts)
  register-rider.py run   <host>    # called BY the host each cycle: fire due+gated riders (hidden, locked)

cadence (HubClock riders): '30s'/'5m'/'2h'/'1d' (clock-aligned interval), '@HH:MM[:SS]' (daily), or
'@<days>HH:MM' with a weekday selector (@sat10:00, @weekday15:35, @mon-fri09:00, @mon,wed,fri07:30). HubClock
riders are dispatched by the hubclock.py daemon (clock-aligned, non-blocking), NOT by `run` — `--every` is the
legacy elapsed-debounce cadence used by the watcher/hook hosts. Each rider also carries `managed_by` naming its
dispatch fabric, so its run-state source is unambiguous (heartbeat for HubClock, last_run for the rest).

hosts (seeded): HubClock (clock-aligned metronome, daemon-dispatched) · ClaudeHubDeploy (~30min, runs with no
session) · SessionStart · Stop · PreToolUse
"""
import os
import sys
import json
import time
import subprocess
import datetime

HUB = os.environ.get("AI_WORKSPACE", r"C:\ai_workspace")
REG = os.path.join(HUB, "_registry", "hosts.json")
LOCKDIR = os.path.join(HUB, "_temp")
REGLOCK = os.path.join(LOCKDIR, "hosts-registry.lock")

NO_LOCK = ("register-rider %s: could not acquire the registry lock (%s) -- ABORTED WITHOUT WRITING.\n"
           "  Another add/rm/run holds it. Retry; a lock older than 30s is stolen automatically.\n")

# managed_by: which fabric dispatches a rider AND therefore where its run-state lives. HubClock riders are
# daemon-dispatched (run-state = the heartbeat; hosts.json last_run stays null BY DESIGN); the rest write
# last_run on hosts.json. Naming it per rider stops an observer mistaking a null last_run for a dead rider.
_MANAGED = {"HubClock": "hubclock-daemon", "ClaudeHubDeploy": "deploy-watcher",
            "SessionStart": "sessionstart-hook", "Stop": "stop-hook", "PreToolUse": "pretooluse-hook"}


def _managed_by(host):
    return _MANAGED.get(host, "host:" + host)


class RegistryError(RuntimeError):
    """The registry could not be read or written SAFELY. Never swallowed into a default."""


def _acquire_reglock(timeout=10.0):
    """Serialize read-modify-write on hosts.json so two concurrent add/rm/run calls can't lost-update each
    other (hit live 2026-06-14: parallel `add` calls had to be &&-chained to avoid clobber). An
    O_CREAT|O_EXCL lock, stolen if >30s stale. KB 2026.06.09-18 audit fix G.

    FAIL CLOSED (audit 2026-08-10). The two previous return paths both lied:
      * timeout returned False and every caller wrote anyway -- the lost update the lock exists to prevent;
      * an OSError on the lock dir returned True, claiming a lock that was never taken, so the release
        path then deleted whatever lock ANOTHER process held.
    `False` now means "do not write", and callers must honour it. 65 armed riders live in this file;
    availability of a *corrupt* registry is not availability."""
    start = time.time()
    while True:
        try:
            fd = os.open(REGLOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode()); os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(REGLOCK) > 30:
                    os.remove(REGLOCK); continue
            except OSError:
                pass
            if time.time() - start > timeout:
                return False
            time.sleep(0.05)
        except OSError:
            return False  # lock dir unusable -> we hold nothing, so we write nothing


def _release_reglock():
    try:
        os.remove(REGLOCK)
    except OSError:
        pass

# Seed host definitions (cadence + whether they run with no session open). Riders are added on top.
SEED = {
    "_schema": 1,
    "hosts": {
        "HubClock": {"cadence": "per-rider (clock-aligned 1s..@daily)",
                     "desc": "the hub metronome daemon (hubclock.py): dispatches each rider at its OWN clock-aligned cadence, non-blocking",
                     "runs_with_no_session": True,
                     "wire": "register a rider with --cadence; the hubclock daemon dispatches it (NOT register-rider run). Arming = operator-gated.",
                     "riders": []},
        "ClaudeHubDeploy": {"cadence_min": 30, "desc": "operator deploy watcher (no Claude gate, no session needed)",
                            "runs_with_no_session": True, "wire": "register a rider (no code edit, no new task)",
                            "riders": []},
        "SessionStart": {"cadence": "per session", "desc": "every Claude Code session start (hook)",
                         "runs_with_no_session": False, "wire": "gated call in session-start-notice.ps1 (governance hook = operator-authorized)",
                         "riders": []},
        "Stop": {"cadence": "per turn", "desc": "every assistant turn end (hook)",
                 "runs_with_no_session": False, "wire": "gated call in the Stop hook (operator-authorized)",
                 "riders": []},
        "PreToolUse": {"cadence": "per matched tool call", "desc": "on Write/Edit etc. (hook)",
                       "runs_with_no_session": False, "wire": "gated call in the PreToolUse guard (operator-authorized)",
                       "riders": []},
    },
}


def _load():
    """Read hosts.json, or SEED it when it genuinely does not exist yet.

    NEVER reseed an EXISTING file (audit 2026-08-10). The old code caught every exception and fell back to
    SEED, so one truncated write -- a crash mid `json.dump`, a full disk -- turned into a silent registry
    with zero riders, and the very next `add` PERSISTED that emptiness. Measured 2026-08-10: HubClock holds
    65 armed riders. Losing them silently is the worst outcome this file can produce, strictly worse than
    refusing to run, so a present-but-unreadable registry is now a hard error."""
    if not os.path.exists(REG):
        d = json.loads(json.dumps(SEED))
    else:
        try:
            with open(REG, encoding="utf-8-sig") as fh:
                d = json.load(fh)
        except (OSError, ValueError) as e:
            raise RegistryError(
                "%s exists but could not be read (%s). REFUSING to reseed -- that would delete every armed "
                "rider. Restore the file (a crashed writer leaves %s.tmp) and re-run." % (REG, e, REG))
        if not isinstance(d, dict) or not isinstance(d.get("hosts"), dict):
            raise RegistryError(
                "%s parsed but has no 'hosts' object. REFUSING to reseed over it; inspect the file by hand."
                % REG)
    # ensure all seed hosts exist (merge, keep existing riders)
    for h, meta in SEED["hosts"].items():
        d["hosts"].setdefault(h, json.loads(json.dumps(meta)))
    # backfill managed_by so every rider names its dispatch fabric (state-source disambiguation; audit fix D)
    for h, meta in d["hosts"].items():
        mb = _managed_by(h)
        for r in meta.get("riders", []):
            if isinstance(r, dict):
                r.setdefault("managed_by", mb)
    d["_schema"] = 1
    return d


def _save(d):
    """Atomic, validated replacement. Same bytes as before -- 22 engines read this file, so the on-disk
    shape (ensure_ascii=False, indent=1, _schema 1) must not move; only the WRITE MECHANISM changes.

    Serialize -> write temp -> re-parse the temp -> os.replace. A crash at any point leaves the previous
    registry intact, because the live path is only ever touched by the atomic rename. Same idiom as
    hubclock.write_beat()."""
    if not isinstance(d, dict) or not isinstance(d.get("hosts"), dict):
        raise RegistryError("refusing to save a registry with no 'hosts' object")
    os.makedirs(os.path.dirname(REG), exist_ok=True)
    blob = json.dumps(d, ensure_ascii=False, indent=1)
    tmp = REG + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
        # read-back: a short write / encoding fault must not reach the live path
        with open(tmp, encoding="utf-8-sig") as fh:
            back = json.load(fh)
        if not isinstance(back.get("hosts"), dict):
            raise RegistryError("post-write validation failed: 'hosts' missing from %s" % tmp)
        os.replace(tmp, REG)
    except RegistryError:
        _unlink(tmp); raise
    except (OSError, ValueError) as e:
        _unlink(tmp)
        raise RegistryError("registry write failed, previous %s left intact: %s" % (REG, e))


def _unlink(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _now():
    return datetime.datetime.now()


def _parse(ts):
    try:
        return datetime.datetime.fromisoformat(ts)
    except Exception:
        return None


def _run_hidden(cmd, timeout=300):
    """Spawn a command with NO console window (CREATE_NO_WINDOW + SW_HIDE). Returns returncode (-1 on error).
    The whole auto-effect contract dies if a child flashes a window — so every spawn goes through here.
    shell=True so cmd.exe parses quotes/spaces/paths natively (rider commands are curator/operator-registered,
    not untrusted input); CREATE_NO_WINDOW keeps even cmd.exe windowless."""
    flags, si = 0, None
    if os.name == "nt":
        flags = 0x08000000  # CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
    try:
        return subprocess.run(cmd, shell=True, creationflags=flags, startupinfo=si, timeout=timeout).returncode
    except Exception as e:
        sys.stderr.write("  rider spawn error: %s\n" % e)
        return -1


def _lint_flash(command):
    """ARM-time foreground-flash lint (warn-only; arming is already operator-gated). Riders are
    dispatched WINDOWLESS (hubclock CREATE_NO_WINDOW / _run_hidden), so a console `python ` rider
    is fine at launch — but these patterns still flash, so surface them when a rider is armed."""
    c = (command or "").lower()
    out = []
    if "-windowstyle hidden" in c or "-w hidden" in c:
        out.append("[flash-lint WARN] '-WindowStyle Hidden' still flashes a conhost + steals focus "
                   "before hiding; use pythonw / wscript Run(...,0) / CREATE_NO_WINDOW.")
    if "cmd /c start" in c or c.startswith("start ") or " start " in c:
        out.append("[flash-lint WARN] `start ...` opens a NEW window, escaping the windowless dispatcher.")
    if ("python.exe" in c or c.startswith("python ") or " python " in c) and "pythonw" not in c:
        out.append("[flash-lint info] console `python` rider — dispatcher hides the launch; ensure the "
                   "script's OWN subprocess children pass CREATE_NO_WINDOW (zt-foreground-guard audits this).")
    return out


def cmd_add(args):
    host, rid = args[0], args[1]
    command = args[2]
    gate, every, cadence, priority, desc = None, None, None, 0, ""
    i = 3
    while i < len(args):
        if args[i] == "--gate":
            gate = args[i + 1]; i += 2
        elif args[i] == "--every":
            every = int(args[i + 1]); i += 2
        elif args[i] == "--cadence":
            cadence = args[i + 1]; i += 2
        elif args[i] == "--priority":
            priority = max(-1000, min(1000, int(args[i + 1]))); i += 2
        elif args[i] == "--desc":
            desc = args[i + 1]; i += 2
        else:
            i += 1
    for _w in _lint_flash(command):
        print("  " + _w)
    if not _acquire_reglock():                       # G: no lost-update on concurrent add/rm/run
        sys.stderr.write(NO_LOCK % ("add", REGLOCK)); return 3
    try:
        d = _load()
        if host not in d["hosts"]:
            print("unknown host %r. known: %s" % (host, ", ".join(d["hosts"]))); return 1
        riders = d["hosts"][host]["riders"]
        row = {"id": rid, "command": command, "gate": gate, "every_min": every, "cadence": cadence,
               "priority": priority, "desc": desc,
               "managed_by": _managed_by(host),
               "registered": _now().isoformat(timespec="seconds"), "last_run": None}
        riders[:] = [r for r in riders if r.get("id") != rid] + [row]   # upsert
        _save(d)
    finally:
        _release_reglock()
    print("registered rider %s on %s (gate=%s every=%s cadence=%s priority=%s managed_by=%s)"
          % (rid, host, bool(gate), every, cadence, priority, _managed_by(host)))
    return 0


def cmd_rm(args):
    host, rid = args[0], args[1]
    if not _acquire_reglock():                       # G: no lost-update on concurrent add/rm/run
        sys.stderr.write(NO_LOCK % ("rm", REGLOCK)); return 3
    try:
        d = _load()
        h = d["hosts"].get(host)
        if not h:
            print("unknown host", host); return 1
        before = len(h["riders"])
        h["riders"] = [r for r in h["riders"] if r.get("id") != rid]
        removed = before - len(h["riders"])
        _save(d)
    finally:
        _release_reglock()
    # printed AFTER the release, but computed inside: `n`/`h` used to be read here after a `finally` that
    # could be reached with them unbound, turning a load error into an UnboundLocalError.
    print("removed %d rider(s) %s from %s" % (removed, rid, host))
    return 0


def cmd_list(_args):
    d = _load()
    for host, h in d["hosts"].items():
        ns = "no-session-ok" if h.get("runs_with_no_session") else "needs-session"
        print("HOST %-16s %-13s %s" % (host, ns, h.get("desc", "")))
        for r in h.get("riders", []):
            cad = r.get("cadence") or (("%sm" % r.get("every_min")) if r.get("every_min") else "-")
            print("   - %-20s cadence=%-9s gate=%-5s by=%-16s last=%s :: %s" %
                  (r["id"], cad, bool(r.get("gate")), r.get("managed_by", "-"), r.get("last_run"), r.get("command")))
    return 0


def cmd_run(args):
    """Called by the HOST each cycle. Fire only DUE (debounce) + work-having (gate) riders, each under a lock."""
    host = args[0]
    d = _load()
    h = d["hosts"].get(host)
    if not h:
        print("unknown host", host); return 1
    if host == "HubClock":
        # HubClock riders are clock-aligned and dispatched by the hubclock.py daemon, not elapsed-debounced here.
        print("HubClock riders are dispatched by the hubclock.py daemon (clock-aligned). Run `hubclock.py run`/`once`.")
        return 0
    now = _now()
    fired, skipped = 0, 0
    for r in h.get("riders", []):
        rid = r["id"]
        # debounce
        ev = r.get("every_min")
        lr = _parse(r.get("last_run") or "")
        if ev and lr and (now - lr).total_seconds() < ev * 60:
            skipped += 1; continue
        # per-rider lock (stale-tolerant): skip if a fresh lock exists
        lock = os.path.join(LOCKDIR, "rider-%s-%s.lock" % (host, rid))
        try:
            if os.path.exists(lock) and (now.timestamp() - os.path.getmtime(lock)) < 3600:
                skipped += 1; continue
            open(lock, "w").write(now.isoformat())
        except OSError:
            pass
        try:
            # gate: non-zero return = no real work -> skip cheaply
            if r.get("gate"):
                if _run_hidden(r["gate"], timeout=120) != 0:
                    skipped += 1; continue
            rc = _run_hidden(r["command"], timeout=600)
            r["last_run"] = now.isoformat(timespec="seconds")
            r["last_rc"] = rc
            fired += 1
            print("  fired %s on %s (rc=%s)" % (rid, host, rc))
        finally:
            try:
                os.remove(lock)
            except OSError:
                pass
    # G: persist last_run/last_rc WITHOUT clobbering a concurrent add -- re-read fresh under lock + merge deltas
    if _acquire_reglock():
        try:
            fresh = _load()
            by_id = {r.get("id"): r for r in fresh["hosts"].get(host, {}).get("riders", [])}
            for r in h.get("riders", []):
                if "last_rc" in r and r.get("id") in by_id:
                    by_id[r["id"]]["last_run"] = r.get("last_run")
                    by_id[r["id"]]["last_rc"] = r.get("last_rc")
            _save(fresh)
        finally:
            _release_reglock()
    else:
        # The old fallback here was `_save(d)`: writing the STALE pre-run snapshot, i.e. performing exactly
        # the lost update the surrounding lock exists to prevent, at the one moment we know a writer is
        # active. The riders already ran; only their bookkeeping is dropped. Say so and exit non-zero.
        sys.stderr.write(NO_LOCK % ("run last_run/last_rc writeback", REGLOCK))
        print("host %s: %d fired, %d skipped (%d riders) -- run-state NOT persisted"
              % (host, fired, skipped, len(h.get("riders", []))))
        return 3
    print("host %s: %d fired, %d skipped (%d riders)" % (host, fired, skipped, len(h.get("riders", []))))
    return 0


def cmd_audit(_args):
    """Read-only duplicate/zombie detector (audit fix C): flag any command armed on >1 host -- the
    'double-mount' that caused the divergent-last_run confusion. A periodic job should live on ONE fabric."""
    d = _load()
    by_cmd, rows = {}, 0
    for host, h in d["hosts"].items():
        for r in h.get("riders", []):
            rows += 1
            by_cmd.setdefault((r.get("command") or "").strip().lower(), []).append((host, r.get("id")))
    dups = {k: v for k, v in by_cmd.items() if len({h for h, _ in v}) > 1}
    if not dups:
        print("registry audit: %d riders, NO duplicate commands across hosts (clean single-fabric)." % rows)
        return 0
    print("registry audit: %d riders, %d duplicate command(s) across hosts:" % (rows, len(dups)))
    for cmd, where in dups.items():
        print("  DUP :: %s" % cmd)
        for host, rid in where:
            print("      - host=%s id=%s" % (host, rid))
    print("  -> retire the superseded mount with `rm <host> <id>` so the job runs on ONE fabric.")
    return 2


def _dispatch(argv):
    if not argv:
        print(__doc__); return 0
    verb, rest = argv[0], argv[1:]
    if verb == "add" and len(rest) >= 3:
        return cmd_add(rest)
    if verb == "rm" and len(rest) >= 2:
        return cmd_rm(rest)
    if verb == "list":
        return cmd_list(rest)
    if verb == "audit":
        return cmd_audit(rest)
    if verb == "run" and len(rest) >= 1:
        return cmd_run(rest)
    print(__doc__)
    return 1


def main(argv):
    """RegistryError is the ONE exception this tool must not render as a traceback.

    Every caller of this script is a host: a hook, the deploy watcher, `run <host>` from a rider fabric. A
    traceback there scrolls past in a hidden window and the operator learns nothing; the whole point of the
    2026-08-10 fail-closed audit is that a refusal to write is REPORTABLE. Exit 4 = registry unsafe, nothing
    was written (0 ok, 1 usage/unknown-host, 2 audit dups, 3 lock not acquired)."""
    try:
        return _dispatch(argv)
    except RegistryError as e:
        sys.stderr.write("register-rider: REGISTRY UNSAFE -- no change was made.\n  %s\n" % e)
        return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
