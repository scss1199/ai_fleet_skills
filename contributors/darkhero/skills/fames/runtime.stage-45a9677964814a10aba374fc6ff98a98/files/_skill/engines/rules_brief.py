#!/usr/bin/env python3
"""Format _registry/rules-blueprint.json for SessionStart / PreCompact injection.

Portal rules tab and agent hooks share this formatter so they never drift.
CITE: _registry/rules-blueprint.json · 50-techniques/consolidate-master-directives.md
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

MAX_BYTES = 4096
TRUNCATION_NOTE = "\n…(truncated; full: _registry/rules-blueprint.json)"
_LBL = {
    "lang": "語言",
    "no-guess": "嚴禁猜",
    "secrets": "金鑰",
    "deletion": "刪除",
    "operator-auth": "授權",
    "zero-foreground": "零前景",
    "no-modal-popup": "零彈窗",
    "kb-readonly": "KB 唯讀",
    "portal-authority": "portal 權威",
    "readout": "READOUT",
    "five-element": "五段落",
    "goal-compact": "goal-compact",
    "consume-submit-cite": "CONSUME/SUBMIT/CITE",
    "effort": "effort",
    "pptt-report": "PPTT report",
    "bus-close": "bus 收尾",
    "zt-north-star": "ZT 北極星",
    "no-operator-zct-waste": "禁止問 operator",
    "automation": "automation",
    "download": "下載",
    "git-smart": "git",
    "piggyback-announce": "piggyback 公告",
    "web-ops": "web ops",
    "no-local-llm": "本地 LLM",
}


def hub_root() -> Path:
    return Path(os.environ.get("AI_WORKSPACE") or os.environ.get("CLAUDE_COMMON") or r"C:\ai_workspace")


def load_blueprint() -> dict:
    p = hub_root() / "_registry" / "rules-blueprint.json"
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except OSError:
        return {}


def rules_hash() -> str:
    p = hub_root() / "_registry" / "rules-blueprint.json"
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def _tier_ids(bp: dict, tiers: list[str] | None) -> list[str]:
    if not tiers:
        return ["T1"]
    if len(tiers) == 1 and tiers[0].upper() == "ALL":
        return [t.get("id", "") for t in bp.get("tiers", []) if t.get("id")]
    return tiers


def format_rules(tiers: list[str] | None = None, max_bytes: int = MAX_BYTES) -> str:
    bp = load_blueprint()
    want = set(_tier_ids(bp, tiers))
    lines = [
        "STANDING RULES (_registry/rules-blueprint.json — portal rules tab = this source; obey every turn):"
    ]
    for tier in bp.get("tiers", []):
        tid = tier.get("id", "")
        if tid not in want:
            continue
        lines.append("[%s %s]" % (tid, tier.get("name", "")))
        for r in tier.get("rules", []):
            tag = _LBL.get(r.get("id", ""), r.get("id", ""))
            rule = (r.get("rule") or "").strip()
            if rule:
                lines.append("- %s: %s" % (tag, rule))
    text = "\n".join(lines)
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    note = TRUNCATION_NOTE
    budget = max_bytes - len(note.encode("utf-8"))
    return raw[:budget].decode("utf-8", errors="ignore") + note


def _normalise(text) -> str:
    return " ".join(str(text or "").split())


def t1_rules() -> list[str]:
    """T1 rule texts, whitespace-normalised: the hard lines a charter must state exactly."""
    for tier in load_blueprint().get("tiers", []):
        if tier.get("id") == "T1":
            return [text for text in (_normalise(r.get("rule")) for r in tier.get("rules", [])) if text]
    return []


def charter_with_t1(cwd) -> Path | None:
    """Nearest loaded AGENTS.md at or above cwd that states every T1 rule exactly, else None.

    cursor_bootstrap_pack.py writes T1 whole into every seat charter, and each engine loads
    that charter at session start: Codex and Cursor read AGENTS.md, and Claude reads it
    through the `@AGENTS.md` import in CLAUDE.md. The hub root charter stays thin because
    every seat also loads it as a parent, so the hub root and non-seat folders carry no T1.
    The walk stops at the git root: Codex reads AGENTS.md only from there down to cwd. For
    Claude, which also reads above it, stopping early can only duplicate T1, never drop it.
    """
    rules = t1_rules()
    if not rules:
        return None
    start = Path(os.path.abspath(cwd))
    for folder in (start, *start.parents):
        charter = folder / "AGENTS.md"
        try:
            text = _normalise(charter.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError):
            text = ""
        if text and all(rule in text for rule in rules):
            return charter
        if (folder / ".git").exists():
            break
    return None


def format_for_session(max_bytes: int = MAX_BYTES, cwd=None) -> str:
    """Standing rules that a session start or a compaction refresh must inject.

    "" when the charter loaded for cwd already carries T1: a second copy only spends tokens.
    Otherwise the full blueprint when it fits max_bytes, else T1 alone and whole. T1 is the
    stop-on-violation tier, and cutting it drops its last rules without any signal. (The old
    fallback tested endswith("truncated"), which the note never matches, so it never ran.)
    """
    if cwd is not None and charter_with_t1(cwd) is not None:
        return ""
    full = format_rules(["ALL"], max_bytes)
    if not full.endswith(TRUNCATION_NOTE):
        return full
    return format_rules(["T1"], 1 << 30)




def _write_stdout(text: str, max_bytes: int) -> None:
    """Emit UTF-8 without Windows CRLF expansion (print adds \r per \n)."""
    data = text.encode('utf-8')
    if len(data) > max_bytes:
        note = TRUNCATION_NOTE
        budget = max_bytes - len(note.encode('utf-8'))
        text = data[:budget].decode('utf-8', errors='ignore') + note
        data = text.encode('utf-8')
    sys.stdout.buffer.write(data)

def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Format rules-blueprint for hook injection")
    ap.add_argument("--tiers", default="ALL", help="comma-separated tier ids or ALL")
    ap.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    ap.add_argument("--hash-only", action="store_true")
    ap.add_argument("--session", action="store_true", help="rules a session start must inject (empty when the --cwd charter carries T1)")
    ap.add_argument("--cwd", default=None, help="session folder for --session (default: current directory)")
    args = ap.parse_args()
    if args.hash_only:
        print(rules_hash())
        return 0
    if args.session:
        text = format_for_session(args.max_bytes, cwd=args.cwd or os.getcwd())
        # Already sized by format_for_session; cutting it again at max_bytes would split T1.
        _write_stdout(text, max(args.max_bytes, len(text.encode("utf-8"))))
        return 0
    tiers = [x.strip() for x in args.tiers.split(",") if x.strip()]
    _write_stdout(format_rules(tiers, args.max_bytes), args.max_bytes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
