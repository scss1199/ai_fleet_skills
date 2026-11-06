#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""claim-linter.py — 0-token load-bearing claim grounding check.

Scans text for paths, completion claims, counts without citation markers.

Usage:
  python claim-linter.py --text "..."
  python claim-linter.py --file path
  python claim-linter.py --hook --taskfile <path> [--json]
  python claim-linter.py --test

CITE: _skill/technique_output/10-foundations/evidence-gate-no-guess.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Load-bearing claim patterns
_PATH = re.compile(r"(?i)(?:[A-Za-z]:\\|%AI_WORKSPACE%|/ai_workspace/|_skill/|_registry/|_temp/)")
_VERSION = re.compile(r"\bv?\d+\.\d+(\.\d+)?\b")
_PERCENT = re.compile(r"\b\d{1,3}%\b")
_DONE_CLAIM = re.compile(
    r"(?i)(已完成|已修復|已部署|shipped|deployed|fixed|passes|all tests pass|"
    r"100%|done|merged|已上線|驗證通過)"
)
_COUNT = re.compile(r"(?i)\b(\d+)\s*(agents?|files?|tests?|seats?|errors?)\b")

# Grounding markers
_GROUND = re.compile(
    r"(?i)(cite:|verify:|unknown\s*[—\-]\s*check|unverified|hypothesis|"
    r"`[^`]+`|```|evidence:|proof:|rc=0|pytest|py_compile|wiki_cite:|mtm-wiki-query)"
)

# Knowledge-class claims need wiki_cite (PFKT v3 Wiki-first)
_KNOWLEDGE = re.compile(
    r"(?i)(wiki\s*page|wiki\s*層|intel\s*kb|onenote|onepkg|obsidian\s*vault|"
    r"shared[- ]knowledge|knowledge\s*ssot|digest\s*promot|compiled\s*wiki)"
)
_WIKI_CITE = re.compile(r"(?i)(wiki_cite:|wiki_cite\s*=|mtm-wiki-query|resolve\s+\w+|`wiki/[^`]+`)")

# Mathematical claims are decided by the hub Lean gate (its rule is the Lean-proved `Fames.mathOk`).
_LEAN_GATE = os.path.join(os.environ.get("AI_WORKSPACE", r"C:\ai_workspace"), "_lean", "fames", "lean_gate.py")
_LEAN_REPLAY_BUDGET_S = 8.0     # the Cursor stop gate gives this script 15 s
_MATH_FIX = ("Mathematical claim: run `python %s attest --file <proof.lean>` and copy the exact matching "
             "`claim_lines` and `evidence_lines` pair; a marker alone cannot validate prose. "
             "Otherwise say UNKNOWN on the claim line"
             % _LEAN_GATE)
# Used only while the Lean gate cannot be loaded: broader than its detector, and nothing but UNKNOWN
# wording on the line excuses a flagged line then.
_MATH_PROOF_FALLBACK = re.compile(
    r"(?i)(?:\bQ\.?E\.?D\b|\bprov(?:ed|en|es|able)\b|\bprove\s+that\b|\bshow(?:n|ed)?\s+that\b|"
    r"\bfollows\s+that\b|\b(?:holds|true)\s+for\s+(?:all|every|any)\b|\bis\s+a\s+theorem\b|"
    r"\bformally\s+verified\b|\bmachine[- ]checked\b|\bmathematically\b|"
    r"\bLean[- ](?:proved|proven|verified|checked)\b|\b(?:verified|checked)\s+(?:in|by|with)\s+Lean\b|"
    r"Lean\s*(?:已經|已经|已)?\s*(?:證明|证明|驗證|验证|檢查|检查)|形式化?\s*(?:驗證|验证|證明|证明)|"
    r"得證|得证|證畢|证毕|已證|已证|證明了|证明了|可證|可证|證得|证得|證出|证出|成立|必然|數學上|数学上)"
)
_MATH_UNKNOWN = re.compile(
    r"(?i)(?:\bUNKNOWN\b|\bunverified\b|\bnot\s+verified\b|\bhypothesis\b|未知|未驗證|未验证|待驗證|待验证|"
    r"假設|假设|推測|推测)"
)
_LEAN_GATE_MODULE = []


def _lean_gate():
    """The hub Lean gate, loaded once; None when it cannot be loaded, which opens nothing."""
    if not _LEAN_GATE_MODULE:
        module = None
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("fames_lean_gate", _LEAN_GATE)
            if spec is not None and spec.loader is not None:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.set_budget(_LEAN_REPLAY_BUDGET_S)
        except Exception:
            module = None
        _LEAN_GATE_MODULE.append(module)
    return _LEAN_GATE_MODULE[0]


def _math_violations(text: str) -> list:
    lines = (text or "").splitlines()
    gate = _lean_gate()
    flagged = []
    if gate is not None:
        try:
            flagged = [v["line"] for v in gate.lint_text(text or "")["violations"]]
        except Exception:
            gate = None
    if gate is None:
        fenced = False
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("```"):
                fenced = not fenced
                continue
            if fenced or not stripped or stripped.startswith(">"):
                continue
            claim = re.split(r"(?i)\bevidence\s*:", stripped, maxsplit=1)[0]
            if _MATH_PROOF_FALLBACK.search(claim) and not _MATH_UNKNOWN.search(claim):
                flagged.append(i)
    return [{"line": i, "claim": lines[i - 1].strip()[:120], "triggers": ["math_proof"], "fix": _MATH_FIX}
            for i in flagged]


def lint_text(text: str) -> dict:
    lines = (text or "").splitlines()
    # Before the grounding skip below: a backtick or a `verify:` tag grounds a path, not a theorem.
    violations = _math_violations(text)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or len(stripped) < 8:
            continue
        if _GROUND.search(stripped):
            continue
        triggers = []
        if _PATH.search(stripped):
            triggers.append("path")
        if _DONE_CLAIM.search(stripped):
            triggers.append("completion")
        if _VERSION.search(stripped) and not _GROUND.search(stripped):
            triggers.append("version")
        if _PERCENT.search(stripped):
            triggers.append("percent")
        if _COUNT.search(stripped):
            triggers.append("count")
        if triggers:
            violations.append({
                "line": i,
                "claim": stripped[:120],
                "triggers": triggers,
                "fix": "Add cite:/verify:/`path` or label unknown — check:",
            })
        # knowledge completion without wiki cite
        if _KNOWLEDGE.search(stripped) and _DONE_CLAIM.search(stripped) and not _WIKI_CITE.search(text or ""):
            violations.append({
                "line": i,
                "claim": stripped[:120],
                "triggers": ["knowledge_no_wiki_cite"],
                "fix": "Knowledge claim needs wiki_cite: <slug> or mtm-wiki-query cite (PFKT wiki_first_v3)",
            })
    return {"ok": len(violations) == 0, "n_violations": len(violations), "violations": violations}


def _run_tests() -> int:
    cases = [
        ("explain how hooks work", True),
        ("The file is at C:\\ai_workspace\\foo.py and it is fixed.", False),
        ("Shipped to production with 15 agents green.", False),
        ("Hypothesis (unverified): may be in hooks.json", True),
        ("unknown — check: grep pfkt in engines", True),
        ("verify: pytest -q passed rc=0", True),
        ("The lemma holds for all n. QED. verify: `pytest`", False),
        ("UNKNOWN whether the lemma holds for all n.", True),
        ("This proves the hook works as intended today.", True),
    ]
    fails = 0
    for text, want_ok in cases:
        got = lint_text(text)["ok"]
        ok = got == want_ok
        print("%s want_ok=%s text=%r" % ("PASS" if ok else "FAIL", want_ok, text[:50]))
        if not ok:
            fails += 1
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--text", default=None)
    ap.add_argument("--file", default=None)
    ap.add_argument("--hook", action="store_true")
    ap.add_argument("--taskfile", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="deny on violations")
    a = ap.parse_args()

    if a.test:
        return _run_tests()

    body = a.text or ""
    if a.taskfile and os.path.isfile(a.taskfile):
        body = open(a.taskfile, encoding="utf-8", errors="replace").read()
    elif a.file and os.path.isfile(a.file):
        body = open(a.file, encoding="utf-8", errors="replace").read()

    res = lint_text(body)
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res["ok"] else (2 if a.strict else 0)

    if res["ok"]:
        print("claim-linter: OK")
        return 0
    print("claim-linter: %d violations" % res["n_violations"])
    for v in res["violations"][:5]:
        print("  L%d [%s] %s" % (v["line"], ",".join(v["triggers"]), v["claim"][:80]))
    return 2 if a.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
