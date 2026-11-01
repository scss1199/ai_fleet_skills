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
  python curator_orders.py answer <seat> <n> --evidence PATH [PATH...] | --cannot REASON
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
CURATOR_FALLBACK = "ai_darkhero"
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


def issue(seat: str, title: str, do: str, freeze=(), forbid=(), cwd: str | None = None) -> dict:
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


def answer(seat: str, n: int, evidence=(), reason: str = "", cwd: str | None = None,
           session: str | None = None) -> dict:
    cwd = cwd or os.getcwd()
    if bool(evidence) == bool(reason.strip()):
        raise ValueError("answer with --evidence PATH... or --cannot REASON, not both")
    missing = [p for p in evidence if not os.path.exists(os.path.join(cwd, p))]
    if missing:
        raise ValueError(f"evidence path not found: {missing}")
    doc = load(seat)
    order = _find(doc, n)
    if order["status"] != "open":
        raise ValueError(f"order #{n} is {order['status']}, not open")
    sid = _session_id(session)
    order["status"] = "done" if evidence else "cannot"
    order["answer"] = {"at": _now(), "from": os.path.abspath(cwd), "session": sid,
                       "evidence": [os.path.abspath(os.path.join(cwd, p)) for p in evidence], "reason": reason.strip()}
    if sid and not owner_of(order):
        # The answering conversation owns the order from now on: when the curator reopens it, only that
        # conversation is pushed to finish it (jci_taipei 2026-10-28: #5 reopened pushed every jci_taipei session).
        order["owner"] = {"session": sid, "from": os.path.abspath(cwd), "at": _now(), "by": "answer"}
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
    if current and current != sid and not is_curator(cwd):
        raise PermissionError(f"order #{n} is owned by conversation {current[:8]}; only it or {curator()} may change that")
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


def close(seat: str, n: int, cwd: str | None = None) -> dict:
    return _curator_change(seat, n, cwd, "closed")


def open_orders(seat: str, session_id: str | None = None) -> list[dict]:
    """The seat's open orders; with `session_id`, only those this conversation must answer (unowned or its own)."""
    orders = [o for o in load(seat)["orders"] if o.get("status") == "open"]
    if session_id is None:
        return orders
    return [o for o in orders if not owned_by_other(o, session_id)]


def injection(seat: str, session_id: str = "") -> str:
    """Context text for a session in `seat`: its open orders, or the curator's review queue. An order another
    conversation owns is one line (read it, do not answer it); the owner and unowned orders get the full text."""
    if seat == curator():
        queue = review_queue()
        if not queue:
            return ""
        rows = "; ".join(f"{s}#{o['n']} {o['status']} {o['title']}" for s, o in queue[:6])
        return (f"CURATOR REVIEW — {len(queue)} answered order(s): {rows}. Check each answer, then "
                f"curator_orders.py close <seat> <n> or reopen <seat> <n> --note TEXT.")
    orders = open_orders(seat)
    if not orders:
        return ""
    lines = [f"CURATOR ORDERS — {curator()}（F1S 校正令）優先於本 cwd 自己的決定；紅線與 operator 本人指令仍在其上。"
             "每一令就是完整提示詞：直接開始執行，不等 operator 開口，先處理，再做其他事："]
    for o in orders:
        extra = "".join(f" [{k}: {', '.join(o[k])}]" for k in ("freeze", "forbid") if o.get(k))
        if owned_by_other(o, session_id):
            lines.append(f"#{o['n']} {o['title']}: 由對話 {owner_of(o)[:8]} 負責中，本對話讀過即可，不要 answer、不要停工{extra}")
        else:
            lines.append(f"#{o['n']} {o['title']}: {o['do']}{extra}")
    lines.append(f"回報: python {HUB}/_skill/engines/curator_orders.py answer {seat} <n> --evidence <path> "
                 "| --cannot \"<原因>\"（answer 的對話成為該令的負責對話；接手前先 claim {seat} <n>）")
    return "\n".join(lines)


def review_queue() -> list[tuple[str, dict]]:
    return [(s, o) for s in _seats_with_orders() for o in load(s)["orders"] if o.get("status") in ("done", "cannot")]


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
    s = sub.add_parser("deliver")
    s.add_argument("seat")
    s.add_argument("n", type=int)
    s.add_argument("--session", required=True, help="the seat's main conversation id the order was sent to")
    s = sub.add_parser("answer")
    s.add_argument("seat")
    s.add_argument("n", type=int)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--evidence", nargs="+")
    g.add_argument("--cannot")
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
    s.add_argument("n", type=int)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "issue":
            out = issue(a.seat, a.title, a.do if a.do is not None else open(a.prompt_file, encoding="utf-8-sig").read(), a.freeze, a.forbid)
        elif a.cmd == "deliver":
            out = deliver(a.seat, a.n, a.session)

        elif a.cmd == "list":
            seats = [a.seat] if a.seat else _seats_with_orders()
            out = {s: load(s)["orders"] for s in seats}
        elif a.cmd == "answer":
            out = answer(a.seat, a.n, a.evidence or (), a.cannot or "")
        elif a.cmd == "claim":
            out = claim(a.seat, a.n, release=a.release, session=a.session)
        elif a.cmd == "reopen":
            out = reopen(a.seat, a.n, a.note)
        else:
            out = close(a.seat, a.n)
    except (PermissionError, ValueError) as exc:
        print(f"refused: {exc}")
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
