#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""f1s_audit.py — the ai_ut rederive pattern applied to F1S itself (operator 2026-10-13).

Scan the whole F1S architecture (rule texts, kernel, phase contract, claim contract, hooks, fleet
delivery), give every element a verdict the way ut_rederive_audit.py does (FORMALIZED / REFINE /
REDUNDANT / DELETE / INFO / CONTRADICTION), prove the formal part with Lean through leanctl, and bind
the proofs to the texts and the running hook by hash.  Exit 0 only when every Lean module is PROVED,
no element is left at CONTRADICTION, and the claim conformance receipt still matches the hook.

  python f1s_audit.py            # writes evidence/f1s-audit.json (machine receipt), prints the summary
  python f1s_audit.py --force    # re-prove every module even when its .lean hash is unchanged
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
    "skill_intake": HUB / "_skill" / "fleet-skills" / "f1s-intake" / "SKILL.md",
    "skill_method": HUB / "_skill" / "fleet-skills" / "mtm-mto-first" / "SKILL.md",
    "skill_verify": HUB / "_skill" / "fleet-skills" / "ztm-verify-before-done" / "SKILL.md",
    "skill_login": HUB / "_skill" / "fleet-skills" / "browser-login-handoff" / "SKILL.md",
    "skill_rea": HUB / "_skill" / "fleet-skills" / "rea-reverse-engineering" / "SKILL.md",
    "skill_ui": HUB / "_skill" / "fleet-skills" / "web-ui-taste" / "SKILL.md",
    "skill_reverse": HUB / "_skill" / "fleet-skills" / "f1s-reverse-learning" / "SKILL.md",
    "skill_atlas": HUB / "_skill" / "fleet-skills" / "web-page-atlas" / "SKILL.md",
    "skill_gas": HUB / "_skill" / "fleet-skills" / "gas-google-sso-webapp" / "SKILL.md",
    "skill_mto": HUB / "_skill" / "fleet-skills" / "mtm-mto-first" / "SKILL.md",
    "skill_runtime": HUB / "_skill" / "fleet-skills" / "windows-runtime-pitfalls" / "SKILL.md",
    "harvest_engine": HUB / "_skill" / "engines" / "f1s-harvest.py",
    "skill_apikey": HUB / "_skill" / "fleet-skills" / "api-key-apply" / "SKILL.md",
    "ui_lint": HUB / "_skill" / "engines" / "ui-guideline-lint.py",
    "skill_review": HUB / "_skill" / "fleet-skills" / "independent-review" / "SKILL.md",
    "skill_fleet_github": HUB / "_skill" / "fleet-skills" / "mtm-fleet-skill-github" / "SKILL.md",
    "omniroute_engine": HUB / "_skill" / "engines" / "omniroute-gateway.py",
    "session_hook": HUB / "_skill" / "fleet-skills" / "token-preflight" / "scripts" / "claude_session_hook.py",
    "skill_pool": HUB / "_skill" / "fleet-skills" / "mtm-api-pool-offload" / "SKILL.md",
    "skill_lean": HUB / "_skill" / "fleet-skills" / "lean-math-prover" / "SKILL.md",
    "distill_url": HUB / "_skill" / "engines" / "distill-url.py",
    "websearch_engine": HUB / "_skill" / "engines" / "websearch.py",
    "skill_preflight": HUB / "_skill" / "fleet-skills" / "token-preflight" / "SKILL.md",
    "git_smart": HUB / "_skill" / "engines" / "git_smart.py",
    "llm_engine": HUB / "_skill" / "engines" / "_llm.py",
    "load_guard": HUB / "ai_darkhero" / "tray" / "scripts" / "load_guard.py",
    "skill_jci_transfer": HUB / "_skill" / "fleet-skills" / "jci-drive-line-web-transfer" / "SKILL.md",
    "skill_line_ingest": HUB / "_skill" / "fleet-skills" / "line-oa-ingest" / "SKILL.md",
    "zat_verify_gate": HUB / "_skill" / "engines" / "zat-verify-gate.py",
    "fames_fleet": HUB / "_skill" / "fleet-skills" / "fames" / "scripts" / "fames_fleet.py",
    "pickup_verify": HUB / "_skill" / "engines" / "fleet-session-pickup-verify.py",
    "skill_agc": HUB / "_skill" / "fleet-skills" / "agc-auto-goal-compact" / "SKILL.md",
    "evolve_engine": HUB / "_skill" / "engines" / "f1s-evolve-tick.py",
    "skill_deploy_cf": HUB / "_skill" / "fleet-skills" / "deploy-nextjs-cloudflare" / "SKILL.md",
    "skill_sync_engine": HUB / "_skill" / "engines" / "fleet-skill-sync.py",
    "bus_engine": HUB / "_skill" / "engines" / "_bus.py",
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
     "requires": None, "detail": "already ①③④⑤ (嚴禁猜, 先重用, verify before done); since 2026-10-15 the precise-edit rule is skill text in mtm-mto-first (精準修改); still no mechanical check",
     "check_text": ("skill_method", "精準修改")},
    {"id": "KB-review-step", "element": "kyloren_bot IG DeRQeVDHdBH: Superpowers / Addy Osmani skills — code review before done", "verdict": "REFINE",
     "requires": None, "detail": "ztm-verify-before-done now routes non-trivial code changes to independent-review (generator is never its own sole judge)",
     "check_text": ("skill_verify", "independent-review")},
    {"id": "OP-login-handoff", "element": "operator 2026-10-15: make the sign-in flow an F1S built-in skill (claude.ai credit claim asked twice while the Browser pane was hidden)", "verdict": "REFINE",
     "requires": None, "detail": "skill browser-login-handoff: reuse a browser-free path first, probe the real signed-in state, check pane visibility (Ctrl+Shift+B) and hand off once; login stays the operator's step",
     "check_text": ("skill_login", "Ctrl+Shift+B")},
    {"id": "OP-login-pointer", "element": "hot_directive names the login skill", "verdict": "REFINE",
     "requires": None, "detail": "per-turn pointer so every conversation routes sign-ins through the skill",
     "check_text": ("hot_directive", "browser-login-handoff")},
    {"id": "OP-login-in-pane", "element": "operator 2026-10-16: 「技能裡面的方法就是要你自己在claude內部的瀏覽器一次搞定並記住全部內容不需要跟我外部的windows chrome瀏覽器存資料」", "verdict": "REFINE",
     "requires": None, "detail": "browser-login-handoff 4b: OAuth consent is completed by the agent in the built-in browser via the same-tab consent URL; only password/MFA goes to the user; clasp's client is blocked for sensitive scopes, use an owner Apps Script bridge",
     "check_text": ("skill_login", "同一個分頁")},
    {"id": "KB-rea", "element": "kyloren IG DefkUKkFA8D (2026-10-16): REA — one MCP that lets Claude Code / Codex / Cursor reverse engineer binaries, Electron/JS apps, APKs and sites (morluto/rea, MIT)", "verdict": "REFINE",
     "requires": None, "detail": "on-demand skill rea-reverse-engineering: npx rea-agents@6.5.0 (provenance checked: repo morluto/rea), no `setup` (would write ~/.claude.json = operator authorization), own/authorised software only, output to scratchpad; live run on _skill/fleet-fly-hooks rc=0, global config untouched",
     "check_text": ("hot_directive", "rea-reverse-engineering")},
    {"id": "KB-web-ui-taste", "element": "kyloren IG DeicLoFhs5O (2026-10-16): five Claude Code web-design tools — Taste Skill, Vercel Web Design Guidelines, Awesome Design (DESIGN.md), Image to Code, Playwright CLI", "verdict": "REFINE",
     "requires": None, "detail": "skill web-ui-taste chains design system -> taste -> image-to-code -> ui-guideline-lint -> phone+desktop screenshots in the built-in browser (no Playwright install); trial on the accountancy app: 53 -> 0 findings, plus a header collapse only the screenshot step caught",
     "check_text": ("hot_directive", "web-ui-taste")},
    {"id": "KB-web-ui-lint", "element": "Vercel Web Interface Guidelines rules decidable from source text", "verdict": "REFINE",
     "requires": None, "detail": "mechanical check ui-guideline-lint.py (9 rules, tests in test_ui_guideline_lint.py); judgement rules stay in the skill",
     "check_text": ("ui_lint", "no-reduced-motion")},
    {"id": "OP-reverse-learning", "element": "operator 2026-10-16: 「把他們各自用到的所有技能 經驗 系統 api 整合會到f1s 使得f1s直接建立一個從各cwd反向學習的機制」", "verdict": "REFINE",
     "requires": None, "detail": "skill f1s-reverse-learning + f1s-harvest.py: harvest skills/memory/tools/APIs from every cwd (never fracdigi/quant), best-single-document coverage, free-pool triage, self-updating goals.json",
     "check_text": ("hot_directive", "f1s-reverse-learning")},
    {"id": "OP-reverse-goals", "element": "operator 2026-10-16: 「讓這個對話的f1s能夠維持長任務自己找目標自己更新目標」", "verdict": "REFINE",
     "requires": None, "detail": "f1s-harvest cycle recomputes goals.json every run; mark needs evidence and settles a whole cross-seat goal",
     "check_text": ("harvest_engine", "def cycle")},
    {"id": "RL-runtime-pitfalls", "element": "reverse-learned from ai_trader / hub-root memories: SO_REUSEADDR multibind, RST before body read, AccessDenied != dead, retry storms, stale index.lock, clock skew", "verdict": "REFINE",
     "requires": None, "detail": "new skill windows-runtime-pitfalls, routed from the hot directive",
     "check_text": ("skill_runtime", "allow_reuse_address = False")},
    {"id": "RL-api-before-integrate", "element": "reverse-learned API lessons: provider limits, pooled token expiry, client_credentials reissue; fleet API catalog", "verdict": "REFINE",
     "requires": None, "detail": "api-key-apply section 接外部 API 前 + f1s-harvest.py api <service>",
     "check_text": ("skill_apikey", "f1s-harvest.py api")},
    {"id": "RL-promote-atlas", "element": "reverse-learned from ai_trader: web-page-atlas (self-improving site map)", "verdict": "REFINE",
     "requires": None, "detail": "promoted to canonical with a fleet-shared _registry/web-atlas store; never store credentials there",
     "check_text": ("skill_atlas", "_registry/web-atlas")},
    {"id": "RL-promote-gas", "element": "reverse-learned from ai_accountancy: gas-google-sso-webapp", "verdict": "REFINE",
     "requires": None, "detail": "promoted to canonical with the 2026-10-16 GAS lessons (trash before rebuild, DEFAULT_SS_ID, same-tab consent, bridge)",
     "check_text": ("skill_gas", "不要先重建")},
    {"id": "RL-tools-catalog", "element": "seat tools integrated as a reuse-before-write catalog", "verdict": "REFINE",
     "requires": None, "detail": "f1s-harvest.py tools <query>; mtm-mto-first: search other seats before writing a new tool",
     "check_text": ("skill_mto", "f1s-harvest.py tools")},
    {"id": "SEAT-ut-completion-order", "element": "ai_ut SUBMIT f1s-ut-intake (2026-10-15): completion order 原話 → 也=上一輪流程 → 使用者來源 → 可推出 → UNKNOWN; 全部=先列全集", "verdict": "REFINE",
     "requires": None, "detail": "f1s-intake §1 補完順序; ai_ut Lean f1s_completion_iff / f1s_underdetermined PROVED in its seat",
     "check_text": ("skill_intake", "補完順序")},
    {"id": "SEAT-ut-submit-filekind", "element": "ai_ut: F1SCore FileKind lacked SUBMIT, so charter-required hand-offs modelled as junk under ⑥", "verdict": "FORMALIZED",
     "requires": "F1SCore.submit_allowed", "detail": "FileKind.submit added and allowed; matches claude-proof-hook md_allowed_dirs _inbox"},
    {"id": "OP-run-here", "element": "operator 2026-10-16: 「以後f1s架構遇到 \"在這裡執行此任務\" 直接執行不要等」", "verdict": "REFINE",
     "requires": None, "detail": "hot_directive: a 「在這裡執行此任務：…」 prompt is an approval — start at once, no confirmation, no offer card",
     "check_text": ("hot_directive", "在這裡執行此任務")},
    {"id": "KB-rea-pin", "element": "REA skill pins the verified package version", "verdict": "REFINE",
     "requires": None, "detail": "version pinned; upgrades re-check npm repository.url first",
     "check_text": ("skill_rea", "rea-agents@6.5.0")},
    {"id": "LAB-review-triage", "element": "kyloren_bot bb489c62 (凱羅實驗室, OpenCoreReview): triage hunks by risk/category before review, ~1/9 tokens", "verdict": "REFINE",
     "requires": None, "detail": "independent-review step 2 now triages hunks and records what was triaged out",
     "check_text": ("skill_review", "triage before reviewing")},
    {"id": "LAB-mechanical-not-prose", "element": "kyloren_bot 83845712 (Uncle Bob): long rule documents are treated as suggestions; enforce with deterministic gates", "verdict": "REFINE",
     "requires": None, "detail": "ztm-verify-before-done: a repeated mistake gets a mechanical check (test/lint/dependency rule/hook class), not more prose; mutation tests optional",
     "check_text": ("skill_verify", "機械檢查")},
    {"id": "LAB-model-cache", "element": "kyloren_bot b7b4e052: thinking/cache bind to model and prior context; xhigh runaway", "verdict": "REFINE",
     "requires": None, "detail": "mtm-mto-first: switch model/effort only at a new-conversation boundary, no volatile data in the system prompt, unattended xhigh/max runs state a budget first",
     "check_text": ("skill_method", "新對話的邊界")},
    {"id": "LAB-browser-batch", "element": "kyloren_bot bac266b7: shared browser, one script for many steps, isolated agent spaces", "verdict": "REFINE",
     "requires": None, "detail": "mtm-mto-first: batch predictable browser steps; parallel agents get their own tab",
     "check_text": ("skill_method", "browser_batch")},
    {"id": "LAB-context-mode", "element": "kyloren_bot 053de955 (context-mode): raw tool output stays out of context; edit/git log survives compaction", "verdict": "REFINE",
     "requires": None, "detail": "large outputs stay in files (mtm-mto-first); the edit log part is REDUNDANT: the fleet idle sweeper commits tracked changes within ~20 min, so git log already is the post-compaction record",
     "check_text": ("skill_method", "大型工具輸出")},
    {"id": "LAB-resident-audit", "element": "kyloren_bot 7b4adc46, 003a6bd3: /doctor, /skill-doctor, 1M-context switch", "verdict": "REFINE",
     "requires": None, "detail": "token-preflight: measure resident context and join with skill-audit logs before pruning; the 1M switch is a global-settings change (operator) and not applied",
     "check_text": ("skill_preflight", "Resident context audit")},
    {"id": "LAB-provenance", "element": "kyloren_bot 7180a9a7 (git-ai): review sees only the diff; record who wrote it and how it was checked", "verdict": "REFINE",
     "requires": None, "detail": "git_smart commits carry Writer / Host / Session trailers, plus Why / Verified-By when given (test_provenance_trailers)",
     "check_text": ("git_smart", "Verified-By")},
    {"id": "LAB-jev-thresholds", "element": "kyloren_bot DdfUWJHE5Mc, 62de1f17: Jev choice/score/noul with confidence; high confidence auto, low to a human, high risk to review", "verdict": "REFINE",
     "requires": None, "detail": "advice-never-admits is FamesTurnRecovery.jev_advice_cannot_change_admission (bound by its own conformance, not re-proved here); fames-protocol jev.decision_policy: at/above calibrated threshold = selection advice, below = model judgment, red-line candidates = operator; thresholds NOT_MEASURED",
     "check_text": ("hot_directive", "decision_policy")},
    {"id": "LAB-declined", "element": "kyloren_bot 25bdd6af (hidden env vars), c9151869 (ELI5 visual skill), Dc_HbaOkg7- (GPT-6 Astra 8 fixes)", "verdict": "INFO",
     "requires": None, "detail": "env-var audit = global settings (operator); ELI5 is a content skill, not a harness rule; Astra's ask-back/stop-halfway fixes are already run-until-no-next-step + ask-once (slide text not captured)"},
    {"id": "LAB-noise", "element": "33 kyloren_bot notes: own LINE-to-Cursor cloud_rest failures (branch main missing, SCM access, 429, OOM guard), 2026-07-21..08-31", "verdict": "DELETE",
     "requires": None, "detail": "bridge fixed to each repo's real branch in hub 2b861cc8 (2026-09-27); no later failures in the archive"},
    {"id": "OP-agc-pointer", "element": "operator 2026-10-15: is auto-compaction (AGC) part of F1S?", "verdict": "REFINE",
     "requires": None, "detail": "AGC already ran as a hook lane; the per-turn hot_directive now names skill agc-auto-goal-compact",
     "check_text": ("hot_directive", "agc-auto-goal-compact")},
    {"id": "OP-seat-sessions-detached", "element": "operator 2026-10-15 screenshot: ai_trader sessions nested under the curator conversation", "verdict": "REFINE",
     "requires": None, "detail": "sessions opened for another seat are detached to top level right after start_session",
     "check_text": ("hot_directive", "detach")},
    {"id": "OP-follower-sync", "element": "operator 2026-10-15: follower HubClock must sync with GitHub by itself", "verdict": "REFINE",
     "requires": None, "detail": "skill mtm-fleet-skill-github: converge + dispatch + sync + omniroute-ensure riders; acceptance = an unattended probe answer at the new version (scar3 1.45.30 in 251 s)",
     "check_text": ("skill_fleet_github", "自動回應")},
    {"id": "OP-omniroute-setup", "element": "OmniRoute first-run on a follower was a hand-typed 2026-10-14 recipe", "verdict": "REFINE",
     "requires": None, "detail": "omniroute-gateway.py setup: admin pw, machine-local keys via stdin, access token minted into the vault (test_omniroute_setup)",
     "check_text": ("omniroute_engine", "def setup(")},
    {"id": "OP-coevolve-down", "element": "operator 2026-10-15: F1S upgrades must reach long conversations in every cwd mid-task, without being asked", "verdict": "REFINE",
     "requires": None, "detail": "claude_session_hook PostToolUse fast path: stat() of protocol/T1/package; on change, hot_refresh + T1/charter diffs injected mid-turn (test_midturn_refresh)",
     "check_text": ("session_hook", "F1S MID-TURN UPDATE")},
    {"id": "OP-coevolve-up", "element": "operator 2026-10-15: a breakthrough in any cwd upgrades F1S back", "verdict": "REFINE",
     "requires": None, "detail": "inbox 'F1S:' proposals -> f1s-evolve-tick: one headless curator turn, then mechanical gates (T1 diff empty, f1s_audit ok, tests green) before ship-f1s (test_f1s_evolve_tick)",
     "check_text": ("hot_directive", "f1s-evolve")},
    {"id": "OP-free-pool-research", "element": "operator 2026-10-15: free models do background search / ASR / OCR for every seat, skill-bound and automatic", "verdict": "REFINE",
     "requires": None, "detail": "skill mtm-api-pool-offload rewritten around distill-url --search, distill-media --engine local, image_ocr.py CLI; hot_directive routes every cwd to it; live: search 7 s with sources, OCR read a screenshot",
     "check_text": ("hot_directive", "mtm-api-pool-offload")},
    {"id": "OP-free-model-labels", "element": "operator 2026-10-15: bind each free model to its strengths and label it in the F1S skills", "verdict": "REFINE",
     "requires": None, "detail": "measured probe (2 rounds x summary/extract/reasoning): gemini default, omniroute auto/reasoning for reasoning, auto/coding fallback; auto/fast, auto/writing, nvidia-nim not routed; bound in _llm.Pool.chat_for (test_llm_task_routes)",
     "check_text": ("skill_pool", "chat_for")},
    {"id": "SEAT-search-field-report", "element": "ai_ut + ai_trader 2026-10-15 field use: 9 free-pool searches, 1 usable (DDG 0 hits, Bing unrelated, ck/a links, cp950 crash, taifex skipped as x.com, header regex ate tables)", "verdict": "REFINE",
     "requires": None, "detail": "websearch: gemini grounding first backend, Bing ck/a decode, relevance filter, exact-domain wall check, \\b on the head strip; distill-url: utf-8 stdout, reader escalation under 800 chars; webops_auto logs to stderr (test_websearch_fixes)",
     "check_text": ("skill_pool", "gemini Google 搜尋")},
    {"id": "SEAT-search-chain-20261016", "element": "ai_trader 2026-10-16 audit: gemini keys 429/429/404 (2.5-flash closed to new users) swallowed as [], DDG 192/192 errors, Bing 0/96 valid, Google News RSS 96/96 answered", "verdict": "REFINE",
     "requires": None, "detail": "websearch: each key walks GEMINI_MODELS (2.5-flash, flash-latest, flash-lite-latest); _b_gemini raises the HTTP codes and search() keeps them in LAST_ERRORS + stderr; keyless _b_gnews second backend (test_websearch_fixes; live 2026-10-16: gemini all 429 recorded, gnews answered)",
     "check_text": ("skill_pool", "websearch.LAST_ERRORS")},
    {"id": "SEAT-search-cjk-relevance", "element": "ai_zonghe 2026-10-16: gemini 2.5-flash 404 + flash-latest/3.8-flash 429 on all keys, DDG timeouts, Bing 10 unrelated hits for a Chinese TCM query passed the filter", "verdict": "REFINE",
     "requires": None, "detail": "gemini/DDG parts already covered by SEAT-search-chain-20261016; new: websearch._tokens matches CJK as bigrams, so one shared common hanzi no longer passes _relevant (test_cjk_relevance_needs_a_shared_bigram_not_one_hanzi)",
     "check_text": ("websearch_engine", "CJK as bigrams")},
    {"id": "SEAT-digest-scope", "element": "ai_trader 2026-10-15: free-pool digest generalised a 4-contract, nearest-2-month, regular-session day-trade margin rule into a universal one", "verdict": "REFINE",
     "requires": None, "detail": "distill-url DIGEST_SYSTEM: rules/fees/margins/discounts keep their scope (contracts, months, session, exceptions); unclear scope -> 適用範圍見原文",
     "check_text": ("distill_url", "不可把限定規則概括成通用規則")},
    {"id": "OP-omniroute-zero-foreground", "element": "scar3 2026-10-15: DETACHED_PROCESS voided CREATE_NO_WINDOW (visible terminal) and 3.8.51 bound 0.0.0.0", "verdict": "REFINE",
     "requires": None, "detail": "omniroute-gateway start: CREATE_NO_WINDOW | new group only, node + omniroute.mjs directly, OMNIROUTE_SERVER_HOST=127.0.0.1 (listening 127.0.0.1:20128 verified)",
     "check_text": ("omniroute_engine", "OMNIROUTE_SERVER_HOST")},
    {"id": "KB-jev-local-models", "element": "operator paste 2026-10-15: official Jev SDK/skill, autotrust JEV-9B/27B open weights, System One Adapter", "verdict": "INFO",
     "requires": None, "detail": "not adopted: SDK/skill need the paid key; autotrust needs >=18 GB NVIDIA (A770 16 GB is reserved for T2I/I2V and tied to power resets) and speaks /v1/decide; the adapter over a generic LLM loses calibration, so it adds nothing over model judgment"},
    {"id": "KB-line-cli", "element": "kyloren_bot cbaf7d43 (Threads 2026-10-14): a skill wrapping line-cli (LINE in the terminal via the Chrome LINE extension)", "verdict": "INFO",
     "requires": None, "detail": "not adopted: it drives the operator's personal LINE login through a third-party tool (secret/login red line); line-oa-ingest stays the LINE route"},
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
    {"id": "KB-skills-how", "element": "kyloren_bot IG DeRQeVDHdBH (2026-10-09, 15 skills): prompt says what, skills teach how", "verdict": "REFINE",
     "requires": None, "detail": "wave 1 (2026-10-15): hot_directive 1399 -> 548 chars, the how of ① moved to skill f1s-intake",
     "check_text": ("skill_intake", "原話綁定")},
    {"id": "KB-skills-method", "element": "③ Musk five steps / reuse order / brownfield search / precise edits as skill text", "verdict": "REFINE",
     "requires": None, "detail": "moved from hot_directive into mtm-mto-first; PROOF code_change still judges it",
     "check_text": ("skill_method", "F1S ③")},
    {"id": "KB-skills-verify", "element": "④⑤⑥ evidence / no lying / no junk files as skill text", "verdict": "REFINE",
     "requires": None, "detail": "moved from hot_directive into ztm-verify-before-done; PROOF Stop hook still judges it",
     "check_text": ("skill_verify", "F1S ④⑤⑥")},
    # operator 2026-10-15: absorb aiposthub mattpocock/skills guide into F1S, strict review of .md/.json necessity
    {"id": "MP-file-necessity", "element": "mattpocock/skills: knowledge kept as repo .md files (GLOSSARY, ADR, docs/agents, tickets, research, specs)", "verdict": "REFINE",
     "requires": None, "detail": "⑥ gains a three-part file-necessity test (named or read back mechanically / no existing store / not a summary); those files fail (b) here",
     "check_text": ("skill_verify", "檔案必要性三條全成立")},
    {"id": "MP-diagnosing-bugs", "element": "mattpocock diagnosing-bugs: red reproduction, one falsifiable hypothesis, tagged debug logs, regression test", "verdict": "REFINE",
     "requires": None, "detail": "new 修 bug section in ztm-verify-before-done; PROOF fix_claim still judges the regression test",
     "check_text": ("skill_verify", "## 修 bug")},
    {"id": "MP-code-review-axes", "element": "mattpocock code-review: standards and spec as separate review axes", "verdict": "REFINE",
     "requires": None, "detail": "independent-review procedure step: Standards pass and Spec pass (operator's words + f1s-intake acceptance) run separately",
     "check_text": ("skill_review", "Review on two separate axes")},
    {"id": "MP-unit-sizing", "element": "mattpocock to-tickets / wayfinder: one fresh-context-sized unit per session", "verdict": "REFINE",
     "requires": None, "detail": "token-preflight PFKT step: size each independent unit to one fresh context window, one unit per session or subagent",
     "check_text": ("skill_preflight", "fit one fresh context window")},
    {"id": "MP-rejected", "element": "mattpocock/skills parts not adopted", "verdict": "INFO",
     "requires": None, "detail": "rejected: GLOSSARY.md (the charter is the glossary); ADRs (commit trailers Why/Verified-By + _registry hold decisions); docs/agents/*.md; tickets as .md (session task list + side sessions hold them); research .md and specs (the reply + kyloren receipts hold them); handoff doc (the AGC compact is the handoff). grill-me / grill-with-docs already adopted as self-interrogation (TH-grill-me, TH-grill-with-docs)"},
    {"id": "KB-noise", "element": "kyloren_bot cards 31019056, e904d45b, f1047cdb, dbea9c8c, a199503d, 3776cbe2, c18d2b35, e7c5cba9, 44b1a930 (IG reels, ASR noise / promos)", "verdict": "DELETE",
     "requires": None, "detail": "no implementable content beyond what ③ already says (fewer lines, reuse); nothing fused"},
    {"id": "EVO-en-translation-rejected", "element": "ai_darkhero f1s-evolve live test 2026-10-15: append an English translation to every report", "verdict": "INFO",
     "requires": None, "detail": "rejected: conflicts with T1 語言 (回覆一律繁體中文; only code/filenames/technique_output in English) and would double every reply's tokens; T1 is not editable by f1s-evolve; no text changed, nothing shipped"},
    # f1s-evolve 2026-10-16: ai_nuwa proposal, commit-msg test-claim gate (evidence ai_nuwa 645cb0f)
    {"id": "EVO-nuwa-test-claim-split", "element": "ai_nuwa: pytest chained with git commit wrote 'N passed' over a failure (f8fbd78, 283559b)", "verdict": "REFINE",
     "requires": None, "detail": "④ in ztm-verify-before-done: test and commit are two steps, read the result before writing the claim; skill text, not hot_directive (how lives in skills, KB-skills-how)",
     "check_text": ("skill_verify", "測試與 commit 分兩步")},
    {"id": "EVO-nuwa-git-smart-test-claim", "element": "ai_nuwa: re-run tests when a commit message claims N passed, refuse on failure or count mismatch", "verdict": "REFINE",
     "requires": None, "detail": "git_smart.py --test-cmd re-runs the seat's suite when the message/Verified-By claims N passed (quoted claims skipped), exit 3 and no commit on failure or mismatch; opt-in per call because the hub has no fleet-wide test command; test_test_claim_gate_refuses_false_claims_on_a_real_repo",
     "check_text": ("git_smart", "def test_claim_problems")},
    {"id": "EVO-nuwa-seat-template-hook", "element": "ai_nuwa: seat template ships .githooks/commit-msg", "verdict": "INFO",
     "requires": None, "detail": "not adopted: no seat template carries .githooks today and core.hooksPath is per-clone config; git_smart commits already run a seat's own commit-msg hook (no --no-verify by default), and --test-cmd covers git_smart callers"},
    {"id": "EVO-trader-three-tier", "element": "ai_trader 2026-10-16 (owner 原話): 確定哪些網站有效後固定撈資料用免費機制, 高智能模型只處理需思考的事", "verdict": "REFINE",
     "requires": None, "detail": "mtm-api-pool-offload 三層分工 table: (1) confirmed site -> zero-model background script / existing rider (new periodic rider still needs operator authorization, T1), (2) bulk fixed-format labelling -> chat_for bulk/extract, (3) reasoning -> conversation model or claude-remote-exec auto lane; evidence ai_trader news_archive pull_log.jsonl (0 token) + _registry/claude-remote-probe.json",
     "check_text": ("skill_pool", "三層分工")},
    {"id": "EVO-trader-tier-pointer", "element": "hot_directive free-pool route names the three tiers", "verdict": "REFINE",
     "requires": None, "detail": "route clause now reads 免費池三層：已確認網站固定撈→零模型背景腳本，量大固定格式→chat_for，推理判斷→本對話模型 (1249 chars, under the 1400 cap); the how stays in the skill",
     "check_text": ("hot_directive", "免費池三層")},
    {"id": "EVO-trader-structured-route", "element": "ai_trader 2026-10-18: bulk/extract routes add OmniRoute ddgw/gpt-5.4-mini (40-title pure-JSON labelling 2.0/1.6/2.3 s, parsed every time, 88/120 agree with gemini; gemini shared quota throttled to ~200 s/day)", "verdict": "REFINE",
     "requires": None, "detail": "_llm.TASK_ROUTES bulk/extract = gemini, ddgw/gpt-5.4-mini, auto/coding; root cause fixed in the engine: chat_for(jsonmode=True) treats a non-JSON answer as that route's failure (not-json, metered error) and falls through (test_llm_task_routes: ddgw-before-auto-coding, prose-falls-through); evidence commit ai_trader 9a95bb69d, news_archive/labels/label_log.jsonl",
     "check_text": ("llm_engine", "not-json")},
    {"id": "EVO-trader-drop-auto-coding", "element": "ai_trader 2026-10-18: remove auto/coding from the structured-output routes (answered in prose on its probe)", "verdict": "INFO",
     "requires": None, "detail": "not adopted: curator probe the same night (3-headline JSON) got valid JSON from auto/coding in 4.2 s on chat/completions while ddgw/gpt-5.4-mini answered 503 Failed to acquire VQD token (keyless upstream); auto/* is a router so its output varies per call; removing it would leave bulk/extract with a quota-throttled gemini and a volatile ddgw only. Kept as the last route; the jsonmode fall-through makes a prose answer harmless",
     "check_text": ("skill_pool", "留作末位")},
    {"id": "EVO-trader-rpd-ledger", "element": "ai_trader gap: free-pool RPD unmeasured (key-health only ok/quota0), proposed f1s-harvest per-provider daily usage so background labelling stops itself", "verdict": "REFINE",
     "requires": None, "detail": "routed to the existing api_budget.py ledger instead of f1s-harvest: _llm.Pool.chat_for meters every routed call (provider level, key='pool', no values) and skips a provider whose headroom is parked (429 -> 15 min) or over the observed rpd; learn --write derives ceilings from 429s; tests test_chat_for_meters_every_routed_call / test_429_parks_the_provider / test_spent_daily_budget_stops_the_background_job (11 passed)",
     "check_text": ("llm_engine", "def _budget_note")},
    # f1s-evolve 2026-10-18: ai_trader memories matrix-lane-v21-two-boards-20261018, cnyes-keyless-news-archive
    {"id": "EVO-trader-narrow-output", "element": "ai_trader 2026-10-18 (owner 「上千個投資標的你只選兩個」): v14 held 2-3 names because of K=3 and the NT$5,000 order cap, not a small universe; v21 two-board panel (2,062 codes) raised WF but passed no pre-registered gate, K=10/20 lost", "verdict": "REFINE",
     "requires": None, "detail": "mtm-mto-first ③: when the output looks narrow, find the parameter that produced the narrowness before adding data or names (step 1 质疑需求 done properly); evidence ai_trader memory matrix-lane-v21-two-boards-20261018 + runtime/research/matrix/research/report-20261018T033035.json",
     "check_text": ("skill_method", "先找出產生窄度的參數")},
    {"id": "EVO-trader-v21-seat-local", "element": "ai_trader v21 numbers (WF +61,361 t 1.07, family p 0.825, worst day -10,986, NOT_QUALIFIED) and TPEx endpoints", "verdict": "INFO",
     "requires": None, "detail": "not copied into F1S: the research verdict is seat-local and already lives in the ai_trader memory; TPEx keyless endpoints enter _registry/f1s-harvest/api-catalog.json through the f1s-harvest cycle scan of matrix_data_pull.py, not by hand"},
    {"id": "EVO-trader-source-card", "element": "ai_trader 2026-10-16: cnyes newslist keyless archive (headline 2012+, tw/us/wd 2015+, 0.7 s/page); GDELT 429 from this IP, FinMind news 400 without token, Google News RSS ~2 days", "verdict": "REFINE",
     "requires": None, "detail": "mtm-api-pool-offload rule: a confirmed source is recorded with keyless-ness, history depth per category, daily volume + page latency, the failed alternatives with their error codes, raw JSON per day with sha256 in pull_log (tier 1 already named cnyes, EVO-trader-three-tier); evidence ai_trader memory cnyes-keyless-news-archive + news_archive/pull_log.jsonl",
     "check_text": ("skill_pool", "同題試過失敗的來源和錯誤碼")},
    # f1s-evolve 2026-10-19: hub-root memory burnin-subtitle-ocr-learning (ledger 42161c5cf4fd)
    {"id": "EVO-theater-cpu-thread-cap", "element": "ai_theater 2026-10-18: rapidocr_onnxruntime default intra_op threads = all cores (27 cores, 96k CPU-s) starved faster-whisper + 4 STT lanes (5 CPU-s per 10 s, 25 min audio in 83 min); whole-frame gray diff still OCR'd 1858/3061 frames, white-text HSV mask cut it to 277", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls new section CPU 配額與批次負載: cap threads before adding any OCR/STT/vision batch job, measure per-frame/per-minute cost before scaling, check CPU quota before blaming the model; cheap change detection aimed at the target region before expensive per-frame recognition; evidence hub-root memory burnin-subtitle-ocr-learning + ai_theater scripts/subtitle_burnin_learn.py (RapidOCR(intra_op_num_threads=...), HSV mask)",
     "check_text": ("skill_runtime", "intra_op_num_threads")},
    {"id": "EVO-theater-fansub-corpus", "element": "ai_theater 2026-10-18: fansub burn-in subtitles are free translations (117 pairs, 12 confirmed by lexical anchors)", "verdict": "REFINE",
     "requires": None, "detail": "mtm-api-pool-offload: aligned fansub corpus is a style/vocabulary reference for the prompt, never per-sentence ground truth; anchor-filter first and the result stays a draft (extends the existing results-are-drafts rule); evidence hub-root memory burnin-subtitle-ocr-learning",
     "check_text": ("skill_pool", "不能當逐句 ground truth")},
    # f1s-evolve 2026-10-19: ai_theater inbox proposal "load_guard.py resume re-arms the subtitle run intent"
    {"id": "EVO-theater-ladder-restore-generation", "element": "ai_theater 2026-10-19 ask: load_guard's background restore must be idempotent and honour an explicit stop/drain posted after the shed", "verdict": "REFINE",
     "requires": None, "detail": "load_guard shed records the intent_generation its own background-off produced (off_generation, persisted in the ladder file); resume_all re-arms only when the schedule stamp AND the session generation are still its own, an unreadable session is UNKNOWN and leaves it off, a ladder file without the field keeps the schedule-only rule (tray/tests/test_load_guard_ladder_restore.py, 12 tests)",
     "check_text": ("load_guard", "off_generation")},
    {"id": "EVO-theater-ladder-misattribution", "element": "ai_theater 2026-10-19 claim: load_guard resume_all posted background enabled=true on every shed/resume cycle 01:56-05:05 (generations 1026..1038)", "verdict": "REFINE",
     "requires": None, "detail": "refuted: ai_darkhero/tray/logs/load_guard.log holds 0 shed/resume/gate events in its whole history and tray/state/load_guard.json level=0 (pid 25200 since 10-15); the gate stamps every POST /api/subtitle/background as ai_theater_background and keeps no access log (logging.debug), so the real poster is UNKNOWN; windows-runtime-pitfalls now says: a shared source label cannot attribute a caller, read the suspect's own log before naming it, callers carry their own source, services persist access logs",
     "check_text": ("skill_runtime", "共用的來源標籤不能歸因呼叫者")},
    # f1s-evolve 2026-10-21: ai_trader memory workflow-audit-20261020 (ledger bceda5503e7f)
    {"id": "EVO-trader-consumer-or-delete", "element": "ai_trader 2026-10-20 owner 「沒成交沒學習就不要發 LINE」 + workflow audit: 10-19 digest said 「當日增減 UNKNOWN / 0 筆」, 36 dead files removed, ORB-family in-session machinery runs 163x/day with every strategy NOT_QUALIFIED, hub efficiency tools gave no seat-level signal", "verdict": "REFINE",
     "requires": None, "detail": "mtm-mto-first ③ step 2 applied to periodic work and notifications: name the consumer before adding a scheduled step, remove a lane's scripts in the same change that records its verdict, push notifications only on a new fact (fill or verdict) and suppress 0/UNKNOWN digests with a reason, measure seat waste from the seat's own logs, list structural idle work for the owner instead of retiring it; evidence ai_trader memory workflow-audit-20261020",
     "check_text": ("skill_method", "講出誰讀它的輸出")},
    {"id": "EVO-trader-timeout-started-state", "element": "ai_trader 2026-10-20: strategy_lineage TimeoutExpired x9 (300 s kill, state never written, retried every tick), news_tone TimeoutExpired x41, autonomy_acceptance rc=1 x286 while the owner had stopped the cockpit", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls 重試: write STARTED state before the work and back off on the same input fingerprint, keep a budget reserve before starting a new unit, skip a step whose known precondition is off; extends the existing retry-cap rule; evidence ai_trader memory workflow-audit-20261020",
     "check_text": ("skill_runtime", "開工前先寫 STARTED 狀態")},
    {"id": "EVO-burnin-duplicate-20261021", "element": "hub-root burnin-subtitle-ocr-learning proposal re-sent 2026-10-21 and 2026-10-22 (ledger 42161c5cf4fd)", "verdict": "INFO",
     "requires": None, "detail": "already integrated 2026-10-19 as EVO-theater-cpu-thread-cap and EVO-theater-fansub-corpus (thread cap, HSV mask, fansub-as-style); nothing new in the memory, no text added"},
    # f1s-evolve 2026-10-22: ai_trader memory matrix-lane-v21-two-boards-20261018 re-sent (ledger 6ce432243457)
    {"id": "EVO-matrix-v21-duplicate-20261022", "element": "ai_trader matrix-lane-v21-two-boards-20261018 proposal re-sent (ledger 6ce432243457)", "verdict": "INFO",
     "requires": None, "detail": "already integrated 2026-10-18 as EVO-trader-narrow-output (mtm-mto-first: find the parameter that produced the narrowness first) and EVO-trader-v21-seat-local (verdict numbers stay seat-local); memory unchanged since (modified 2026-10-17T19:33Z), no text added"},
    # 2026-10-20 (two YouTube videos reverse-learned; shipped 1.45.61 without audit rows — bound here so the
    # three passages are mechanically guarded like every other F1S text)
    {"id": "EVO-lean-public-record", "element": "lean-math-prover: what the public record says about AI + formal mathematics (IMO 2024 AlphaProof silver only after human Lean translation, days of compute)", "verdict": "REFINE",
     "requires": None, "detail": "facts quoted from named pages with read date; Lean stays the kernel that accepts or rejects, never a claim of autonomous mathematics",
     "check_text": ("skill_lean", "AI and formal mathematics")},
    {"id": "EVO-metr-verifier-not-goal", "element": "ztm-verify-before-done: 驗證器不是目標 (METR 2026-08-26) — passing a check that can be gamed is not reaching the goal", "verdict": "REFINE",
     "requires": None, "detail": "F1S ④⑤⑥ restated through Goodhart: the green test after a fix must be one that this bug would turn red; no effort on making checks look green",
     "check_text": ("skill_verify", "驗證器不是目標")},
    {"id": "EVO-pool-blocked-source-ladder", "element": "mtm-api-pool-offload: 封鎖源的退路階梯 — when one source blocks (百度 403 shell, wiki disambiguation 404) step down the ladder before reporting not found", "verdict": "REFINE",
     "requires": None, "detail": "built-in browser get_page_text for walled pages, MediaWiki search API before guessing titles; a first failure is never 查無",
     "check_text": ("skill_pool", "封鎖源的退路階梯")},
    # 2026-10-21 ai_career proposals
    {"id": "EVO-career-linkedin-jobs-pointer", "element": "ai_career: linkedin-jobs skill (built-in browser LinkedIn sign-in, voyager API, guest fallback, 104 via built-in browser)", "verdict": "REFINE",
     "requires": None, "detail": "skill already exists seat-local at ai_darkhero/.claude/skills/linkedin-jobs (no new .md per ⑥); browser-login-handoff step 2 now points every seat to it so a signed-in site is probed before any login handoff",
     "check_text": ("skill_login", "LinkedIn 職缺讀法")},
    {"id": "EVO-career-python-I-encoding", "element": "ai_career: python -I ignores PYTHONIOENCODING -> cp950 UnicodeEncodeError on CJK output", "verdict": "REFINE",
     "requires": None, "detail": "verified 2026-10-21 (-I: ignore_environment=1, stdout cp950); windows-runtime-pitfalls: reconfigure stdout inside the script; the CV variant flow part is ai_career-only and stays in that seat",
     "check_text": ("skill_runtime", "會忽略 PYTHONIOENCODING")},
    # 2026-10-22 jci_taipei proposal
    {"id": "EVO-latency-number-needs-proof", "element": "jci_taipei: generic latency-probe pattern (per-target correctness proof, repeated rounds, saved run compared with previous)", "verdict": "REFINE",
     "requires": None, "detail": "verified 2026-10-22: both probes exist (page_latency_probe.py 7a3f7c5: adaptive rounds, 429/503 backoff, vs_prev regressed; llm_provider_probe.py: code word, ok-rate then median); run 20261022T035229Z 26/26 pages with proof, /events p50 1541.8 ms; ztm-verify-before-done gains the latency-evidence rule, no new skill or file",
     "check_text": ("skill_verify", "延遲數字的證據")},
    # 2026-10-22 jci_taipei permission/skill gaps (memory jci-write-paths, commits 356aa86/756a78f)
    {"id": "EVO-jci-roster-write-path", "element": "jci_taipei: member-sheet + website Drive-registry rows missing from the credential table; GAS overwrite of 姓名 assumed impossible", "verdict": "REFINE",
     "requires": None, "detail": "verified 2026-10-22 in RosterSheetMerge.gs (_isOverwriteCol_ needs overwrite_roles; empty value returns early, only 備註 clears) and sync_members_to_sheet.push_via_gas; credential table gains both rows and the grep-the-handler-before-impossible rule",
     "check_text": ("skill_jci_transfer", "先 grep 那個 handler 有沒有這個欄位")},
    {"id": "EVO-login-stale-realm", "element": "jci_taipei: sso_browser.py check google.cloud.console ok:false (stale profile), re-seed needs a headful window", "verdict": "REFINE",
     "requires": None, "detail": "browser-login-handoff §2: a stale Edge realm is not login evidence; the built-in browser probe is the single route and re-seeding is not attempted (no-popup red line kept)",
     "check_text": ("skill_login", "舊的 Edge profile 檢查不算登入證據")},
    {"id": "EVO-proof-publish-read-only", "element": "jci_taipei: PROOF publish gate denied a pure read naming a dot-env file and a public path", "verdict": "REFINE",
     "requires": None, "detail": "claude-proof-hook: a served-directory path alone now needs a write/copy/move verb in the shell command; deploy symbols, deploy commands, file hosts and Write/Edit into public stay gated; tests/test_proof_publish_gate.py 17 passed incl. the read and write controls",
     "check_text": ("proof_hook", "PUBLIC_PATH_ONLY")},
    {"id": "EVO-line-group-member-403", "element": "jci_taipei: LINE OA group member IDs 403 at this account level", "verdict": "REFINE",
     "requires": None, "detail": "line-oa-ingest boundary list + jci credential table: only member count and speakers' profiles; said at intake before work",
     "check_text": ("skill_line_ingest", "Group member user IDs are 403")},
    {"id": "EVO-automode-classifier-rejected", "element": "jci_taipei: let one in-chat go-ahead cover the auto-mode classifier for a whole verify step", "verdict": "INFO",
     "requires": None, "detail": "rejected: the classifier is Claude Code harness permission policy (settings.json, out of F1S scope); widening a go-ahead across tool calls would loosen an authorization boundary; no text added"},
    # 2026-10-23 f1s-evolve tick (ledger 8fcbf62f78bb, 338e25dad27d, f4c2b92671df)
    {"id": "EVO-pfkt-hub-wide-template-verify", "element": "ai_trader: pfkt-fragment split template `pytest -q` run by zat-verify-gate at the hub root = workspace-wide pytest (2026-09-17)", "verdict": "REFINE",
     "requires": None, "detail": "is_cmd_allowed refuses a bare pytest / py_compile . (no seat path) for mint, split and done; split reuses the caller's seat-scoped pytest verify; tests/test_pfkt_atomic_writes.py covers both",
     "check_text": ("zat_verify_gate", "def _hub_wide_verify")},
    {"id": "EVO-llm-probe-prod-key", "element": "ai_ziyaoastro: llm_provider_probe.py (8k system prompt + code word, Render prod key, rounds, ranking)", "verdict": "REFINE",
     "requires": None, "detail": "probe already absorbed 2026-10-22 (EVO-latency-number-needs-proof); only the new part added: measure with the exact prod key and a real-size prompt, never api-matrix status or a one-word ping",
     "check_text": ("skill_verify", "正式環境實際用的那把 key")},
    {"id": "EVO-trader-credit-options-v23", "element": "ai_trader: v23 credit balance + option institutional OI research lane and FinMind keyless dataset list", "verdict": "INFO",
     "requires": None, "detail": "rejected: seat-local research result (NOT_QUALIFIED verdict, dataset inventory); nothing generalizes beyond ai_trader's own memory; no text added"},
    # 2026-10-23 curator feedback sweep (operator 「撈取所有對f1s和ai_darkhero整套系統的反饋開始進行升級…確保自動套用」):
    # 1615 operator messages from every Claude + Codex transcript, 571 about agent/system behaviour, 100 themes.
    {"id": "EVO-run-until-done-meta-rows", "element": "run-until-done: per-prompt cap never engaged (93 of 93 logged blocks read 1/2)", "verdict": "REFINE",
     "requires": "F1SCore.blocks_bounded", "detail": "the hook's own isMeta reason row counted as a new operator prompt; the human-prompt test now skips isMeta/compact rows like PROOF does; tests/test_run_until_done_turn_cap.py fails on the old hook",
     "check_text": ("run_until_done_hook", "Same filter as claude-proof-hook.py")},
    {"id": "EVO-notification-turn-not-a-prompt", "element": "session hook: every background-task notification bound as an UNKNOWN operator turn and re-sent ~2 KB of contract", "verdict": "REFINE",
     "requires": None, "detail": "task / side-session / CI notifications skip the turn binding and recurrence line; T1/charter refresh and PROOF carry-over still run, and the mid-turn signature is not recorded so an upgrade still reaches the next tool call",
     "check_text": ("session_hook", "MACHINE_EVENT_TAGS")},
    {"id": "EVO-recurrence-phantom-seat", "element": "session hook: PROOF recurrence keyed seats by cwd basename (hub root read as `ai_workspace`, tray/ as `tray`)", "verdict": "REFINE",
     "requires": None, "detail": "both the session cwd and each logged block's cwd resolve through _seat_for_cwd (project-matrix, hub root -> curator), cached per cwd",
     "check_text": ("session_hook", "Both sides go through _seat_for_cwd")},
    {"id": "EVO-attest-clone-behind", "element": "fleet-skill-pulse red 11 runs: a published capability receipt stayed in the shared clone's working tree while its branch was behind", "verdict": "REFINE",
     "requires": None, "detail": "attest-capabilities puts the receipt path back to HEAD when the clone could not follow the push, so the publisher's fast-forward is no longer refused; _harness/tests/test_capability_receipt_clone.py fails on the old engine",
     "check_text": ("fames_fleet", "clone_behind")},
    {"id": "EVO-pickup-verify-rolling", "element": "fleet-contract-sync verify demanded all 26 seats in one 360 s run; HubClock riders share 2 logical CPUs (~50 s/seat), so 758 of 1485 runs failed UNKNOWN", "verdict": "REFINE",
     "requires": None, "detail": "each seat is judged on its newest real probe within ROLLING_SECONDS (this run or the rotation); a FAIL stays a FAIL, a seat no run reached stays UNKNOWN",
     "check_text": ("pickup_verify", "ROLLING_SECONDS")},
    {"id": "EVO-sibling-session-merge", "element": "operator asked five times (10-15..10-21) to merge a seat's other conversations and close them", "verdict": "REFINE",
     "requires": None, "detail": "agc-auto-goal-compact gets the procedure: find, read the last report, re-verify claims as UNKNOWN, park the merged goal, archive (reversible) only idle sessions",
     "check_text": ("skill_agc", "同座位多對話收斂")},
    {"id": "EVO-feedback-stream-not-automated", "element": "automatic operator-feedback -> f1s-evolve stream (f1s-harvest kind `feedback`)", "verdict": "INFO",
     "requires": None, "detail": "rejected for now: lexical coverage cannot tell an integrated directive from a new one (「禁止寫垃圾 .md」 scored 0.14); 65 of 73 directive messages fell under 0.3, so the stream would flood evolve with covered items; sweeps stay curator-run like this one"},
    {"id": "EVO-codex-hook-silent", "element": "Codex surface: hooks configured with trusted-hash entries, yet no October Codex session carries F1S context; last Codex hook fire 2026-09-29", "verdict": "INFO",
     "requires": None, "detail": "recorded, not fixed: the October Codex runs were scripted exec calls; re-trusting hooks inside Codex is the operator's step; Claude Code (every cwd) is the live surface"},
    {"id": "EVO-evolve-prefix-word", "element": "f1s-evolve read only messages starting with 'F1S:'; jci_taipei's 'F1S addendum to …' sat unread", "verdict": "REFINE",
     "requires": None, "detail": "pending() matches F1S as a leading word, case-insensitive; HubClock handoffs and other prefixes stay out; tests/test_f1s_evolve_tick.py",
     "check_text": ("evolve_engine", "sat unread a day")},
    {"id": "EVO-latency-content-freshness", "element": "jci_taipei addendum (a): a fast 200 served 2.5-month-old fallback data from a dead GAS source", "verdict": "REFINE",
     "requires": None, "detail": "ztm-verify-before-done latency proof (1): a data page also needs fresh date/source, not just HTML",
     "check_text": ("skill_verify", "快又 200 的過期備援不算對")},
    {"id": "EVO-worker-ab-staged-version", "element": "jci_taipei addendum (b): an A/B against an unstaged uploaded Worker version measures the old version", "verdict": "REFINE",
     "requires": None, "detail": "deploy-nextjs-cloudflare VERIFY: the B side counts only when the version-scoped tail shows scriptVersion.id = candidate (staged at 0%)",
     "check_text": ("skill_deploy_cf", "an unstaged \"B\" silently measures A")},
    # 2026-10-23 f1s-evolve tick (ai_darkhero proposals: tray retirement, hook FPs, psutil, audio, _bus id collision)
    {"id": "EVO-retire-on-evidence", "element": "ai_darkhero: tray cleanup 42 -> 25 actions by per-feature log signatures over full history", "verdict": "REFINE",
     "requires": None, "detail": "mtm-mto-first step 2 gets the five-part retirement procedure (own log signature, full rotated history, parked != retired, safety couplings, _delete + sha256 MANIFEST)",
     "check_text": ("skill_mto", "憑證據退役，不憑沉默")},
    {"id": "EVO-run-until-done-noun-phrase", "element": "run-until-done matched 才跑 inside the noun phrase 只在通話時才跑的程式", "verdict": "REFINE",
     "requires": None, "detail": "the 再/才 + verb pending pattern refuses a following 的; tests/test_bus_send_unique_id.py keeps 我才跑驗證 blocked",
     "check_text": ("run_until_done_hook", "(?:再|才)(?:檢查|確認|驗證|回報|繼續|看|跑)(?!的)")},
    {"id": "EVO-proof-capability-blocker-fp", "element": "ai_darkhero: PROOF tagged the tray capability reply as blocker", "verdict": "INFO",
     "requires": None, "detail": "rejected: the current hook judges that reply as `decision` only (its last line asks 需要你決定：要不要我現在…做出來, a model step), which is a true positive; no blocker hit reproduces, so nothing is loosened"},
    {"id": "EVO-operator-physical-step", "element": "ai_darkhero: 需要你決定 rejected twice for USB debugging / LINE mic steps only the operator can physically do", "verdict": "REFINE",
     "requires": None, "detail": "f1s-intake §3: an operator-only physical / third-party-app step is one plain line plus a background waiter that verifies when it happens, never a decision; PROOF passes the plain line (no decision/handback hit)",
     "check_text": ("skill_intake", "只有使用者能親手做的實體／第三方 App 步驟")},
    {"id": "EVO-psutil-n2-ui-priority", "element": "ai_darkhero: psutil O(N^2) per-tick scans, tray inheriting BelowNormal/2-CPU affinity, py-spy wall samples", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls: ppid_map once per tick + caches, reset UI process priority with an always-unioned exemption, per-thread CPU via threads() deltas",
     "check_text": ("skill_runtime", "psutil 在 Windows 的 O(N²) 陷阱")},
    {"id": "EVO-audio-capture-call-detect", "element": "ai_darkhero: app-chosen devices, WASAPI session call detection, EXCLUDE loopback decay, synthetic e2e scope", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls gets an audio section; the whisper echo/pinyin and credit-phantom items stay seat-local (linecall memory)",
     "check_text": ("skill_runtime", "INCLUDE（單一 App 樹）可靠")},
    {"id": "EVO-bus-same-second-id", "element": "_bus.send id = int(time.time())-frm-k: same-second sends overwrote each other (2 of 4 F1S proposals lost)", "verdict": "REFINE",
     "requires": None, "detail": "send claims the file with os.link and suffixes -2, -3...; inbox.py send reads the file back before printing sent and warns on control characters; tests/test_bus_send_unique_id.py",
     "check_text": ("bus_engine", "Claim the name with os.link")},
    {"id": "EVO-absorb-idempotent", "element": "fleet-skill-pulse re-stamped ~60 unchanged incubator files every 15 min, so every f1s-evolve run saw concurrent hub edits and held its ship", "verdict": "REFINE",
     "requires": None, "detail": "absorb keeps an unchanged submission's SKILL.md and meta.json (original absorbed_at); a changed body is still rewritten; _harness/tests/test_fleet_skill_sync_dotdirs.py fails on the old engine",
     "check_text": ("skill_sync_engine", "re-stamping it every 15 min")},
    {"id": "EVO-hub-subdir-seat", "element": "session hook: a curator shell in the hub's _registry folder was labelled seat `_registry` (TOKEN CORE _registry)", "verdict": "REFINE",
     "requires": None, "detail": "a cwd inside the hub but in no ai_* seat resolves to the hub-root seat (local curator); outside the hub stays basename; tests/test_proof_recurrence.py fails on the shipped 1.45.69 hook",
     "check_text": ("session_hook", "Hub infrastructure (_registry, _skill, _lean...) belongs to the hub-root seat")},
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
    # F1S wave 2 (accelerate): re-prove a module only when its .lean hash differs from the last audit's
    # bound hash (or its receipt is gone / was not PROVED); the text checks below always run.
    try:
        previous = json.loads(OUT.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        previous = {}
    force = "--force" in sys.argv[1:]
    for name, path in MODULES.items():
        receipt = HERE / "evidence" / f"{name}.receipt.json"
        prior = (previous.get("proofs") or {}).get(name) or {}
        bound = ((previous.get("bound") or {}).get(name) or {}).get("sha256")
        if (not force and prior.get("verdict") == "PROVED" and bound and bound == sha(path)
                and receipt.is_file() and prior.get("theorems")):
            proofs[name] = {**prior, "reused": True}
        else:
            proofs[name] = {**lean(path, receipt), "reused": False}
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
    # 2026-10-16: a 1609-char hot directive passed this audit, then failed at install (fames_capabilities caps it
    # at 1400) and left the fleet on a half-shipped package. Check the same cap here, before any ship step.
    try:
        directive = json.loads(TEXTS["hot_directive"].read_text(encoding="utf-8-sig"))["unified_entrypoint"]["hot_directive"]
        directive_ok = 100 <= len(directive) <= 1400
    except (OSError, ValueError, KeyError, TypeError):
        directive, directive_ok = "", False
    if not directive_ok:
        print(f"  FAIL hot_directive length {len(directive)} outside 100..1400 (fames_capabilities cap)")
    ok = all(p["verdict"] == "PROVED" for p in proofs.values()) and unresolved == 0 and conf_ok and directive_ok
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
