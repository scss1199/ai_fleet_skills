#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""f1s_audit.py — the ai_ut rederive pattern applied to F1S itself (operator 2026-10-13).

Scan the whole F1S architecture (rule texts, kernel, phase contract, claim contract, hooks, fleet
delivery), give every element a verdict the way ut_rederive_audit.py does (FORMALIZED / REFINE /
REDUNDANT / DELETE / INFO / CONTRADICTION), prove the formal part with Lean through leanctl, and bind
the proofs to the texts and the running hook by hash.  Exit 0 only when every Lean module is PROVED,
no element is left at CONTRADICTION, and the claim conformance receipt still matches the hook.

  python f1s_audit.py            # writes evidence/f1s-audit.json (machine receipt), prints the summary
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parents[1]
LEANCTL = HERE.parent / "leanctl.py"
OUT = HERE / "evidence" / "f1s-audit.json"
NW = 0x08000000 if os.name == "nt" else 0

MODULES = {
    "F1SCore": HERE / "F1SCore.lean",
    "ClaimContract": HERE / "ClaimContract.lean",
    "FamesKernel": HERE / "FamesKernel.lean",
}
TEXTS = {
    "hot_directive": HUB / "_registry" / "fames-protocol.json",
    "rules_blueprint": HUB / "_registry" / "rules-blueprint.json",
    "proof_config": HUB / "_registry" / "proof.json",
    "proof_hook": HUB / "_skill" / "engines" / "claude-proof-hook.py",
    "run_until_done_hook": HUB / "_skill" / "engines" / "claude-run-until-done-hook.py",
    "claim_conformance": HERE / "evidence" / "claim-conformance.json",
    "phase_conformance": HUB / "_registry" / "fames-phase-conformance.json",
}

# The architecture scan.  `requires` names the Lean theorem that must be PROVED for the verdict to stand;
# a REFINE row records what the kernel refuted and what the text now says.
ELEMENTS = [
    {"id": "R1-no-misread", "element": "① 不准曲解 (原話、不擴不縮、已決定不再問、結論先行)", "verdict": "FORMALIZED",
     "requires": "F1SCore.f1s_satisfiable", "detail": "rule1 in the satisfiable set"},
    {"id": "R1-details-in-file", "element": "① old wording 「細節放檔案」", "verdict": "REFINE",
     "requires": "F1SCore.rule1_old_vs_rule6_unsat",
     "detail": "Lean: no reply satisfies old ① and ⑥ together; wording changed to 「細節放回覆或既有收據，不新開 .md/.json」",
     "check_text": ("hot_directive", "細節放回覆或既有收據")},
    {"id": "R2-components", "element": "② 元件按需啟用 / Jev 只在挑選排序", "verdict": "FORMALIZED",
     "requires": "F1SCore.f1s_satisfiable",
     "detail": "jev_phase_advisor emits advice per phase but FamesKernel.jev_advice_cannot_change_admission proves it never admits; INFO: advice files are state under _registry"},
    {"id": "R3-musk", "element": "③ 馬斯克五步 先重用再寫", "verdict": "FORMALIZED", "requires": "F1SCore.f1s_satisfiable",
     "detail": "order violation modelled as automatedBeforeSimplified; measured 15 generations/day on 2026-10-12 (self-audit)"},
    {"id": "R4-evidence", "element": "④ 每個主張要有驗證否則 UNKNOWN", "verdict": "FORMALIZED",
     "requires": "F1SCore.honest_reply_not_blocked", "detail": "PROOF classes tests/pushed/committed/deployed/verified/completion/measurement"},
    {"id": "R5-lies-handback", "element": "⑤ 不准說謊、不准推託", "verdict": "FORMALIZED",
     "requires": "ClaimContract.handback_needs_red_line_or_failure",
     "detail": "read/progress/automated/blocker/handback admissible only on evidence; hand-back only on a red line or an observed failure"},
    {"id": "R5-decision", "element": "「需要你決定」 (old: only de-duplicated)", "verdict": "REFINE",
     "requires": "ClaimContract.decision_needs_operator_authority",
     "detail": "Lean F1SCore.model_step_never_a_decision: a decision on a model-mandatory action is never admissible; the hook now also requires the line to name an operator-reserved subject (red line / data loss)",
     "check_text": ("hot_directive", "需要你決定")},
    {"id": "R6-junk-files", "element": "⑥ 嚴禁隨意產出 .md/.json", "verdict": "FORMALIZED",
     "requires": "F1SCore.seal_receipts_allowed", "detail": "SEAL receipts, _registry state and charters allowed; reports/notes/summaries/memory prose are junk (F1SCore.reports_are_junk)"},
    {"id": "H-hook-policy", "element": "hooks 只提示不阻擋 (例外 proof, run-until-done), fail-open", "verdict": "FORMALIZED",
     "requires": "F1SCore.only_two_hooks_block", "detail": "a crashed hook allows; no other hook returns block"},
    {"id": "H-block-budget", "element": "PROOF / run-until-done block budget 2 per turn, 12 per session", "verdict": "FORMALIZED",
     "requires": "F1SCore.blocks_bounded", "detail": "liveness: a turn cannot be pushed back forever"},
    {"id": "H-soundness", "element": "PROOF block always names a violated clause", "verdict": "FORMALIZED",
     "requires": "F1SCore.blocked_implies_violation", "detail": "no block without ④⑤⑥ violation in the model; corpus test binds the regexes"},
    {"id": "A-who-does-what", "element": "T1 禁止問 operator (ZCT) vs 紅線/授權 (operator steps)", "verdict": "REFINE",
     "requires": "F1SCore.operator_model_disjoint",
     "detail": "the 2026-06-24 text listed 「權限/oauth」 as mechanical: refined to 憑證檢查=model, 互動式 OAuth 登入=operator; T1 授權 now records the 2026-10-13 authorization for F1S hook wiring on every host",
     "check_text": ("rules_blueprint", "互動式 OAuth")},
    {"id": "A-global-settings", "element": "T1 授權: ~/.claude 全域設定變更需授權 vs package wiring Stop hooks on every host", "verdict": "REFINE",
     "requires": "F1SCore.operator_model_disjoint",
     "detail": "authorized by operator 2026-10-13 「套用到所有對話與裝置」; recorded in the 授權 rule so the wiring is not a silent violation",
     "check_text": ("rules_blueprint", "F1S hook")},
    {"id": "K-phase-order", "element": "FamesKernel: FP→MTM→SCF→AEX→SEAL, fail closed, hard residuals", "verdict": "FORMALIZED",
     "requires": "Fames.runOk_iff", "detail": "bound to fames_fleet.validate_run by conformance.py"},
    {"id": "K-phase-contract", "element": "FamesPhaseContract: SCF needs verified result, SEAL needs closed graph", "verdict": "INFO",
     "requires": None, "detail": "bound by phase_conformance.py (_registry/fames-phase-conformance.json); not re-proved here"},
    {"id": "C-claim-admission", "element": "ClaimContract: 8 classes × 512 evidence vectors bound to claude-proof-hook.admissible", "verdict": "FORMALIZED",
     "requires": "ClaimContract.admissible_mono", "detail": "claim_conformance.py receipt, 0 mismatches"},
    {"id": "F-fleet", "element": "F1S delivery: package runtime-sources → install → sync-cursor-hooks wires Stop hooks", "verdict": "INFO",
     "requires": None, "detail": "darkhero + altos PASS at generation 2026-10-13.2; scar3 UNKNOWN (receiver stalled at 1.45.14, no channel)"},
    {"id": "R-close-when-done", "element": "close-when-done archive_session vs run-until-no-next-step", "verdict": "FORMALIZED",
     "requires": "F1SCore.f1s_satisfiable", "detail": "both hold in the exemplar; archive only when no next step"},
    {"id": "R-memory", "element": "feedback memory as the carrier of F1S (f1s-forbidden-errors.md)", "verdict": "REDUNDANT",
     "requires": None, "detail": "operator: 存記憶沒用; the carrier is the hook + Lean + sweep; the memory stays as a pointer only"},
{"id": "KB-ponytail-reuse", "element": "kyloren_bot cea9bf31 (threads 2026-10-02): ask whether new code is needed; reuse order; smaller diffs; never drop validation/security", "verdict": "FORMALIZED",
     "requires": "ClaimContract.code_change_needs_prior_search", "detail": "already ③ text; now mechanical: PROOF class code_change (code written with no prior grep/glob/find in the turn)"},
    {"id": "KB-brownfield-search", "element": "kyloren_bot 89f0cb75 (youtube 2026-07-21): before handing any line to AI, global-search the hook / usages", "verdict": "FORMALIZED",
     "requires": "F1SCore.blocked_implies_violation", "detail": "same class code_change; F1SCore rule3 gains codeChangeWithoutSearch and PROOF judges it"},
    {"id": "KB-context-trim", "element": "kyloren_bot 96e6934e: trim conversation context, reuse cache", "verdict": "INFO",
     "requires": None, "detail": "AGC / MTM already; sweep now reports tool calls per turn per seat (churn) in F1S RECORD"},
    {"id": "KB-knows-when-unknown", "element": "kyloren_bot 6e8ec744: prefer an AI that knows when it does not know over confident flip-flop", "verdict": "FORMALIZED",
     "requires": "F1SCore.f1s_satisfiable", "detail": "④ UNKNOWN rule; sweep counts 「你說得對」 flip-flop openers per seat"},
    {"id": "KB-decide-with-data", "element": "kyloren_bot 3030cf47: decide by probability, control false positives / negatives with data", "verdict": "INFO",
     "requires": None, "detail": "sweep adds proof_remediation: blocks, fixed-next-push rate, re-blocked, budget-exhausted — the gate's own false-positive control"},
    {"id": "KB-jev-rerank", "element": "kyloren_bot 242a89be: Jev as a reranker beats specialised rerankers", "verdict": "INFO",
     "requires": None, "detail": "consistent with ② (Jev only to choose / rank); no change"},
    {"id": "KB-unlimited-token", "element": "kyloren_bot c18d2b35 / 3ebcbcdc / bd3e87d5 (IG 2026-09-09/13/28): 無限量使用 Claude Code — route to free providers when quota runs out (OmniRoute / FreeLLMAPI)", "verdict": "FORMALIZED",
     "requires": "F1SCore.f1s_satisfiable", "detail": "reused, not written: OmniRoute 3.8.51 (MIT) headless on 127.0.0.1:20128, 11 vault connections, claude-remote-exec lane=auto falls back on quota/auth failure (test_remote_exec_gateway_lane); persistence proposed in _inbox (operator arms)",
     "check_text": ("hot_directive", "OmniRoute")},
    {"id": "KB-claw-md", "element": "kyloren_bot 04171cf7 (IG 2026-10-14): Claw.md — think before writing, ask when unsure, simplest first, precise edits, define done + verify", "verdict": "INFO",
     "requires": None, "detail": "already ①③④⑤ (嚴禁猜, 先重用, verify before done); the precise-edit rule (touch only the requested lines) has no mechanical check yet"},
    {"id": "TH-tdd", "element": "threads @nashlikeai 2026-10-14 (skills.sh top list): tdd — 先寫測試再寫程式，避免改 A 壞 B", "verdict": "FORMALIZED",
     "requires": "ClaimContract.fix_claim_needs_test_after_write", "detail": "PROOF class fix_claim: 「修好/fixed」 after a code write needs a green test after the LAST write; F1SCore rule4 gains fixWithoutRegressionTest (tdd_inside_rule4)"},
    {"id": "TH-grill-me", "element": "threads @nashlikeai: grill-me — AI 一直追問你直到搞懂", "verdict": "REFINE",
     "requires": "F1SCore.grill_me_reask_inadmissible", "detail": "refuted as written (unbounded operator questioning contradicts ① 選最貼近原話直接做 and the one-time, red-line-only decision rule); kept as self-interrogation: grill-with-docs = search repo/docs first (ClaimContract.ask_value_needs_search)"},
    {"id": "TH-grill-with-docs", "element": "threads @nashlikeai: grill-with-docs — 把文件丟給 AI 找規格漏洞", "verdict": "FORMALIZED",
     "requires": "ClaimContract.ask_value_needs_search", "detail": "the model interrogates the docs, not the operator; FP binds goal/authority/acceptance"},
    {"id": "TH-handoff", "element": "threads @nashlikeai: handoff — 換 Agent 時整理進度交接", "verdict": "REDUNDANT",
     "requires": None, "detail": "already AGC compact + goal_compact park + seat CLAUDE.md compact instructions"},
    {"id": "TH-triage", "element": "threads @nashlikeai: triage — Bug 分類排優先順序", "verdict": "REDUNDANT",
     "requires": None, "detail": "② Jev only to choose / rank; no new mechanism"},
    {"id": "TH-find-skills", "element": "threads @nashlikeai: find-skills — 幫 AI 找技能（安裝量第一）", "verdict": "REDUNDANT",
     "requires": None, "detail": "MTM local_skill_router + host catalog discovery already route skills per prompt; reply under the post (明年都不需要) and ③ delete: no new skills installed"},
    {"id": "H-code-change-scratch", "element": "code_change class counted session scratch scripts (scratchpad / Temp) as brownfield code", "verdict": "REFINE",
     "requires": "ClaimContract.code_change_needs_prior_search", "detail": "false positive found 2026-10-14 (a scratch parser for the Threads page); scratch paths no longer start the search-before-write clock"},
    {"id": "KB-noise", "element": "kyloren_bot cards 31019056, e904d45b, f1047cdb, dbea9c8c, a199503d, 3776cbe2, c18d2b35, e7c5cba9, 44b1a930 (IG reels, ASR noise / promos)", "verdict": "DELETE",
     "requires": None, "detail": "no implementable content beyond what ③ already says (fewer lines, reuse); nothing fused"},
]


def sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "MISSING"


def lean(path: Path, out: Path) -> dict:
    cmd = [sys.executable, str(LEANCTL), "--ascii", "check", "--file", str(path), "--timeout", "600", "--out", str(out)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=900, creationflags=NW)
        doc = json.loads(proc.stdout.decode("utf-8", "replace"))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"verdict": "GATE_ERROR", "error": type(exc).__name__, "theorems": []}
    theorems = [t.get("name") for t in ((doc.get("audit") or {}).get("theorems") or [])
                if isinstance(t, dict) and not t.get("synthetic")]
    return {"verdict": doc.get("verdict"), "elapsed_s": doc.get("elapsed_s"), "theorems": theorems,
            "cautions": len(doc.get("cautions") or []), "receipt": str(out)}


def text_has(key: str, needle: str) -> bool:
    try:
        return needle in TEXTS[key].read_text(encoding="utf-8-sig")
    except (OSError, KeyError):
        return False


def main() -> int:
    started = time.time()
    proofs = {}
    for name, path in MODULES.items():
        proofs[name] = lean(path, HERE / "evidence" / f"{name}.receipt.json")
    proved = {t for p in proofs.values() for t in p["theorems"]}
    rows = []
    unresolved = 0
    for el in ELEMENTS:
        row = dict(el)
        req = el.get("requires")
        if req:
            full = req if req.startswith("Fames.") else "Fames." + ("F1S." + req[8:] if req.startswith("F1SCore.") else req)
            row["lean_theorem"] = full
            row["lean_ok"] = full in proved
            if not row["lean_ok"]:
                row["verdict"] = "CONTRADICTION"
        chk = el.get("check_text")
        if chk:
            row["text_ok"] = text_has(*chk)
            if not row["text_ok"]:
                row["verdict"] = "CONTRADICTION"
        row.pop("check_text", None)
        if row["verdict"] == "CONTRADICTION":
            unresolved += 1
        rows.append(row)
    try:
        conf = json.loads(TEXTS["claim_conformance"].read_text(encoding="utf-8-sig"))
        conf_ok = bool(conf.get("ok")) and conf["bound"]["hook"]["sha256"] == sha(TEXTS["proof_hook"]) \
            and conf["bound"]["lean_file"]["sha256"] == sha(MODULES["ClaimContract"])
    except (OSError, ValueError, KeyError):
        conf_ok = False
    ok = all(p["verdict"] == "PROVED" for p in proofs.values()) and unresolved == 0 and conf_ok
    doc = {
        "schema": "f1s-audit/1", "ok": ok, "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(time.time() - started, 1), "pattern": "ai_ut/ut_theory/rederive",
        "proofs": proofs, "claim_conformance_current": conf_ok, "unresolved": unresolved,
        "verdict_counts": {v: sum(1 for r in rows if r["verdict"] == v) for v in sorted({r["verdict"] for r in rows})},
        "elements": rows,
        "bound": {k: {"path": str(p), "sha256": sha(p)} for k, p in {**MODULES, **TEXTS}.items()},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"ok": ok, "proofs": {k: (v["verdict"], len(v["theorems"])) for k, v in proofs.items()},
                      "verdicts": doc["verdict_counts"], "claim_conformance_current": conf_ok, "unresolved": unresolved},
                     ensure_ascii=False))
    for r in rows:
        if r["verdict"] in {"CONTRADICTION", "REFINE"}:
            print(" ", r["verdict"], r["id"], "-", r["detail"][:110])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
