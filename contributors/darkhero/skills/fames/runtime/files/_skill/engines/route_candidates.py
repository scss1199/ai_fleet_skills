#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""route_candidates.py — the routes a request could take, for a model that just said it has none.

F1S 強制思考 item A (operator 2026-10-19 「強制模型思考怎麼解決而不是一直犯錯」). On 2026-10-18 a session answered
「LINE 不能直接送檔案…傳不出去」 with zero tool calls while skill `line-oa-send` existed; pushed once, it built the route
in two minutes. The gap was not knowledge but LOOKING. So when PROOF pushes back on a blocker / hand-back / decision
line, it now hands the model the top candidate routes for the operator's own words (this module), and the model must
try one or cite a failing tool result for each. Two sources, both local, zero model tokens:

  * ztm-task-router.py routes (_registry/ztm-task-routes.json) — mechanical task -> command
  * the fleet skill index: name + description frontmatter of every _skill/fleet-skills/*/SKILL.md, scored by latin
    word + CJK bigram overlap with the request (the router's own tokenizer treats a CJK run as one token and missed
    the LINE case entirely)

  python route_candidates.py "檔案傳到 LINE 不要用雲端硬碟"   # prints the ranked candidates as JSON
Fails open: any error -> [] (a broken helper never blocks a turn).
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
ROUTER = HUB / "_skill" / "engines" / "ztm-task-router.py"
STOP = {"the", "and", "for", "with", "that", "this", "use", "when", "from", "your", "you", "are", "not", "any",
        "一下", "一個", "這個", "那個", "然後", "直接", "不要", "少廢話", "他媽", "你他媽"}
_index_cache: list[dict] | None = None


def _grams(text: str) -> set[str]:
    text = (text or "").lower()
    latin = {w for w in re.findall(r"[a-z][a-z0-9_./-]{2,}", text) if w not in STOP}
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


def skill_index() -> list[dict]:
    global _index_cache
    if _index_cache is None:
        rows = []
        for sk in sorted(SKILLS.glob("*/SKILL.md")):
            fm = _frontmatter(sk)
            name = fm.get("name") or sk.parent.name
            desc = fm.get("description") or ""
            rows.append({"name": name, "desc": desc, "grams": _grams(name + " " + desc), "path": str(sk)})
        _index_cache = rows
    return _index_cache


def _router_routes(text: str, top: int) -> list[dict]:
    try:
        spec = importlib.util.spec_from_file_location("ztm_task_router_for_candidates", ROUTER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        routes = mod.match_routes(text, top=top) or []
    except Exception:  # noqa: BLE001 - fail open
        return []
    out = []
    for r in routes:
        if isinstance(r, (list, tuple)) and r and isinstance(r[0], dict):
            r = r[0]                       # match_routes yields (route_dict, score) pairs
        if not isinstance(r, dict):
            continue
        name = str(r.get("id") or r.get("name") or r.get("task") or "")
        how = str(r.get("cmd") or r.get("command") or r.get("action") or r.get("how") or "")[:160]
        if name and how:
            out.append({"kind": "route", "name": name, "how": how, "score": 1.0})
    return out


def candidates(text: str, top: int = 3) -> list[dict]:
    """Ranked routes for `text`: skill matches by overlap, plus router routes; [] when nothing scores."""
    try:
        q = _grams(text)
        if not q:
            return []
        scored = []
        for row in skill_index():
            hit = q & row["grams"]
            if not hit:
                continue
            # weight: each latin hit 2, each CJK bigram 1; normalise lightly by description size
            score = sum(2 if re.match(r"[a-z]", h) else 1 for h in hit) / (1 + len(row["grams"]) ** 0.25)
            scored.append({"kind": "skill", "name": row["name"], "how": row["desc"][:160], "score": round(score, 3),
                           "hits": sorted(hit)[:6]})
        scored.sort(key=lambda r: -r["score"])
        out = scored[:top]
        for r in _router_routes(text, top):
            if len(out) >= top + 1:
                break
            out.append(r)
        return out[:top + 1]
    except Exception:  # noqa: BLE001 - fail open
        return []


def render(rows: list[dict], tool_calls: int | None = None) -> str:
    """One block for a hook reason: numbered routes, or '' when there are none."""
    if not rows:
        return ""
    head = ("You made %d tool call(s) this turn. " % tool_calls) if tool_calls is not None else ""
    lines = [f"  {i}) {r['kind']} `{r['name']}` — {r['how']}" for i, r in enumerate(rows, 1)]
    return (head + "Routes for the operator's request that this turn did not try:\n" + "\n".join(lines) +
            "\nTry one NOW, or cite the failing tool result for each before claiming there is no route.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(candidates(" ".join(sys.argv[1:])), ensure_ascii=False, indent=1))
