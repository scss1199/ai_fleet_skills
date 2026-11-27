#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""fleet-rogue-scheduler-sweep.py — OS tasks + repo schtasks junk vs HubClock canon.

Writes:
  _registry/fleet-rogue-schedulers.json
  _logs/fleet/rogue-scheduler-report.md

Usage:
  python fleet-rogue-scheduler-sweep.py

CITE: rules-blueprint#automation · hubclock skill · zt-foreground-guard.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import COMMON as HUB, REGISTRY, LOGS  # noqa: E402
from _subproc_win import run_hidden  # noqa: E402

OUT = os.path.join(REGISTRY, "fleet-rogue-schedulers.json")
REPORT = os.path.join(LOGS, "fleet", "rogue-scheduler-report.md")
MATRIX = os.path.join(REGISTRY, "project-matrix.json")
HOSTS = os.path.join(REGISTRY, "hosts.json")
CONTRACT = os.path.join(REGISTRY, "workspace-seat-contract.json")

# Enabled OS tasks matching these = violation unless in allowlist
TASK_PATTERNS = re.compile(
    r"ai_|claude|metadata|wallpaper|trader|fintrend|heartlink|ziyao|fracdigi|hub",
    re.I,
)
ALLOWED_DISABLED = {
    "ClaudeHubDeploy",
    "ClaudeHub_KeyPoolTick",
    "ClaudeWallpaperHealth",
    "ClaudeQuantDailyGitBackup",
}
# Install/create only. Mentions in docstrings/cites ("Register-ScheduledTask works")
# and HubClock restart via pythonw are NOT repo-schtasks violations.
REPO_BAD = re.compile(
    r"schtasks\s+/[Cc]reate\b|Register-ScheduledTask\s+-",
    re.I,
)
AGENT_FROM_PATH = re.compile(r"ai_[a-z0-9_]+|fracdigi", re.I)


def _sweep_diagnostic_context():
    """Diagnostic identity is optional and never blocks the original scan."""
    try:
        source_hash = None
        try:
            with open(__file__, "rb") as source:
                source_hash = hashlib.sha256(source.read()).hexdigest()
        except Exception:
            pass
        return {"run_id": uuid.uuid4().hex, "source_sha256": source_hash}
    except Exception:
        return None


def _record_sweep_phase(context, stage, event, started, *, seat=None, result=None, error=None):
    """Persist timing/count metadata only; never task names, commands or content."""
    try:
        if context is None:
            return
        seat_name = seat if isinstance(seat, str) and re.fullmatch(r"ai_[a-z0-9_]+|fracdigi", seat) else None
        record = {
            "schema": 1,
            "run_id": context["run_id"],
            "source_sha256": context["source_sha256"],
            "pid": os.getpid(),
            "stage": stage,
            "event": event,
            "seat": seat_name,
            "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
            "elapsed_ms": round(max(0, time.monotonic() - started) * 1000, 3),
            "result_count": len(result) if type(result) in (list, tuple, dict, set) else None,
            "exception_type": type(error).__name__ if error is not None else None,
        }
        directory = os.path.join(LOGS, "fleet")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "rogue-scheduler-phases.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    except Exception:
        pass


def _timed_sweep_phase(context, stage, function, *args, seat=None):
    started = time.monotonic()
    _record_sweep_phase(context, stage, "start", started, seat=seat)
    try:
        result = function(*args)
    except BaseException as error:
        _record_sweep_phase(context, stage, "exception", started, seat=seat, error=error)
        raise
    _record_sweep_phase(context, stage, "finish", started, seat=seat, result=result)
    return result


def _load(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default if default is not None else {}


def _agents():
    doc = _load(MATRIX, {})
    out = []
    for _k, meta in (doc.get("projects") or {}).items():
        p = meta.get("path")
        if not p:
            continue
        base = os.path.basename(p.rstrip("/\\"))
        if base.startswith("ai_") or base == "fracdigi":
            out.append((base, os.path.join(HUB, p)))
    return sorted(out)


def _hubclock_cmds():
    hosts = _load(HOSTS, {})
    cmds = []
    for _host, block in (hosts.get("hosts") or {}).items():
        for r in block.get("riders") or []:
            c = (r.get("command") or "").strip()
            if c:
                cmds.append(c.lower())
    return cmds


def _query_schtasks():
    rows = []
    try:
        r = run_hidden(
            ["schtasks", "/Query", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            return rows
        for line in (r.stdout or "").splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) < 3:
                continue
            name = parts[0].lstrip("\\")
            if not TASK_PATTERNS.search(name):
                continue
            nxt, status = parts[1], parts[2]
            rows.append({"task": name, "next_run": nxt, "status": status})
    except OSError:
        pass
    return rows


def _task_detail(task_name):
    try:
        r = run_hidden(
            ["schtasks", "/Query", "/TN", "\\" + task_name, "/FO", "LIST", "/V"],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            return {}
        txt = r.stdout or ""
        out = {}
        for key in ("Task To Run", "Status", "Repeat: Every"):
            m = re.search(rf"^{re.escape(key)}:\s+(.+)$", txt, re.M)
            if m:
                out[key.lower().replace(" ", "_").replace(":", "")] = m.group(1).strip()
        return out
    except OSError:
        return {}


def _is_comment_line(path: str, line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    low = path.lower()
    if low.endswith(".ps1") or low.endswith(".py"):
        return s.startswith("#")
    if low.endswith((".bat", ".cmd")):
        return s.upper().startswith("REM ") or s.startswith("::") or s.startswith("@REM")
    if low.endswith(".md"):
        # charter docs often mention forbidden patterns — not install scripts
        return True
    if low.endswith(".vbs"):
        return s.startswith("'")
    return False


def _scan_repo_scripts(agent, root):
    hits = []
    skip = {".git", ".venv", "node_modules", "__pycache__", ".whisper-env", "_archive", "_delete",
            # bundled skill copies (.agents/.claude/.cursor, .fames.previous-*) carry the hub's own hooks and rule
            # text, not installers: ai_wallpaper on SCAR3 2026-11-10 got 17 false hits from them
            ".agents", ".claude", ".cursor"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".fames.previous")]
        for fn in filenames:
            if not fn.endswith((".ps1", ".vbs", ".bat", ".cmd", ".py")):
                continue
            path = os.path.join(dirpath, fn)
            try:
                txt = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            # Whole-file prefilter: almost no file names a scheduler verb, and the per-line comment test over
            # 8.5M lines made this sweep ~90 s (loop-engine's 120 s helper timeout fired 326 times).
            if not REPO_BAD.search(txt):
                continue
            for i, line in enumerate(txt.splitlines(), 1):
                if _is_comment_line(path, line):
                    continue
                if "re.compile" in line or REPO_BAD.search(line) and re.search(r"""\br['"]""", line):
                    continue        # a regex / raw-string literal that names the verb (a detector, not an installer)
                if REPO_BAD.search(line):
                    hits.append({
                        "file": path.replace(HUB + os.sep, ""),
                        "line": i,
                        "snippet": line.strip()[:120],
                    })
    return hits


def _agent_for_task(task_name, detail_cmd):
    if task_name.startswith("Microsoft") or "\\Microsoft\\" in task_name:
        return "system"
    blob = f"{task_name} {detail_cmd or ''}".replace("\\", "/").lower()
    for agent, _root in _agents():
        key = agent.lower()
        short = key[3:] if key.startswith("ai_") else key
        if key in blob or short in blob or short in task_name.lower():
            return agent
    m = AGENT_FROM_PATH.search(blob)
    return m.group(0).lower() if m else "unknown"


def build():
    diagnostics = _sweep_diagnostic_context()
    hub_cmds = _hubclock_cmds()
    os_tasks = []
    for t in _timed_sweep_phase(diagnostics, "os-list", _query_schtasks):
        name = t["task"]
        status = (t.get("status") or "").lower()
        detail = _timed_sweep_phase(diagnostics, "os-detail", _task_detail, name)
        cmd = detail.get("task_to_run") or ""
        agent = _agent_for_task(name, cmd)
        on_hub = any(fragment in cmd.lower() for fragment in ("hubclock", "register-rider", "metadata-acq-tick"))
        for hc in hub_cmds:
            if hc and cmd.lower() and cmd.lower() in hc:
                on_hub = True
                break
        enabled = status == "ready"
        if agent == "system":
            continue
        violation = enabled and name not in ALLOWED_DISABLED
        if violation:
            kind = "rogue-os-task-enabled"
        elif enabled and name in ALLOWED_DISABLED:
            kind = "legacy-os-task-still-enabled"
        else:
            kind = "legacy-disabled"
        os_tasks.append({
            "task": name,
            "agent": agent,
            "enabled": enabled,
            "command": cmd[:300],
            "violation": kind if violation or (enabled and name in ALLOWED_DISABLED) else None,
            "fix": (
                "Disable-ScheduledTask -TaskName '%s'; migrate to HubClock rider (SUBMIT proposal)" % name
                if violation
                else ("Disable-ScheduledTask -TaskName '%s' (legacy, already HubClock replacement)" % name
                      if enabled and name in ALLOWED_DISABLED else None)
            ),
        })

    repo_hits = {}
    for agent, root in _agents():
        if not os.path.isdir(root):
            continue
        hits = _timed_sweep_phase(diagnostics, "repo-scan", _scan_repo_scripts, agent, root, seat=agent)
        if hits:
            repo_hits[agent] = hits

    contract = _load(CONTRACT, {})
    agents_out = []
    violators = []
    for agent, root in _agents():
        flags = []
        fixes = []
        agent_tasks = [t for t in os_tasks if t.get("agent") == agent and t.get("violation")]
        if agent_tasks:
            flags.append("rogue-os-task=%s" % ",".join(t["task"] for t in agent_tasks))
            fixes.extend(t["fix"] for t in agent_tasks if t.get("fix"))
            violators.append(agent)
        rh = repo_hits.get(agent) or []
        if rh:
            flags.append("repo-schtasks-scripts=%d" % len(rh))
            fixes.append("刪除/改寫 schtasks/Register-ScheduledTask → HubClock register-rider 提案")
        if flags:
            agents_out.append({
                "agent": agent,
                "flags": flags,
                "fixes": fixes,
                "repo_hits": rh[:8],
                "os_tasks": agent_tasks,
            })

    doc = {
        "schema": 1,
        "generated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "contract_version": contract.get("version"),
        "summary": {
            "enabled_rogue_os_tasks": sum(1 for t in os_tasks if t.get("violation") == "rogue-os-task-enabled"),
            "agents_with_repo_schtasks": len(repo_hits),
            "violator_agents": sorted(set(violators)),
        },
        "os_tasks": os_tasks,
        "agents": agents_out,
        "repo_schtasks": repo_hits,
    }
    return doc


def _write_report(doc):
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    s = doc["summary"]
    lines = [
        "# Rogue Scheduler Report",
        "",
        "Generated: **%s**" % doc["generated"],
        "",
        "## Summary",
        "",
        "| metric | value |",
        "|--------|------:|",
        "| enabled rogue OS tasks | %d |" % s["enabled_rogue_os_tasks"],
        "| agents with schtasks in repo | %d |" % s["agents_with_repo_schtasks"],
        "",
        "## Enabled OS tasks (must migrate to HubClock)",
        "",
    ]
    for t in doc["os_tasks"]:
        if t.get("violation") == "rogue-os-task-enabled":
            lines.append("### %s · %s" % (t["task"], t.get("agent", "?")))
            lines.append("- cmd: `%s`" % (t.get("command") or "—"))
            lines.append("- fix: %s" % (t.get("fix") or "—"))
            lines.append("")
    if not any(t.get("violation") == "rogue-os-task-enabled" for t in doc["os_tasks"]):
        lines.append("- (none)")
    lines.extend(["", "## Repo schtasks / Register-ScheduledTask", ""])
    for agent, hits in sorted((doc.get("repo_schtasks") or {}).items()):
        lines.append("### %s (%d hits)" % (agent, len(hits)))
        for h in hits[:5]:
            lines.append("- `%s:%d` %s" % (h["file"], h["line"], h["snippet"][:80]))
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:      # --help (or any argument) must not run a real sweep and rewrite the registry (scar3 2026-11-10)
        print(__doc__)
        return 0 if set(argv) <= {"-h", "--help"} else 2
    doc = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    _write_report(doc)
    s = doc["summary"]
    print(
        "fleet-rogue-scheduler: rogue_os=%d repo_agents=%d → %s"
        % (s["enabled_rogue_os_tasks"], s["agents_with_repo_schtasks"], OUT)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
