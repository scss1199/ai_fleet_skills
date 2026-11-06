#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""route_candidates.py — the routes a request could take, for a model that just said it has none.

F1S 強制思考 item A (operator 2026-10-19 「強制模型思考怎麼解決而不是一直犯錯」). On 2026-10-18 a session answered
「LINE 不能直接送檔案…傳不出去」 with zero tool calls while skill `line-oa-send` existed; pushed once, it built the route
in two minutes. The gap was not knowledge but LOOKING. When PROOF pushes back on a blocker / hand-back / decision
line it hands the model the top candidate routes for the operator's own words, and the model must try one or cite a
failing tool result for each.

v2 (same day, operator 「把不能的地方全部弄通」): v1 indexed only the 56 fleet skills and came up empty on 35 of 85
real operator prompts. Sources now, all local, zero model tokens:
  1 fleet skills       _skill/fleet-skills/*/SKILL.md name + description
  2 fleet ledger       _registry/f1s-harvest/ledger.json — every seat's skills, memory lessons, tools, APIs, article
                       cards (2172 items on 2026-10-19); same-seat items boosted
  3 curator memory     ~/.claude/projects/C--ai-workspace-ai-darkhero/memory/MEMORY.md index lines (the harvest
                       skips the curator seat by design, so gh-auth-sync, power-loss etc. live only here)
  4 hub + curator code _skill/engines/*.py and ai_darkhero/scripts/*.py first docstring line
  5 task router        ztm-task-router.py routes
and it never returns empty: a prompt with no content words (「又來」「廢話」) routes to continuing the previous operator
instruction; a prompt with content but no local match routes to free-pool research (distill-url.py --search) — a
named route the model must run, instead of "no route".

  python route_candidates.py "檔案傳到 LINE 不要用雲端硬碟"   # ranked candidates as JSON
Fails open: any error inside a source -> that source contributes nothing; the fallback still answers.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace")
SKILLS = HUB / "_skill" / "fleet-skills"
LEDGER = HUB / "_registry" / "f1s-harvest" / "ledger.json"
CURATOR_MEMORY = Path.home() / ".claude" / "projects" / "C--ai-workspace-ai-darkhero" / "memory" / "MEMORY.md"
CODE_DIRS = (HUB / "_skill" / "engines", HUB / "ai_darkhero" / "scripts")
ROUTER = HUB / "_skill" / "engines" / "ztm-task-router.py"
RESEARCH = "python C:/ai_workspace/_skill/engines/distill-url.py --search"
STOP = {"the", "and", "for", "with", "that", "this", "use", "when", "from", "your", "you", "are", "not", "any",
        "一下", "一個", "這個", "那個", "然後", "直接", "不要", "少廢話", "他媽", "你他媽", "你這", "是不", "不是",
        "什麼", "為什", "麼又", "怎麼", "浪費", "費時", "時間", "廢物", "白癡", "智障", "繼續", "推進", "下一", "一步"}
# A canonical fleet skill is the preferred route: without the boost a short seat-local summary (jci-line-oa-token-
# reissue) outscored `line-oa-send` on the very prompt this helper exists for (measured 2026-10-19 on 2715 rows).
KIND_WEIGHT = {"skill": 1.25, "memory": 1.0, "system": 0.9, "api": 0.7, "article": 0.8, "code": 0.85, "route": 1.0}
SHORT_PROMPT = 16   # chars: a short all-CJK prompt made of reaction words (「又滿是怎樣」) is a reaction, not a task
# Same markers the complaint sweep used; a short prompt without one (「鞋帶 位置不對 看截圖」) is a real instruction.
REACTION = re.compile(r"他媽|媽的|廢物|白癡|智障|垃圾|怎樣|幾[變遍次]|浪費|又來|又是|又滿|廢話|搞什麼|在幹嘛|有沒有在聽")
_cache: dict[str, list[dict]] = {}


def _grams(text: str) -> set[str]:
    text = (text or "").lower()
    latin = {w for w in re.findall(r"[a-z][a-z0-9_./-]{1,}", text) if w not in STOP and len(w) > 1}
    cjk = re.findall(r"[\u4e00-\u9fff]+", text)
    bi = {run[i:i + 2] for run in cjk for i in range(len(run) - 1)}
    return (latin | bi) - STOP


def _frontmatter(path: Path) -> dict:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return {}
    m = re.match(r"---\s*\n(.*?)\n---", head, re.S)
    if not m:
        return {}
    out, key, buf = {}, None, []
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if km and not line.startswith(" "):
            if key:
                out[key] = " ".join(buf).strip()
            key, val = km.group(1), km.group(2).strip()
            buf = [] if val in (">-", ">", "|", "|-") else [val]
        elif key:
            buf.append(line.strip())
    if key:
        out[key] = " ".join(buf).strip()
    return out


def _row(kind: str, name: str, how: str, seat: str = "", path: str = "") -> dict:
    return {"kind": kind, "name": name, "how": how[:160], "seat": seat, "path": path,
            "grams": _grams(name + " " + how)}


# ------------------------------------------------------------------ sources (each fails open to [])
def _src_skills() -> list[dict]:
    out = []
    for sk in sorted(SKILLS.glob("*/SKILL.md")):
        fm = _frontmatter(sk)
        out.append(_row("skill", fm.get("name") or sk.parent.name, fm.get("description") or "", "fleet", str(sk)))
    return out


def _src_ledger() -> list[dict]:
    try:
        items = json.loads(LEDGER.read_text(encoding="utf-8-sig")).get("items") or []
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for it in items:
        if it.get("status") in ("rejected", "noise"):
            continue
        kind = it.get("kind") or "system"
        out.append(_row(kind if kind in KIND_WEIGHT else "system", str(it.get("name") or ""),
                        str(it.get("summary") or ""), str(it.get("seat") or ""), str(it.get("path") or "")))
    return out


def _src_curator_memory() -> list[dict]:
    try:
        text = CURATOR_MEMORY.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for m in re.finditer(r"^- \[([^\]]+)\]\(([^)]+)\)\s*[—-]\s*(.+)$", text, re.M):
        out.append(_row("memory", m.group(1), m.group(3), "ai_darkhero", str(CURATOR_MEMORY.parent / m.group(2))))
    return out


def _src_code() -> list[dict]:
    out = []
    for d in CODE_DIRS:
        for py in sorted(d.glob("*.py")) if d.is_dir() else []:
            try:
                head = py.read_text(encoding="utf-8", errors="replace")[:2500]
            except OSError:
                continue
            m = re.search(r'"""\s*(.+?)(?:\n\s*\n|""")', head, re.S) or re.search(r"'''\s*(.+?)(?:\n\s*\n|''')", head, re.S)
            if not m:
                continue
            first = " ".join(m.group(1).split())[:220]
            out.append(_row("code", py.stem, first, "ai_darkhero" if "ai_darkhero" in str(d) else "hub", str(py)))
    return out


def _src_router(text: str, top: int) -> list[dict]:
    try:
        spec = importlib.util.spec_from_file_location("ztm_task_router_for_candidates", ROUTER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        routes = mod.match_routes(text, top=top) or []
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in routes:
        if isinstance(r, (list, tuple)) and r and isinstance(r[0], dict):
            r = r[0]
        if not isinstance(r, dict):
            continue
        name = str(r.get("id") or r.get("name") or r.get("task") or "")
        how = str(r.get("cmd") or r.get("command") or r.get("action") or r.get("how") or "")[:160]
        if name and how:
            out.append({"kind": "route", "name": name, "how": how, "seat": "hub", "path": "", "score": 1.0})
    return out


def index() -> list[dict]:
    if "index" not in _cache:
        rows: list[dict] = []
        for src in (_src_skills, _src_ledger, _src_curator_memory, _src_code):
            try:
                rows += src()
            except Exception:  # noqa: BLE001 - one broken source never empties the index
                continue
        _cache["index"] = rows
    return _cache["index"]


# ------------------------------------------------------------------ ranking + fallbacks
def candidates(text: str, top: int = 3, seat: str = "") -> list[dict]:
    """Ranked routes for `text`, never []: content words -> matches or a research route; no content -> continue."""
    try:
        q = _grams(text)
        stripped = (text or "").strip()
        reaction = (len(stripped) <= SHORT_PROMPT and not re.search(r"[A-Za-z0-9]", stripped)
                    and bool(REACTION.search(stripped)))
        if not q or reaction:
            return [{"kind": "continue", "name": "continue-previous-instruction",
                     "how": "this prompt carries no new task: re-read the operator's previous instruction in this "
                            "conversation and act on what it asked, with tools, before replying", "score": 0.0}]
        scored = []
        for row in index():
            hit = q & row["grams"]
            if not hit:
                continue
            raw = sum(2 if re.match(r"[a-z]", h) else 1 for h in hit) / (1 + len(row["grams"]) ** 0.25)
            raw *= KIND_WEIGHT.get(row["kind"], 0.8)
            if seat and row["seat"] == seat:
                raw *= 1.5          # a route that already lives in this seat beats a foreign one
            scored.append({"kind": row["kind"], "name": row["name"], "how": row["how"], "seat": row["seat"],
                           "path": row["path"], "score": round(raw, 3), "hits": sorted(hit)[:6]})
        scored.sort(key=lambda r: -r["score"])
        out = scored[:top]
        for r in _src_router(text, top):
            if len(out) >= top + 1:
                break
            out.append(r)
        if not out:
            words = " ".join(sorted(q, key=len, reverse=True)[:6])
            out = [{"kind": "research", "name": "free-pool-web-research",
                    "how": f"nothing local matches: {RESEARCH} \"{words}\" --n 5 (keyless web search on the free "
                           "pool, zero Claude tokens), read the top hits, then act or cite what they say", "score": 0.0}]
        return out[:top + 1]
    except Exception:  # noqa: BLE001 - the helper must still answer
        return [{"kind": "research", "name": "free-pool-web-research",
                 "how": f"{RESEARCH} \"<the operator's request>\" --n 5, then act or cite the result", "score": 0.0}]


def render(rows: list[dict], tool_calls: int | None = None) -> str:
    """One block for a hook reason: numbered routes, or '' when there are none."""
    if not rows:
        return ""
    head = ("You made %d tool call(s) this turn. " % tool_calls) if tool_calls is not None else ""
    lines = []
    for i, r in enumerate(rows, 1):
        where = f" [{r['seat']}]" if r.get("seat") and r["seat"] not in ("fleet", "hub") else ""
        lines.append(f"  {i}) {r['kind']} `{r['name']}`{where} — {r['how']}")
    return (head + "Routes for the operator's request that this turn did not try:\n" + "\n".join(lines) +
            "\nTry one NOW, or cite the failing tool result for each before claiming there is no route.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(candidates(" ".join(sys.argv[1:])), ensure_ascii=False, indent=1))
