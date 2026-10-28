#!/usr/bin/env python3
"""claude-run-until-done-hook.py — Claude Code `Stop` hook (operator 2026-10-10, armed 2026-10-11).

Operator: 「現在一直跑到沒有下一步為止 一直按tab建議有夠智障」. Conversations run at
medium/high effort end their turn with "next step is X" and leave the operator to press
the suggested follow-up. This hook reads the reply that is about to end the turn and,
when its closing part still names a pending next step or offers to do more, answers
`{"decision": "block", "reason": ...}` so the model keeps going in the same turn.

It is the ONE operator-authorized exception to T1 `f1s` (F1S = FAMES 一套系統; "no hook blocks
Stop"); see rule `run-until-no-next-step` in _registry/rules-blueprint.json.
Since 2026-10-24 (T1 `f1s-governs`) it also keeps a seat's turn going while the curator's correction order for
that seat is open (_skill/engines/curator_orders.py), 「沒有下一步」 included; only 「需要你決定」 ends it first.

Guard rails (all fail open — any error, missing file or unreadable transcript = exit 0,
no output, the turn ends normally):
  * `Stop` only, never `SubagentStop`.
  * Bounded: at most `max_blocks_per_turn` pushes per user prompt (default 2) and
    `max_blocks_per_session` per session (default 12), tracked in
    _registry/run-until-done/<session_id>.json.
  * Escape phrases (「沒有下一步」, 「需要你決定」, "nothing actionable", ...) always let the
    turn end, so the model can stop for a real operator decision.
  * Kill switch: `"enabled": false` in _registry/run-until-done.json.
  * Spawns nothing; the launcher is the hub's pythonw fail-open wrapper (zero foreground).

Evidence: every decision is appended to _registry/run-until-done/log.jsonl.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace")
CONFIG = HUB / "_registry" / "run-until-done.json"
STATE_DIR = HUB / "_registry" / "run-until-done"
CLAUDE_PROJECTS_ROOT = Path.home() / ".claude" / "projects"
TAIL_BYTES = 4 * 1024 * 1024      # how much of the transcript tail to scan
TAIL_CHARS = 1800                 # judge only the closing part of the reply
MAX_ROWS = 400                    # rows walked backwards before giving up

DEFAULTS = {
    "enabled": True,
    "max_blocks_per_turn": 2,
    "max_blocks_per_session": 12,
    # The closing part of the reply still hands a step back to the operator.
    "pending_patterns": [
        r"下一步",
        r"接下來(?:我|會|再|可以|就)",
        r"之後(?:我|再|會)",
        r"稍後(?:我|再|會|檢查|確認)",
        r"等(?:它|他|其|排程|跑|結果|完成|結束|回來|下次)[^。\n]{0,20}(?:再|後|就)",
        # (?!的): 「只在通話時才跑的程式」 is a noun phrase, not a deferred step (2026-10-23 false positive).
        r"(?:再|才)(?:檢查|確認|驗證|回報|繼續|看|跑)(?!的)",
        r"我(?:會|將)(?:在|於|等|再)",
        r"待(?:完成|確認|驗證|跑完)",
        r"(?:要不要|需不需要|需要|是否要|是否需要|可以)我(?:來|幫|先|再|繼續|接著)?",
        r"如果你(?:要|想|需要|同意|確認)",
        r"你(?:可以|再|決定後)(?:告訴|跟)我",
        r"\bnext steps?\b",
        r"\bI(?:'ll| will| can| could) (?:check|verify|continue|follow|wait|re-?run|come back|look|do|run)\b",
        r"\bonce (?:it|that|the \w+) (?:finishes|completes|is done|lands|returns)\b",
        r"\bthen I(?:'ll| will)\b",
        r"\bafter (?:it|that|the (?:run|job|task)) (?:finishes|completes|ends)\b",
        r"\b(?:want|would you like) me to\b",
        r"\b(?:shall|should|can|could) I\b",
        r"\blet me know\b",
        r"\bif you(?:'d like| want| prefer| confirm)\b",
        r"\bready (?:to|when you)\b",
    ],
    # The reply explicitly closed the task or stopped for a decision only the operator can make.
    "done_patterns": [
        r"沒有下一步",
        r"無下一步",
        r"已?無(?:可做|可執行|其他|剩餘)[^。\n]{0,6}(?:步驟|動作|下一步)",
        r"需要你(?:決定|授權|親自|手動|確認|選)",
        r"需要 ?operator ?(?:決定|授權|親自|手動|確認)",
        r"(?:由|等)(?:你|operator)(?:決定|授權|親手|親自)",
        r"只能由你",
        r"你的決定",
        r"\bnothing (?:left|actionable|further|more|else) (?:to do|remains|is left)?",
        r"\bno (?:next|further|remaining) (?:step|steps|action|actions)\b",
        r"\bno further action\b",
        r"\b(?:needs|requires|is) (?:your|the operator'?s?) (?:decision|authorit|approval|call)",
        r"\bblocked on (?:you|the operator)\b",
        r"\byour (?:decision|call)\b",
    ],
}

REASON = (
    "run-until-done (operator standing rule run-until-no-next-step, 2026-10-10: "
    "「一直跑到沒有下一步為止」): the reply that was about to end this turn still names a "
    "pending next step or offers to do more{matched}. Do it NOW, in this same turn: start "
    "the background waiter, verify the result, act on it, and keep going until nothing "
    "actionable is left. Never hand \"next step is X\" back to the operator to press. "
    "End the turn only when (a) nothing actionable remains — then say so plainly with the "
    "words 「沒有下一步」 — or (b) the only remaining step needs the operator's own authority "
    "or would destroy data — then state it on one line beginning 「需要你決定：」 and stop. "
    "(push {n}/{cap} for this prompt)"
)


REASON_PINNED = (
    "run-until-done / F1S 當下閉環: this session edited FAMES-release-pinned file(s) {paths} and they still differ "
    "from the shipped runtime, so fames-converge and fleet-skill-pulse go red for the whole fleet until they ship "
    "(2026-10-18: one unshipped f1s_audit.py edit kept them red 8 h). Before ending the turn, run the tests that "
    "cover the change and ship it now: {command} -- or, if the edit was wrong, restore the file to the shipped "
    "bytes. Only an operator-only decision (one line 「需要你決定：」) may end the turn first. (push {n}/{cap})"
)
REASON_ORDERS = (
    "run-until-done / F1S governs this cwd (T1 f1s-governs): the curator's correction order(s) {orders} for seat "
    "{seat} are still open. They outrank this seat's own plan; red lines and the operator's own words here stay "
    "above them. Before ending the turn, do the order and answer it: {command} <n> --evidence <path>, or "
    "--cannot \"<reason>\" when a red line or the operator's instruction here forbids it. (push {n}/{cap})"
)
REASON_CAPTURE = (
    "run-until-done / live capture (operator 2026-10-24: a Google Meet caption scraper in a background tab stalled at "
    "12:03 and nobody saw it until the meeting ended 55 min later): this reply leaves a capture running unattended "
    "(matched: {matched!r}) and nothing watches it. Before ending the turn: 1) for anything that cannot be redone, run "
    "a second, independent capture (e.g. the local audio recorder) and read back that its file grows; 2) register the "
    "watch so the idle waiter wakes you the moment it stalls: python C:\\ai_workspace\\_skill\\engines\\f1s_live.py "
    "capture add --name <name> --file <file that grows> --stale-s 90 --check-every-s 300 --hours <h>; 3) tell the "
    "operator what is watched and how. When it ends: f1s_live.py capture done --name <name>. (push {n}/{cap})"
)
# A capture noun and a still-running phrase on one line of the closing reply: 「字幕側錄會一直跑到結束，你們不用做任何事」.
CAPTURE_NOUN = re.compile(r"(?i)錄音|錄影|側錄|字幕|擷取|錄製|會議|直播|串流|record|captur|stream|transcri|meeting")
CAPTURE_ONGOING = re.compile(
    r"(?i)會一直|一直(?:跑|錄|記|在)|持續(?:中|在|側錄|錄|擷取|記錄|跑)|繼續(?:跑|錄|記|側錄)|(?:跑|錄|記)到(?:會議)?結束|"
    r"不用做任何事|放著(?:跑|錄)|還在(?:跑|錄|進行)|進行中|"
    r"\bkeeps?\s+(?:recording|capturing|running)|\bwill\s+keep\s+(?:recording|capturing|running)|"
    r"\buntil\s+(?:it|the\s+meeting|the\s+stream)\s+ends\b|\bis\s+(?:still\s+)?(?:recording|capturing)\b"
)


QUOTED = re.compile(r"「[^」\n]*」|“[^”\n]*”|\"[^\"\n]*\"|`[^`\n]*`")


def _unattended_capture(text: str, session_id: str) -> str | None:
    """The phrase that leaves a capture running, when this conversation registered no capture watch; None otherwise.
    Quoted text is not this reply's own claim: the report on the 2026-10-24 incident quoted 「會一直跑到結束」 and was
    blocked for it."""
    for line in text[-TAIL_CHARS:].splitlines():
        line = QUOTED.sub("", line)
        hit = CAPTURE_ONGOING.search(line)
        if not hit or not CAPTURE_NOUN.search(line):
            continue
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import f1s_live
            if f1s_live.active_captures(session_id):
                return None
        except Exception:  # noqa: BLE001 - fail open: a broken watch store never blocks a turn
            return None
        return hit.group(0)
    return None


OPERATOR_DECISION = re.compile(r"需要你(?:決定|授權)|需要 ?operator ?(?:決定|授權)|\b(?:needs|requires) (?:your|the operator'?s?) "
                               r"(?:decision|authorit|approval)", re.IGNORECASE)


def _pinned_unshipped(transcript: Path) -> list[str]:
    """Pinned files this transcript edited that still differ from the shipped runtime; [] on any error."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import pinned_drift
        rows = pinned_drift.drifted()
        return pinned_drift.edited_by(transcript, [r["path"] for r in rows]) if rows else []
    except Exception:  # noqa: BLE001 - fail open: a broken checker never blocks a turn
        return []


def _origin_cwd(transcript: Path) -> str:
    """The cwd the session was opened in (its first transcript row that records one): the seat it serves. The Stop
    event's own cwd follows every `cd` of the turn, so a seat shell that ended in the hub root read as the curator."""
    try:
        with transcript.open("rb") as fh:
            for _ in range(200):
                raw = fh.readline()
                if not raw:
                    break
                try:
                    row = json.loads(raw.decode("utf-8-sig"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(row, dict) and str(row.get("cwd") or "").strip():
                    return str(row["cwd"])
    except OSError:
        pass
    return ""


def _open_orders(doc: dict, transcript: Path) -> tuple[str, list[dict]]:
    """(seat, the curator's open orders this conversation must answer) — curator_orders.py; ("", []) on any error
    (fail open). An order another conversation owns (it answered or claimed it) does not hold this turn: on 2026-10-28
    reopened jci_taipei#5 pushed every jci_taipei session, and only its owner had the evidence to answer."""
    try:
        cwd = _origin_cwd(transcript) or str(doc.get("cwd") or "")
        if not cwd.strip():
            return "", []
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import curator_orders
        seat = curator_orders.seat_of(cwd)
        return seat, curator_orders.open_orders(seat, session_id=str(doc.get("session_id") or ""))
    except Exception:  # noqa: BLE001 - fail open: a broken order store never blocks a turn
        return "", []


# ---------------------------------------------------------------- input / config


def _read_hook_input(stream) -> dict:
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
    except (TypeError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        if CONFIG.is_file():
            loaded = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                for key in DEFAULTS:
                    if key in loaded:
                        cfg[key] = loaded[key]
    except (OSError, ValueError):
        pass  # a broken config file means defaults, never a crash
    return cfg


def _compile(patterns) -> list[re.Pattern]:
    out = []
    for item in patterns if isinstance(patterns, list) else []:
        try:
            out.append(re.compile(str(item), re.IGNORECASE))
        except re.error:
            continue
    return out


# ---------------------------------------------------------------- transcript


def _safe_transcript_path(doc: dict) -> Path | None:
    raw = str(doc.get("transcript_path") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).expanduser().resolve()
        path.relative_to(CLAUDE_PROJECTS_ROOT.resolve())
        return path if path.is_file() else None
    except (OSError, RuntimeError, ValueError):
        return None


def _tail_rows(path: Path):
    """Yield the transcript's last rows newest first, from a bounded tail read."""
    with path.open("rb") as fh:
        end = fh.seek(0, os.SEEK_END)
        start = max(0, end - TAIL_BYTES)
        fh.seek(start)
        data = fh.read(end - start)
    lines = data.split(b"\n")
    if start > 0 and lines:
        lines = lines[1:]  # the first fragment may be a cut record
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(row, dict):
            yield row


def _blocks(row: dict) -> list:
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _is_human_prompt(row: dict) -> bool:
    if row.get("type") != "user":
        return False
    # A block's own reason comes back as an isMeta user row; counting it as a new prompt reset the per-prompt
    # cap on every push (93 of 93 logged blocks read 1/2, 2026-10-11..23). Same filter as claude-proof-hook.py.
    if any(row.get(flag) for flag in ("isMeta", "isCompactSummary", "isVisibleInTranscriptOnly")):
        return False
    blocks = _blocks(row)
    if not blocks:
        return False
    return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)


def closing_text(path: Path) -> tuple[str, str | None]:
    """Text the model produced after its last tool call, plus the prompt row's uuid.

    Walk backwards: assistant text blocks are collected until a tool_use block or a
    user row is met. The user row that ends the walk (or the nearest human prompt
    before it) identifies the turn for the per-turn budget.
    """
    parts: list[str] = []
    turn_uuid = None
    ended = False
    walked = 0
    for row in _tail_rows(path):
        walked += 1
        if walked > MAX_ROWS:
            break
        kind = row.get("type")
        if not ended:
            if kind == "assistant":
                blocks = _blocks(row)
                if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in blocks):
                    ended = True
                else:
                    for b in blocks:
                        if isinstance(b, dict) and b.get("type") == "text":
                            parts.insert(0, str(b.get("text") or ""))
                continue
            if kind == "user":
                ended = True
                if _is_human_prompt(row):
                    turn_uuid = str(row.get("uuid") or "")
                    break
                continue
            continue
        if _is_human_prompt(row):
            turn_uuid = str(row.get("uuid") or "")
            break
    return "\n".join(parts).strip(), turn_uuid


# ---------------------------------------------------------------- state / log


def _state_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80] or "unknown"
    return STATE_DIR / f"{safe}.json"


def _load_state(session_id: str) -> dict:
    try:
        doc = json.loads(_state_path(session_id).read_text(encoding="utf-8-sig"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(session_id: str, state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        target = _state_path(session_id)
        staged = target.with_name(target.name + f".{os.getpid()}.tmp")
        staged.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(staged, target)
    except OSError:
        pass


def _log(entry: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- decision


def judge(text: str, cfg: dict) -> tuple[str, str | None]:
    """Return ("block" | "allow", matched pattern or reason)."""
    tail = text[-TAIL_CHARS:]
    if not tail.strip():
        return "allow", "empty_closing"
    for pat in _compile(cfg.get("done_patterns")):
        if pat.search(tail):
            return "allow", f"done:{pat.pattern}"
    for pat in _compile(cfg.get("pending_patterns")):
        hit = pat.search(tail)
        if hit:
            return "block", hit.group(0)
    return "allow", "no_pending_marker"


def evaluate(doc: dict, cfg: dict | None = None) -> dict | None:
    """Return the hook payload to print, or None for silence (= let the turn end)."""
    cfg = cfg or _config()
    if not cfg.get("enabled", True):
        return None
    if doc.get("hook_event_name") != "Stop":
        return None
    session_id = str(doc.get("session_id") or "")
    path = _safe_transcript_path(doc)
    if path is None:
        return None
    text, turn_uuid = closing_text(path)
    verdict, matched = judge(text, cfg)
    decided = bool(OPERATOR_DECISION.search(text[-TAIL_CHARS:]))
    pinned = [] if decided else _pinned_unshipped(path)
    seat, orders = ("", []) if decided or pinned else _open_orders(doc, path)
    # An unwatched capture is checked even after 「需要你決定」: a decision line does not watch a recording.
    capture = None if pinned or orders else _unattended_capture(text, session_id)
    if pinned:
        verdict, matched = "block", "pinned_unshipped:" + ",".join(pinned)
    elif orders:
        verdict, matched = "block", f"curator_orders:{seat}#" + ",".join(str(o.get("n")) for o in orders)
    elif capture:
        verdict, matched = "block", f"unattended_capture:{capture}"
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id": session_id,
        "cwd": str(doc.get("cwd") or ""),
        "stop_hook_active": bool(doc.get("stop_hook_active")),
        "turn": turn_uuid,
        "verdict": verdict,
        "matched": matched,
        "closing_chars": len(text),
    }
    if verdict != "block":
        _log(entry)
        return None

    state = _load_state(session_id)
    if state.get("turn") != turn_uuid:
        state = {"turn": turn_uuid, "blocks": 0, "session_blocks": int(state.get("session_blocks") or 0)}
    per_turn = int(cfg.get("max_blocks_per_turn") or 0)
    per_session = int(cfg.get("max_blocks_per_session") or 0)
    if state.get("blocks", 0) >= per_turn or state.get("session_blocks", 0) >= per_session:
        entry.update({"verdict": "allow", "matched": f"budget_exhausted:{matched}",
                      "blocks": state.get("blocks"), "session_blocks": state.get("session_blocks")})
        _log(entry)
        return None
    state["blocks"] = int(state.get("blocks", 0)) + 1
    state["session_blocks"] = int(state.get("session_blocks", 0)) + 1
    state["last"] = entry["ts"]
    _save_state(session_id, state)
    entry.update({"blocks": state["blocks"], "session_blocks": state["session_blocks"]})
    _log(entry)
    if pinned:
        import pinned_drift
        reason = REASON_PINNED.format(paths=", ".join(pinned), command=pinned_drift.ship_command(pinned),
                                      n=state["blocks"], cap=per_turn)
    elif orders:
        import curator_orders
        reason = REASON_ORDERS.format(orders=", ".join(f"#{o.get('n')} {o.get('title')}" for o in orders), seat=seat,
                                      command=f"python {curator_orders.__file__} answer {seat}",
                                      n=state["blocks"], cap=per_turn)
    elif capture:
        reason = REASON_CAPTURE.format(matched=capture, n=state["blocks"], cap=per_turn)
    else:
        reason = REASON.format(matched=f" (matched: {matched!r})", n=state["blocks"], cap=per_turn)
    return {"decision": "block", "reason": reason}


def main() -> int:
    doc = _read_hook_input(sys.stdin)
    payload = evaluate(doc)
    if payload:
        print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
