#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""f1s_daily.py — every conversation on this machine feeds F1S back once a day, and every open one gets the result.
operator 2026-10-27: 「建立一個每日自動整理全部對話內容來反向升級f1s的工作流程 順便去包含文章(如果我沒有特別要求
馬上讀哪個文章的話 就是會24hr小時內讀完配合所有正在執行或封存的任務)整理出有用的東西 提高矩陣作用 並動態作用回所有
正在跑的對話」 (asked in altos, executed on darkhero; altos receives this file through the FAMES package).

One HubClock rider (`f1s-daily`, 6 h) runs `tick`; zero Claude tokens, free pool only, zero foreground:
  1. SCAN     ~/.claude/projects/*/*.jsonl incrementally (byte offset per transcript; a new transcript older than
              NEW_FILE_DAYS is only counted). Per seat (from each row's cwd): sessions (open = f1s_live waiter armed,
              else archived), operator correction prompts, 「需要你決定」 lines, repeated tool-error signatures, and the
              URLs the operator pasted (an URL a tool in the same session already fetched counts as read on request).
  2. ARTICLES every unread URL (conversation URLs + LINE links the bot could not read, article_relay) is read on the
              free pool (distill-url.py) inside ARTICLE_SLA_S; each receipt carries read_at, the summary, the key points
              and the open/archived sessions it relates to (free-pool match over session titles). LINE content cards
              that arrived in the window are related the same way.
  3. DAILY    (once per local day): corrections and repeated errors become `conversation` items that f1s-harvest
              scores, triages and proposes to f1s-evolve (canonical only through its T1 / Lean / test gates); the
              seat matrix (open / archived / corrections / decisions / errors / articles) lands in digest-<date>.json
              and as `f1s_daily` on each project-matrix.json project, with the gaps; live.md is rewritten.
  4. LIVE     _registry/f1s-daily/live.md is watched by claude_session_hook (MIDTURN_WATCH + instruction files):
              every open conversation gets its diff at the next prompt or tool call, f1s_live wakes the idle ones.
Never reads fracdigi / quant transcripts; ai_ut prompt text never leaves the machine (counted, not quoted).
  python f1s_daily.py tick [--force-daily] [--json]
  python f1s_daily.py status [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = Path(os.environ.get("AI_WORKSPACE") or HERE.parents[1])
PROJECTS = Path.home() / ".claude" / "projects"
OUT = HUB / "_registry" / "f1s-daily"
STATE = OUT / "state.json"
LIVE = OUT / "live.md"
LOCK = OUT / "tick.lock"
MATRIX = HUB / "_registry" / "project-matrix.json"
CURATOR = "ai_darkhero"

NEVER = ("fracdigi", "quant")          # vault red line: not even read
LOCAL_ONLY = ("ai_ut",)                # proprietary: counted, never quoted, never sent to the pool
NEW_FILE_DAYS = 14
FIRST_READ_BYTES = 32 * 1024 * 1024
KEEP_DAYS = 14
ARTICLE_SLA_S = 24 * 3600
ARTICLES_PER_TICK = 40                 # 6 h rider: 160 a day keeps a backlog inside the 24 h SLA
DAILY_AFTER_HOUR = 3
LIVE_MAX_CHARS = 2600
NW = 0x08000000 if os.name == "nt" else 0

CORRECTION = re.compile(r"不要|不是|不准|不對|錯了|搞錯|為什麼|為何|嚴禁|禁止|別再|別給|別問|別用|我說|我要的是|不用|"
                        r"廢話|說謊|推託|浪費|又沒|又是|又不|還是沒|沒有用|根本|亂[改做寫講]")
URL = re.compile(r"https?://[^\s<>\"'）)」】\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]+")
SECRET = re.compile(r"(?:sk-|ghp_|gho_|xox[bp]-|AIza|eyJ)[A-Za-z0-9_\-.]{10,}|[A-Za-z0-9_\-]{40,}")
DECISION = re.compile(r"需要你決定|需要你(?:來)?(?:選|決)|請你決定|由你決定")
MACHINE_ENTRY = ("sdk-cli", "sdk-py", "sdk-ts")
# Not articles (first tick 2026-10-27 fetched localhost, sign-in pages and the operator's own deployments): a local or
# private address, a sign-in / console / API host, a fleet deployment, a private Google doc, a vault seat's site.
NOT_ARTICLE = re.compile(r"^(?:localhost|127\.|10\.|192\.168\.|\[|(?:accounts|id|auth|login|signin|secure\.id|console|dash|"
                         r"api|developers|platform|cloud)\.)|\.(?:workers\.dev|vercel\.app|fly\.dev|onrender\.com|pages\.dev)$|"
                         r"^(?:docs|drive)\.google\.com$")
TOKEN_PARAM = re.compile(r"(?i)token|key|secret|sig|auth|code|session|passw|mcp_")


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _local(ts: float) -> str:
    """Local naive second-resolution stamp: the one clock every stored ts / since / cut compares in."""
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")[:19]


def _row_ts(value) -> str:
    """A transcript timestamp (UTC, `Z`) as a local naive stamp; '' when unparseable."""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    return _local(dt.timestamp()) if dt.tzinfo else dt.isoformat(timespec="seconds")[:19]


def never(seat: str) -> bool:
    return any(n in str(seat).lower() for n in NEVER)


def _epoch(value) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _module(name: str, file: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, HERE / file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def redact(text: str) -> str:
    return SECRET.sub("[redacted]", text)


def article_url(url: str) -> str:
    """The URL worth reading as an article with credential-like query parameters removed, or '' for anything else."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    url = url.rstrip(".,;:!?。，")
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if not host or "." not in host or "](" in url or NOT_ARTICLE.search(host) or never(host):
        return ""
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TOKEN_PARAM.search(k)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def seat_of_cwd(cwd: str) -> str:
    """Seat from a row's cwd: the first path part under the hub (ai_x, jci_taipei), `hub` at the root, else ''."""
    try:
        rel = Path(cwd).resolve().relative_to(HUB.resolve())
    except (ValueError, OSError):
        return ""
    head = rel.parts[0] if rel.parts else ""
    if not head or head.startswith((".", "_")):
        return "hub"
    return head


def _blocks(row: dict) -> list:
    msg = row.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _human_text(row: dict) -> str:
    """The operator's own prompt text, or '' for tool results, hook/meta rows and headless (sdk) prompts."""
    if row.get("type") != "user" or row.get("entrypoint") in MACHINE_ENTRY:
        return ""
    if any(row.get(f) for f in ("isMeta", "isCompactSummary", "isVisibleInTranscriptOnly", "isSidechain")):
        return ""
    blocks = _blocks(row)
    if not blocks or any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
        return ""
    text = "\n".join(str(b.get("text") or "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    return "" if text.lstrip().startswith("<") else text.strip()


def error_sig(text: str) -> str:
    """A tool error's signature: first meaningful line, numbers / paths / quoted values folded."""
    # A shell error starts with "Exit code 1": the line after it says what failed (first tick: 702 "Exit code N").
    line = next((ln.strip() for ln in str(text).splitlines() if ln.strip() and not re.fullmatch(r"Exit code \d+", ln.strip())), "")
    line = re.sub(r"<[^>]{0,40}>", "", line)
    line = re.sub(r"[A-Za-z]:[\\/][^\s'\"]+|/[\w.\-/]+", "<path>", line)
    line = re.sub(r"'[^']*'|\"[^\"]*\"", "<v>", line)
    line = re.sub(r"\d+", "N", line)
    return redact(line)[:140]


def _tool_inputs(row: dict) -> str:
    return " ".join(json.dumps(b.get("input") or {}, ensure_ascii=False)
                    for b in _blocks(row) if isinstance(b, dict) and b.get("type") == "tool_use")


def scan_file(path: Path, rec: dict, state: dict, now: float) -> None:
    """Read the transcript from its recorded offset; complete lines only."""
    size = path.stat().st_size
    start = int(rec.get("offset") or 0)
    if size < start:                                   # rewritten: start over
        start = 0
    if size == start:
        return
    with path.open("rb") as fh:
        fh.seek(start)
        data = fh.read()
    end = data.rfind(b"\n")
    if end < 0:
        return
    rec["offset"] = start + end + 1
    sid = path.stem
    sess = state["sessions"].setdefault(sid, {"seat": rec.get("seat") or "", "title": "", "first": "", "last": ""})
    for raw in data[:end].split(b"\n"):
        if b'"type":"user"' not in raw and b'"type":"assistant"' not in raw:
            continue
        try:
            row = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        ts = _row_ts(row.get("timestamp"))
        if not sess["seat"]:
            sess["seat"] = seat_of_cwd(str(row.get("cwd") or ""))
        seat = sess["seat"]
        if not seat or never(seat):
            continue
        sess["first"] = sess["first"] or ts
        sess["last"] = max(sess["last"], ts)
        if row.get("type") == "user":
            text = _human_text(row)
            if text:
                if not sess["title"]:
                    sess["title"] = "" if seat in LOCAL_ONLY else redact(text[:120]).replace("\n", " ")
                if len(text) <= 1500 and CORRECTION.search(text):
                    state["corrections"].append({"seat": seat, "session": sid, "ts": ts,
                                                 "text": "" if seat in LOCAL_ONLY else redact(text[:400])})
                for url in ([] if seat in LOCAL_ONLY else URL.findall(text)):   # ai_ut URLs never leave
                    url = article_url(url)
                    if not url:
                        continue
                    key = _sha(url)
                    state["urls"].setdefault(key, {"url": url, "seat": seat, "session": sid, "seen": ts,
                                                   "source": "conversation", "status": "pending"})
            for b in _blocks(row):
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    body = b.get("content")
                    if isinstance(body, list):
                        body = " ".join(str(x.get("text") or "") for x in body if isinstance(x, dict))
                    sig = error_sig(str(body or ""))
                    if sig:
                        e = state["errors"].setdefault(seat, {}).setdefault(sig, {"n": 0, "last": "", "sessions": []})
                        e["n"] += 1
                        e["last"] = max(e["last"], ts)
                        if sid not in e["sessions"]:
                            e["sessions"] = (e["sessions"] + [sid])[-5:]
        else:
            inputs = _tool_inputs(row)
            if "http" in inputs:
                for key, u in state["urls"].items():
                    if u["status"] == "pending" and u["session"] == sid and u["url"] in inputs:
                        u.update(status="read_in_session", read_at=ts)
            for b in _blocks(row):
                if isinstance(b, dict) and b.get("type") == "text":
                    for ln in str(b.get("text") or "").splitlines():
                        if DECISION.search(ln):
                            state["decisions"].append({"seat": seat, "session": sid, "ts": ts,
                                                       "text": "" if seat in LOCAL_ONLY else redact(ln.strip()[:200])})


def scan(state: dict, now: float) -> dict:
    files = state.setdefault("files", {})
    read = new = 0
    for path in sorted(PROJECTS.glob("*/*.jsonl")):
        low = path.parent.name.lower()
        if any(n in low for n in NEVER):
            continue
        key = str(path)
        rec = files.get(key)
        try:
            st = path.stat()
        except OSError:
            continue
        if rec is None:
            new += 1
            rec = files[key] = {"offset": 0}
            if now - st.st_mtime > NEW_FILE_DAYS * 86400:
                rec["offset"] = st.st_size               # old: counted as archived, never read back
                state["sessions"].setdefault(path.stem, {"seat": "", "title": "", "first": "",
                                                         "last": _local(st.st_mtime), "old": True})
                continue
            rec["offset"] = max(0, st.st_size - FIRST_READ_BYTES)
        if rec.get("offset", 0) == st.st_size:
            continue
        try:
            scan_file(path, rec, state, now)
            read += 1
        except OSError:
            continue
    return {"transcripts": len(files), "new": new, "read": read}


def prune(state: dict, now: float) -> None:
    cut = _local(now - KEEP_DAYS * 86400)
    state["corrections"] = [c for c in state["corrections"] if c["ts"] >= cut][-2000:]
    state["decisions"] = [d for d in state["decisions"] if d["ts"] >= cut][-2000:]
    for seat, sigs in state["errors"].items():
        state["errors"][seat] = {k: v for k, v in sigs.items() if v["last"] >= cut}
    state["urls"] = {k: v for k, v in state["urls"].items()
                     if v["status"] == "pending" or str(v.get("read_at") or v["seen"]) >= cut}


# ── articles ────────────────────────────────────────────────────────────────────────────────────
def _pool():
    try:
        return _module("_llm", "_llm.py").Pool()
    except Exception:  # noqa: BLE001 — another host may not carry the pool: articles wait, scan goes on
        return None


def open_sessions() -> set[str]:
    """Conversations whose f1s_live waiter is armed (idle) or that are mid-turn; the rest count as archived."""
    try:
        return {r["session_id"] for r in _module("f1s_live", "f1s_live.py").status()
                if r.get("waiter") not in ("host_gone", "disabled", "expired", None, "")}
    except Exception:  # noqa: BLE001
        return set()


def line_links(state: dict) -> int:
    """LINE links the bot could not read (article_relay.pending) join the queue; nothing is marked handed there."""
    try:
        relay = _module("article_relay", "article_relay.py")
    except Exception:  # noqa: BLE001
        return 0
    added = 0
    for source in relay.DEST:
        try:
            _arts, links, _st = relay.pending(source)
        except Exception:  # noqa: BLE001
            continue
        for row in links:
            url = article_url(str(row.get("one_line") or "").strip())
            key = _sha(url)
            if url.startswith("http") and key not in state["urls"]:
                state["urls"][key] = {"url": url, "seat": relay.DEST[source], "session": "", "status": "pending",
                                      "seen": _local(float(row["at"])),
                                      "source": f"line:{source}"}
                added += 1
    return added


def line_cards(since: float) -> list[dict]:
    """LINE content cards that arrived since `since` (already read by the bot): related, not re-read."""
    out = []
    try:
        relay = _module("article_relay", "article_relay.py")
        for source in relay.DEST:
            d = relay.out_dir(source)
            for row in _read(d / "index.json", {}).get("items") or []:
                if row.get("mode") in relay.CONTENT_MODES and relay._epoch(row.get("arrived_at")) >= since:
                    out.append({"source": f"line:{source}", "item": row.get("item"), "title": row.get("title") or "",
                                "summary": str(row.get("one_line") or "")[:300], "seat": relay.DEST[source],
                                "card": str(d / "cards" / f"{row.get('item')}.md")})
    except Exception:  # noqa: BLE001
        pass
    return out


RELATE_PROMPT = (
    "An article was read for a multi-project AI fleet. Pick the conversations (tasks) it is useful for, from the list "
    "below, at most 5, only real relevance. Output ONLY JSON: {\"related\":[{\"session\":\"<id>\",\"why\":\"<one short "
    "Traditional Chinese reason>\"}]} — an empty list when nothing fits.\n\nARTICLE:\n%s\n\nTASKS:\n%s")


def relate(pool, article: str, tasks: list[dict]) -> list[dict]:
    if pool is None or not tasks:
        return []
    listing = "\n".join(json.dumps({"session": t["id"][:8], "seat": t["seat"], "state": t["state"],
                                    "title": t["title"]}, ensure_ascii=False) for t in tasks)
    try:
        raw = pool.chat_for("extract", [{"role": "user", "content": RELATE_PROMPT % (article[:2500], listing)}],
                            jsonmode=True, max_tokens=600)
        m = re.search(r"\{[\s\S]*\}", str(raw or ""))
        picks = json.loads(m.group(0)).get("related") or [] if m else []
    except Exception:  # noqa: BLE001 — a pool failure relates nothing; it never stops the batch
        return []
    if not isinstance(picks, list):
        return []
    picks = [p for p in picks if isinstance(p, dict)]
    by8 = {t["id"][:8]: t for t in tasks}
    out = []
    for p in picks[:5]:
        t = by8.get(str(p.get("session") or "")[:8])
        if t:
            out.append({"session": t["id"], "seat": t["seat"], "state": t["state"], "why": str(p.get("why") or "")[:120]})
    return out


def task_list(state: dict, opened: set[str], n: int = 60) -> list[dict]:
    rows = [{"id": sid, "seat": s["seat"], "title": s["title"], "last": s["last"],
             "state": "open" if sid in opened else "archived"}
            for sid, s in state["sessions"].items() if s.get("title") and s["seat"] not in LOCAL_ONLY]
    rows.sort(key=lambda r: (r["state"] != "open", r["last"]), reverse=False)
    opened_rows = [r for r in rows if r["state"] == "open"]
    archived = sorted((r for r in rows if r["state"] != "open"), key=lambda r: r["last"], reverse=True)
    return (opened_rows + archived)[:n]


def read_articles(state: dict, now: float, opened: set[str], limit: int = ARTICLES_PER_TICK) -> dict:
    for u in state["urls"].values():                   # SLA: every pending URL past 24h is late, read or not
        if u["status"] == "pending":
            u["late"] = now - _epoch(u["seen"]) > ARTICLE_SLA_S
    pool = _pool()
    todo = sorted((u for u in state["urls"].values() if u["status"] == "pending"), key=lambda u: u["seen"])[:limit]
    if not todo:
        return {"read": 0, "pending": 0}
    if pool is None:
        return {"read": 0, "pending": len(todo), "blocked": "free pool (_llm.py) not on this host"}
    try:
        distill = _module("distill_url", "distill-url.py")
    except Exception as exc:  # noqa: BLE001
        return {"read": 0, "pending": len(todo), "blocked": f"distill-url: {type(exc).__name__}"}
    tasks = task_list(state, opened)
    done = failed = 0
    for u in todo:
        try:
            res = distill.distill_one(u["url"])
            res = res if isinstance(res, dict) else {}
        except Exception as exc:  # noqa: BLE001 — one bad URL never stops the batch
            res = {"error": f"{type(exc).__name__}: {exc}"[:200]}
        dig = res.get("digest") if isinstance(res.get("digest"), dict) else {}
        summary = str(dig.get("summary") or dig.get("snapshot") or "")
        points = dig.get("key_points") or dig.get("hub_skill") or []
        delegated = res.get("delegated") if isinstance(res.get("delegated"), dict) else {}
        if not summary and delegated.get("rc") == 0:     # youtube / sider engines write their own digest
            summary = str(delegated.get("stdout") or "")[-600:]
        if not summary:
            res.setdefault("error", res.get("reason") or res.get("status") or dig.get("__error__") or "")
        if not isinstance(points, list):
            points = [str(points)]
        u["read_at"] = _local(now)
        u["late"] = now - _epoch(u["seen"]) > ARTICLE_SLA_S
        if summary.strip():
            u.update(status="read", title=str(res.get("title") or res.get("_title") or "")[:160],
                     summary=summary[:600], points=[str(p)[:200] for p in points[:6]])
            u["related"] = relate(pool, summary + "\n" + "\n".join(u["points"]), tasks)
            done += 1
        else:
            u["attempts"] = int(u.get("attempts") or 0) + 1
            u["error"] = str(res.get("error") or res.get("verdict") or "no text")[:200]
            if u["attempts"] >= 3:
                u["status"] = "unreadable"            # never fabricated: recorded as unreadable with the reason
            failed += 1
    return {"read": done, "failed": failed, "pending": sum(1 for u in state["urls"].values() if u["status"] == "pending")}


# ── daily ───────────────────────────────────────────────────────────────────────────────────────
def lessons(state: dict, since: str) -> list[dict]:
    """f1s-harvest `conversation` items: one per correction prompt, one per repeated tool-error signature (>=3)."""
    out = []
    for c in state["corrections"]:
        if c["ts"] >= since and c["text"]:
            out.append({"kind": "conversation", "seat": c["seat"], "name": "correction " + _sha(c["text"]),
                        "path": str(PROJECTS), "state": "correction", "summary": c["text"][:300], "text": c["text"]})
    # Same window as render_live: a signature whose last hit is older than `since` is history, not a lesson
    # (2026-10-28: the 10-13 write-gate probe session resurfaced as "repeated tool error x4" 15 days later).
    for seat, sigs in state["errors"].items():
        if seat in LOCAL_ONLY:
            continue
        for sig, e in sigs.items():
            if e["n"] >= 3 and e["last"] >= since:
                out.append({"kind": "conversation", "seat": seat, "name": "tool-error " + _sha(sig), "path": str(PROJECTS),
                            "state": "tool-error", "summary": f"repeated tool error x{e['n']}: {sig}", "text": sig})
    return out


def matrix(state: dict, opened: set[str], since: str) -> dict:
    rows: dict[str, dict] = {}

    def row(seat: str) -> dict:
        return rows.setdefault(seat, {"open": 0, "archived": 0, "corrections_24h": 0, "decisions_24h": 0,
                                      "errors_repeated": 0, "articles_related": 0})
    for sid, s in state["sessions"].items():
        if s.get("seat"):
            row(s["seat"])["open" if sid in opened else "archived"] += 1
    for c in state["corrections"]:
        if c["ts"] >= since:
            row(c["seat"])["corrections_24h"] += 1
    for d in state["decisions"]:
        if d["ts"] >= since:
            row(d["seat"])["decisions_24h"] += 1
    for seat, sigs in state["errors"].items():
        row(seat)["errors_repeated"] = sum(1 for e in sigs.values() if e["n"] >= 3)
    for u in state["urls"].values():
        for r in u.get("related") or []:
            row(r["seat"])["articles_related"] += 1
    return rows


def gaps(rows: dict) -> dict:
    """Seats with conversations but no project-matrix entry, and registered projects with no conversation."""
    projects = _read(MATRIX, {}).get("projects") or {}
    seats = {s for s in rows if s not in ("hub", "")}
    return {"unregistered_seats": sorted(s for s in seats if s not in projects),
            "registered_without_conversations": sorted(p for p in projects if p not in seats and not never(p))}


def write_matrix(rows: dict, gap: dict, day: str) -> str:
    """Each registered project gets `f1s_daily` (its row + day); the rest of the file stays byte-identical."""
    try:
        original = MATRIX.read_text(encoding="utf-8-sig")
        doc = json.loads(original)
    except (OSError, ValueError):
        return "unreadable"
    indent = next((n for n in (2, 1, 4) if json.dumps(doc, ensure_ascii=False, indent=n) + "\n" in (original, original + "\n")
                   or json.dumps(doc, ensure_ascii=False, indent=n) == original), None)
    if indent is None:
        return "format-unknown (not written)"
    for name, proj in (doc.get("projects") or {}).items():
        if isinstance(proj, dict):
            proj["f1s_daily"] = {"day": day, **rows.get(name, {"open": 0, "archived": 0}),
                                 "gap": "no conversations" if name in gap["registered_without_conversations"] else ""}
    text = json.dumps(doc, ensure_ascii=False, indent=indent) + ("\n" if original.endswith("\n") else "")
    if text != original:
        _write(MATRIX, text)
    return "written"


def fleet_hygiene_rows(since: str) -> list[dict]:
    """Every host's latest hygiene.json from the carrier clone (fleet-hygiene.py fleet), newest first; none = no section."""
    try:
        mod = _module("fleet_hygiene_for_daily", "fleet-hygiene.py")
        rows = mod.fleet()
    except Exception:  # noqa: BLE001 - the digest never fails on a missing or broken sibling
        return []
    return sorted((r for r in rows if str(r.get("at") or "") >= since[:10]), key=lambda r: str(r.get("at")), reverse=True)[:6]


def render_live(day: str, state: dict, rows: dict, gap: dict, since: str) -> str:
    lines = [f"# F1S daily digest {day} (f1s_daily.py; replaces the previous one)",
             "Apply from this turn in every conversation: the operator corrections below are the operator's own words "
             "from other conversations; do not repeat what they reject. Articles: use them where the related task is yours."]
    corr = [c for c in state["corrections"] if c["ts"] >= since and c["text"]]
    if corr:
        lines.append("## Operator corrections (24h)")
        for c in corr[-8:]:
            lines.append(f"- [{c['seat']}] 「{c['text'][:160].replace(chr(10), ' ')}」")
    errs = sorted(((e["n"], seat, sig) for seat, sigs in state["errors"].items() if seat not in LOCAL_ONLY
                   for sig, e in sigs.items() if e["n"] >= 3 and e["last"] >= since), reverse=True)
    if errs:
        lines.append("## Repeated tool errors (fix the cause, not the retry)")
        lines += [f"- [{seat}] x{n}: {sig[:120]}" for n, seat, sig in errs[:6]]
    hyg = fleet_hygiene_rows(since)
    if hyg:   # before the articles: live.md is capped at LIVE_MAX_CHARS and the first render of 2026-10-30 cut this off
        lines.append("## Fleet hygiene (每台自己的 check/sweep 報告, fleet-hygiene.py fleet)")
        for h in hyg:
            act = h.get("activity") or {}
            lines.append(f"- [{h['contributor']}] {str(h.get('at'))[5:16]} cwd {h.get('seats')} 違規 {h.get('violations')} "
                         f"(active {act.get('ACTIVE')}/idle {act.get('IDLE')}/dormant {act.get('DORMANT')}) 搬 {h.get('moved')} "
                         f"_delete {h.get('delete_gb')} GB" + (f" 首項 {h['findings'][0][:60]}" if h.get("findings") else ""))
    arts = [u for u in state["urls"].values() if u["status"] == "read" and str(u.get("read_at") or "") >= since]
    if arts:
        lines.append("## Articles read (24h)")
        for u in arts[:6]:
            rel = ", ".join(f"{r['seat']}:{r['session'][:8]}({r['state']})" for r in (u.get("related") or [])[:3]) or "none"
            lines.append(f"- {(u.get('title') or u['url'])[:80]} — {str(u.get('summary') or '')[:140]} — related: {rel}")
    dec = {s: r["decisions_24h"] for s, r in rows.items() if r["decisions_24h"]}
    if dec:
        lines.append("## 「需要你決定」 asked (24h): " + ", ".join(f"{s} {n}" for s, n in sorted(dec.items())))
    if gap["unregistered_seats"]:
        lines.append("## Matrix gaps: unregistered seats " + ", ".join(gap["unregistered_seats"]))
    text = "\n".join(lines) + "\n"
    return text if len(text) <= LIVE_MAX_CHARS else text[:LIVE_MAX_CHARS - 40].rsplit("\n", 1)[0] + "\n(truncated)\n"


def daily(state: dict, now: float, opened: set[str]) -> dict:
    day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    since = _local(now - 86400)
    rows = matrix(state, opened, since)
    gap = gaps(rows)
    items = lessons(state, since)
    _write(OUT / "lessons.json", {"day": day, "items": items})   # f1s-harvest reads this (kind `conversation`)
    live = render_live(day, state, rows, gap, since)
    if live != (LIVE.read_text(encoding="utf-8") if LIVE.is_file() else ""):
        _write(LIVE, live)
    digest = {"schema": "f1s-daily/1", "day": day, "generated": _iso(now), "matrix": rows, "gaps": gap,
              "lessons": len(items), "corrections_24h": sum(r["corrections_24h"] for r in rows.values()),
              "articles": [{k: u.get(k) for k in ("url", "source", "seat", "seen", "read_at", "late", "status", "title",
                                                   "summary", "points", "related", "error")}
                           for u in state["urls"].values() if str(u.get("read_at") or u["seen"]) >= since],
              "line_cards": [], "live": str(LIVE), "project_matrix": write_matrix(rows, gap, day)}
    pool = _pool()
    tasks = task_list(state, opened)
    for card in line_cards(now - 86400):
        card["related"] = relate(pool, card["title"] + "\n" + card["summary"], tasks)
        digest["line_cards"].append(card)
    _write(OUT / f"digest-{day}.json", digest)
    state["last_daily"] = day
    return {"day": day, "digest": str(OUT / f"digest-{day}.json"), "lessons": len(items),
            "project_matrix": digest["project_matrix"], "live_chars": len(live)}


def _load_grant(owner: str, step_w: float) -> dict:
    scripts = HUB / "ai_darkhero" / "tray" / "scripts"
    if not (scripts / "load_grant.py").is_file():
        return {"ok": True, "reason": "no load scheduler on this host"}
    if str(scripts) not in sys.path:
        sys.path.append(str(scripts))
    try:
        import load_grant as lg  # noqa: E402
        return lg.wait_grant(owner, step_w, 600.0)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"load grant failed: {type(exc).__name__}"}


def load_state() -> dict:
    st = _read(STATE, {})
    for k, v in (("files", {}), ("sessions", {}), ("corrections", []), ("decisions", []), ("errors", {}), ("urls", {})):
        st.setdefault(k, v)
    return st


def _holder_alive() -> bool:
    """A killed tick leaves its lock behind; only a live holder pid keeps it (unknown = alive, fail safe)."""
    try:
        pid = int(LOCK.read_text(encoding="utf-8").strip() or 0)
        import psutil
        return pid > 0 and psutil.pid_exists(pid) and "python" in psutil.Process(pid).name().lower()
    except (OSError, ValueError):
        return True
    except Exception:
        return True


def tick(force_daily: bool = False, now: float | None = None) -> dict:
    now = now or _now()
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        try:
            if now - LOCK.stat().st_mtime < 3 * 3600 and _holder_alive():
                return {"skipped": "another tick holds the lock"}
            LOCK.unlink()
        except FileNotFoundError:                      # the holder released it between open and stat
            pass
        return tick(force_daily, now)
    try:
        grant = _load_grant("f1s-daily/tick", 5.0)
        if not grant.get("ok"):
            return {"deferred": grant.get("reason")}
        state = load_state()
        result = {"at": _iso(now), "scan": scan(state, now)}
        prune(state, now)
        _write(STATE, state)
        result["line_links"] = line_links(state)
        opened = open_sessions()
        result["articles"] = read_articles(state, now, opened)
        _write(STATE, state)
        hour = datetime.fromtimestamp(now).hour
        today = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        if force_daily or (state.get("last_daily") != today and hour >= DAILY_AFTER_HOUR):
            result["daily"] = daily(state, now, opened)
            _write(STATE, state)
        state.setdefault("ticks", []).append({k: result[k] for k in result if k != "at"} | {"at": result["at"]})
        state["ticks"] = state["ticks"][-20:]
        _write(STATE, state)
        return result
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


def status() -> dict:
    st = load_state()
    urls = list(st["urls"].values())
    return {"transcripts": len(st["files"]), "sessions": len(st["sessions"]), "corrections": len(st["corrections"]),
            "decisions": len(st["decisions"]), "urls_pending": sum(u["status"] == "pending" for u in urls),
            "urls_read": sum(u["status"] == "read" for u in urls), "urls_late": sum(bool(u.get("late")) for u in urls),
            "last_daily": st.get("last_daily"), "last_tick": (st.get("ticks") or [{}])[-1].get("at"),
            "live": str(LIVE) if LIVE.is_file() else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick")
    t.add_argument("--force-daily", action="store_true")
    t.add_argument("--json", action="store_true")
    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        doc = tick(a.force_daily) if a.cmd == "tick" else status()
    except Exception as exc:  # noqa: BLE001 — a failure never leaves the rider red forever; it is printed
        doc = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(doc, ensure_ascii=False, indent=1 if getattr(a, "json", False) else None))
    return 1 if "error" in doc else 0


if __name__ == "__main__":
    sys.exit(main())
