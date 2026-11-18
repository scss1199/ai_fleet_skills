#!/usr/bin/env python3
"""curator_orders.py — F1S governs every cwd: ai_darkhero's correction orders outrank a seat's own decisions.

operator 2026-10-24: 「你來想一個好辦法解決 ai_darkhero 的對話擁有最高權限來校正除了你以外的cwd內容」, then
「優先於 然後馬上實作疊代f1s (f1s就是會優先於其他cwd的意思 你構造f1s 用f1s統御其他cwd)」. T1 `f1s-governs` states
the precedence; red lines and the operator's own words in a seat stay above an order.

An order lives in _registry/curator-orders/<seat>.json and reaches the seat four ways:
  1. claude_session_hook.py puts the seat's open orders first in every SessionStart / UserPromptSubmit context,
  2. claude-run-until-done-hook.py keeps the seat's turn going while an order is open (its existing caps apply),
  3. git_smart.py refuses a non-curator commit that touches a path an order froze,
  4. fleet-process-guard.py stops a process whose command line an order forbids (never the protected list).
The seat answers with evidence paths or a reason; the curator closes the order (its freeze/forbid end) or reopens it.

operator 2026-10-29 (「讓f1s直接把這裡討論的內容變成完整提示詞直接送到其他對應cwd的主對話直接開始」): the `do` text IS the
complete prompt the seat executes -- self-contained (goal, context, concrete steps, constraints, acceptance, how to
answer), never a pointer into ai_darkhero's conversation. Delivery to the seat's MAIN conversation: f1s_live wakes an
idle chat with the full text; when the curator sends it itself (desktop send_message, or start_session in that cwd
when no chat is open) it records `deliver <seat> <n> --session <id>` so the order knows which conversation runs it.

CLI (issue / reopen / close only from the curator's cwd, ai_darkhero or the hub root):
  python curator_orders.py issue <seat> --title T (--do TEXT | --prompt-file PATH) [--freeze HUB_PATH]... [--forbid CMDLINE_PART]...
  python curator_orders.py deliver <seat> <n> --session LOCAL_ID   (the seat's main conversation it was sent to)
  python curator_orders.py list [<seat>]
  python curator_orders.py answer <seat> <n> --evidence PATH [PATH...] [--note "dead 15 -> 3; commit abc1234"] | --cannot REASON
  python curator_orders.py claim <seat> <n> [--release] [--session ID]   (owner: the one conversation pushed to answer)
  python curator_orders.py reopen <seat> <n> --note TEXT
  python curator_orders.py close <seat> <n>
The cwd check keeps a seat from issuing or closing by accident; it is not a sandbox.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _projects  # noqa: E402
from _paths import COMMON as HUB, REGISTRY  # noqa: E402

ORDERS_DIR = os.path.join(REGISTRY, "curator-orders")
CONTROL_STATE = os.path.join(REGISTRY, "f1s-control.json")
SESSION_SCOPE = os.path.join(REGISTRY, "f1s-session-scope.json")  # {"sessions": {<id>: <the one thing it does>}}
TECHNIQUES = os.path.join(REGISTRY, "f1s-apply.json")
UNCLAIMED_AFTER_S = 3600
STALE_OWNER_AFTER_S = 6 * 3600  # owner transcript silent this long: the claim blocks every other chat (ai_metadata #14/#15, 11-10)
HANDOVER_AFTER_S = 3600  # owner transcript silent this long (the cache TTL): a same-seat chat holding evidence may answer
CLAUDE_PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects")
CURATOR_FALLBACK = "ai_darkhero"
REVIEW_SAMPLE = 8       # one routine order in this many still gets the curator's review
REVIEW_BATCH = 8        # answers with fresh evidence that wake an idle curator chat together (wake_queue)
REVIEW_BATCH_H = 6.0    # ... or the oldest of them waiting this many hours
MECHANICAL = "mechanical"
ACTIVE = ("open", "done", "cannot")  # freeze / forbid hold until the curator closes the order
PROTECTED = ("logioptionsplus", "optionsplusupdater")  # T1 protect-logi-options-plus: never a forbid target
MIN_FORBID_CHARS = 8  # "python" would stop half the box


def seat_of(cwd: str) -> str:
    """Registered seat owning `cwd` (nearest registered ancestor; hub root and hub infra -> curator)."""
    node = os.path.abspath(cwd or os.getcwd())
    while True:
        try:
            name, meta = _projects.whoami(node)
        except Exception:
            name, meta = "unknown", None
        if meta:
            return str(name)
        parent = os.path.dirname(node)
        if parent == node:
            return "unknown"
        node = parent


def curator() -> str:
    seat = seat_of(HUB)
    return seat if seat != "unknown" else CURATOR_FALLBACK


def is_curator(cwd: str) -> bool:
    return seat_of(cwd) == curator()


def _session_cwd() -> str | None:
    """Folder of the Claude Code session running this command (nearest claude-code ancestor), or None.

    The cwd alone can be faked by `cd C:\\ai_workspace`: on 2026-10-28 a jci_taipei session closed its own orders
    #4 and #5 that way, minutes after answering them, before the curator had reviewed either."""
    try:
        import psutil  # noqa: WPS433
        for proc in psutil.Process(os.getpid()).parents():
            try:
                if proc.name().lower().startswith("claude") and "claude-code" in (proc.exe() or "").lower():
                    return proc.cwd()
            except (psutil.Error, OSError):
                continue
    except Exception:  # noqa: BLE001 - no psutil or no access: fall back to the cwd check alone
        return None
    return None


def _require_curator(cwd: str, what: str) -> dict:
    """Both the command's cwd and the session it runs in must be the curator's; returns the audit record."""
    session = _session_cwd()
    if not is_curator(cwd) or (session is not None and not is_curator(session)):
        raise PermissionError(f"only {curator()} {what} (cwd resolves to {seat_of(cwd)}, "
                              f"session to {seat_of(session) if session else 'none'})")
    return {"cwd": os.path.abspath(cwd), "session": session}


def _path(seat: str) -> str:
    return os.path.join(ORDERS_DIR, f"{seat}.json")


def load(seat: str) -> dict:
    try:
        with open(_path(seat), encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, dict) and isinstance(doc.get("orders"), list):
            return doc
    except (OSError, ValueError):
        pass
    return {"schema": 1, "seat": seat, "orders": []}


def _save(seat: str, doc: dict) -> None:
    os.makedirs(ORDERS_DIR, exist_ok=True)
    tmp = _path(seat) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, _path(seat))


def _seats_with_orders() -> list[str]:
    try:
        return sorted(f[:-5] for f in os.listdir(ORDERS_DIR) if f.endswith(".json"))
    except OSError:
        return []


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _find(doc: dict, n: int) -> dict:
    for order in doc["orders"]:
        if order.get("n") == n:
            return order
    raise ValueError(f"no order #{n} for {doc['seat']}")


def _hub_rel(path: str) -> str:
    full = os.path.abspath(os.path.join(HUB, path))
    rel = os.path.relpath(full, HUB).replace("\\", "/")
    if rel.startswith("../") or rel == "..":
        raise ValueError(f"freeze path outside the hub: {path}")
    return rel


def issue(seat: str, title: str, do: str, freeze=(), forbid=(), cwd: str | None = None, routine: bool = False,
          ledger: bool = False, machine: dict | None = None) -> dict:
    """ledger=True: an engine reads the answer back into its own table (f1s_fanout), so any answer closes the order.
    machine={...}: an engine issues it from inside a seat's own session (Stop hook), so the curator-session check is
    skipped; the order is marked `"machine": true` and the dict's fields (e.g. "gap") are stored on it. Never routine-free."""
    cwd = cwd or os.getcwd()
    if not (do or "").strip():
        raise ValueError("an order needs its full prompt text (--do or --prompt-file)")
    if machine is None:
        _require_curator(cwd, "issues orders")
    elif not is_curator(cwd):
        raise PermissionError(f"machine issue needs the curator cwd (cwd resolves to {seat_of(cwd)})")
    if seat == curator() and not machine:      # machine = a gap order from the curator's own report, done by a station
        raise ValueError("an order corrects another cwd, not the curator")
    if seat not in _projects._load():
        raise ValueError(f"unknown seat {seat!r}")
    for part in forbid:
        low = part.lower()
        if len(part.strip()) < MIN_FORBID_CHARS:
            raise ValueError(f"forbid pattern too broad: {part!r} (min {MIN_FORBID_CHARS} chars)")
        if any(p in low for p in PROTECTED):
            raise ValueError("Logi Options+ is protected (T1 protect-logi-options-plus)")
    doc = load(seat)
    order = {"n": max((o.get("n", 0) for o in doc["orders"]), default=0) + 1, "issued_at": _now(),
             "issued_from": os.path.abspath(cwd), "title": title, "do": do,
             "freeze": [_hub_rel(p) for p in freeze], "forbid": list(forbid), "status": "open"}
    if machine is not None:
        routine = True
        order["machine"] = True
        order.update(machine)
    if routine and not freeze and not forbid:
        order["routine"] = True
        if ledger:
            order["ledger"] = True
    doc["orders"].append(order)
    _save(seat, doc)
    return order


# operator 2026-11-17: 「還沒解決的 < 推理應當如何解決過程自動去補缺口」 — the "not solved yet" bullets of a final report
# become routine orders for the conversation's own seat; F1S hands an unowned one to a lean station after 2 h.
RUN_UNTIL_DONE = os.path.join(REGISTRY, "run-until-done.json")
GAP_PER_DAY = 6
GAP_MAX_ITEMS = 5
GAP_MIN_CHARS = 12
GAP_DEDUPE_S = 14 * 86400
GAP_CONTEXT_CHARS = 1200
GAP_SKIP_SEATS = ("quant", "fracdigi", "kyloren_quant", "ai_accountancy")
GAP_HEADINGS = ("還沒解決的", "還沒解決", "尚未解決", "未解決", "還沒做的", "未完成", "not solved yet", "unresolved")
GAP_OPERATOR_CALLS = ("需要你決定", "授權", "你點頭", "operator 親手", "金鑰", "永久刪除")
_BULLET = re.compile(r"^\s*(?:[-*•])\s+(.*\S)\s*$")
_HEADING_MARKS = "#*:： \t"


def _heading_text(line: str) -> str:
    return line.strip().strip(_HEADING_MARKS).strip().lower()


def _is_heading(line: str) -> bool:
    s = line.strip()
    return s.startswith("#") or bool(re.fullmatch(r"\*\*[^*]+\*\*\s*[:：]?", s)) or bool(re.fullmatch(r"__[^_]+__\s*[:：]?", s))


def gap_items(text: str) -> list[str]:
    """Bullets under a 「還沒解決的」-style heading of a final reply, minus short ones and the operator's own calls."""
    items: list[str] = []
    in_section = False
    blank = False
    for line in (text or "").splitlines():
        if not in_section:
            if _is_heading(line) and _heading_text(line) in GAP_HEADINGS:
                in_section, blank = True, False
            continue
        if not line.strip():
            blank = True
            continue
        if "沒有下一步" in line:
            break
        bullet = _BULLET.match(line)
        if bullet:
            blank = False
            items.append(bullet.group(1))
            continue
        if _is_heading(line):
            if _heading_text(line) in GAP_HEADINGS:
                blank = False
                continue
            break
        if blank or not line[:1].isspace():
            break
        # an indented line right after a bullet continues it; the bullet text stays as written on its own line
    out = [i for i in items if len(i) >= GAP_MIN_CHARS and not any(k in i for k in GAP_OPERATOR_CALLS)]
    return out[:GAP_MAX_ITEMS]


def _gap_hash(item: str) -> str:
    import hashlib
    return hashlib.sha1(" ".join(item.split()).lower().encode("utf-8")).hexdigest()


def _gap_switch() -> bool:
    """`live_wake.gap_orders` in run-until-done.json: default on, false/0 off; unreadable = on (fail open like its neighbours)."""
    try:
        with open(RUN_UNTIL_DONE, encoding="utf-8-sig") as fh:
            value = (json.load(fh).get("live_wake") or {}).get("gap_orders", True)
    except (OSError, ValueError, AttributeError):
        return True
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "off", "no", "")
    return bool(value)


GAP_REFS_CHARS = 600  # URLs and `code` references of the whole reply, so an item that says "this video" can be done


def _gap_context(item: str, text: str) -> str:
    """The reply text that ends at the item (2026-11-17 ai_darkhero#3: the head of a long reply said nothing about an
    item near its end); the head when the item is not found or already sits inside it."""
    at = text.find(item[:30])
    return text[:GAP_CONTEXT_CHARS] if at <= GAP_CONTEXT_CHARS else text[at - GAP_CONTEXT_CHARS:at]


def _gap_refs(text: str) -> str:
    refs: list[str] = []
    for ref in re.findall(r"https?://[^\s)>\]】」`]+|`[^`\n]{3,120}`", text):
        if ref not in refs and sum(map(len, refs)) + len(ref) <= GAP_REFS_CHARS:
            refs.append(ref)
    return "References in the whole reply: " + " ; ".join(refs) + "\n\n" if refs else ""


def _gap_do(item: str, context_text: str) -> str:
    return (
        "A conversation in this cwd ended its report with this item still unsolved:\n\n"
        f"\"{item}\"\n\n"
        "Surrounding reply (verbatim, for context):\n\n"
        f"{_gap_context(item, context_text or '')}\n\n"
        f"{_gap_refs(context_text or '')}"
        "Find the root cause, make the smallest change that fixes it, and verify with a re-run test or a measurement. "
        "Answer this order with `--evidence <path or commit:sha> --note \"<before -> after>\"`, or with "
        "`--cannot \"<reason>\"` when it needs the operator's authority, money, a secret, permanent deletion, a new "
        "scheduled job, or a file outside this cwd. Never ask a question."
    )


def issue_gaps(seat: str, items, context_text: str, session_id: str = "", now: float | None = None) -> list[int]:
    """One machine-issued routine order per gap item for `seat`; returns the order numbers issued.
    Guards: seat not skipped, switch on, no same item (sha1) within 14 days, at most GAP_PER_DAY per 24 h."""
    if seat in GAP_SKIP_SEATS or not items or not _gap_switch():
        return []
    now = time.time() if now is None else now
    doc = load(seat)

    def age(order: dict) -> float:
        try:
            return now - time.mktime(time.strptime(str(order.get("issued_at")), "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, OverflowError):
            return 0.0

    seen = {o.get("gap") for o in doc["orders"] if o.get("gap") and age(o) < GAP_DEDUPE_S}
    today = sum(1 for o in doc["orders"] if o.get("gap") and age(o) < 86400)
    made: list[int] = []
    for item in items:
        digest = _gap_hash(item)
        if digest in seen:
            continue
        if today >= GAP_PER_DAY:
            break
        order = issue(seat, "未解決缺口：" + item[:40], _gap_do(item, context_text),
                      cwd=os.path.join(HUB, curator()), routine=True,
                      machine={"gap": digest, "gap_session": session_id})
        seen.add(digest)
        today += 1
        made.append(order["n"])
    return made


def deliver(seat: str, n: int, session: str, cwd: str | None = None) -> dict:
    """Record the seat's main conversation the curator sent this order to (desktop send_message / start_session)."""
    cwd = cwd or os.getcwd()
    _require_curator(cwd, "delivers orders")
    if not str(session or "").strip():
        raise ValueError("deliver needs the target conversation id")
    doc = load(seat)
    order = _find(doc, n)
    order["delivery"] = {"session": str(session).strip(), "at": _now(), "from": os.path.abspath(cwd)}
    _save(seat, doc)
    return order


def _session_id(session: str | None = None) -> str:
    """The Claude conversation running this command (CLAUDE_CODE_SESSION_ID), or "" outside one."""
    return str(session if session is not None else os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip()


def owner_of(order: dict) -> str:
    return str((order.get("owner") or {}).get("session") or "")


def order_text(order: dict) -> str:
    """The prompt a seat executes: `do`, plus the curator's reopen note when the order was reopened. On 2026-11-18 five
    reopened free-pool orders carried their concrete task only in the note; the hook and the station showed `do` alone,
    so stations re-answered the same cannot in 20 s."""
    do = str(order.get("do") or "")
    note = str(order.get("note") or "").strip()
    if order.get("reopened_at") and note:
        return f"{do}\n\n【curator 重開說明（最新，優先於先前的回覆）】{note}"
    return do


def owned_by_other(order: dict, session_id: str) -> bool:
    """True when another conversation owns this order: it reads the order but is not pushed to answer it."""
    owner = owner_of(order)
    return bool(owner) and bool(session_id) and owner != session_id


COMMIT = "commit:"


def _commit_time(cwd: str, ref: str) -> float | None:
    """Commit time of `ref` in the repository holding cwd; None when it is not a commit there."""
    import subprocess  # noqa: PLC0415
    try:
        run = subprocess.run(["git", "-C", cwd, "show", "-s", "--format=%ct", ref + "^{commit}"], capture_output=True, text=True,
                             timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    out = run.stdout.strip()
    return float(out) if run.returncode == 0 and out.isdigit() else None


def _seat_commit_time(seat: str, cwd: str, ref: str) -> float | None:
    """A seat's commit, looked up where the answer was typed and then in the seat's own repository: a shell drifted to
    the hub root had `commit:<sha>` refused though the commit existed (jci_taipei #62, 2026-11-13)."""
    found = _commit_time(cwd, ref)
    return found if found is not None else _commit_time(os.path.join(str(HUB), seat), ref)


def _accepted_mechanically(order: dict, seat: str = "") -> bool:
    """A machine-issued order answered with evidence written after it was issued closes without waking the curator: 68 such
    reviews cost 0.2M each and reopened 4, two of them for stale evidence, which this checks (2026-11-03). Every REVIEW_SAMPLE-th
    order and any reopened one still go to review, so the other kinds of defect keep being seen."""
    if not order.get("routine") or order.get("reopened_at") or order.get("n", 0) % REVIEW_SAMPLE == 0:
        return False
    if order.get("ledger"):
        # A self-review answer is read back by f1s_fanout.collect and reported as one table per version: 371 of them woke the
        # curator once each in three days and none was reopened for its content (2026-11-11).
        return True
    return _evidence_fresh(order, seat)


def _evidence_fresh(order: dict, seat: str = "") -> bool:
    """True when at least one evidence path or commit of the answer was written after the order was issued."""
    try:
        issued = time.mktime(time.strptime(order.get("issued_at", ""), "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return False
    for path in (order.get("answer") or {}).get("evidence") or ():
        if path.startswith(COMMIT):
            if (_seat_commit_time(seat, order["answer"].get("from") or str(HUB), path[len(COMMIT):]) or 0) >= issued:
                return True
            continue
        try:
            if os.path.getmtime(path) >= issued:
                return True
        except OSError:
            continue
    return False


def answer(seat: str, n: int, evidence=(), reason: str = "", cwd: str | None = None,
           session: str | None = None, note: str = "") -> dict:
    """evidence -> done (note = the seat's counts / commit / what it left, read back by f1s_fanout.collect);
    reason -> cannot. One of the two; jci_taipei 2026-11-10 #24 had to park its counts in a scratchpad file."""
    cwd = cwd or os.getcwd()
    if not evidence and not reason.strip():
        reason = note      # `--note "no finding possible: <why>"` alone is the one-line answer the fan-out order asks for
    if bool(evidence) == bool(reason.strip()):
        raise ValueError("answer with --evidence PATH... [--note TEXT], --cannot REASON, or --note TEXT alone; not both")
    reason = (reason or note).strip()
    # `commit:<sha>` is evidence too: seats were writing a one-off runtime/curator-<n>.txt per order only to have a path
    # to name (2026-11-13: ai_trader, ai_photo, sdnext_a770), and nothing ever read those files again.
    missing = [p for p in evidence if (_seat_commit_time(seat, cwd, p[len(COMMIT):]) is None if p.startswith(COMMIT)
                                       else not os.path.exists(os.path.join(cwd, p)))]
    if missing:
        raise ValueError(f"evidence path not found: {missing}")
    doc = load(seat)
    order = _find(doc, n)
    if order["status"] != "open":
        raise ValueError(f"order #{n} is {order['status']}, not open")
    sid = _session_id(session)
    if owner_of(order) and owner_of(order) != sid:
        if evidence and _silent_owner_handover(order, seat, cwd, sid):
            order["owner"] = {"session": sid, "from": os.path.abspath(cwd), "at": _now(), "by": "handover",
                              "took_from": owner_of(order)}
        else:
            # ai_trader 2026-11-07..09: the main chat answered #87 that its Fable session had claimed, from a shell
            # drifted to the hub root; only the owner, or the curator's own session (not its cwd), may answer it.
            _require_curator(cwd, f"answers order #{n} owned by conversation {owner_of(order)[:8]}")
    order["status"] = "done" if evidence else "cannot"
    order["answer"] = {"at": _now(), "from": os.path.abspath(cwd), "session": sid,
                       "evidence": [p if p.startswith(COMMIT) else os.path.abspath(os.path.join(cwd, p)) for p in evidence],
                       "reason": reason}
    if sid and not owner_of(order):
        # The answering conversation owns the order from now on: when the curator reopens it, only that
        # conversation is pushed to finish it (jci_taipei 2026-10-28: #5 reopened pushed every jci_taipei session).
        order["owner"] = {"session": sid, "from": os.path.abspath(cwd), "at": _now(), "by": "answer"}
    if _accepted_mechanically(order, seat):
        order.update(status="closed", closed_at=_now(), closed_from=MECHANICAL)
    _save(seat, doc)
    return order


def _silent_owner_handover(order: dict, seat: str, cwd: str, sid: str) -> bool:
    """True when a conversation of the same seat may answer, with evidence, an order another conversation owns: the owner's
    transcript exists and was last written HANDOVER_AFTER_S ago or more. Third time the finished work of a seat waited for
    the curator behind a silent owner (ai_metadata #14/#15 11-10, #27 11-11, ai_ziyaoastro #57/#58 11-17: 2.1 h, 3.3 h, 5 h
    silent, all under the 6 h STALE line). A missing transcript or unreadable projects dir is unknown, not silent, and a
    station- owner has no transcript: those stay with the curator. The session's own folder decides the seat, not the shell."""
    owner = owner_of(order)
    if not sid or owner.startswith(STATION_SESSION):
        return False
    where = _session_cwd() or cwd
    if seat_of(where) != seat or is_curator(where):
        return False
    silent = _owner_silent_s(owner)
    return HANDOVER_AFTER_S <= silent < float("inf")


def claim(seat: str, n: int, release: bool = False, cwd: str | None = None, session: str | None = None) -> dict:
    """Bind an open order to one conversation (or release it). The owning conversation, or the curator, may change
    an existing owner; any conversation may claim an unowned order. Freeze / forbid are unaffected."""
    cwd = cwd or os.getcwd()
    sid = _session_id(session)
    if not sid:
        raise ValueError("no session id: run inside a Claude conversation (CLAUDE_CODE_SESSION_ID) or pass --session")
    doc = load(seat)
    order = _find(doc, n)
    if order["status"] != "open":
        raise ValueError(f"order #{n} is {order['status']}, not open")
    current = owner_of(order)
    if current and current != sid:
        # The session's own folder decides, not the shell cwd: `cd C:\ai_workspace` let ai_trader's main chat
        # override the claim its Fable session held (#86/#87, 2026-11-07).
        _require_curator(cwd, f"changes the owner of order #{n} (owned by conversation {current[:8]})")
    if release:
        order.pop("owner", None)
    else:
        order["owner"] = {"session": sid, "from": os.path.abspath(cwd), "at": _now(), "by": "claim"}
    _save(seat, doc)
    return order


def _curator_change(seat: str, n: int, cwd: str | None, status: str, note: str = "") -> dict:
    cwd = cwd or os.getcwd()
    who = _require_curator(cwd, "reopens or closes orders")
    doc = load(seat)
    order = _find(doc, n)
    if status == "open" and order.get("answer"):
        order.setdefault("history", []).append(order.pop("answer"))
    order["status"] = status
    order[f"{status}_at" if status == "closed" else "reopened_at"] = _now()
    order["closed_from" if status == "closed" else "reopened_from"] = who
    if note:
        order["note"] = note
    _save(seat, doc)
    return order


def reopen(seat: str, n: int, note: str, cwd: str | None = None) -> dict:
    return _curator_change(seat, n, cwd, "open", note)


def close(seat: str, n: int, cwd: str | None = None, note: str = "") -> dict:
    return _curator_change(seat, n, cwd, "closed", note)


def out_of_scope(session_id: str | None) -> bool:
    """True for a conversation the operator keeps on one job: no orders, no review queue, no articles, no idle wake.
    Operator 2026-11-02 「另一個對話保持只看商品販售的內容」: the sale chat shares the curator's cwd, so it was woken 43
    times for the review queue and did the curator's work. An unreadable file scopes nobody."""
    if not session_id:
        return False
    try:
        with open(SESSION_SCOPE, encoding="utf-8") as fh:
            return session_id in (json.load(fh).get("sessions") or {})
    except (OSError, ValueError, AttributeError):
        return False


ARCHIVE_DUE = os.path.join(REGISTRY, "session-consolidate", "archive-due.json")
ARCHIVE_DUE_STAMP = os.path.join(REGISTRY, "session-consolidate", "archive-due.stamp")
ARCHIVE_DUE_REFRESH_S = 30 * 60


def _refresh_archive_due(now: float, spawn=None) -> None:
    """Re-scan in a hidden child at most every ARCHIVE_DUE_REFRESH_S (the stamp holds the last spawn epoch)."""
    _hidden_refresh(now, ARCHIVE_DUE_STAMP, ARCHIVE_DUE_REFRESH_S, ["session-consolidate.py", "due"], spawn)


def _hidden_refresh(now: float, stamp: str, every_s: float, script_args: list, spawn=None) -> None:
    try:
        with open(stamp, encoding="utf-8") as fh:
            if now - float(fh.read().strip() or 0) < every_s:
                return
    except (OSError, ValueError):
        pass
    try:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write(str(now))
        argv = [os.path.join(os.path.dirname(sys.executable), "pythonw.exe") if os.name == "nt" else sys.executable,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), script_args[0]), *script_args[1:]]
        if not os.path.exists(argv[0]):
            argv[0] = sys.executable
        if spawn:
            spawn(argv)
        else:
            import subprocess
            subprocess.Popen(argv, cwd=HUB, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=0x08000000 | 0x00000008 if os.name == "nt" else 0, close_fds=True)
    except OSError:
        pass


TOKEN_WATCH_STAMP = os.path.join(REGISTRY, "f1s-waste.stamp")
TOKEN_WATCH_REFRESH_S = 3600


def token_watch(now: float | None = None, spawn=None, line_fn=None) -> str:
    """operator 2026-11-06 「讓這個主對話去監控各cwd的付費模型與免費模型的消耗狀態與使用狀態」: the curator sees paid spend
    per cwd by model and free-pool use every turn; f1s_waste.py measure re-runs hidden at most hourly. Fail-open."""
    now = time.time() if now is None else now
    _hidden_refresh(now, TOKEN_WATCH_STAMP, TOKEN_WATCH_REFRESH_S, ["f1s_waste.py", "measure", "--days", "2"], spawn)
    if line_fn is None:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("f1s_waste_watch", os.path.join(os.path.dirname(os.path.abspath(__file__)), "f1s_waste.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            line_fn = mod.watch_line
        except Exception:
            return ""
    try:
        return line_fn() or ""
    except Exception:
        return ""


def archive_due(session_id: str = "", now: float | None = None, spawn=None, own: bool = False) -> str:
    """operator 2026-11-06 「注意f1s是否能自動關閉並整併已經沒有任務或沒有意義的子對話」: the curator conversation sees the
    sessions session-consolidate.py `due` found (ended 沒有下一步 or stale, no open ask) and archives them; the scan
    re-runs hidden every 30 min. Never lists the asking conversation itself. Fail-open: no file, no line.
    own (operator 2026-11-13, every cwd): only the sessions this conversation started itself, so a seat's chat closes
    its own finished children without waiting for the curator."""
    now = time.time() if now is None else now
    _refresh_archive_due(now, spawn)
    try:
        with open(ARCHIVE_DUE, encoding="utf-8") as fh:
            rows = json.load(fh).get("due") or []
        if now - os.path.getmtime(ARCHIVE_DUE) > 4 * ARCHIVE_DUE_REFRESH_S:
            return ""
    except (OSError, ValueError, AttributeError):
        return ""
    rows = [r for r in rows if r.get("session_id") != session_id and r.get("host_id") and r.get("host_id") != session_id]
    if own:
        rows = [r for r in rows if session_id and session_id in (r.get("parent"), r.get("parent_session"))]
    if not rows:
        return ""
    items = "; ".join(f"{r['host_id']} ({r.get('reason')}, {str(r.get('title') or '')[:30]})" for r in rows[:8])
    whose = "conversation(s) you started are confirmed complete" if own else "conversation(s) have no task left"
    return (f"SESSION ARCHIVE DUE — {len(rows)} {whose}: {items}. Archive each with "
            f"archive_session (reason = its reason); a reopened one comes back on its next order. " + ARCHIVE_RC_HINT)


# ai_photo 2026-11-18: archive_session refuses an idle chat while Remote Control is on ("still has live work").
ARCHIVE_RC_HINT = ("If archive_session says live work and the target is idle (isRunning=false) with remoteControlActive=true, "
                   "call set_remote_control(enabled=false) on it, then archive_session again; for self, "
                   "set_remote_control(self, false) before archive_session(self).")


def open_orders(seat: str, session_id: str | None = None) -> list[dict]:
    """The seat's open orders; with `session_id`, only those this conversation must answer (unowned or its own)."""
    if out_of_scope(session_id):
        return []
    orders = [o for o in load(seat)["orders"] if o.get("status") == "open"]
    if session_id is None:
        return orders
    # A gap order (issue_gaps) is station work: it never holds the conversation whose report produced it.
    return [o for o in orders if not owned_by_other(o, session_id) and not o.get("gap")]


STATION_SESSION = "station-"   # f1s_station.order answers under this id: the order was done outside every conversation
STATION_LINE_S = 24 * 3600


def station_line(seat: str, now: float | None = None) -> str:
    """One line for the seat's conversations: the orders a lean station did for them in the last day (f1s_live sends a
    routine order there when the conversation is too large to wake). The hook shows an unchanged line once."""
    now = time.time() if now is None else now
    done = []
    for o in load(seat)["orders"]:
        ans = o.get("answer") or {}
        if not str(ans.get("session") or "").startswith(STATION_SESSION):
            continue
        try:
            at = time.mktime(time.strptime(ans.get("at", ""), "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        if now - at <= STATION_LINE_S:
            done.append(f"#{o.get('n')} {o.get('title')} ({o.get('status')}): {str(ans.get('reason') or '')[:160]}")
    return ("STATION DONE — 精簡站已代本 cwd 做完（不必重做；有疑問再看證據）: " + "; ".join(done)) if done else ""


def injection(seat: str, session_id: str = "") -> str:
    if out_of_scope(session_id):
        return ""
    return "\n".join(t for t in (_injection(seat, session_id), station_line(seat), handoff_line(seat, session_id),
                                 model_lane_line(seat, session_id)) if t)


def model_lane_line(seat: str, session_id: str = "", transcript=None) -> str:
    """operator 2026-11-17 Fable/Opus hybrid: the MODEL LANE line from f1s_model_lane for this conversation's own model
    (switch away from a spent quota, or back once it reset); the curator seat also gets the refresh prompt when the plan
    windows are unknown. "" when the transcript is not found or anything fails (fail-open)."""
    try:
        import f1s_model_lane as ml
        from pathlib import Path as _Path
        if transcript is None:
            import glob as _glob
            ok = session_id and session_id.replace("-", "").isalnum()
            found = _glob.glob(os.path.join(CLAUDE_PROJECTS, "*", f"{session_id}.jsonl")) if ok else []
            transcript = _Path(found[0]) if found else None
        if transcript is None:
            return ""
        model = ""
        with open(transcript, "rb") as fh:
            fh.seek(max(0, os.path.getsize(transcript) - 512 * 1024))
            for raw in reversed(fh.read().decode("utf-8", errors="replace").splitlines()):
                if '"assistant"' in raw and '"model"' in raw:
                    try:
                        model = (json.loads(raw).get("message") or {}).get("model") or ""
                    except ValueError:
                        continue
                    if ml.family(model):
                        break
        hosts = [h for h in _projects_host_ids(session_id)] if session_id else []
        out = ml.line(hosts[0] if hosts else session_id, model, transcript=transcript)
        if seat == curator():
            out = "\n".join(t for t in (out, ml.stale_prompt()) if t)
        return out
    except Exception:
        return ""


def _projects_host_ids(session_id: str) -> list:
    """Desktop host id (local_...) of a CLI transcript uuid, from ~/.claude/sessions/<pid>.json; [] when unknown."""
    import glob as _glob
    out = []
    for f in _glob.glob(os.path.join(os.path.expanduser("~"), ".claude", "sessions", "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if d.get("sessionId") == session_id and str(d.get("hostSessionId") or "").startswith("local_"):
            out.append(d["hostSessionId"])
    return out


HANDOFF_OVER_K = 150
ROLLOVER_OVER_K = 180       # `live_wake.rollover_over_k`: above this the advisory becomes a roll-over order, 0 = off
BRIEF_REQUEST_CHARS = 1500


def last_typed_request(path) -> str:
    """The last prompt a person typed in a transcript; wake turns (task notifications, hook feedback, side sessions,
    system reminders) and tool results are skipped. "" when none is found or the file cannot be read."""
    import f1s_waste
    last = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isSidechain"):
                    continue
                content = (rec.get("message") or {}).get("content")
                if isinstance(content, list):
                    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                        continue
                    content = "\n".join(b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text")
                if not isinstance(content, str) or not content.strip():
                    continue
                # 2026-11-19: a request relayed by another session (or typed while the app adds a "Linked sessions
                # now" note) opens with <system-reminder> blocks; skipping the whole row lost the only task the
                # rolled-over 44817296 had ("No typed request found"). Judge the text after those blocks.
                text = re.sub(r"(?s)^(\s*<system-reminder>.*?</system-reminder>\s*)+", "", content).strip()
                if not text or text.startswith(("<system-reminder>", "<command-", "<local-command", "Caveat:")):
                    continue
                if f1s_waste.wake_kind(text) == "operator":
                    last = text
    except OSError:
        return ""
    return last


ROLLOVER_TTL_S = 30 * 60      # an armed hand-over nobody picked up within this is stale
ROLLOVER_TASKS = 12


def rollover_path(seat: str) -> str:
    """The armed hand-over of a seat. Writer: `rollover-brief --arm`; readers: f1s_live.wait (wakes the cleared
    conversation) and claude_session_hook (SessionStart source=clear injects it). One file per seat, rewritten, TTL."""
    return os.path.join(HUB, "_registry", "fames-hot", f"rollover-{seat}.json")


def transcript_state(path) -> tuple[str, list[str]]:
    """(model of the last assistant row, the open steps of the last update_plan list). ("", []) when unreadable."""
    model, items = "", []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if '"assistant"' not in raw:
                    continue
                try:
                    msg = json.loads(raw).get("message") or {}
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if str(msg.get("model") or "").startswith("claude-"):
                    model = msg["model"]
                for b in msg.get("content") or []:
                    if (isinstance(b, dict) and b.get("type") == "tool_use" and str(b.get("name") or "").endswith("update_plan")
                            and isinstance((b.get("input") or {}).get("items"), list)):
                        items = b["input"]["items"]
    except OSError:
        return "", []
    open_steps = [str(i.get("content") or "") for i in items
                  if isinstance(i, dict) and i.get("status") != "completed" and i.get("content")]
    return model, open_steps[:ROLLOVER_TASKS]


def rollover_brief_text(seat: str, session_id: str, context: int, last_request: str, model: str = "",
                        open_tasks: list | None = None) -> str:
    """The whole prompt of the conversation that takes over a rolled-over one. Pure: no file is read or written."""
    k = f"{context // 1000}K"
    sid = session_id or "unknown"
    transcript = f"C:/Users/<user>/.claude/projects/*/{session_id}.jsonl" if session_id else "(unknown)"
    if last_request:
        task = ("Task to carry out now (the operator's latest request, verbatim):\n"
                + last_request[:BRIEF_REQUEST_CHARS])
    else:
        task = "No typed request found; ask nothing, read the park file."
    lines = [f"This conversation continues {seat}'s conversation {sid}, which F1S rolled over at {k}"
             + (f" on model {model} (keep it)." if model else "."),
             "Read first, and only if needed: C:/ai_workspace/_registry/agc-compact/" + f"{seat}.md" + " and C:/ai_workspace/_logs/park/"
             + f"{seat}.md" + " (last entry).",
             task]
    if open_tasks:
        lines.append("Open steps left by the old conversation (finish them; drop any the request above already covers):\n"
                     + "\n".join(f"- {t[:200]}" for t in open_tasks))
    lines += ["Reply rules: report in Traditional Chinese, conclusion first in two sentences, numbers only from measurements made in this "
              "conversation, no questions about mechanical work.",
              f"The old conversation's transcript ({transcript}) is for exact details only."]
    return "\n".join(lines)


def rollover_brief(seat: str, session_id: str = "", park: bool = True, arm: bool = False) -> str:
    import glob as _glob
    from pathlib import Path as _Path
    if park:
        try:
            kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
            subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "goal_compact.py"), "park", seat],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, **kw)
        except Exception:
            pass
    found = _glob.glob(os.path.join(CLAUDE_PROJECTS, "*", f"{session_id}.jsonl")) if session_id and session_id.replace("-", "").isalnum() else []
    request, context, model, tasks = "", 0, "", []
    if found:
        request = last_typed_request(found[0])
        model, tasks = transcript_state(found[0])
        try:
            import f1s_live
            context = f1s_live.context_tokens(_Path(found[0]), settled=True)
        except Exception:
            pass
    text = rollover_brief_text(seat, session_id, context, request, model, tasks)
    if arm:
        arm_rollover(seat, session_id, text, model)
    return text


def _write_rollover(path: str, doc: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def arm_rollover(seat: str, session_id: str, brief: str, model: str = "", now: float | None = None) -> dict:
    """Record the hand-over for the conversation that clears itself next (clear_session "self" keeps the session's
    model, folder and permissions, and unlike start_session it is not refused on a turn nobody typed)."""
    now = time.time() if now is None else now
    doc = {"seat": seat, "session": session_id, "model": model, "brief": brief, "armed_at": now,
           "armed_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "delivered": []}
    _write_rollover(rollover_path(seat), doc)
    return doc


def take_rollover(seat: str, via: str, session_id: str = "", now: float | None = None) -> dict:
    """The armed hand-over of `seat` if it is fresh, with `via` recorded as one delivery ({} otherwise). `via` is
    "start" (SessionStart source=clear, session_id = the new conversation) or "wake" (the old conversation's idle
    waiter, session_id = the armed one). Each via delivers at most once. Never raises."""
    now = time.time() if now is None else now
    path = rollover_path(seat)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict) or now - float(doc.get("armed_at") or 0) > ROLLOVER_TTL_S:
            return {}
        if via == "wake" and session_id != doc.get("session"):
            return {}
        if via == "start" and session_id == doc.get("session"):
            return {}
        done = [d for d in doc.get("delivered") or [] if isinstance(d, dict)]
        if any(d.get("via") == via for d in done):
            return {}
        doc["delivered"] = done + [{"via": via, "session": session_id, "at": now}]
        _write_rollover(path, doc)
        return doc
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def rollover_start_text(seat: str, session_id: str) -> str:
    """For SessionStart source=clear: the armed brief as this new conversation's task. "" when none."""
    doc = take_rollover(seat, "start", session_id)
    return ("F1S ROLLOVER — this conversation was cleared to continue a full one on the same model; the hand-over below "
            "is your task. Start it at once, without waiting for the operator:\n" + doc["brief"]) if doc else ""


def rollover_wake_text(seat: str, session_id: str) -> str:
    """For the old conversation's idle waiter after it cleared itself: the wake text. "" when nothing is armed."""
    doc = take_rollover(seat, "wake", session_id)
    if not doc:
        return ""
    if any(d.get("via") == "start" for d in doc.get("delivered") or [] if isinstance(d, dict)):
        return "F1S ROLLOVER — the hand-over in your context (F1S ROLLOVER) is your task: carry it out now."
    return "F1S ROLLOVER — carry out this hand-over now:\n" + doc["brief"]


def handoff_line(seat: str, session_id: str = "", context: int | None = None, over: int | None = None,
                 rollover: int | None = None) -> str:
    """operator 2026-11-14: the ai_darkhero main chat spent 17.4M in two days, 692 calls at 160K each, most of them tool calls.
    Once this conversation holds more than `live_wake.handoff_over_k` (K tokens, default 150, 0 = off) every prompt says so
    with the two existing ways out: a lean station for the execution, or AGC park and a new chat. Advisory, never blocks;
    f1s_waste.py counts what still ran here as `fat_exec`. "" below the line, unknown, or right after a compaction."""
    try:
        if over is None:
            import json as _json
            with open(os.path.join(HUB, "_registry", "run-until-done.json"), encoding="utf-8-sig") as fh:
                over = int(float((_json.load(fh).get("live_wake") or {}).get("handoff_over_k", HANDOFF_OVER_K)) * 1000)
    except (OSError, ValueError, TypeError, AttributeError):
        over = HANDOFF_OVER_K * 1000
    try:
        if context is None:
            import glob as _glob
            from pathlib import Path as _Path
            found = _glob.glob(os.path.join(CLAUDE_PROJECTS, "*", f"{session_id}.jsonl")) if session_id and session_id.replace("-", "").isalnum() else []
            if not found:
                return ""
            import f1s_live
            context = f1s_live.context_tokens(_Path(found[0]), settled=True)
    except Exception:
        return ""
    if rollover is None:
        try:
            with open(os.path.join(HUB, "_registry", "run-until-done.json"), encoding="utf-8-sig") as fh:
                rollover = int(float((json.load(fh).get("live_wake") or {}).get("rollover_over_k", ROLLOVER_OVER_K)) * 1000)
        except (OSError, ValueError, TypeError, AttributeError):
            rollover = ROLLOVER_OVER_K * 1000
    if not over or context <= over:
        return ""
    if rollover and context > rollover:
        sess = f" --session {session_id}" if session_id else ""
        return (f"ROLL OVER {context // 1000}K > {rollover // 1000}K: this conversation holds {context // 1000}K; do not do this prompt's work here. "
                "If a background task of this conversation is still running, let it finish first. "
                f"Run `python C:/ai_workspace/_skill/engines/curator_orders.py rollover-brief --seat {seat}{sess} --arm` (it parks the seat, "
                "records the hand-over with the operator's request, the model and the open steps, and prints it). "
                "Then call mcp__ccd_session_mgmt__clear_session with session_id \"self\": the same session keeps its model, folder and "
                "permissions, it works on turns nobody typed, and when this turn ends F1S hands the cleared conversation the brief "
                "(SessionStart) and wakes it (idle waiter). Tell the operator in one line that the conversation rolls over, then end the turn. "
                "If clear_session is refused (Remote Control, pinned, or open live work), start a new conversation in the same cwd with "
                "the printed text as its whole prompt (mcp__ccd_session__start_session, initiation \"user_asked\", context \"fresh\", "
                "no worktree, model = the one in the brief) and archive this one (mcp__ccd_session_mgmt__archive_session \"self\"). "
                + ARCHIVE_RC_HINT + " If neither works, fall back to a lean station and say so.")
    cwd = os.path.join(HUB, seat).replace(os.sep, "/")
    return (f"FAT CHAT {context // 1000}K > {over // 1000}K: every tool call here re-reads {context // 1000}K. Hand execution to a lean "
            f"station (about 30K, one result row back): `python _skill/engines/f1s_station.py run --cwd {cwd} --tools Read,Grep,Glob,Bash,Edit,Write "
            f"--prompt-file <brief>`; or park (`python _skill/engines/goal_compact.py park {seat}`) and go on in a new chat. "
            "Keep decisions and the reply here.")


DELIVER_RECENT_S = 3 * 86400


def _handoff_over() -> int:
    try:
        with open(os.path.join(HUB, "_registry", "run-until-done.json"), encoding="utf-8-sig") as fh:
            return int(float((json.load(fh).get("live_wake") or {}).get("handoff_over_k", HANDOFF_OVER_K)) * 1000)
    except (OSError, ValueError, TypeError, AttributeError):
        return HANDOFF_OVER_K * 1000


def delivery_line(seat: str, over: int | None = None, now: float | None = None, sizes: dict | None = None) -> str:
    """Where a new order's prompt goes, decided from the seat's own transcripts at no model cost. 2026-11-16: jci_taipei's
    `wake` was four orders the curator sent (send_message) into its 180-197K main chat, 143 calls at that size; the rule
    "send it to the seat's main conversation" picked the most expensive chat the seat had. Each chat the seat used in the
    last three days is listed with what its next call re-reads: one under `live_wake.handoff_over_k` may take the message,
    and when every one is over it (or none exists) the prompt starts a new chat in that cwd. `sizes` = {session id: tokens}
    for tests; 0 = unknown (just compacted) and is not offered."""
    over = _handoff_over() if over is None else over
    if not over:
        return ""
    now = time.time() if now is None else now
    if sizes is None:
        sizes = {}
        try:
            import glob as _glob
            from pathlib import Path as _Path
            import f1s_live
            for path in _glob.glob(os.path.join(CLAUDE_PROJECTS, "C--ai-workspace-" + seat.replace("_", "-"), "*.jsonl")):
                if now - os.path.getmtime(path) > DELIVER_RECENT_S:
                    continue
                with open(path, "rb") as fh:                 # a headless station's transcript: nothing can message it
                    if b'"sdk-cli"' in fh.read(65536):
                        continue
                sizes[os.path.basename(path)[:-6]] = f1s_live.context_tokens(_Path(path), settled=True)
        except Exception:
            return ""
    cwd = os.path.join(HUB, seat).replace(os.sep, "/")
    lean = sorted((tokens, sid) for sid, tokens in sizes.items() if 0 < tokens <= over)
    fat = sorted(((tokens, sid) for sid, tokens in sizes.items() if tokens > over), reverse=True)
    new_chat = (f"start a new chat in {cwd} with this order's full prompt (start_session user_asked, fresh, use_worktree false; "
                "detach it), then `deliver --session <its id>`")
    if lean:
        text = "DELIVER — send_message only to a chat under the line: " + ", ".join(f"{sid[:8]} {t // 1000}K" for t, sid in lean[:4])
        if fat:
            text += "; never to " + ", ".join(f"{sid[:8]} {t // 1000}K" for t, sid in fat[:4]) + f" (over {over // 1000}K: every call re-reads it)"
        return text + f"; or {new_chat}."
    if fat:
        return ("DELIVER — NEW CHAT: every chat " + seat + " used in three days is over " + f"{over // 1000}K ("
                + ", ".join(f"{sid[:8]} {t // 1000}K" for t, sid in fat[:4]) + "); do not send_message there, each tool call would "
                f"re-read all of it. {new_chat[0].upper() + new_chat[1:]}. The seat's hooks also show the order at its next prompt.")
    return f"DELIVER — NEW CHAT: {seat} has no chat of known size in three days; {new_chat}."


def _injection(seat: str, session_id: str = "") -> str:
    """Context text for a session in `seat`: its open orders, or the curator's review queue. An order another
    conversation owns is one line (read it, do not answer it); the owner and unowned orders get the full text."""
    if out_of_scope(session_id):
        return ""
    if seat == curator():
        queue = review_queue()
        techniques = "\n".join(t for t in (_waiting_techniques(seat), archive_due(session_id), token_watch(), _fanout_line()) if t)
        unclaimed = _unclaimed_orders()
        if not queue:
            return "\n".join(t for t in (techniques, unclaimed) if t)
        rows = "; ".join(f"{s}#{o['n']} {review_flag(o, s)} {o['title']}" for s, o in queue[:6])
        return "\n".join(t for t in (f"CURATOR REVIEW — {len(queue)} answered order(s): {rows}. `curator_orders.py review` "
                                     f"prints each answer's evidence and note; then close <seat> <n> [<n> ...] or "
                                     f"reopen <seat> <n> --note TEXT.", techniques, unclaimed) if t)
    orders = open_orders(seat)
    kids = archive_due(session_id, own=True)
    if not orders:
        return kids
    lines = [f"CURATOR ORDERS — {curator()}（F1S 校正令）優先於本 cwd 自己的決定；紅線與 operator 本人指令仍在其上。"
             "每一令就是完整提示詞：直接開始執行，不等 operator 開口，先處理，再做其他事："]
    for o in orders:
        extra = "".join(f" [{k}: {', '.join(o[k])}]" for k in ("freeze", "forbid") if o.get(k))
        if owned_by_other(o, session_id):
            lines.append(f"#{o['n']} {o['title']}: 由對話 {owner_of(o)[:8]} 負責中，本對話讀過即可，不要 answer、不要停工"
                         f"（例外：負責對話靜默滿 {HANDOVER_AFTER_S // 3600} 小時且你手上已有完成證據，answer --evidence 即接手）{extra}")
        else:
            lines.append(f"#{o['n']} {o['title']}: {order_text(o)}{extra}")
    lines.append(f"回報: python {HUB}/_skill/engines/curator_orders.py answer {seat} <n> --evidence <commit:SHA 或既有的程式／測試檔路徑；不要為了回報新開檔> "
                 f"[--note \"計數前後、留下什麼\"] "
                 f"| --cannot \"<原因>\"（answer 的對話成為該令的負責對話；接手前先 claim {seat} <n>，已有負責對話就不要接）。"
                 "交給別的對話（如 Fable）時，交付物是檔案列（依 item id 冪等、寫前讀回）；send_message 只是通知，"
                 "回 undelivered/queued 是排隊不是遺失，不要重送")
    return "\n".join(lines + ([kids] if kids else []))


def _brief(orders: list[dict]) -> list[dict]:
    """What a listing needs: every active order and the closed count. 11-02: `list` printed 311 KB per call, 110 calls in 3 days."""
    rows = [{"n": o.get("n"), "status": o.get("status"), "title": o.get("title"), "owner": (owner_of(o) or "")[:8],
             "evidence": (o.get("answer") or {}).get("evidence") or [], "reason": (o.get("answer") or {}).get("reason") or ""}
            for o in orders if o.get("status") in ACTIVE]
    closed = len(orders) - len(rows)
    return rows + ([{"closed": closed}] if closed else [])


def _waiting_techniques(seat: str) -> str:
    """f1s_apply orders every other seat; the curator's own rows have no order to arrive in, so they are named here."""
    try:
        with open(TECHNIQUES, encoding="utf-8") as fh:
            rows = json.load(fh).get("techniques", {}).values()
    except (OSError, ValueError, AttributeError):
        return ""
    waiting = sum(1 for r in rows if r.get("seat") == seat and r.get("status") == "new" and not r.get("held"))
    if not waiting:
        return ""
    return (f"ARTICLE TECHNIQUES — {waiting} waiting for this seat: f1s_apply.py list --seat {seat}, apply and measure the worthwhile ones, "
            "f1s_apply.py close <id> applied|covered --evidence <path> or rejected --note <why>; an opinion with nothing to take apart: nouse --note <why> (not handed on).")


def _fanout_line() -> str:
    """A completed F1S fan-out the curator has not reported yet (f1s_fanout.py); empty when none or on any error."""
    lines = []
    for name in ("f1s_fanout", "f1s_reuse", "f1s_posture"):     # one line each: fan-out due, reuse ledger, night queue
        try:
            lines.append(__import__(name).curator_line())
        except Exception:  # noqa: BLE001
            pass
    return chr(10).join(x for x in lines if x)


def _unclaimed_orders() -> str:
    """An order waits for a chat in its seat, and a seat with no open chat never takes it (11-02: ai_network, ai_demo,
    ai_career, sdnext_a770 sat unowned). Engines cannot open a conversation, so the curator is told. An owned order whose
    owner stopped writing is the same wait with a lock on it (ai_metadata #14/#15 2026-11-10: owner silent, seat chat skipped it)."""
    rows, stale = [], []
    for seat in _seats_with_orders():
        for o in open_orders(seat):
            try:
                age = time.time() - time.mktime(time.strptime(o.get("issued_at", ""), "%Y-%m-%dT%H:%M:%S"))
            except (TypeError, ValueError):
                continue
            if not owner_of(o) and age > UNCLAIMED_AFTER_S:
                rows.append(f"{seat}#{o['n']} {o['title']}")
            elif owner_of(o) and _claim_silent_s(o) > STALE_OWNER_AFTER_S:
                stale.append(f"{seat}#{o['n']} owner {owner_of(o)[:8]}")
    lines = []
    if rows:
        lines.append(f"UNCLAIMED ORDERS — {len(rows)} open with no conversation: {'; '.join(rows[:6])}. Send each into that seat's main chat "
                     "(send_message; no open chat: f1s_station.py run in that cwd with the order text in the prompt, the station "
                     "cannot read outside its cwd), or measure and close them yourself. Never a session card that waits for a click.")
    if stale:
        lines.append(f"STALE CLAIMS — {len(stale)} open order(s) whose owning conversation wrote nothing for "
                     f"{STALE_OWNER_AFTER_S // 3600}h+: {'; '.join(stale[:6])}. list_sessions first (host_gone is not dead); "
                     "if the owner is not running, curator_orders.py claim <seat> <n> --release, then send the order into a live chat of that seat.")
    return "\n".join(lines)


def _claim_silent_s(order: dict, now: float | None = None) -> float:
    """How long the owner of this claim has been silent. A station- owner has no transcript (2026-11-17: ai_trader#145 was
    named stale seconds after a station took it), so the age of its claim decides; an unreadable claim time is not stale."""
    owner = owner_of(order)
    if not owner.startswith(STATION_SESSION):
        return _owner_silent_s(owner, now)
    try:
        claimed = time.mktime(time.strptime(str((order.get("owner") or {}).get("at")), "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return 0.0
    return max(0.0, (time.time() if now is None else now) - claimed)


def _owner_silent_s(session_id: str, now: float | None = None) -> float:
    """Seconds since the owner's transcript was last written; 0 when unknown (no projects dir), so nothing is called stale
    on a host that cannot see transcripts. A missing transcript under a readable projects dir counts as silent forever."""
    now = now if now is not None else time.time()
    try:
        dirs = os.listdir(CLAUDE_PROJECTS)
    except OSError:
        return 0.0
    newest = None
    for d in dirs:
        path = os.path.join(CLAUDE_PROJECTS, d, f"{session_id}.jsonl")
        try:
            m = os.path.getmtime(path)
        except OSError:
            continue
        newest = m if newest is None else max(newest, m)
    return float("inf") if newest is None else max(0.0, now - newest)


def _judged_by_control_loop() -> set[tuple[str, int]]:
    """(seat, n) f1s_control still owns: it closes or reopens them from the re-measured number, days after the answer."""
    try:
        with open(CONTROL_STATE, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return set()
    if not doc.get("enabled"):
        return set()
    return {(s, t["order"]) for s, t in (doc.get("seats") or {}).items() if t.get("order")}


def review_queue() -> list[tuple[str, dict]]:
    judged = _judged_by_control_loop()
    return [(s, o) for s in _seats_with_orders() for o in load(s)["orders"]
            if o.get("status") in ("done", "cannot") and (s, o.get("n")) not in judged]


def review_flag(order: dict, seat: str = "") -> str:
    """What the curator has to judge in an answered order: `cannot` (a reason, no evidence), `reopened` (sent back before),
    `stale` (no evidence newer than the order), else `fresh`."""
    if order.get("status") == "cannot":
        return "cannot"
    if order.get("reopened_at"):
        return "reopened"
    return "fresh" if _evidence_fresh(order, seat) else "stale"


def wake_queue(batch: int = REVIEW_BATCH, hours: float = REVIEW_BATCH_H, now: float | None = None) -> list[tuple[str, dict]]:
    """The review queue when it is worth waking an idle curator chat, else []. Every answer used to wake it within 2 minutes
    (90 answers in 4 days, 0.16M each) and 2 of 86 answers with evidence were reopened (2026-11-14): an answer with fresh
    evidence now waits for the next prompt, until `batch` of them wait or the oldest has waited `hours`. `cannot`, `stale`
    and `reopened` answers wake at once. batch 0 = every answer wakes, as before."""
    queue = review_queue()
    if not queue or not batch:
        return queue
    now = time.time() if now is None else now
    waited = []
    for seat, order in queue:
        if review_flag(order, seat) != "fresh":
            return queue
        try:
            waited.append(now - time.mktime(time.strptime((order.get("answer") or {}).get("at") or "", "%Y-%m-%dT%H:%M:%S")))
        except ValueError:
            return queue
    return queue if len(queue) >= batch or max(waited) >= hours * 3600 else []


def review_table() -> list[str]:
    """One line per answered order with what the review needs (flag, evidence, the seat's note), so the curator reads the
    queue in one call instead of a `list` per seat."""
    rows = []
    for seat, order in review_queue():
        ans = order.get("answer") or {}
        evid = ", ".join(p if p.startswith(COMMIT) else os.path.basename(p) for p in ans.get("evidence") or ()) or "-"
        rows.append(f"{seat}#{order['n']} {review_flag(order, seat)} | {order.get('title', '')[:60]} | {evid[:80]} | "
                    f"{' '.join((ans.get('reason') or '').split())[:160]}")
    return rows


def _active() -> list[tuple[str, dict]]:
    return [(s, o) for s in _seats_with_orders() for o in load(s)["orders"] if o.get("status") in ACTIVE]


def frozen_hits(committer: str, paths) -> list[dict]:
    """Hub-relative paths an active order froze; the curator's own commits are never refused."""
    if committer == curator():
        return []
    hits = []
    for seat, order in _active():
        for pat in order.get("freeze") or []:
            for p in paths:
                if p == pat or p.startswith(pat.rstrip("/") + "/") or fnmatch.fnmatch(p, pat):
                    hits.append({"seat": seat, "n": order["n"], "path": p, "pattern": pat})
    return hits


def active_forbids() -> list[dict]:
    return [{"seat": s, "n": o["n"], "pattern": p, "title": o["title"]}
            for s, o in _active() for p in (o.get("forbid") or [])]


def forbid_match(name: str, cmdline: str, forbids: list[dict]) -> dict | None:
    low_name = (name or "").lower()
    if any(p in low_name for p in PROTECTED):
        return None
    low = (cmdline or "").lower()
    return next((f for f in forbids if f["pattern"].lower() in low), None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("issue")
    s.add_argument("seat")
    s.add_argument("--title", required=True)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--do")
    g.add_argument("--prompt-file", help="the complete prompt, read as UTF-8 (argv mangles non-ASCII on Windows)")
    s.add_argument("--freeze", action="append", default=[])
    s.add_argument("--forbid", action="append", default=[])
    s = sub.add_parser("list")
    s.add_argument("seat", nargs="?")
    s.add_argument("--full", action="store_true", help="every field of every order, closed ones too")
    s = sub.add_parser("deliver")
    s.add_argument("seat")
    s.add_argument("n", type=int)
    s.add_argument("--session", required=True, help="the seat's main conversation id the order was sent to")
    s = sub.add_parser("answer")
    s.add_argument("seat")
    s.add_argument("n", type=int)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--evidence", nargs="+")
    g.add_argument("--cannot")
    s.add_argument("--note", default="", help="with --evidence: before -> after counts, commit, what was left and why; alone: a one-line answer")
    s = sub.add_parser("claim")
    s.add_argument("seat")
    s.add_argument("n", type=int)
    s.add_argument("--release", action="store_true")
    s.add_argument("--session", default=None, help="conversation id (default: CLAUDE_CODE_SESSION_ID)")
    s = sub.add_parser("reopen")
    s.add_argument("seat")
    s.add_argument("n", type=int)
    s.add_argument("--note", required=True)
    s = sub.add_parser("close")
    s.add_argument("seat")
    s.add_argument("n", type=int, nargs="+")
    sub.add_parser("review")
    s = sub.add_parser("rollover-brief", help="park the seat and print the hand-over prompt for a new conversation")
    s.add_argument("--seat", required=True)
    s.add_argument("--session", default="")
    s.add_argument("--no-park", action="store_true")
    s.add_argument("--arm", action="store_true", help="record it for clear_session(self): SessionStart and the idle waiter deliver it")
    a = ap.parse_args(argv)
    if a.cmd == "rollover-brief":
        text = rollover_brief(a.seat, a.session, park=not a.no_park, arm=a.arm)
        try:
            print(text)
        except UnicodeEncodeError:
            sys.stdout.write(text.encode(sys.stdout.encoding or "utf-8", "backslashreplace").decode(sys.stdout.encoding or "utf-8") + "\n")
        return 0
    if a.cmd == "review":
        print("\n".join(review_table()) or "review queue empty")
        return 0
    try:
        if a.cmd == "issue":
            out = issue(a.seat, a.title, a.do if a.do is not None else open(a.prompt_file, encoding="utf-8-sig").read(), a.freeze, a.forbid)
        elif a.cmd == "deliver":
            out = deliver(a.seat, a.n, a.session)

        elif a.cmd == "list":
            seats = [a.seat] if a.seat else _seats_with_orders()
            out = {s: load(s)["orders"] if a.full else _brief(load(s)["orders"]) for s in seats}
        elif a.cmd == "answer":
            out = answer(a.seat, a.n, a.evidence or (), a.cannot or "", note=a.note)
        elif a.cmd == "claim":
            out = claim(a.seat, a.n, release=a.release, session=a.session)
        elif a.cmd == "reopen":
            out = reopen(a.seat, a.n, a.note)
        else:
            out = [{k: close(a.seat, n).get(k) for k in ("n", "status", "title")} for n in a.n]
            out = out[0] if len(out) == 1 else out
    except (PermissionError, ValueError) as exc:
        print(f"refused: {exc}")
        return 2
    if isinstance(out, dict) and "do" in out:      # the seat already holds the order's text; this line only confirms the step
        out = {k: out.get(k) for k in ("n", "status", "title")}
    print(json.dumps(out, ensure_ascii=False, indent=None if a.cmd == "list" else 2))
    if a.cmd == "issue" and (line := delivery_line(a.seat)):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
