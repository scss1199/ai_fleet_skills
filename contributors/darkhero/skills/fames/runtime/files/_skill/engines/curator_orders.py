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
          ledger: bool = False) -> dict:
    """ledger=True: an engine reads the answer back into its own table (f1s_fanout), so any answer closes the order."""
    cwd = cwd or os.getcwd()
    if not (do or "").strip():
        raise ValueError("an order needs its full prompt text (--do or --prompt-file)")
    _require_curator(cwd, "issues orders")
    if seat == curator():
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
    if routine and not freeze and not forbid:
        order["routine"] = True
        if ledger:
            order["ledger"] = True
    doc["orders"].append(order)
    _save(seat, doc)
    return order


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
            f"archive_session (reason = its reason); a reopened one comes back on its next order.")


def open_orders(seat: str, session_id: str | None = None) -> list[dict]:
    """The seat's open orders; with `session_id`, only those this conversation must answer (unowned or its own)."""
    if out_of_scope(session_id):
        return []
    orders = [o for o in load(seat)["orders"] if o.get("status") == "open"]
    if session_id is None:
        return orders
    return [o for o in orders if not owned_by_other(o, session_id)]


def injection(seat: str, session_id: str = "") -> str:
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
            lines.append(f"#{o['n']} {o['title']}: 由對話 {owner_of(o)[:8]} 負責中，本對話讀過即可，不要 answer、不要停工{extra}")
        else:
            lines.append(f"#{o['n']} {o['title']}: {o['do']}{extra}")
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
            "f1s_apply.py close <id> applied|covered --evidence <path> or rejected --note <why>.")


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
            elif owner_of(o) and _owner_silent_s(owner_of(o)) > STALE_OWNER_AFTER_S:
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
    a = ap.parse_args(argv)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
