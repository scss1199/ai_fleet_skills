#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
r"""fleet-job-dispatch.py — machine-targeted jobs over the shared skills repo.

Why
---
2026-10-12: darkhero could drive scar3 only because a claude.ai Remote Control session
happened to be listed; altos never appeared, and no hub channel names a machine:
_bus is machine-local, the LINE->Drive->line-cursor-agent-bridge lane has no routing
(every machine running the rider races for the same job), the Cloudflare digest is
read-only. Every follower already fetches `scss1199/ai_fleet_skills`, so a job file in
that repo under `jobs/<target_host>/` is the one transport that reaches each machine
without a live session.

Shape
-----
  jobs/<host>/<job_id>.json          written by the authority (`submit`), never edited
  jobs/<host>/<job_id>.result.json   written by the target host (`tick`), one per job
`<host>` is the lower-case hostname (socket.gethostname()). A host claims ONLY its own
folder, so there is no cross-machine race; a local lock stops two ticks on one host.

Kinds
-----
  probe   fixed read-only inventory: hostname, hub commit, local FAMES package_sha,
          fleet receipt, HubClock riders touching fames/fleet-skill, Claude CLI
          readiness. Zero model tokens; works on a host whose Claude CLI is not even
          logged in — that is the point: the first thing a follower reports is what it
          still lacks.
  prompt  the job text goes to the local Claude CLI through claude-remote-exec.py
          (stdin prompt, cwd asserted under cwd_root, CREATE_NO_WINDOW). A host whose
          CLI is not ready records the NAMED blocker instead of pretending.

Hard lines kept: no new scheduled task (a HubClock rider row is proposed, arming is
operator-owned); zero foreground (CREATE_NO_WINDOW everywhere); no force push; no
secrets in job files (job text is the only payload; results are capped); UNKNOWN
fails closed (a result is written for every claimed job, success or not).

Usage
-----
  python fleet-job-dispatch.py submit --target-host scar3 --kind probe
  python fleet-job-dispatch.py submit --target-host scar3 --seat ai_scar3 --prompt-file p.txt
  python fleet-job-dispatch.py tick [--host scar3] [--dry-run] [--json]
  python fleet-job-dispatch.py status [--json]
  python fleet-job-dispatch.py results --job <id> [--json]
CITE: _registry/fleet-skill-github.json · _registry/claude-remote-control.json
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENG = os.path.dirname(os.path.abspath(__file__))
if ENG not in sys.path:
    sys.path.insert(0, ENG)
from _paths import COMMON as HUB  # noqa: E402

NO_WINDOW = 0x08000000
JOBS_DIR = "jobs"
MAX_PROMPT_CHARS = 12000
MAX_RESULT_CHARS = 20000
DEFAULT_TTL_HOURS = 48


# ----------------------------------------------------------------------------- helpers

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def this_host() -> str:
    return socket.gethostname().strip().lower()


def repo_root(hub: Path | None = None) -> Path:
    """The ai_fleet_skills clone every follower already keeps (fleet-skill-github.json SSOT)."""
    hub = Path(hub or HUB)
    rel = "_skill/ai_fleet_skills"
    try:
        reg = _read_json(hub / "_registry" / "fleet-skill-github.json")
        rel = (reg.get("shared_repo") or {}).get("repo_path") or rel
    except (OSError, ValueError):
        pass
    return hub / rel if not os.path.isabs(rel) else Path(rel)


def git(repo: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=timeout)


def _fetch(repo: Path, branch: str = "main") -> list[str]:
    f = git(repo, "fetch", "origin", branch, "--quiet")
    return [] if f.returncode == 0 else ["fetch_failed:" + f.stderr.strip()[-200:]]


def remote_ls(repo: Path, folder: str, branch: str = "main") -> list[str]:
    """File names under <folder> on origin/<branch>, read from git objects (the clone's worktree is never touched)."""
    r = git(repo, "ls-tree", "--name-only", f"origin/{branch}", f"{folder.rstrip('/')}/")
    if r.returncode:
        return []
    return [line.strip().split("/")[-1] for line in r.stdout.splitlines() if line.strip()]


def remote_read(repo: Path, path: str, branch: str = "main") -> bytes | None:
    r = subprocess.run(["git", "-C", str(repo), "show", f"origin/{branch}:{path}"], capture_output=True,
                       creationflags=NO_WINDOW, timeout=60)
    return r.stdout if r.returncode == 0 else None


def _publish(repo: Path, hub: Path, files: dict, message: str, branch: str = "main") -> dict:
    """Commit new files on top of origin/<branch> through a detached temporary worktree and push.

    The follower's clone is written by riders (attest, sync) and is often dirty; rebasing it
    conflicted on 2026-10-12. A temporary worktree never sees that dirt, so the only failure
    left is a push race, retried after a fresh fetch."""
    errs = _fetch(repo, branch)
    if errs:
        return {"ok": False, "error": ";".join(errs)}
    wt = hub / "_temp" / "fleet-job-dispatch" / f"wt-{uuid.uuid4().hex}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    try:
        for attempt in range(3):
            if wt.exists():
                git(repo, "worktree", "remove", "--force", str(wt))
            a = git(repo, "worktree", "add", "--detach", str(wt), f"origin/{branch}")
            if a.returncode:
                return {"ok": False, "error": "worktree_add_failed:" + a.stderr.strip()[-200:]}
            # A follower's clone is a sparse checkout of its own folders (altos 2026-10-27: contributors/altos,
            # contributors/darkhero, jobs/altos); the worktree inherits that cone, so a job for another host
            # was "pathspec did not match any file(s) known to git". The temporary worktree checks out everything.
            git(wt, "sparse-checkout", "disable")
            rel = []
            for relpath, doc in files.items():
                _write_json(wt / relpath, doc)
                rel.append(relpath)
            git(wt, "add", "-f", "--", *rel)
            c = git(wt, "-c", "user.name=fleet-job-dispatch", "-c", "user.email=fleet-job-dispatch@local",
                    "commit", "-q", "-m", message, "--", *rel)
            if c.returncode and "nothing to commit" not in (c.stdout + c.stderr):
                return {"ok": False, "error": "commit_failed:" + (c.stderr or c.stdout).strip()[-200:]}
            pu = git(wt, "push", "origin", f"HEAD:{branch}")
            if pu.returncode == 0:
                sha = git(wt, "rev-parse", "--short", "HEAD").stdout.strip()
                _fetch(repo, branch)
                return {"ok": True, "commit": sha, "attempts": attempt + 1}
            errs = _fetch(repo, branch)
            if errs:
                return {"ok": False, "error": ";".join(errs)}
        return {"ok": False, "error": "push_rejected_3x"}
    finally:
        git(repo, "worktree", "remove", "--force", str(wt))
        git(repo, "worktree", "prune")


# ------------------------------------------------------------------------------ submit

def submit(repo: Path, hub: Path, target_host: str, kind: str, seat: str | None, prompt: str | None,
           ttl_hours: float, source: str, push: bool = True) -> dict:
    host = target_host.strip().lower()
    if not host or "/" in host or "\\" in host or ".." in host:
        return {"ok": False, "error": "bad_target_host"}
    if kind not in ("probe", "prompt", "converge"):
        return {"ok": False, "error": "bad_kind"}
    if kind == "prompt":
        if not prompt or not prompt.strip():
            return {"ok": False, "error": "prompt_required"}
        if len(prompt) > MAX_PROMPT_CHARS:
            return {"ok": False, "error": f"prompt_over_{MAX_PROMPT_CHARS}_chars"}
    now = _now()
    job_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    doc = {
        "schema": "fleet-job/1", "id": job_id, "target_host": host, "kind": kind,
        "seat": seat, "prompt": prompt if kind == "prompt" else None,
        "from": source, "created_at": _iso(now), "expires_at": _iso(now + timedelta(hours=ttl_hours)),
    }
    relpath = f"{JOBS_DIR}/{host}/{job_id}.json"
    out = {"ok": True, "job": job_id, "path": relpath, "target_host": host, "kind": kind}
    if push:
        out["push"] = _publish(repo, hub, {relpath: doc}, f"chore(jobs/{host}): submit {kind} {job_id}")
        out["ok"] = bool(out["push"].get("ok"))
    else:
        out["doc"] = doc
    return out


# ------------------------------------------------------------------------------- probe

def _run(args: list[str], timeout: int = 180, cwd: Path | None = None) -> dict:
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW, timeout=timeout, cwd=str(cwd) if cwd else None)
        return {"exit": r.returncode, "stdout": r.stdout[-4000:], "stderr": r.stderr[-1000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exit": -1, "stdout": "", "stderr": type(exc).__name__}


OMNIROUTE_NEEDS = {"node_min": (22, 22, 2), "ram_avail_mb": 1500, "disk_free_mb": 4096}  # measured on darkhero 2026-10-14: install 2205 MB, RSS 394-428 MB


def _node_version() -> tuple[int, ...] | None:
    import shutil

    exe = shutil.which("node")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        return tuple(int(x) for x in r.stdout.strip().lstrip("v").split(".")[:3])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def hardware(hub: Path) -> dict:
    """Stdlib-only facts (no platform.* calls: they spawn `cmd /c ver` when WMI is off -> visible flash)."""
    import shutil

    out: dict = {"cpu_count": os.cpu_count()}
    try:
        if os.name == "nt":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = MEM()
            m.dwLength = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            out["ram_total_mb"] = m.ullTotalPhys // 2**20
            out["ram_avail_mb"] = m.ullAvailPhys // 2**20
            v = sys.getwindowsversion()
            out["os"] = f"Windows {v.major}.{v.minor}.{v.build}"
    except Exception:  # noqa: BLE001
        out["ram_total_mb"] = out.get("ram_total_mb", "UNKNOWN")
    try:
        out["disk_free_mb"] = shutil.disk_usage(str(hub)).free // 2**20
    except OSError:
        out["disk_free_mb"] = "UNKNOWN"
    nv = _node_version()
    out["node"] = ".".join(map(str, nv)) if nv else None
    reasons = []
    if not nv:
        reasons.append("node_missing")
    elif not (nv >= OMNIROUTE_NEEDS["node_min"] and (nv[0] in (22,) or 24 <= nv[0] < 27)):
        reasons.append("node_too_old_or_unsupported")
    if isinstance(out.get("ram_avail_mb"), int) and out["ram_avail_mb"] < OMNIROUTE_NEEDS["ram_avail_mb"]:
        reasons.append("ram_avail_below_%d_mb" % OMNIROUTE_NEEDS["ram_avail_mb"])
    if isinstance(out.get("disk_free_mb"), int) and out["disk_free_mb"] < OMNIROUTE_NEEDS["disk_free_mb"]:
        reasons.append("disk_free_below_%d_mb" % OMNIROUTE_NEEDS["disk_free_mb"])
    out["omniroute_fit"] = {"fit": not reasons, "reasons": reasons, "needs": {**OMNIROUTE_NEEDS, "node_min": "22.22.2 (22.x) or 24-26"}}
    return out


def probe(hub: Path) -> dict:
    """Fixed read-only inventory; every field is UNKNOWN when its source is missing."""
    out: dict = {"hostname": this_host(), "hub": str(hub), "collected_at": _iso(_now())}
    hc = git(hub, "rev-parse", "--short", "HEAD")
    br = git(hub, "rev-parse", "--abbrev-ref", "HEAD")
    out["hub_commit"] = hc.stdout.strip() if hc.returncode == 0 else "UNKNOWN"
    out["hub_branch"] = br.stdout.strip() if br.returncode == 0 else "UNKNOWN"
    try:
        bm = _read_json(hub / "_skill/fleet-skills/fames/bundle-manifest.json")
        out["fames"] = {"version": bm.get("version"), "package_sha": bm.get("package_sha")}
    except (OSError, ValueError):
        out["fames"] = "UNKNOWN"
    try:
        rel = _read_json(hub / "_registry/fames-runtime-release.json")
        out["runtime_release"] = {"generation": rel.get("generation"), "state": rel.get("state")}
    except (OSError, ValueError):
        out["runtime_release"] = "UNKNOWN"
    rec = _run([sys.executable, str(hub / "_skill/engines/mtm-fleet-skill-github.py"), "receipt", "--json"], cwd=hub)
    try:
        raw = rec["stdout"]
        doc = json.loads(raw[raw.index("{"):])
        out["receipt"] = {"expected": doc.get("expected_package_sha"),
                          "nodes": {n["node"]: [n.get("verdict"), n.get("package_sha")] for n in doc.get("nodes", [])}}
    except (ValueError, KeyError, TypeError):
        out["receipt"] = "UNKNOWN"
    try:
        hosts = _read_json(hub / "_registry/hosts.json")
        riders = hosts["hosts"]["HubClock"]["riders"]
        out["riders"] = [{"id": r.get("id"), "enabled": r.get("enabled"),
                          "cmd": str(r.get("cmd") or r.get("command"))[:120]}
                         for r in riders if any(k in json.dumps(r).lower() for k in ("fames", "fleet-skill", "fleet-job"))]
    except (OSError, ValueError, KeyError, TypeError):
        out["riders"] = "UNKNOWN"
    chk = _run([sys.executable, str(hub / "_skill/engines/claude-remote-exec.py"), "check", "--json"], cwd=hub, timeout=90)
    try:
        doc = json.loads(chk["stdout"][chk["stdout"].index("{"):])
        out["claude_cli"] = {"ready": doc.get("ready"), "blocker": doc.get("blocker"), "cli": doc.get("cli")}
    except (ValueError, KeyError, TypeError):
        out["claude_cli"] = "UNKNOWN"
    out["nested_hub_folder_present"] = (hub / hub.name).is_dir()
    # 2026-10-14 operator: 「適不適合他們的硬體環境要適合才裝」 — the facts an install decision needs.
    out["hardware"] = hardware(hub)
    # 2026-10-13: which F1S Stop hooks this host's Claude settings actually wire (the lie gate lands only
    # when claude-proof-hook.py is listed here, not when the file merely exists).
    try:
        settings = Path.home() / ".claude" / "settings.json"
        doc = _read_json(settings)
        wired: dict = {}
        for event in ("Stop", "SubagentStop", "SessionStart", "UserPromptSubmit"):
            names = []
            for group in (doc.get("hooks") or {}).get(event) or []:
                for handler in (group.get("hooks") or []) if isinstance(group, dict) else []:
                    cmd = str((handler or {}).get("command") or "")
                    names.append(cmd.rstrip('"').replace("/", "\\").rsplit("\\", 1)[-1].strip('"'))
            wired[event] = names
        out["claude_hooks"] = wired
    except (OSError, ValueError, AttributeError, TypeError):
        out["claude_hooks"] = "UNKNOWN"
    for name in ("claude-proof-hook.py", "claude-run-until-done-hook.py"):
        out[f"has_{name.split('.')[0].replace('-', '_')}"] = (hub / "_skill/engines" / name).is_file()
    return out


def run_prompt(hub: Path, seat: str, prompt: str) -> dict:
    """Local Claude CLI through claude-remote-exec.py; a NAMED blocker when it is not ready."""
    exe = hub / "_skill/engines/claude-remote-exec.py"
    def _check(*extra: str, timeout: int = 90):
        chk = _run([sys.executable, str(exe), "check", "--json", *extra], cwd=hub, timeout=timeout)
        try:
            return json.loads(chk["stdout"][chk["stdout"].index("{"):]), chk
        except (ValueError, KeyError, TypeError):
            return None, chk

    ready, chk = _check()
    if ready is not None and ready.get("blocker") == "claude_auth_unverified":
        # The verdict is only refreshed at logon (12h TTL), so a follower that stays up
        # rejects every prompt job afterwards. A job is waiting and will spend a call
        # anyway: prove the credential once, then re-read readiness.
        ready, chk = _check("--probe", timeout=300)
    if ready is None:
        return {"ok": False, "blocker": "claude_remote_exec_check_unreadable", "stderr": chk["stderr"]}
    if not ready.get("ready"):
        return {"ok": False, "blocker": ready.get("blocker") or "claude_cli_not_ready", "check": ready}
    timeout = 900
    try:
        timeout = int(_read_json(hub / "_registry/claude-remote-control.json").get("exec", {}).get("timeout_sec") or 900)
    except (OSError, ValueError, TypeError):
        pass
    tmp = hub / "_temp" / "fleet-job-dispatch" / f"prompt-{uuid.uuid4().hex}.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(prompt, encoding="utf-8")
    try:
        r = _run([sys.executable, str(exe), "run", "--seat", seat, "--prompt-file", str(tmp)], cwd=hub, timeout=timeout + 30)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return {"ok": r["exit"] == 0, "exit": r["exit"], "stdout": r["stdout"][-MAX_RESULT_CHARS:], "stderr": r["stderr"]}


# -------------------------------------------------------------------------------- tick

def pending_jobs(repo: Path, host: str) -> list[str]:
    """Job ids on origin/main under jobs/<host>/ that have no result yet (git objects only)."""
    names = remote_ls(repo, f"{JOBS_DIR}/{host.lower()}")
    results = {n[:-len(".result.json")] for n in names if n.endswith(".result.json")}
    return sorted(n[:-5] for n in names if n.endswith(".json") and not n.endswith(".result.json")
                  and not n.endswith(".claim.json") and n[:-5] not in results)


def run_converge(hub: Path, seat: str) -> dict:
    """The canonical converge with --arm, so a follower's own fames-converge rider is (re)registered on the command
    that attests and publishes. scar3's rider ran a seat script that never attested, so the fleet read it UNKNOWN
    for weeks (2026-10-23). A fixed command: the job carries no code, only the seat name."""
    script = hub / "_skill" / "fleet-skills" / "fames" / "scripts" / "fames_fleet.py"
    try:
        proc = subprocess.run([sys.executable, str(script), "converge", "--workspace", str(hub), "--host", seat, "--arm"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "blocker": f"converge_failed: {type(exc).__name__}"}
    return {"ok": proc.returncode == 0, "seat": seat, "rc": proc.returncode, "tail": (proc.stdout + proc.stderr)[-1500:]}


def tick(repo: Path, hub: Path, host: str | None = None, dry_run: bool = False,
         prober=None, runner=None) -> dict:
    host = (host or this_host()).lower()
    prober = prober or probe
    runner = runner or run_prompt
    lock = hub / "_temp" / "fleet-job-dispatch" / f"tick-{host}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            if time.time() - lock.stat().st_mtime > 3600:  # a dead tick never blocks the host forever
                lock.unlink()
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            else:
                return {"ok": False, "host": host, "error": "tick_already_running"}
        except OSError:
            return {"ok": False, "host": host, "error": "tick_already_running"}
    os.close(fd)
    try:
        errs = _fetch(repo)
        if errs:
            return {"ok": False, "host": host, "error": ";".join(errs)}
        jobs = pending_jobs(repo, host)
        done = []
        for job_id in jobs:
            raw = remote_read(repo, f"{JOBS_DIR}/{host}/{job_id}.json")
            try:
                job = json.loads(raw.decode("utf-8-sig")) if raw else {}
            except ValueError:
                job = {}
            job.setdefault("id", job_id)
            job.setdefault("kind", "unreadable")
            result: dict = {"schema": "fleet-job-result/1", "job": job_id, "host": host,
                            "started_at": _iso(_now()), "kind": job.get("kind")}
            if job.get("target_host", host) != host:
                result.update({"ok": False, "blocker": "target_host_mismatch"})
            elif job.get("expires_at") and job["expires_at"] < _iso(_now()):
                result.update({"ok": False, "blocker": "expired"})
            elif dry_run:
                result.update({"ok": None, "dry_run": True})
            elif job.get("kind") == "probe":
                result.update({"ok": True, "probe": prober(hub)})
            elif job.get("kind") == "prompt":
                seat = job.get("seat") or "ai_" + host
                result.update(runner(hub, seat, job.get("prompt") or ""))
            elif job.get("kind") == "converge":
                result.update(run_converge(hub, job.get("seat") or "ai_" + host))
            else:
                result.update({"ok": False, "blocker": "unknown_kind"})
            result["finished_at"] = _iso(_now())
            if dry_run:
                done.append({"job": result["job"], "dry_run": True})
                continue
            relpath = f"{JOBS_DIR}/{host}/{job_id}.result.json"
            push = _publish(repo, hub, {relpath: result}, f"chore(jobs/{host}): result {job_id} ok={result.get('ok')}")
            done.append({"job": result["job"], "ok": result.get("ok"), "blocker": result.get("blocker"), "push": push})
        return {"ok": all(d.get("push", {}).get("ok", True) for d in done), "host": host,
                "claimed": len(jobs), "results": done}
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def status(repo: Path) -> dict:
    _fetch(repo)
    rows = []
    r = git(repo, "ls-tree", "-r", "--name-only", "origin/main", f"{JOBS_DIR}/")
    names = [line.strip() for line in r.stdout.splitlines() if line.strip()] if r.returncode == 0 else []
    jobs = [n for n in names if n.endswith(".json") and not n.endswith(".result.json")]
    for n in sorted(jobs):
        host = n.split("/")[1]
        job = n.split("/")[-1][:-5]
        res = f"{JOBS_DIR}/{host}/{job}.result.json"
        row = {"host": host, "job": job, "result": res in names}
        if row["result"]:
            try:
                doc = json.loads((remote_read(repo, res) or b"{}").decode("utf-8-sig"))
                row.update({"ok": doc.get("ok"), "blocker": doc.get("blocker"), "finished_at": doc.get("finished_at")})
            except ValueError:
                row["ok"] = "UNKNOWN"
        rows.append(row)
    return {"repo": str(repo), "jobs": rows}


# --------------------------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hub", type=Path, default=Path(HUB))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--target-host", required=True)
    s.add_argument("--kind", choices=("probe", "prompt", "converge"), default="probe")
    s.add_argument("--seat")
    s.add_argument("--prompt-file", type=Path)
    s.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)
    s.add_argument("--from", dest="source", default="ai_darkhero")
    s.add_argument("--no-push", action="store_true")
    t = sub.add_parser("tick")
    t.add_argument("--host")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--json", action="store_true")
    st = sub.add_parser("status")
    st.add_argument("--json", action="store_true")
    r = sub.add_parser("results")
    r.add_argument("--job", required=True)
    r.add_argument("--json", action="store_true")
    a = ap.parse_args()
    hub = a.hub.resolve()
    if not hub.is_absolute() or not (hub / "_registry").is_dir():
        print(json.dumps({"ok": False, "error": "hub_not_absolute_or_missing_registry", "hub": str(a.hub)}))
        return 2
    repo = repo_root(hub)
    if not (repo / ".git").exists():
        print(json.dumps({"ok": False, "error": "fleet_skills_clone_missing", "repo": str(repo)}))
        return 2
    if a.cmd == "submit":
        prompt = a.prompt_file.read_text(encoding="utf-8") if a.prompt_file else None
        out = submit(repo, hub, a.target_host, a.kind, a.seat, prompt, a.ttl_hours, a.source, push=not a.no_push)
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1
    if a.cmd == "tick":
        out = tick(repo, hub, a.host, a.dry_run)
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1
    if a.cmd == "status":
        print(json.dumps(status(repo), ensure_ascii=False, indent=None if a.json else 1))
        return 0
    if a.cmd == "results":
        _fetch(repo)
        r = git(repo, "ls-tree", "-r", "--name-only", "origin/main", f"{JOBS_DIR}/")
        hits = [n for n in r.stdout.splitlines() if n.strip().endswith(f"/{a.job}.result.json")]
        if not hits:
            print(json.dumps({"ok": False, "error": "no_result_yet", "job": a.job}))
            return 1
        print((remote_read(repo, hits[0].strip()) or b"").decode("utf-8-sig"))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
