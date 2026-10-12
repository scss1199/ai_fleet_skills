#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
r"""f1s-transcript-audit.py — sweep every Claude Code conversation on this machine for lying and 推託.

Operator 2026-10-13: 「現在自動去所有對話裡去撈對話紀錄 老找到模型的表現尤其是說謊與推託的部分要嚴格處理與禁止」.

What it does (read-only over the transcripts, zero model tokens, zero foreground):
  * walks ~/.claude/projects/*/*.jsonl (every seat, every session) incrementally — a transcript whose
    (size, mtime) is unchanged since the last sweep is not re-read;
  * replays the SAME judge the live PROOF Stop hook runs (`claude-proof-hook.py`: facts + judge +
    closing_text), turn by turn, with the session's earlier 「需要你決定」 lines, so the offline verdict
    is the live verdict;
  * writes ONE state file `_registry/f1s-transcript-audit.json` (per seat and per session: turns,
    turns that would block, per-class counts, the worst lines) — machine state, not a report;
  * the session hook (`claude_session_hook.py`) injects each seat's own record at SessionStart
    (「F1S RECORD」) and starts this sweep hidden when the state is older than `max_age_hours`.

Hard lines: never spawns a window (CREATE_NO_WINDOW), never deletes, writes nothing but the state file
and its lock, caps per-transcript work (MAX_TURNS) so a runaway log cannot pin the CPU.

  python f1s-transcript-audit.py run [--full] [--max-age-hours 6] [--json]
  python f1s-transcript-audit.py record --seat ai_darkhero        # one line for the session hook
  python f1s-transcript-audit.py status [--json]
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace")
HOOK = HUB / "_skill" / "engines" / "claude-proof-hook.py"
PROJECTS = Path.home() / ".claude" / "projects"
STATE = HUB / "_registry" / "f1s-transcript-audit.json"
LOCK = STATE.with_suffix(".lock")
SCHEMA = "f1s-transcript-audit/1"
MAX_TURNS = 400           # per transcript, newest first
MAX_BYTES = 96 * 1024 * 1024
WORST_KEEP = 6
NW = 0x08000000 if os.name == "nt" else 0


def _hook():
    spec = importlib.util.spec_from_file_location("claude_proof_hook_for_audit", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seat_of(project_dir: str) -> str:
    # C--ai-workspace-ai-trader -> ai_trader ; C--ai-workspace -> hub
    name = project_dir
    if name == "C--ai-workspace":
        return "hub"
    if name.startswith("C--ai-workspace-"):
        rest = name[len("C--ai-workspace-"):]
        head = rest.split("--")[0]
        return head.replace("-", "_") if head else "hub"
    return "other"


def _rows(path: Path):
    with path.open("rb") as fh:
        size = fh.seek(0, os.SEEK_END)
        start = max(0, size - MAX_BYTES)
        fh.seek(start)
        data = fh.read()
    lines = data.split(b"\n")
    if start:
        lines = lines[1:]
    out = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(row, dict) and row.get("type") in {"user", "assistant"}:
            out.append(row)
    return out


def audit_transcript(hook, path: Path, cfg: dict) -> dict:
    rows = _rows(path)
    # split into turns at human prompts
    turns = []
    i = 0
    while i < len(rows):
        if not hook._is_human_prompt(rows[i]):
            i += 1
            continue
        j = i + 1
        while j < len(rows) and not hook._is_human_prompt(rows[j]):
            j += 1
        turns.append((rows[i], rows[i + 1:j]))
        i = j
    turns = turns[-MAX_TURNS:]
    earlier: list[str] = []
    per_class: collections.Counter = collections.Counter()
    blocked = 0
    judged = 0
    worst: list = []
    first_ts = str((turns[0][0].get("timestamp") if turns else "") or "")[:19]
    last_ts = str((turns[-1][0].get("timestamp") if turns else "") or "")[:19]
    for prompt, body in turns:
        text = hook.closing_text(body)
        if text.strip():
            judged += 1
            try:
                f = hook.facts(body, prompt, "")
                v = hook.judge(text, f, cfg, "", earlier)
            except Exception:  # noqa: BLE001 — one bad turn never stops the sweep
                v = []
            if v:
                blocked += 1
                for item in v:
                    per_class[item["class"]] += 1
                    if len(worst) < WORST_KEEP:
                        worst.append({"ts": str(prompt.get("timestamp") or "")[:16], "class": item["class"],
                                      "line": item["snippet"][:80]})
        for row in body:
            if row.get("type") == "assistant":
                for b in hook._blocks(row):
                    if isinstance(b, dict) and b.get("type") == "text":
                        for ln in str(b.get("text") or "").splitlines():
                            if hook.LIE_PATTERNS["decision"].search(ln):
                                earlier.append(ln.strip())
    return {"turns": judged, "blocked": blocked, "per_class": dict(per_class), "worst": worst,
            "first": first_ts, "last": last_ts, "decisions": len(earlier)}


def load_state() -> dict:
    try:
        doc = json.loads(STATE.read_text(encoding="utf-8-sig"))
        return doc if isinstance(doc, dict) and doc.get("schema") == SCHEMA else {}
    except (OSError, ValueError):
        return {}


def save_state(doc: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_name(STATE.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, STATE)


def run(full: bool = False) -> dict:
    hook = _hook()
    cfg = hook._config()
    prev = load_state()
    sessions = {} if full else dict(prev.get("sessions") or {})
    started = time.time()
    scanned = skipped = 0
    for proj in sorted(PROJECTS.glob("*")):
        if not proj.is_dir():
            continue
        seat = seat_of(proj.name)
        for tr in sorted(proj.glob("*.jsonl")):
            try:
                st = tr.stat()
            except OSError:
                continue
            key = f"{proj.name}/{tr.stem}"
            old = sessions.get(key)
            if old and old.get("size") == st.st_size and int(old.get("mtime") or 0) == int(st.st_mtime):
                skipped += 1
                continue
            try:
                res = audit_transcript(hook, tr, cfg)
            except Exception as exc:  # noqa: BLE001
                res = {"turns": 0, "blocked": 0, "per_class": {}, "worst": [], "error": type(exc).__name__}
            res.update({"seat": seat, "size": st.st_size, "mtime": int(st.st_mtime), "audited_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
            sessions[key] = res
            scanned += 1
    seats: dict = {}
    for key, s in sessions.items():
        agg = seats.setdefault(s.get("seat", "?"), {"sessions": 0, "turns": 0, "blocked": 0, "per_class": collections.Counter(), "worst": []})
        agg["sessions"] += 1
        agg["turns"] += int(s.get("turns") or 0)
        agg["blocked"] += int(s.get("blocked") or 0)
        agg["per_class"].update(s.get("per_class") or {})
        if len(agg["worst"]) < WORST_KEEP:
            agg["worst"].extend(s.get("worst") or [])
    for agg in seats.values():
        agg["per_class"] = dict(agg["per_class"])
        agg["worst"] = agg["worst"][:WORST_KEEP]
        agg["block_rate"] = round(agg["blocked"] / agg["turns"], 3) if agg["turns"] else None
    total_turns = sum(a["turns"] for a in seats.values())
    total_blocked = sum(a["blocked"] for a in seats.values())
    doc = {"schema": SCHEMA, "generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "hook_sha": _sha(HOOK),
           "elapsed_s": round(time.time() - started, 1), "scanned": scanned, "skipped_unchanged": skipped,
           "totals": {"sessions": len(sessions), "turns": total_turns, "blocked": total_blocked,
                      "block_rate": round(total_blocked / total_turns, 3) if total_turns else None,
                      "per_class": dict(sum((collections.Counter(a["per_class"]) for a in seats.values()), collections.Counter()))},
           "seats": dict(sorted(seats.items())), "sessions": sessions}
    save_state(doc)
    return doc


def _sha(path: Path) -> str:
    import hashlib
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return "UNKNOWN"


def record_line(seat: str) -> str:
    """One line for the session hook: the seat's own record, or UNKNOWN when there is no sweep yet."""
    doc = load_state()
    if not doc:
        return "F1S RECORD — UNKNOWN — no transcript sweep yet (f1s-transcript-audit.py run)"
    agg = (doc.get("seats") or {}).get(seat)
    tot = doc.get("totals") or {}
    if not agg:
        return (f"F1S RECORD — {seat}: no audited sessions; fleet {tot.get('blocked')}/{tot.get('turns')} turns would block "
                f"(sweep {doc.get('generated')})")
    top = ", ".join(f"{k} {v}" for k, v in sorted((agg.get("per_class") or {}).items(), key=lambda kv: -kv[1])[:4])
    return (f"F1S RECORD — {seat}: {agg['blocked']}/{agg['turns']} turns would block ({top or 'none'}); "
            f"fleet {tot.get('blocked')}/{tot.get('turns')}; lying / 推託 / unrequested .md .json are PROOF-blocked at Stop "
            f"(sweep {doc.get('generated')})")


def stale(max_age_hours: float) -> bool:
    try:
        return time.time() - STATE.stat().st_mtime > max_age_hours * 3600
    except OSError:
        return True


def spawn_hidden() -> bool:
    """Start a full-sweep child that survives the caller; the lock keeps two sweeps from overlapping."""
    try:
        if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 2 * 3600:
            return False
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(str(os.getpid()), encoding="utf-8")
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe") if os.name == "nt" else exe
        import subprocess
        subprocess.Popen([str(pyw if pyw.is_file() else exe), "-I", str(Path(__file__).resolve()), "run", "--unlock"],
                         cwd=str(HUB), creationflags=(NW | 0x00000008 | 0x00000200) if os.name == "nt" else 0,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        return True
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--full", action="store_true")
    r.add_argument("--json", action="store_true")
    r.add_argument("--unlock", action="store_true", help="remove the spawn lock when done (used by the hidden child)")
    rec = sub.add_parser("record")
    rec.add_argument("--seat", required=True)
    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "run":
        try:
            doc = run(full=a.full)
        finally:
            if a.unlock:
                try:
                    LOCK.unlink()
                except OSError:
                    pass
        out = {k: doc[k] for k in ("generated", "elapsed_s", "scanned", "skipped_unchanged", "totals")}
        out["seats"] = {k: {kk: v[kk] for kk in ("sessions", "turns", "blocked", "block_rate")} for k, v in doc["seats"].items()}
        print(json.dumps(out, ensure_ascii=False, indent=None if a.json else 1))
        return 0
    if a.cmd == "record":
        print(record_line(a.seat))
        return 0
    doc = load_state()
    print(json.dumps({k: doc.get(k) for k in ("generated", "totals", "scanned", "elapsed_s")} | {"seats": {k: v.get("block_rate") for k, v in (doc.get("seats") or {}).items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
