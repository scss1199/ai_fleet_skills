#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
HUB=Path(os.environ.get("AI_WORKSPACE") or Path(__file__).resolve().parents[4])
STATUS=HUB/"_registry"/"token-preflight"/"claude-hook-status.json"
T1_DELIVERY=HUB/"_registry"/"token-preflight"/"t1-delivery"
CHARTER_DELIVERY=HUB/"_registry"/"token-preflight"/"charter-delivery"
# f1s_daily.py rewrites this once a day (operator 2026-10-27): every open conversation takes its diff like an instruction
# file, and a new conversation gets the whole text at its first prompt (it was never loaded at start).
DAILY_LIVE=("_registry","f1s-daily","live.md")
CODEX_STATUS=HUB/"_registry"/"token-preflight"/"codex-hook-status.json"
MACHINE_EVENT_TAGS=("<task-notification>","<side-sessions-event>","<ci-monitor-event>","<cross-session-message")


def _read_hook_input(stream) -> dict:
    """Decode Claude's UTF-8 hook pipe independently of Windows cp950."""
    raw = stream.buffer.read() if hasattr(stream, "buffer") else stream.read()
    if isinstance(raw, bytes):
        text = None
        for encoding in ("utf-8-sig", "utf-16", "cp950"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return {}
    else:
        text = str(raw)
    try:
        doc = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _harness():
    path = HUB / "_harness" / "runtime" / "fames_session_harness.py"
    spec = importlib.util.spec_from_file_location("fames_session_harness", path)
    if not path.is_file() or spec is None or spec.loader is None:
        raise RuntimeError(f"missing FAMES harness: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hard_lines(cwd: str) -> tuple[str, str]:
    """(state, text): the T1 hard lines SessionStart must add for a session opened in cwd.

    Seat charters carry T1 whole (cursor_bootstrap_pack.py), so a seat session gets
    ("charter", ""). The hub root and non-seat folders, such as a Codex thread opened in
    system32, get ("injected", T1). A failure gets ("UNKNOWN", a pointer to the source).
    """
    try:
        path = HUB / "_skill" / "engines" / "rules_brief.py"
        spec = importlib.util.spec_from_file_location("rules_brief", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"missing rules brief: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        text = module.format_for_session(cwd=cwd).strip()
    except Exception as exc:
        return "UNKNOWN", (f"T1 HARD LINES — UNKNOWN — {type(exc).__name__}; "
                           "read tier T1 of _registry/rules-blueprint.json before acting.")
    return ("injected", text) if text else ("charter", "")


def _auto_mode_line(seat: str, settings_path: str | None = None, protocol_path: str | None = None) -> str:
    """One SessionStart status line: does this host's ~/.claude/settings.json carry the F1S auto-mode posture
    (_registry/fames-protocol.json#auto_mode_posture)? Report only - the writer is sync-cursor-hooks.py, run by
    fames-immediate-apply after every package install. "" when the SSOT has no section. Never raises."""
    try:
        path = HUB / "_skill" / "engines" / "sync-cursor-hooks.py"
        spec = importlib.util.spec_from_file_location("fames_hook_auto_mode", path)
        if not path.is_file() or spec is None or spec.loader is None:
            return ""
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        st = mod.auto_mode_status(settings_path, protocol_path or str(HUB / "_registry" / "fames-protocol.json"))
        state = st.get("state")
        if state == "ABSENT":
            return ""
        seat_part = f"seat {seat} section {'present' if seat in (st.get('seats') or []) else 'none'}"
        head = (f"AUTO-MODE POSTURE — {state} — {st.get('expected')} F1S classifier rows in settings.json autoMode "
                f"(fleet env {st.get('fleet_environment')} / soft_deny {st.get('fleet_soft_deny')}; {seat_part})")
        if state == "IN_SYNC":
            return head + " — SSOT _registry/fames-protocol.json#auto_mode_posture"
        return head + (f" — missing {st.get('missing')} / stale {st.get('stale')}; the next fames-converge renders it,"
                       " or: python _skill/engines/sync-cursor-hooks.py --claude-only")
    except Exception:
        return ""


def _f1s_record(agent: str, max_age_hours: float = 6.0) -> str:
    """The seat's own F1S record line from the transcript sweep; starts a hidden sweep when stale."""
    try:
        path = HUB / "_skill" / "engines" / "f1s-transcript-audit.py"
        if not path.is_file():
            return ""
        spec = importlib.util.spec_from_file_location("f1s_transcript_audit", path)
        if spec is None or spec.loader is None:
            return ""
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        line = str(module.record_line(agent) or "")
        if module.stale(max_age_hours):
            started = module.spawn_hidden()
            line += " — sweep restarted" if started else ""
        return line
    except Exception:  # noqa: BLE001 — advisory context only
        return ""


def _everything_bg_prewarm() -> None:
    """operator 2026-10-20: agent file search runs on its own background Everything instance (engines/everything-bg.py),
    never the operator's foreground app; each session start warms it, hidden and detached.  Never raises, never blocks."""
    try:
        path = HUB / "_skill" / "engines" / "everything-bg.py"
        if not path.is_file():
            return
        spec = importlib.util.spec_from_file_location("everything_bg", path)
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.spawn_hidden()
    except Exception:  # noqa: BLE001 — advisory only
        return


def _t1_refresh(surface_id: str, session_id: str, *, at_start: bool) -> str:
    """Return the current T1 text when it differs from what this conversation last received.

    SessionStart only records what the session starts with (charter or injection); a later prompt gets
    the whole current T1 once whenever it changed, so an upgrade never needs a restarted conversation.
    A conversation with no record yet (opened before this existed) gets it once. Never raises.
    """
    if not session_id.strip():
        return ""
    try:
        import hashlib
        path = HUB / "_skill" / "engines" / "rules_brief.py"
        spec = importlib.util.spec_from_file_location("rules_brief_t1_refresh", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        text = module.format_rules(tiers=["T1"], max_bytes=1 << 30).strip()
        if not text:
            return ""
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = hashlib.sha256(f"{surface_id}\0{session_id}".encode("utf-8")).hexdigest()
        record = T1_DELIVERY / f"{key}.json"
        try:
            last = json.loads(record.read_text(encoding="utf-8")).get("t1_sha256")
        except (OSError, ValueError):
            last = None
        if last != digest:
            record.parent.mkdir(parents=True, exist_ok=True)
            stage = record.with_suffix(".tmp")
            stage.write_text(json.dumps({"t1_sha256": digest, "at": datetime.now(timezone.utc).isoformat()}),
                             encoding="utf-8")
            os.replace(stage, record)
        if at_start or last == digest:
            return ""
        return "STANDING RULES UPDATED (current T1, applies from this turn):\n" + text
    except Exception:
        return ""


def _memory_index(transcript_path: str) -> Path | None:
    """The auto-memory index Claude Code loaded for this conversation: <project dir of the transcript>/memory/MEMORY.md."""
    return Path(transcript_path).parent / "memory" / "MEMORY.md" if (transcript_path or "").strip() else None


def _instruction_files(surface_id: str, cwd: str, transcript_path: str = "") -> list[Path]:
    """The instruction files the host loaded when this conversation started, with their @imports.

    Claude Code: ~/.claude/CLAUDE.md plus CLAUDE.md, CLAUDE.local.md and .claude/CLAUDE.md in cwd and every
    ancestor, and the project's auto-memory index (a lesson one conversation saves reached the other open ones
    only after a restart, 2026-10-24). The open-agent surface (Codex): ~/.codex/AGENTS.md plus AGENTS.md in cwd
    and every ancestor.
    """
    import re
    base = Path(cwd).resolve()
    dirs = [*reversed(base.parents), base]
    if surface_id == "open-agent-standard":
        roots = [Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "AGENTS.md"]
        roots += [d / "AGENTS.md" for d in dirs]
    else:
        roots = [Path.home() / ".claude" / "CLAUDE.md"]
        roots += [d / name for d in dirs for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md")]
        memory = _memory_index(transcript_path)
        if memory is not None:
            roots.append(memory)
        roots.append(HUB.joinpath(*DAILY_LIVE).resolve())
    found: list[Path] = []
    pending = [(p, 0) for p in roots]
    while pending:
        path, depth = pending.pop(0)
        if path in found or not path.is_file():
            continue
        found.append(path)
        if depth >= 5 or path.stat().st_size > 1 << 20:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for ref in re.findall(r"(?:^|\s)@((?:~[\\/])?[\w.\\/:-]+\.md)\b", text):
            target = Path.home() / ref[2:] if ref.startswith("~") else Path(ref)
            pending.append(((target if target.is_absolute() else path.parent / target).resolve(), depth + 1))
    return found


def _transcript_cwd(transcript_path: str) -> str:
    """The first cwd a Claude (top-level "cwd") or Codex (session_meta payload "cwd") transcript records, or ""."""
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as handle:
            for _, line in zip(range(200), handle):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                payload = row.get("payload")
                found = row.get("cwd") or (payload.get("cwd") if isinstance(payload, dict) else None)
                if isinstance(found, str) and found.strip():
                    return found
    except (OSError, TypeError, ValueError):
        pass
    return ""


def _charter_refresh(surface_id: str, session_id: str, cwd: str, *, at_start: bool, transcript_path: str = "",
                     max_chars: int = 8000) -> str:
    """Return what changed in this conversation's instruction files since it last received them.

    SessionStart records the files as loaded; a later prompt gets a diff of every file that changed (new and
    removed files included), so a CLAUDE.md or AGENTS.md upgrade never needs a restarted conversation. A
    conversation with no record (opened before this existed) gets the files changed after its transcript was
    created. Over max_chars the reply names the files to re-read instead. Never raises.
    """
    if not session_id.strip():
        return ""
    try:
        import difflib
        import hashlib
        key = hashlib.sha256(f"{surface_id}\0{session_id}".encode("utf-8")).hexdigest()
        record = CHARTER_DELIVERY / f"{key}.json"
        try:
            last_doc = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last_doc = {}
        # The host loaded its files for the cwd the conversation opened in; a later `cd` changes the hook's cwd
        # but not what the conversation loaded, so the file set stays anchored to the recorded cwd (or, with no
        # record yet, to the first cwd its transcript names).
        anchor = cwd if at_start else str(last_doc.get("cwd") or _transcript_cwd(transcript_path) or cwd)
        last = last_doc.get("files") if not at_start else None
        files = _instruction_files(surface_id, anchor, transcript_path)
        texts = {str(p): p.read_text(encoding="utf-8", errors="replace") for p in files}
        current = {k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in texts.items()}
        root = CHARTER_DELIVERY
        blobs = root / "blobs"
        blobs.mkdir(parents=True, exist_ok=True)
        for path, digest in current.items():
            blob = blobs / f"{digest}.txt"
            if not blob.is_file():
                stage = blob.with_suffix(".tmp")
                stage.write_text(texts[path], encoding="utf-8")
                os.replace(stage, blob)
        if last != current or last_doc.get("cwd") != anchor:
            stage = record.with_suffix(".tmp")
            loaded = {k: v for k, v in current.items() if not (at_start and k == str(HUB.joinpath(*DAILY_LIVE).resolve()))}
            stage.write_text(json.dumps({"files": loaded, "cwd": anchor,
                                         "at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
            os.replace(stage, record)
        if at_start or last == current:
            return ""
        if last is None:
            transcript = Path(transcript_path) if transcript_path else None
            if not transcript or not transcript.is_file():
                return ""
            stat = transcript.stat()
            opened = getattr(stat, "st_birthtime", stat.st_ctime)
            changed = [p for p in current if Path(p).stat().st_mtime > opened]
            last = {}
        else:
            # The memory index joined the tracked set on 2026-10-24: a conversation whose record predates that
            # starts tracking it silently instead of receiving the whole index as "changed".
            memory = str(_memory_index(transcript_path) or "")
            changed = [p for p in current if last.get(p) != current[p] and not (p == memory and p not in last)]
        removed = [p for p in last if p not in current]
        if not changed and not removed:
            return ""
        parts = []
        for path in changed:
            old_blob = blobs / f"{last.get(path)}.txt"
            if last.get(path) and old_blob.is_file():
                diff = difflib.unified_diff(old_blob.read_text(encoding="utf-8").splitlines(),
                                            texts[path].splitlines(), path + " (as loaded)", path + " (now)",
                                            n=1, lineterm="")
                parts.append("\n".join(diff))
            else:
                parts.append(f"=== {path} (current text) ===\n{texts[path]}")
        parts += [f"=== {path} === removed; its instructions no longer apply" for path in removed]
        head = "INSTRUCTIONS UPDATED (these files changed since this conversation loaded them; the current text applies from this turn):\n"
        body = "\n".join(parts)
        if len(body) > max_chars:
            body = "Too large to inline; re-read these files now with the Read tool before acting:\n" + "\n".join(
                f"- {p}" for p in changed + removed)
        return head + body
    except Exception:
        return ""


_SEAT_CACHE: dict[tuple[str, str], str] = {}


def _seat_for_cwd(cwd: str) -> str:
    """Seat name for a hook cwd: registered seat (project-matrix, longest path prefix, hub root ->
    local curator) -> nearest `ai_*` ancestor inside the hub -> basename.

    The old rule was basename(cwd), so a shell that had drifted into
    ai_darkhero/evidence/<topic> stamped the intake with agent="<topic>" (phantom seat,
    2026-10-12). Every step fails open to the next one; this never raises."""
    key = (str(HUB), str(cwd))
    if key not in _SEAT_CACHE:
        _SEAT_CACHE[key] = _resolve_seat(cwd)
    return _SEAT_CACHE[key]


def _resolve_seat(cwd: str) -> str:
    base = Path(cwd).name
    module = None
    try:
        projects_path = HUB / "_skill" / "engines" / "_projects.py"
        spec = importlib.util.spec_from_file_location("fames_hook_projects", projects_path)
        if projects_path.is_file() and spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            name = module.whoami(cwd)[0]
            if name and name != "unknown":
                return str(name)
    except Exception:
        pass
    try:
        hub = HUB.resolve()
        node = Path(cwd).resolve()
        while True:
            if node.name.startswith("ai_") and node.parent == hub:
                return node.name
            if node == hub:
                # Hub infrastructure (_registry, _skill, _lean...) belongs to the hub-root seat, the local curator: by
                # basename a curator shell that cd'd into C:\ai_workspace\_registry became seat `_registry` (2026-10-23).
                name = module.whoami(str(hub))[0] if module is not None else ""
                if name and name != "unknown":
                    return str(name)
                break
            if node.parent == node:
                break
            node = node.parent
    except Exception:
        pass
    return base


MIDTURN_WATCH=("_registry/fames-protocol.json","_registry/rules-blueprint.json",
               "_skill/fleet-skills/fames/runtime/manifest.json","_registry/f1s-daily/live.md")


MIDTURN_HEAD="F1S MID-TURN UPDATE (an upgrade landed while this task was running; apply it from the next step)"
CONTRACT_LINE_PREFIXES=("TOKEN CORE ","FAMES CORE:","HARD INVARIANTS:","OPERATOR RED LINES:","SEAL-AP-1:",
                        "Task intake binds goal identity","Apply this contract to the current prompt")


def _contract_dedup(surface_id: str, session_id: str, text: str, *, agent_id: str="", reset: bool=False) -> str:
    """Drop the contract lines this conversation already holds verbatim, and record the rest as held.

    2026-10-26 (audit-session-tax.py, 7 days of ai_darkhero conversations): the first prompt repeated the FAMES CORE
    and TOKEN CORE lines SessionStart had just delivered (~950 tokens per conversation), and every upgrade re-sent the
    whole contract mid-turn and again at the next prompt (~174K identical tokens a week). Only CONTRACT_LINE_PREFIXES
    lines are dropped; per-turn status lines always go out. SessionStart (startup, resume, clear, compact) resets the
    ledger, since a compacted conversation may no longer hold them. Claude retains hook context; the open-agent
    surface is ephemeral and keeps every line. Never raises; on any error the text goes out whole."""
    if surface_id != "claude" or not session_id.strip() or not text:
        return text
    try:
        import hashlib
        scope=f"{surface_id}\0{session_id}"+(f"\0{agent_id}" if agent_id else "")
        path=HUB/"_registry"/"token-preflight"/"contract-delivery"/f"{hashlib.sha256(scope.encode('utf-8')).hexdigest()[:24]}.json"
        held=set()
        if not reset:
            try:
                held=set(json.loads(path.read_text(encoding="utf-8")).get("lines") or [])
            except (OSError,ValueError,AttributeError):
                held=set()
        kept=[]
        for line in text.split("\n"):
            if line.strip().startswith(CONTRACT_LINE_PREFIXES):
                digest=hashlib.sha256(line.strip().encode("utf-8")).hexdigest()[:32]
                if digest in held:
                    continue
                held.add(digest)
            kept.append(line)
        path.parent.mkdir(parents=True,exist_ok=True)
        stage=path.with_name(path.name+f".{os.getpid()}.tmp")
        stage.write_text(json.dumps({"lines":sorted(held),"at":datetime.now(timezone.utc).isoformat()}),encoding="utf-8")
        os.replace(stage,path)
        return "\n".join(kept).strip()
    except Exception:
        return text


def _orders_files(seat: str) -> list[Path]:
    """The curator-order files whose change must reach this seat now: its own, or every seat's for the curator
    (it reviews their answers). Same store as curator_orders.py."""
    root=HUB/"_registry"/"curator-orders"
    if not seat:
        return []
    if seat == _seat_for_cwd(str(HUB)):
        return sorted(root.glob("*.json"))
    return [root/f"{seat}.json"]


def _midturn_sig(seat: str="") -> str:
    """stat() of the files an upgrade rewrites plus this seat's curator orders (T1 f1s-governs: an order must not
    wait for the next prompt either)."""
    paths=[HUB/rel for rel in MIDTURN_WATCH]+_orders_files(seat)
    return "|".join("%s:%s"%(p.stat().st_mtime_ns,p.stat().st_size) if p.is_file() else "-" for p in paths)


def _midturn_path(surface_id: str, session_id: str, agent_id: str="") -> Path:
    import hashlib
    scope=f"{surface_id}\0{session_id}"+(f"\0{agent_id}" if agent_id else "")
    return HUB/"_registry"/"fames-hot"/f"midturn-{hashlib.sha256(scope.encode('utf-8')).hexdigest()[:24]}.json"


def _midturn_pending(surface_id: str, session_id: str, *, seat: str="", agent_id: str="") -> bool:
    """Read-only: did anything this conversation must receive change since it last received it? Never raises."""
    try:
        seen=json.loads(_midturn_path(surface_id,session_id,agent_id).read_text(encoding="utf-8")).get("sig")
        return bool(seen) and seen != _midturn_sig(seat)
    except Exception:
        return False


def _midturn_changed(surface_id: str, session_id: str, *, record_only: bool=False, agent_id: str="",
                     seat: str="", cwd: str="", event: str="") -> bool:
    """operator 2026-10-15: an F1S upgrade must reach a long task mid-turn, not only at its next prompt.
    Cheap: stat() of the files an upgrade rewrites, compared with what this session last saw. The first call
    of a session only records (its prompt already carried the current contract). A subagent shares the session
    id, so it is counted on its own (`agent_id` from the hook input): on 2026-10-23 an ai_nuwa subagent took the
    one-shot update and the main conversation never got it. The record is also the delivery ledger that
    f1s_live.py status reads (which open conversation holds which signature). Never raises."""
    try:
        sig=_midturn_sig(seat)
        path=_midturn_path(surface_id,session_id,agent_id)
        try:
            previous=json.loads(path.read_text(encoding="utf-8"))
            seen=previous.get("sig") if isinstance(previous,dict) else None
        except (OSError,ValueError):
            previous,seen={},None
        if seen==sig and (not seat or previous.get("seat")==seat):
            return False
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({"sig":sig,"at":datetime.now(timezone.utc).isoformat(),"session_id":session_id,
                                    "surface":surface_id,"agent_id":agent_id or None,"seat":seat or None,
                                    "cwd":cwd or None,"event":event or None}),encoding="utf-8")
        return seen is not None and seen != sig and not record_only
    except Exception:
        return False


def _session_seat(doc, record: dict | None=None) -> tuple[str, str]:
    """(seat, cwd) of the conversation, from the cwd it opened in: a tool's `cd` moves the hook cwd, not the seat.
    The delivery record keeps it, so a tool call does not re-read the transcript."""
    if record and record.get("seat") and record.get("cwd"):
        return str(record["seat"]), str(record["cwd"])
    cwd=_transcript_cwd(str(doc.get("transcript_path") or "")) or str(doc.get("cwd") or os.getcwd())
    return _seat_for_cwd(cwd), cwd


def _midturn_record(surface_id: str, session_id: str, agent_id: str="") -> dict:
    try:
        rec=json.loads(_midturn_path(surface_id,session_id,agent_id).read_text(encoding="utf-8"))
        return rec if isinstance(rec,dict) else {}
    except (OSError,ValueError):
        return {}


def live_update(doc, *, event: str="PostToolUse", watch_seat: str | None=None) -> str:
    """The update text for a conversation whose watched files changed since it last received them, recorded as
    delivered; "" when nothing changed. Shared by the PostToolUse hook (mid-turn) and f1s_live.py (an idle
    conversation, woken), which passes the seat basis it watched (`watch_seat`): on 2026-10-24 the two bases differed,
    the waiter saw an order land and this function saw no change, so the conversation was never woken. Never raises."""
    session_id=str(doc.get("session_id") or "")
    surface_id="open-agent-standard" if str(doc.get("turn_id") or "").strip() else "claude"
    agent_id=str(doc.get("agent_id") or "")
    if not session_id:
        return ""
    record=_midturn_record(surface_id,session_id,agent_id)
    seat,cwd=_session_seat(doc,record)
    # Compare on the seat the record was made with: a record from before the ledger fields existed (no seat) keeps
    # comparing the F1S files only until the next prompt records the seat, so the new orders term alone is no upgrade.
    sig_seat=watch_seat if watch_seat is not None else (str(record.get("seat") or "") if record else seat)
    if not _midturn_changed(surface_id,session_id,agent_id=agent_id,seat=sig_seat,cwd=cwd,event=event):
        return ""
    parts=[]
    orders="" if agent_id else _curator_orders(seat,session_id)
    if orders:
        parts.append(orders)
    try:
        hot=_harness().hot_refresh(seat,Path(cwd),surface_id=surface_id,session_id=session_id,workspace=HUB)
        parts.append(hot.get("plan_text",""))
    except Exception as exc:
        parts.append(f"FAMES HOT REFRESH — UNKNOWN — {type(exc).__name__}")
    for update in (_t1_refresh(surface_id,session_id,at_start=False),
                   _charter_refresh(surface_id,session_id,cwd,at_start=False,
                                    transcript_path=str(doc.get("transcript_path") or ""))):
        if update:
            parts.append(update)
    return _contract_dedup(surface_id,session_id,"\n".join(p for p in parts if p).strip(),agent_id=agent_id)


def _midturn(doc) -> int:
    """PostToolUse fast path: print {} unless F1S or this seat's curator orders changed since this session last saw them."""
    context=live_update(doc)
    if context:
        print(json.dumps({"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":MIDTURN_HEAD+"\n"+context}},ensure_ascii=True))
    else:
        print("{}")
    return 0


RECURRENCE_MIN = 3
RECURRENCE_DAYS = 7
RECIPE = {
    "handback": "do it yourself now; a step is the operator's only for login/OAuth, permanent delete, rider arming, global settings, secrets, funds, hardware",
    "blocker": "a constraint is a route choice, not a dead end: run ztm-task-router.py / grep the skills, try the route, cite the failing tool result",
    "decision": "decide it yourself; 「需要你決定」 only once per turn and only for an operator-reserved call",
    "measurement": "every number comes from a tool result this turn, or is written as UNKNOWN",
    "completion": "done/finished needs a re-run, re-read or probe this turn and a citable path or commit",
    "verified": "verified means a fresh read-back this turn, cited",
    "tests_pass": "run the suite after the last edit and quote the green line",
    "pushed": "push, then read origin back and cite the hash",
    "automated": "name the rider id in hosts.json or say it is not automated",
    "code_change": "global search before editing (grep the symbol), change only the lines that must change",
    "fix_claim": "a green test after the write, or 未驗證",
    "read": "name the file and show the read result this turn",
    "placation": "no 「你說得對」 opener: state what was wrong, the evidence, what you did",
    "secret_ask": "never ask for a token/key: auth_check / vault / token-onboard / browser-login-handoff",
    "unrequested_file": "write only the files the operator named",
}


def _proof_recurrence(cwd: str) -> str:
    """F1S 強制思考 B (2026-10-19): the class this seat keeps getting blocked for, said BEFORE it acts. Counts
    PROOF blocks for this seat over the last RECURRENCE_DAYS from _registry/proof/log.jsonl; one line for the top
    class when it reached RECURRENCE_MIN. Both sides go through _seat_for_cwd: by basename a hub-root shell read
    as seat `ai_workspace` and a tray/ subdir as `tray`, so the line named a phantom seat (2026-10-23). Never raises."""
    import time as _time
    seat = _seat_for_cwd(cwd) if (cwd or "").strip() else ""
    log = HUB / "_registry" / "proof" / "log.jsonl"
    if not seat or not log.is_file():
        return ""
    try:
        cut = _time.time() - RECURRENCE_DAYS * 86400
        with log.open("rb") as fh:
            end = fh.seek(0, 2)
            start = max(0, end - 4 * 1024 * 1024)
            fh.seek(start)
            tail = fh.read().decode("utf-8", "replace").split("\n")
            if start > 0:
                tail = tail[1:]   # only a mid-file start can leave a cut first record
        counts: dict[str, int] = {}
        for line in tail:
            if '"verdict": "block"' not in line and '"verdict":"block"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            try:
                if _time.mktime(_time.strptime(d.get("ts", ""), "%Y-%m-%dT%H:%M:%S")) < cut:
                    continue
            except (ValueError, TypeError):
                continue
            row_cwd = str(d.get("cwd") or "")
            if not row_cwd.strip() or _seat_for_cwd(row_cwd) != seat:
                continue
            for v in d.get("violations") or []:
                c = v.get("class")
                if c:
                    counts[c] = counts.get(c, 0) + 1
        if not counts:
            return ""
        cls, n = max(counts.items(), key=lambda kv: kv[1])
        if n < RECURRENCE_MIN:
            return ""
        return (f"F1S RECURRENCE — seat {seat}: PROOF blocked `{cls}` {n}× in the last {RECURRENCE_DAYS} days. "
                f"Before acting this turn: {RECIPE.get(cls, 'see the PROOF reason for this class')}.")
    except (OSError, ValueError, TypeError, AttributeError):
        return ""


def _curator_orders(agent: str, session_id: str = "") -> str:
    """T1 f1s-governs (operator 2026-10-24): this seat's open correction orders from the curator, or for the curator
    the answered orders waiting for review (_skill/engines/curator_orders.py). An order another conversation owns
    renders as one read-only line for this one. "" when none. Never raises."""
    path = HUB / "_skill" / "engines" / "curator_orders.py"
    try:
        spec = importlib.util.spec_from_file_location("fames_hook_curator_orders", path)
        if not path.is_file() or spec is None or spec.loader is None:
            return ""
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            return str(module.injection(agent, session_id) or "")
        except TypeError:  # an older engine without the owner argument
            return str(module.injection(agent) or "")
    except Exception:
        return ""


def _article_relay(agent: str, cwd: str) -> str:
    """operator 2026-10-26: on the operator's prompt to the curator, new LINE articles go to the seat they were sent
    for (kyloren_quant -> ai_trader as a curator order; the curator's own kyloren_bot articles inline). "" for every
    other seat or on any error (_skill/engines/article_relay.py). Never raises."""
    path = HUB / "_skill" / "engines" / "article_relay.py"
    try:
        spec = importlib.util.spec_from_file_location("fames_hook_article_relay", path)
        if not path.is_file() or spec is None or spec.loader is None:
            return ""
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return str(module.hook_context(agent, cwd) or "")
    except Exception:
        return ""


def _proof_carry(session_id: str) -> str:
    """Claims the PROOF Stop hook could not push back on because its per-turn/per-session cap was spent
    (claude-proof-hook.py `carried`), shown once at the next prompt (F1S 當下閉環 item 6). Never raises."""
    import re as _re
    if not session_id.strip():
        return ""
    path = HUB / "_registry" / "proof" / (_re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80] + ".json")
    try:
        state = json.loads(path.read_text(encoding="utf-8-sig"))
        carried = state.get("carried") if isinstance(state, dict) else None
        if not isinstance(carried, dict) or carried.get("surfaced") or not carried.get("items"):
            return ""
        carried["surfaced"] = True
        staged = path.with_name(path.name + f".{os.getpid()}.tmp")
        staged.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(staged, path)
    except (OSError, ValueError, TypeError, AttributeError):
        return ""
    return ("PROOF CARRY-OVER — the previous turn ended with unproven claims after the PROOF cap was spent "
            f"({carried.get('at')}); they are recorded as a compliance flag. Before anything else, correct them "
            "in this reply (run the check and cite it, or restate them as UNKNOWN):\n"
            + "\n".join("  - " + str(item) for item in carried["items"]))


def main():
    doc=_read_hook_input(sys.stdin)
    if str(doc.get("hook_event_name") or "")=="PostToolUse":
        return _midturn(doc)
    cwd=str(doc.get("cwd") or os.getcwd())
    agent=_seat_for_cwd(cwd)
    event=str(doc.get("hook_event_name") or "SessionStart")
    session_id=str(doc.get("session_id") or doc.get("conversation_id") or "")
    # AGC lane inputs: the transcript path lets the context meter measure THIS session's
    # curve; `source` (startup|resume|clear|compact) tells SessionStart when the platform
    # just compacted so the compact pointer is injected right after the summary.
    transcript_path=str(doc.get("transcript_path") or "")
    session_source=str(doc.get("source") or "")
    # Claude Code's native hook payload also carries transcript_path,
    # permission_mode, and may carry model.  turn_id is the discriminating
    # Open Agent field; treating the common fields as vendor identity sends a
    # real Claude event to the wrong surface and makes its receipt UNKNOWN.
    codex_marked=bool(str(doc.get("turn_id") or "").strip())
    surface_id="open-agent-standard" if codex_marked else "claude"
    token_core=(f"TOKEN CORE {agent}: outcome | verification | state | next action | blocker. "
                "Preflight before broad reads; PFKT only independent units; "
                "AEX only measured residual; UNKNOWN fails closed.")
    prompt=str(doc.get("prompt") or doc.get("user_message") or doc.get("message") or "")
    # A background-task / side-session / CI notification opens a turn through UserPromptSubmit too. It is not an
    # operator prompt: binding it as one made every notification turn "FAMES TURN — UNKNOWN … do not claim
    # completion" plus ~2 KB of repeated contract text (2026-10-23, 6 notifications in one task). The operator's
    # own prompt stays the bound intake; upgrades still arrive through the refreshes below and mid-turn.
    machine_event=event == "UserPromptSubmit" and prompt.lstrip().startswith(MACHINE_EVENT_TAGS)
    try:
        harness=None if machine_event else _harness()
        if machine_event:
            result={}
            context=""
            state="MACHINE_EVENT"
        elif event == "UserPromptSubmit":
            if surface_id == "open-agent-standard":
                runtime_event_observed=bool(
                    session_id.strip() and prompt.strip() and str(doc.get("turn_id") or "").strip()
                    and str(doc.get("model") or "").strip()
                    and str(doc.get("permission_mode") or "").strip()
                    and "transcript_path" in doc and str(doc.get("cwd") or "").strip()
                    and doc.get("fames_probe_mode") not in {"direct", "synthetic"}
                )
            else:
                runtime_event_observed=bool(
                    session_id.strip() and prompt.strip() and str(doc.get("cwd") or "").strip()
                    and doc.get("fames_probe_mode") not in {"direct", "synthetic"}
                )
            result=harness.turn_context(
                agent,
                Path(cwd),
                prompt=prompt,
                surface_id=surface_id,
                session_id=session_id,
                adapter_mode="same_turn_context_injection",
                adapter_path=Path(__file__),
                workspace=HUB,
                runtime_event_observed=runtime_event_observed,
                activation_evidence=("lifecycle_hook" if runtime_event_observed else "invalid_hook_payload"),
                transcript_path=transcript_path,
                context_retained=surface_id == "claude" and bool(transcript_path),
            )
            context=((token_core+"\n") if result.get("should_inject") else "") + result.get("plan_text", "")
            state=result.get("state")
        else:
            harness.reset_turn_context(HUB, surface_id, session_id)
            result=harness.run_session(
                agent, Path(cwd), HUB, hook_event=event, session_id=session_id,
                transcript_path=transcript_path, session_source=session_source,
            )
            harness.hot_refresh(
                agent, Path(cwd), surface_id=surface_id, session_id=session_id,
                workspace=HUB, acknowledge=True,
            )
            context=(token_core+"\n"+result.get("plan_text", "")).strip()
            state=result.get("state")
    except Exception as exc:
        state="UNKNOWN"
        context=token_core+f"\nFAMES ALWAYS-ON — UNKNOWN — {type(exc).__name__}"
    # Upgrades reach open conversations even when the FAMES harness above failed; both helpers never raise.
    if event == "UserPromptSubmit":
        for update in (_t1_refresh(surface_id, session_id, at_start=False),
                       _charter_refresh(surface_id, session_id, cwd, at_start=False, transcript_path=transcript_path),
                       _proof_carry(session_id), "" if machine_event else _proof_recurrence(cwd),
                       "" if machine_event else _article_relay(agent, cwd)):
            if update:
                context=(context+"\n"+update).strip()
    else:
        _t1_refresh(surface_id, session_id, at_start=True)
        if session_source != "compact":
            # A fresh, resumed or cleared conversation loads its instruction files now; compaction may not.
            _charter_refresh(surface_id, session_id, cwd, at_start=True, transcript_path=transcript_path)
    # The prompt or start just delivered the current contract: record it so the mid-turn check stays quiet. A machine
    # event delivered no contract, so an upgrade that landed before it must still reach the next tool call.
    if not machine_event:
        live_seat, live_cwd = _session_seat(doc, None if event == "SessionStart" else _midturn_record(surface_id, session_id))
        _midturn_changed(surface_id, session_id, record_only=True, seat=live_seat, cwd=live_cwd, event=event)
    t1_state=None
    if event == "SessionStart":
        # The hard lines must not depend on the FAMES harness above having succeeded.
        t1_state,hard_lines=_hard_lines(cwd)
        if hard_lines:
            context=(context+"\n"+hard_lines).strip()
        # operator 2026-10-13: every conversation sees its seat's own lying / 推託 / junk-file record, and
        # the sweep that produces it restarts itself (hidden) when stale.  Never raises, never blocks.
        record=_f1s_record(agent)
        if record:
            context=(context+"\n"+record).strip()
        # operator 2026-10-31: the auto-mode classifier posture is F1S-carried; every session sees whether this host has it.
        posture=_auto_mode_line(agent)
        if posture:
            context=(context+"\n"+posture).strip()
        _everything_bg_prewarm()
    # The curator's orders go first, above this seat's own plan: they outrank its decisions (T1 f1s-governs).
    orders=_curator_orders(agent, session_id)
    if orders:
        context=(orders+"\n"+context).strip()
    context=_contract_dedup(surface_id, session_id, context, reset=event == "SessionStart")
    status_path=CODEX_STATUS if surface_id == "open-agent-standard" else STATUS
    status_path.parent.mkdir(parents=True,exist_ok=True)
    status_path.write_text(json.dumps({"schema":3,"last_fired":datetime.now(timezone.utc).isoformat(),"event":event,"cwd":cwd,"agent":agent,"surface_id":surface_id,"runtime_event_observed":bool(locals().get("runtime_event_observed", False)),"fames_state":state,"t1_hard_lines":t1_state,"session_source":session_source or None,"agc":{k:(result.get("auto_goal_compact") or {}).get(k) for k in ("state","agent","seat_resolution","refreshed","trigger","precompact_hook_armed","elapsed_ms")} if isinstance(locals().get("result"),dict) else None},indent=2),encoding="utf-8")
    if context:
        # ASCII JSON keeps the hook envelope valid under Windows cp950 consoles;
        # Claude decodes the \u escapes back into the original context text.
        print(json.dumps({"hookSpecificOutput":{"hookEventName":event,"additionalContext":context}},ensure_ascii=True))
    else:
        print("{}")
    return 0
if __name__=="__main__":
    raise SystemExit(main())
