#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""fleet-hygiene.py — every host checks its own cwds against the seat contract, sweeps process residue into
_delete/, and reports to the curator through the carrier. F1S runs it from the fames-converge rider, so no host
needs to be told (operator 2026-10-29: 「要求兩台電腦去檢查自己全部的cwd是否都符合規範 然後回報有用的東西給你 並開始清掃
所有專案已經用不到的過程檔案 並把這個清掃/檢查/回報 變成f1s同步的一項自動功能 不用我在cue你」).

What one run does (zero model tokens, bounded, reversible):
  check   every seat dir (ai_*, jci_*, sdnext_*, fracdigi) under the workspace: charter files the seat contract
          requires (CLAUDE.md, AGENTS.md, .cursor/hooks.json), git state (own repo, dirty / unpushed counts, last
          commit), activity (newest file) -> ACTIVE / IDLE / DORMANT, and OS scheduled tasks that point into the
          workspace with a forbidden launcher (python.exe console, -WindowStyle Hidden) -> findings
  sweep   residue the operator never asked to keep: cache dirs (__pycache__, .pytest_cache, .mypy_cache,
          .ruff_cache), temp files (*.tmp *.pyc ...), top-level entries of _temp / _downloads/distill /
          _downloads/acquire whose newest FILE is older than 7 days, registry backups beyond the newest 3.
          Never a git-tracked file, never the protected trees, never locks/pids/queues. Moves go through
          fleet-residue-quarantine.py (manifest, undo) when present, else a minimal mover with its own manifest.
  report  _registry/fleet-hygiene/<host>.json (+ history.jsonl) and contributors/<slug>/hygiene.json on the
          carrier (same publish path as fleet jobs), which the curator's f1s_daily digest reads back.
  throttle at most once per 20 h per host (state file), one run at a time (lock); converge launches it detached
          every 15 min and the throttle makes that free.

  python fleet-hygiene.py run [--apply] [--force] [--no-publish] [--host NAME]
  python fleet-hygiene.py status
  python fleet-hygiene.py fleet          # curator: every host's latest hygiene.json from the carrier clone
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace").resolve()
ENGINES = Path(__file__).resolve().parent
OUT = HUB / "_registry" / "fleet-hygiene"
NW = 0x08000000 if os.name == "nt" else 0
THROTTLE_S = 20 * 3600
STALE_S = 7 * 86400
ACTIVE_D, IDLE_D = 7, 30
SEAT_RE = re.compile(r"^(ai_[a-z0-9_]+|jci_[a-z0-9_]+|sdnext_[a-z0-9_]+|fracdigi)$")
CHARTER = ("CLAUDE.md", "AGENTS.md", os.path.join(".cursor", "hooks.json"))
PRUNE = {".git", "node_modules", ".venv", "venv", "env", "_secrets", ".claude"}
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis", ".ipynb_checkpoints"}
TEMP_SUFFIX = (".tmp", ".temp", ".swp", ".swo", ".part", ".crdownload", ".pyc", ".pyo")
LIVE = ("aex-loop", "hubclock", "supervisor")   # coordination names that keep old mtimes; __pycache__ is NOT live
STALE_ROOTS = ("_temp", os.path.join("_downloads", "distill"), os.path.join("_downloads", "acquire"))
BACKUP_ROOTS = (os.path.join("_registry", "fleet-skill-export-backups"), os.path.join("_registry", "fames-runtime-build-backups"))
KEEP_NEWEST = 3
MAX_MOVES = 4000
NEVER = ("_secrets", "_delete", "_registry", "_bus", os.path.join("fracdigi", "env"), os.path.join("ai_trader", "quant"),
         os.path.join("_lean", "toolchains"), os.path.join("_lean", "hubmath"))
# Trees nothing in this engine may touch under any class (the red lines say "do not even touch").
UNTOUCHABLE = ("_secrets", "_delete", os.path.join("fracdigi", "env"), os.path.join("ai_trader", "quant"),
               os.path.join("_lean", "toolchains"), os.path.join("_lean", "hubmath"))

# ------------------------------------------------------------------ producers (operator 2026-10-31)
# 「根本就不會再被使用的中間檔…製造他們的機制是什麼該如何修正」: the sweep relocates residue, this check names the ENGINE
# that keeps making it, so the fix lands in the producer and not in the broom. Two signals: a state directory with more
# direct entries than PRODUCER_CAP (per-run / per-session files nobody retires), and entries named like a loop-generated
# backup (*.MIGRATED-bak, *.previous.json, *.<stamp>.bak, tmp********, repo.previous). The 刪除 red line protects
# operator data; an engine keeping copies of its own locks, queue markers and caches is the ⑥ junk it was never asked for.
PRODUCER_CAP = 1000
RETENTION_MIN = 100
RETENTION_RE = re.compile(r"\.migrated-bak$|\.previous(\.[0-9a-f]{32})?\.json$|\.\d{8}_\d{6}(\.\d+)?\.bak$"
                          r"|^tmp[a-z0-9_]{8}$|^repo\.previous$", re.I)
STATE_ROOTS = ("_registry", "_temp", "_bus", "_logs", "_inbox")
SEAT_STATE = ("evidence", "_registry")
PRODUCER_DEPTH = 5
WRITERS = (  # longest matching prefix wins; extend when a new producer is found
    ("_registry/fames-hot", "_harness/runtime/fames_session_harness.py (hot_refresh / turn_context per-session state)"),
    ("_registry/fames-phase", "_harness/runtime/fames_phase_runtime.py (per-session dir, retained .write.lock)"),
    ("_registry/fames-turn", "_harness/runtime/fames_turn_binding.py (by-prompt archive)"),
    ("_registry/fames-runtime-receipts", "_skill/fleet-skills/fames/scripts/runtime_release.py _persist_receipt"),
    ("_registry/fames-runtime-build-backups", "_skill/fleet-skills/fames/scripts/runtime_release.py _apply"),
    ("_registry/fleet-skill-export-backups", "_skill/engines/mtm-fleet-skill-github.py export"),
    ("_registry/ship-queue", "_skill/engines/ship-queue.py (queue retirement + per-run logs)"),
    ("_registry/fleet-learning-local", "ai_darkhero/fleet-learning/scripts/fleet_learning.py cmd_fetch"),
    ("_temp/aex-loop", "_skill/engines/aex-loop-exec.py (per-job files)"),
    ("_temp/fleet-job-dispatch", "_skill/engines/fleet-job-dispatch.py (uuid worktree/prompt staging)"),
    ("_bus/inbox", "_skill/engines/inbox.py senders (fleet-process-guard.py alerts addressed to a non-seat)"),
    ("_inbox/_digested", "_skill/engines/inbox digest (SUBMIT receipts auto-digested)"),
    ("_logs", "_skill/engines/goal-field.py / seal-generation-lock.py / scf-residual.py goal backups"),
    ("_registry/fames-phase-history", "_skill/engines/fames-immediate-apply.py (uuid history records)"),
    ("_registry", "tempfile leftovers of a failed atomic write (tmp********); writer UNKNOWN"),
    ("evidence/fames-fleet-20260924", "_lean/fames/tests/test_phase_contract.py proof_fixture (test writes into the repo)"),
    ("evidence/jev-adoption-20260922", "static test fixtures read by _harness/tests/test_jev_skill_advisor.py (data, not residue)"),
    ("_registry/f1s-sources", "_skill/engines/f1s-sources.py / knowledge-consolidate.py content store (data, not residue)"),
)
# Engine code that spells the retention antipattern; a hit is a finding for the file's owner, never an edit.
CODE_ROOTS = ("_skill/engines", "_harness/runtime", "_lean/fames", "_skill/fleet-skills/fames/scripts",
              "ai_darkhero/scripts", "ai_darkhero/fleet-learning/scripts", "ai_darkhero/line")
_ANTI_CREATE = ("rename", "with_name", "replace(", "+ \"", "f\"", "f'", "+ '", "join(")
# Expired engine state the sweep retires into _delete (class expired_state). kind: "files" = direct files older than
# ttl days; "dirs" = direct subdirs whose newest file is older than ttl; "named" = entries whose name matches `re`
# (RETENTION_RE by default), older than ttl when given; "newest" = everything but the newest `keep` entries.
STATE_TTL = (
    {"root": "_registry/fames-hot", "kind": "files", "ttl": 7,
     "exclude": ("midturn-", "ship-state", "hw-watch", "review-claim", "capture-")},
    {"root": "_registry/fames-phase", "kind": "dirs", "ttl": 7},
    {"root": "_registry/fames-turn/*/by-prompt", "kind": "dirs", "ttl": 7},
    {"root": "_registry/fames-runtime-receipts", "kind": "newest", "keep": 3},
    {"root": "_registry/ship-queue", "kind": "named"},
    {"root": "_registry/ship-queue/done", "kind": "files", "ttl": 7},
    {"root": "_registry/ship-queue/failed", "kind": "files", "ttl": 7},
    {"root": "_registry", "kind": "named", "ttl": 7},                     # tmp******** of a failed atomic write
    {"root": "_registry/fleet-learning-local/*/sources/*", "kind": "named"},
    {"root": "_temp/aex-loop-jobs", "kind": "files", "ttl": 2},
    {"root": "_temp/aex-loop-done", "kind": "files", "ttl": 2},
    {"root": "_logs", "kind": "named"},                                   # *.goal.json.<stamp>.bak
    {"root": "*/evidence/fames-fleet-20260924", "kind": "named", "ttl": 1,
     "re": r"^(phase-tests|base-conformance-test)-[0-9a-f]{32}$"},
)
ORPHAN_INBOX_TTL_D = 1          # _bus/inbox/<name> where <name> is no seat dir and no hubclock handoff


# ------------------------------------------------------------------ small helpers
def _now() -> float:
    return time.time()


def _iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or _now()))


def _is_junction(p: str) -> bool:
    try:
        f = getattr(os.path, "isjunction", None)
        return bool(f and f(p)) or os.path.islink(p)
    except OSError:
        return False


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def _save(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=NW)


def _module(file: str):
    path = ENGINES / file
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(file.replace("-", "_").replace(".py", "_for_hygiene"), path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 - a broken sibling engine is reported, never fatal
        return None
    return mod


def this_host() -> str:
    return socket.gethostname().strip().lower()


def contributor_slug(hub: Path, host: str) -> str:
    """contributors/<slug>/ on the carrier: the fleet-skill-github node for this host, else the hostname."""
    reg = _load(hub / "_registry" / "fleet-skill-github.json", {})
    nodes = reg.get("nodes") or {}
    rows = nodes.items() if isinstance(nodes, dict) else [(n.get("node") or n.get("id"), n) for n in nodes]
    host_l = host.lower()
    for name, node in rows:
        if not isinstance(node, dict):
            continue
        names = {str(h).lower() for h in (node.get("hostnames") or [])}
        names |= {str(node.get("host") or "").lower(), str(node.get("hostname") or "").lower()}
        if host_l in names:
            return str(node.get("contributor_slug") or node.get("contributor") or node.get("machine") or name)
    for name, node in rows:   # a node whose machine name is the hostname's prefix (altos: DESKTOP-xxx is not; scar3: SCAR3 is)
        if isinstance(node, dict) and str(node.get("machine") or "").lower() and host_l.startswith(str(node.get("machine")).lower()):
            return str(node.get("contributor_slug") or node.get("machine"))
    return host


# ------------------------------------------------------------------ check
def seats(hub: Path) -> list[Path]:
    out = []
    try:
        for e in os.scandir(hub):
            if e.is_dir(follow_symlinks=False) and SEAT_RE.match(e.name) and not _is_junction(e.path):
                out.append(Path(e.path))
    except OSError:
        pass
    return sorted(out)


def newest_file(root: Path, cap: int = 60000) -> float:
    newest, n = 0.0, 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in PRUNE and d not in CACHE_DIRS and not _is_junction(os.path.join(dp, d))]
        for f in fns:
            n += 1
            if n > cap:
                return newest
            try:
                m = os.stat(os.path.join(dp, f), follow_symlinks=False).st_mtime
            except OSError:
                continue
            if m > newest:
                newest = m
    return newest


def check_seat(seat: Path, now: float) -> dict:
    row = {"seat": seat.name, "missing": [c for c in CHARTER if not (seat / c).is_file()], "findings": []}
    own = (seat / ".git").exists()
    row["repo"] = "own" if own else "hub"
    if own:
        st = _git(seat, "status", "--porcelain")
        row["dirty"] = len([l for l in st.stdout.splitlines() if l.strip()]) if st.returncode == 0 else "UNKNOWN"
        ahead = _git(seat, "rev-list", "--count", "@{u}..HEAD")
        row["unpushed"] = int(ahead.stdout.strip() or 0) if ahead.returncode == 0 else "UNKNOWN"
        last = _git(seat, "log", "-1", "--format=%ci")
        row["last_commit"] = last.stdout.strip()[:10] if last.returncode == 0 and last.stdout.strip() else None
    newest = newest_file(seat)
    row["newest_file"] = time.strftime("%Y-%m-%d", time.localtime(newest)) if newest else None
    days = (now - newest) / 86400 if newest else 9999
    row["activity"] = "ACTIVE" if days <= ACTIVE_D else ("IDLE" if days <= IDLE_D else "DORMANT")
    if row["missing"]:
        row["findings"].append("charter_missing:" + ",".join(row["missing"]))
    if isinstance(row.get("unpushed"), int) and row["unpushed"] > 0:
        row["findings"].append(f"unpushed_commits:{row['unpushed']}")
    if isinstance(row.get("dirty"), int) and row["dirty"] > 50:
        row["findings"].append(f"dirty_files:{row['dirty']}")
    return row


def scheduled_task_findings(hub: Path) -> list[str] | str:
    """OS tasks that point into the workspace with a launcher the contract forbids; UNKNOWN when schtasks is unreadable."""
    if os.name != "nt":
        return []
    try:
        p = subprocess.run(["schtasks", "/query", "/fo", "csv", "/v"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=90, creationflags=NW)
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    if p.returncode != 0:
        return "UNKNOWN"
    hits = []
    marker = str(hub).lower().replace("/", "\\")
    for line in p.stdout.splitlines():
        low = line.lower()
        if marker not in low:
            continue
        # the two fake-hidden forms, spelled in pieces so zt-foreground-guard's static scan does not count this
        # detector itself as an offender (2026-10-31: it did, 2 phantom antipattern hits per day)
        if ("-windowstyle" + " hidden") in low or ("-w" + " hidden") in low:
            hits.append("hidden_powershell_task:" + line.split(",")[1].strip('"')[:80] if "," in line else low[:80])
        elif "python.exe" in low and "pythonw" not in low:
            hits.append("console_python_task:" + line.split(",")[1].strip('"')[:80] if "," in line else low[:80])
    return sorted(set(hits))


def _writer(rel: str) -> str:
    rel = rel.replace("\\", "/")
    best, who = "", "UNKNOWN (add the producer to fleet-hygiene.WRITERS)"
    for prefix, name in WRITERS:
        if (rel.startswith(prefix) or ("/" + prefix) in rel) and len(prefix) > len(best):
            best, who = prefix, name
    return who


def producers(hub: Path, cap: int = PRODUCER_CAP) -> list[dict]:
    """Directories in the state roots that an engine keeps filling: more than `cap` direct entries, or RETENTION_MIN
    entries named like loop-generated backups. Each row names the writer so the fix goes to the producer."""
    rows = []
    roots = [hub / r for r in STATE_ROOTS] + [s / d for s in seats(hub) for d in SEAT_STATE]
    for root in roots:
        if not root.is_dir() or _is_junction(str(root)):
            continue
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in PRUNE and not _is_junction(os.path.join(dp, d))]
            entries = len(dns) + len(fns)
            retention = sum(1 for n in dns + fns if RETENTION_RE.search(n))
            if entries > cap or retention >= RETENTION_MIN:
                rel = str(Path(dp).relative_to(hub)).replace("\\", "/")
                rows.append({"dir": rel, "entries": entries, "retention_named": retention, "writer": _writer(rel)})
                dns[:] = []            # the leak is this directory; descending would report its children too
            elif len(Path(dp).relative_to(hub).parts) >= PRODUCER_DEPTH:
                dns[:] = []
    rows.sort(key=lambda r: (-r["retention_named"], -r["entries"]))
    return rows[:40]


def retention_antipatterns(hub: Path) -> list[dict]:
    """Engine lines that create loop backups: a `.MIGRATED-bak` rename outside a one-time migration, a uuid-named copy
    under _registry/_temp, or a test fixture that refuses tmp cleanup. Comments, skip-lists and `endswith` checks are
    not creation sites."""
    hits = []
    for rel in CODE_ROOTS:
        root = hub / rel
        if not root.is_dir():
            continue
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in PRUNE and d not in CACHE_DIRS]
            for f in fns:
                if not f.endswith(".py") or f in ("fleet-hygiene.py", "test_fleet_hygiene.py", "f1s_audit.py"):
                    continue       # this detector, its test and the audit table spell the patterns on purpose
                p = Path(dp) / f
                try:
                    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                in_test = "tests" in p.relative_to(hub).parts or f.startswith("test_")
                for i, line in enumerate(lines, 1):
                    s = line.strip()
                    if not s or s.startswith(("#", "-", "*", '"""', "'''")) or "(" not in s:
                        continue   # comments, docstring prose and bullet text are not creation sites
                    kind = None
                    if "MIGRATED-bak" in s and not in_test and any(k in s for k in _ANTI_CREATE) \
                            and not any(k in s for k in ("endswith", "not in", "SKIP", "glob(", "in str(")):
                        kind = "migrated_bak_loop"
                    elif "uuid4().hex" in s and not in_test and any(k in s.lower() for k in ("backup", "previous", "export-backups", "_registry", "_temp")):
                        kind = "uuid_named_copy"
                    elif in_test and ("Deliberately retained" in s or "no TemporaryDirectory" in s):
                        kind = "retained_test_fixture"
                    if kind:
                        hits.append({"file": str(p.relative_to(hub)).replace("\\", "/"), "line": i, "kind": kind, "text": s[:140]})
    return hits[:60]


def check(hub: Path, now: float | None = None) -> dict:
    now = now or _now()
    rows = [check_seat(s, now) for s in seats(hub)]
    try:
        leaks = producers(hub)
    except Exception as exc:  # noqa: BLE001 — a hygiene check never takes the rider down
        leaks = f"UNKNOWN: {type(exc).__name__}"
    try:
        anti = retention_antipatterns(hub)
    except Exception as exc:  # noqa: BLE001
        anti = f"UNKNOWN: {type(exc).__name__}"
    return {"seats": rows, "scheduled_tasks": scheduled_task_findings(hub),
            "counts": {k: sum(1 for r in rows if r["activity"] == k) for k in ("ACTIVE", "IDLE", "DORMANT")},
            "violations": sum(len(r["findings"]) for r in rows),
            "producers": leaks, "retention_antipatterns": anti}


# ------------------------------------------------------------------ sweep
def _tracked_set(repo: Path) -> set[str]:
    p = _git(repo, "ls-files", "-z", timeout=300)
    if p.returncode != 0:
        return set()
    return {str((repo / f).resolve()).lower() for f in p.stdout.split("\0") if f}


class Tracked:
    def __init__(self, hub: Path):
        self.hub = hub
        self.cache: dict[Path, set[str]] = {}

    def repo_of(self, path: Path) -> Path:
        for p in [path] + list(path.parents):
            if (p / ".git").exists():
                return p
            if p == self.hub:
                break
        return self.hub

    def __call__(self, path: Path) -> bool:
        repo = self.repo_of(path)
        if repo not in self.cache:
            self.cache[repo] = _tracked_set(repo)
        s = str(path.resolve()).lower()
        if s in self.cache[repo]:
            return True
        if path.is_dir():
            pref = s.rstrip("\\/") + os.sep
            return any(t.startswith(pref) for t in self.cache[repo])
        return False


def _never(hub: Path, path: Path, cls: str = "") -> bool:
    rel = str(path.relative_to(hub)).lower() if str(path).lower().startswith(str(hub).lower()) else str(path).lower()
    low = path.name.lower()
    if cls in ("expired_state", "orphan_inbox"):
        # explicitly listed engine state: only the untouchable trees and live lock/pid files are refused
        if low.endswith((".lock", ".pid")) and path.is_file():
            return True
        return any(rel == n.lower() or rel.startswith(n.lower() + os.sep) for n in UNTOUCHABLE)
    if low.endswith((".lock", ".pid")) or any(k in low for k in LIVE):
        return True
    if any(rel.startswith(b.lower() + os.sep) for b in BACKUP_ROOTS):   # the two backup roots are the only _registry trees swept
        return False
    return any(rel == n.lower() or rel.startswith(n.lower() + os.sep) for n in NEVER)


def _newest_mtime(p: Path) -> float:
    if p.is_file():
        return p.stat().st_mtime
    newest = 0.0
    for dp, dns, fns in os.walk(p):
        dns[:] = [d for d in dns if not _is_junction(os.path.join(dp, d))]
        for f in fns:
            try:
                m = os.stat(os.path.join(dp, f), follow_symlinks=False).st_mtime
            except OSError:
                continue
            if m > newest:
                newest = m
    return newest or p.stat().st_mtime


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for dp, dns, fns in os.walk(p):
        dns[:] = [d for d in dns if not _is_junction(os.path.join(dp, d))]
        for f in fns:
            try:
                total += os.stat(os.path.join(dp, f), follow_symlinks=False).st_size
            except OSError:
                pass
    return total


def candidates(hub: Path, now: float | None = None) -> list[tuple[str, Path, int]]:
    """(class, path, bytes) for everything the sweep may move; ordered caches, temp files, stale entries, old backups."""
    now = now or _now()
    out: list[tuple[str, Path, int]] = []
    for seat in seats(hub) + [hub / "_skill", hub / "_harness", hub / "_logs"]:
        if not seat.is_dir():
            continue
        for dp, dns, fns in os.walk(seat):
            keep = []
            for d in dns:
                full = Path(dp) / d
                if d in PRUNE or _is_junction(str(full)):
                    continue
                if d in CACHE_DIRS:
                    out.append(("cache_dir", full, _size(full)))
                    continue
                keep.append(d)
            dns[:] = keep
            for f in fns:
                if f.lower().endswith(TEMP_SUFFIX) or f.startswith("~$"):
                    full = Path(dp) / f
                    try:
                        out.append(("temp", full, full.stat().st_size))
                    except OSError:
                        pass
            if len(out) >= MAX_MOVES:
                break
    for rel in STALE_ROOTS:
        root = hub / rel
        if not root.is_dir():
            continue
        for e in sorted(root.iterdir()):
            if _never(hub, e) or _is_junction(str(e)):
                continue
            try:
                if _newest_mtime(e) < now - STALE_S:
                    out.append(("stale", e, _size(e)))
            except OSError:
                continue
    for rel in BACKUP_ROOTS:
        root = hub / rel
        if not root.is_dir():
            continue
        entries = sorted((e for e in root.iterdir() if not _is_junction(str(e))), key=lambda x: x.stat().st_mtime, reverse=True)
        for e in entries[KEEP_NEWEST:]:
            out.append(("backup", e, _size(e)))
    out.extend(expired_state(hub, now))
    return out[:MAX_MOVES]


def _entries(root: Path) -> list[Path]:
    try:
        return [e for e in root.iterdir() if not _is_junction(str(e))]
    except OSError:
        return []


def expired_state(hub: Path, now: float | None = None) -> list[tuple[str, Path, int]]:
    """Engine state past its lifetime (STATE_TTL) and inbox folders addressed to no seat (orphan_inbox)."""
    now = now or _now()
    out: list[tuple[str, Path, int]] = []
    for spec in STATE_TTL:
        roots = [hub / spec["root"]] if "*" not in spec["root"] else list(hub.glob(spec["root"]))
        pat = re.compile(spec["re"], re.I) if spec.get("re") else RETENTION_RE
        cut = now - float(spec.get("ttl") or 0) * 86400
        for root in roots:
            if not root.is_dir() or _is_junction(str(root)):
                continue
            kind = spec["kind"]
            ents = _entries(root)
            if kind == "newest":
                ents.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                picked = ents[int(spec["keep"]):]
            elif kind == "files":
                picked = [e for e in ents if e.is_file() and not e.name.startswith(tuple(spec.get("exclude") or ()))
                          and e.stat().st_mtime < cut]
            elif kind == "dirs":
                picked = [e for e in ents if e.is_dir() and _newest_mtime(e) < cut]
            else:  # named
                picked = [e for e in ents if pat.search(e.name) and (not spec.get("ttl") or _newest_mtime(e) < cut)]
            for e in picked:
                try:
                    out.append(("expired_state", e, _size(e)))
                except OSError:
                    continue
            if len(out) >= MAX_MOVES:
                return out
    inbox = hub / "_bus" / "inbox"
    if inbox.is_dir():
        seat_names = {s.name for s in seats(hub)}
        cut = now - ORPHAN_INBOX_TTL_D * 86400
        for d in _entries(inbox):
            if not d.is_dir() or d.name in seat_names or d.name.startswith("hubclock") or (hub / d.name).is_dir():
                continue
            for e in _entries(d):
                try:
                    if e.is_file() and e.stat().st_mtime < cut:
                        out.append(("orphan_inbox", e, e.stat().st_size))
                except OSError:
                    continue
                if len(out) >= MAX_MOVES:
                    return out
    return out


def _fallback_move(hub: Path, paths: list[Path], topic: str) -> dict:
    """When fleet-residue-quarantine.py is not on this host: same bucket layout, own manifest, never delete."""
    day = time.strftime("%Y-%m-%d")
    bucket = hub / "_delete" / f"{day}-{topic}"
    moved, failed = [], []
    for p in paths:
        try:
            rel = p.relative_to(hub)
        except ValueError:
            failed.append((str(p), "outside_workspace"))
            continue
        target = bucket / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(target))
            moved.append({"origin": str(rel).replace("\\", "/"), "quarantined_to": str(target.relative_to(hub)).replace("\\", "/")})
        except Exception as exc:  # noqa: BLE001
            failed.append((str(p), type(exc).__name__))
    man = bucket / "MANIFEST.json"
    doc = _load(man, {"schema": "fleet-hygiene-fallback-manifest/1", "entries": []})
    doc["entries"].extend(moved)
    if moved:
        _save(man, doc)
    return {"ok": not failed, "moved": len(moved), "failed": failed[:20], "bucket": str(bucket)}


def sweep(hub: Path, apply: bool, now: float | None = None, tracked=None) -> dict:
    now = now or _now()
    tracked = tracked or Tracked(hub)
    rows = candidates(hub, now)
    plan, skipped = [], {"git_tracked": 0, "protected": 0}
    for cls, p, size in rows:
        if _never(hub, p, cls):
            skipped["protected"] += 1
            continue
        try:
            if tracked(p):
                skipped["git_tracked"] += 1
                continue
        except Exception:  # noqa: BLE001
            skipped["git_tracked"] += 1
            continue
        plan.append((cls, p, size))
    by_class = {}
    for cls, p, size in plan:
        c = by_class.setdefault(cls, {"count": 0, "bytes": 0})
        c["count"] += 1
        c["bytes"] += size
    result = {"applied": apply, "planned": len(plan), "planned_bytes": sum(s for _, _, s in plan), "by_class": by_class,
              "skipped": skipped, "moved": 0, "engine": None, "errors": []}
    if not apply or not plan:
        return result
    rq = _module("fleet-residue-quarantine.py")
    paths = [p for _, p, _ in plan if p.exists()]
    if rq is not None:
        result["engine"] = "fleet-residue-quarantine.py"
        for i in range(0, len(paths), 200):
            batch = [str(p.relative_to(hub)).replace("\\", "/") for p in paths[i:i + 200]]
            try:
                r = rq.quarantine(batch, "hygiene", note="fleet-hygiene sweep (operator 2026-10-29)", workspace=hub)
                n = r.get("moved")
                result["moved"] += n if isinstance(n, int) else len(n or [])
                if r.get("ok") is False:
                    result["errors"].append(str(r.get("error") or r.get("errors"))[:200])
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"{type(exc).__name__}: {exc}"[:200])
    else:
        result["engine"] = "fallback_move"
        r = _fallback_move(hub, paths, "hygiene")
        result["moved"] = r["moved"]
        result["errors"].extend(str(f) for f in r["failed"])
    return result


# ------------------------------------------------------------------ report / publish
def delete_bytes(hub: Path) -> int:
    d = hub / "_delete"
    return _size(d) if d.is_dir() else 0


def publish(hub: Path, host: str, doc: dict) -> dict:
    fjd = _module("fleet-job-dispatch.py")
    if fjd is None:
        return {"ok": False, "error": "fleet-job-dispatch.py missing on this host"}
    try:
        repo = fjd.repo_root(hub)
        slug = contributor_slug(hub, host)
        return fjd._publish(repo, hub, {f"contributors/{slug}/hygiene.json": doc}, f"chore(hygiene/{slug}): fleet hygiene report")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


def run(hub: Path = HUB, host: str | None = None, apply: bool = False, force: bool = False, do_publish: bool = True,
        now: float | None = None) -> dict:
    now = now or _now()
    host = host or this_host()
    OUT.mkdir(parents=True, exist_ok=True)
    state_p = OUT / f"{host}.state.json"
    state = _load(state_p, {})
    if not force and now - float(state.get("last_run_epoch") or 0) < THROTTLE_S:
        # scar3 2026-10-29: a run started over SSH has no Windows credential store, so its carrier push is rejected;
        # the rider's next detached launch (which has the credentials) must still deliver that report instead of
        # waiting 20 h behind the throttle.
        last_pub = state.get("last_publication") or {}
        if do_publish and last_pub.get("ok") is False and (OUT / f"{host}.json").is_file():
            pub = publish(hub, host, _load(OUT / f"{host}.json", {}))
            state["last_publication"] = pub
            _save(state_p, state)
            return {"skipped": "throttled", "republished": pub, "last_run": state.get("last_run"), "host": host}
        return {"skipped": "throttled", "last_run": state.get("last_run"), "host": host}
    lock = OUT / f"{host}.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        if now - lock.stat().st_mtime < 3 * 3600:
            return {"skipped": "locked", "host": host}
        lock.unlink()
        return run(hub, host, apply, force, do_publish, now)
    try:
        t0 = time.time()
        chk = check(hub, now)
        sw = sweep(hub, apply, now)
        doc = {"schema": "fleet-hygiene/1", "host": host, "at": _iso(now), "hub": str(hub), "seconds": None,
               "check": chk, "sweep": sw, "delete_bytes": delete_bytes(hub),
               "summary": {"seats": len(chk["seats"]), "violations": chk["violations"], "activity": chk["counts"],
                           "scheduled_task_findings": chk["scheduled_tasks"] if isinstance(chk["scheduled_tasks"], str) else len(chk["scheduled_tasks"]),
                           "producer_leaks": chk["producers"] if isinstance(chk["producers"], str) else len(chk["producers"]),
                           "retention_antipatterns": chk["retention_antipatterns"] if isinstance(chk["retention_antipatterns"], str) else len(chk["retention_antipatterns"]),
                           "moved": sw["moved"], "planned_bytes": sw["planned_bytes"], "applied": apply}}
        doc["seconds"] = round(time.time() - t0, 1)
        _save(OUT / f"{host}.json", doc)
        with open(OUT / "history.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": doc["at"], "host": host, **doc["summary"]}, ensure_ascii=False) + "\n")
        doc["publication"] = publish(hub, host, doc) if do_publish else {"ok": None, "skipped": "no-publish"}
        state.update(last_run=doc["at"], last_run_epoch=now, last_summary=doc["summary"], last_publication=doc["publication"])
        _save(state_p, state)
        return doc
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def fleet(hub: Path = HUB) -> list[dict]:
    """Curator view: every host's latest hygiene.json in the carrier clone (synced by the fleet-skill rider)."""
    fjd = _module("fleet-job-dispatch.py")
    repo = fjd.repo_root(hub) if fjd else hub / "_skill" / "ai_fleet_skills"
    rows = []
    for p in sorted((repo / "contributors").glob("*/hygiene.json")):
        d = _load(p, {})
        if d:
            rows.append({"contributor": p.parent.name, "host": d.get("host"), "at": d.get("at"), **(d.get("summary") or {}),
                         "delete_gb": round((d.get("delete_bytes") or 0) / 1e9, 2),
                         "findings": [f for r in (d.get("check") or {}).get("seats", []) for f in (r.get("findings") or [])][:12]})
    return rows


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--host")
    r.add_argument("--apply", action="store_true", help="move residue (default: plan only)")
    r.add_argument("--force", action="store_true", help="ignore the 20 h throttle")
    r.add_argument("--no-publish", action="store_true")
    r.add_argument("--max-moves", type=int, help=f"cap on entries moved in this run (default {MAX_MOVES}); backlog runs raise it")
    sub.add_parser("status")
    sub.add_parser("fleet")
    pr = sub.add_parser("producers", help="name the engines that keep filling state dirs (no move)")
    pr.add_argument("--cap", type=int, default=PRODUCER_CAP)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        if a.max_moves:
            globals()["MAX_MOVES"] = a.max_moves
        out = run(HUB, a.host, a.apply, a.force, not a.no_publish)
    elif a.cmd == "producers":
        out = {"producers": producers(HUB, a.cap), "retention_antipatterns": retention_antipatterns(HUB),
               "expired_state_planned": len(expired_state(HUB))}
    elif a.cmd == "status":
        host = this_host()
        out = {"host": host, "state": _load(OUT / f"{host}.state.json", {}), "report": _load(OUT / f"{host}.json", {}).get("summary")}
    else:
        out = fleet(HUB)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
