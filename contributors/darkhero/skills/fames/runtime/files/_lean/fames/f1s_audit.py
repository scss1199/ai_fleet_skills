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
    "sources_engine": HUB / "_skill" / "engines" / "f1s-sources.py",
    "daily_engine": HUB / "_skill" / "engines" / "f1s_daily.py",
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
    "curator_orders": HUB / "_skill" / "engines" / "curator_orders.py",
    "f1s_live": HUB / "_skill" / "engines" / "f1s_live.py",
    "f1s_pytest_guard": HUB / "_skill" / "engines" / "f1s_pytest_guard" / "f1s_pytest_guard.py",
    "pinned_drift": HUB / "_skill" / "engines" / "pinned_drift.py",
    "skill_vet": HUB / "_skill" / "engines" / "fleet-skill-vet.py",
    "asu_verify": HUB / "_skill" / "engines" / "asu-verify.py",
    "skill_deploy_cf": HUB / "_skill" / "fleet-skills" / "deploy-nextjs-cloudflare" / "SKILL.md",
    "skill_sync_engine": HUB / "_skill" / "engines" / "fleet-skill-sync.py",
    "bus_engine": HUB / "_skill" / "engines" / "_bus.py",
    "ship_engine": HUB / "_skill" / "engines" / "ship-f1s.py",
    "jev_router": HUB / "_harness" / "runtime" / "jev_turn_router.py",
}

# The architecture scan.  `requires` names the Lean theorem that must be PROVED for the verdict to stand;
# a REFINE row records what the kernel refuted and what the text now says.
ELEMENTS = [
    {"id": "R1-no-misread", "element": "① 不准曲解 (原話、不擴不縮、已決定不再問、結論先行)", "verdict": "FORMALIZED",
     "requires": "F1SCore.f1s_satisfiable", "detail": "rule1 in the satisfiable set"},
    {"id": "R1-details-in-file", "element": "① old wording 「細節放檔案」", "verdict": "REFINE",
     "requires": "F1SCore.rule1_old_vs_rule6_unsat",
     "detail": "Lean: no reply satisfies old ① and ⑥ together; wording changed to 「細節放回覆或既有收據，不新開 .md/.json」",
     "check_text": ("hot_directive", "不新開 .md/.json")},
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
    {"id": "OP-parallel-free-models", "element": "operator 2026-10-27: 時間最貴，能平行拆分就盡可能拆；夠簡單的子任務叫不同的免費模型去執行", "verdict": "REFINE",
     "requires": None, "detail": "hot_directive parallel clause: independent verifiable subtasks open subagents in the same turn, simple mechanical subtasks fan out to several free-pool models; results merge only after read-back (same 1399-char budget)",
     "check_text": ("hot_directive", "夠簡單的派免費池多模型並行")},
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
     "requires": None, "detail": "task / side-session / CI notifications and cross-session peer messages skip the turn binding and recurrence line; T1/charter refresh and PROOF carry-over still run, and the mid-turn signature is not recorded so an upgrade still reaches the next tool call",
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
    {"id": "EVO-ctypes-shared-argtypes", "element": "ai_darkhero: two modules set user32.BeginPaint.argtypes to their own POINTER(PAINTSTRUCT); swallowed ArgumentError in a WNDPROC spun the message pump", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls: shared windll argtypes take c_void_p for struct pointers (or a private WinDLL), diagnose with py-spy --native + GetUpdateRect; evidence ai_darkhero 21550c71, sleep-mode thread 139.6 -> 2.2 CPU-s/600 s",
     "check_text": ("skill_runtime", "函式指標全行程共用一份")},
    {"id": "EVO-psutil-create-time-queue-dir", "element": "ai_darkhero: psutil create_time snapshot fallback (10.9 of 15 s cold scan); ship-queue dir with 26,138 retired files globbed per probe", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls: read create_time only after the cmdline filter (Process object as cache key); re-list a retire-in-place queue dir only on mtime change with a 2 s settle window; evidence ai_darkhero 739740e7, 21550c71, tests tray/tests/test_tray_process_scan_cost.py",
     "check_text": ("skill_runtime", "就地退役檔案的佇列目錄")},
    {"id": "EVO-midturn-subagent-scope", "element": "mid-turn F1S update was one-shot per session id; a subagent (same session id) consumed it and the main conversation never received it (ai_nuwa, 1.45.71)", "verdict": "REFINE",
     "requires": None, "detail": "the delivery record is keyed by session id plus the hook input's agent_id (documented common input field, present inside a subagent), so the main thread and each subagent get the update once each; main-thread keys are unchanged",
     "check_text": ("session_hook", "A subagent shares the session")},
    {"id": "EVO-agc-should-compact-actor", "element": "ai_metadata: ctx_meter should_compact=true (n_now=245 vs n*=19.5) with no actor; proposal = UserPromptSubmit systemMessage telling the operator to run /compact", "verdict": "INFO",
     "requires": None, "detail": "nag rejected (AGC rule 3 forbids hand /compact; mechanical work is never handed to the operator); skill names the three actors (cold-page refresh, PARK, autoCompactWindow from W*)",
     "check_text": ("skill_agc", "的執行者只有三個")},
    # 2026-10-23 operator: absorb AI techniques from LINE OA + subscribed sources; F1S verifies itself on every ship
    {"id": "SRC-sphinx-old-code-reviewer", "element": "f1s-sources 0e1c32a5 (Sphinx): a reviewer that never saw the chat reads the diff before ship", "verdict": "REFINE",
     "requires": None, "detail": "ship-f1s step 0 runs the shipped tests with the shipped .py files at HEAD bytes; tests that pass there stop the ship (test_ship_f1s_and_seal)",
     "check_text": ("ship_engine", "they pass whatever the change does")},
    {"id": "SRC-helper-mode-choice", "element": "kyloren 4122208e: consultant / subagent / fork, chosen by need and cost", "verdict": "REFINE",
     "requires": None, "detail": "token-preflight step 3: subagent when only the result matters, fork when the context matters (shared prompt cache), independent reviewer when direction is in doubt",
     "check_text": ("skill_preflight", "it shares the prompt cache")},
    {"id": "SRC-claw-ponytail-covered", "element": "kyloren 04171cf7 (Claw.md four rules) and cea9bf31 (Ponytail, over-engineering)", "verdict": "INFO",
     "requires": None, "detail": "already in F1S: mtm-mto-first reuse order (標準函式庫) and only-the-lines-needed; no change"},
    # 2026-10-23 operator: 「發現可平行時主動開子任務、完畢自動帶回主任務…都是我要求主對話去收編」. 7 days of transcripts:
    # 28,208 tool calls, 200 subagent calls (0.7 %, 19 of 58 sessions); 32 of 44 session starts were proposal cards
    # the operator had to click; the hot directive never mentioned splitting, and pfkt-parallel-wave loads only when the
    # prompt already says "parallel".
    {"id": "EVO-split-and-merge", "element": "parallel split and child-result merge left to the operator", "verdict": "REFINE",
     "requires": None, "detail": "hot directive: independent units -> subagents started in the same turn, results read back and merged by the parent; token-preflight step 3 carries the merge rule",
     "check_text": ("hot_directive", "子對話回報只是線索")},
    {"id": "EVO-split-merge-skill", "element": "merge rule in the skill that the hot directive routes to", "verdict": "REFINE",
     "requires": None, "detail": "token-preflight: a report is a lead, not evidence; fold the verified part into the parent's result",
     "check_text": ("skill_preflight", "a report is a lead, not evidence")},
    # 2026-10-23 operator: 「確認f1s能力自動同步且能夠自我疊代驗證程式碼的使用率與乾淨程度」. Audit (two subagents):
    # 16 tracked .pyc forced in by ship-f1s `git add -f`, two live engines untracked, 4 engines with no reference at all,
    # 48,663 never-pruned per-session hot states.
    {"id": "EVO-ship-hygiene", "element": "F1S package hygiene checked on every ship", "verdict": "REFINE",
     "requires": None, "detail": "ship-f1s step 0: no tracked caches, every hook/rider engine tracked, week-old session states moved to _delete/; caches excluded from the forced add",
     "check_text": ("ship_engine", "Every ship checks the package it is about to commit")},
    # 2026-10-24 operator after two power losses 14 min apart: ai_darkhero is the one load scheduler; F1S asks it too.
    {"id": "EVO-load-grant", "element": "every planned load increase asks ai_darkhero's load grant (steady power, <= 40 W step, <= 250 W)", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls rule for agents; ship-f1s and f1s-evolve wait for a grant before their gate tests; ai_theater ramp + CPU fleet ask before each step",
     "check_text": ("skill_runtime", "加負載先拿 load grant")},
    # 2026-10-24 operator: 「優先於 然後馬上實作疊代f1s (f1s就是會優先於其他cwd的意思 你構造f1s 用f1s統御其他cwd)」.
    {"id": "OP-f1s-governs", "element": "T1 f1s-governs: ai_darkhero correction orders outrank a seat's own decisions; red lines and the operator's own words stay above", "verdict": "REFINE",
     "requires": None, "detail": "curator_orders.py store + CLI; claude_session_hook puts open orders first, run-until-done holds the turn, git_smart refuses frozen paths, fleet-process-guard stops forbidden processes (test_curator_orders)",
     "check_text": ("rules_blueprint", "F1S 統御各 cwd")},
    {"id": "OP-f1s-governs-enforced", "element": "the four enforcement points read one order store", "verdict": "REFINE",
     "requires": None, "detail": "freeze / forbid hold until the curator closes the order; the curator's own commits are never refused; Logi Options+ is never a forbid target",
     "check_text": ("curator_orders", "def frozen_hits")},
    # f1s-evolve 2026-10-28 (jci_taipei proposal): reopened order #5 was pushed to every jci_taipei session by run-until-done,
    # while only the conversation that had answered it held the evidence; the others could neither answer nor say cannot.
    {"id": "EVO-order-owner-session", "element": "a curator order is pushed to the one conversation that owns it; other conversations of the seat read it as one line and are not held", "verdict": "REFINE",
     "requires": None, "detail": "curator_orders: the answering conversation becomes the order's owner (CLAUDE_CODE_SESSION_ID), `claim <seat> <n> [--release]` binds or frees it; open_orders(seat, session_id) and injection(seat, session_id) drop or shorten orders another conversation owns; run-until-done and claude_session_hook pass the session id; freeze / forbid unchanged (test_curator_orders::test_a_reopened_order_holds_only_its_owning_conversation)",
     "check_text": ("curator_orders", "def owned_by_other")},
    # 2026-10-24 operator: 「一樣改 目的就是當任何對話一閒置後立刻套用」.
    {"id": "OP-f1s-live-idle-wake", "element": "an idle conversation applies an F1S upgrade or its seat's curator order the moment it lands", "verdict": "REFINE",
     "requires": None, "detail": "f1s_live.py wait runs as an asyncRewake Stop hook and exits 2 with the update text; quiet exit when the conversation turns active, a newer waiter takes over, the kill switch is off or the daily cap is hit (test_f1s_live)",
     "check_text": ("f1s_live", "def wait(")},
    {"id": "OP-f1s-live-midturn-orders", "element": "a curator order reaches a running task at its next tool call; the delivery record is a ledger of who holds which contract", "verdict": "REFINE",
     "requires": None, "detail": "claude_session_hook._midturn_sig adds this seat's order file; live_update is shared by the mid-turn hook and the idle waiter; f1s_live.py status lists conversations behind the contract",
     "check_text": ("f1s_live", "def status(")},
    # 2026-10-24 operator: 「那種不負責任快一個小時的會議記錄沒錄到這種廢物事件為什麼可以發生? … 嚴格修正並立刻套用到所有正在執行或是未來開啟的任何對話內」.
    {"id": "OP-live-capture-watch", "element": "a capture that cannot be redone is never left running unwatched", "verdict": "REFINE",
     "requires": None, "detail": "f1s_live.py capture add/done: the idle waiter wakes the conversation when the capture file stops growing (STALLED) or on its check beat (CHECK), exempt from the wake cap; claude-run-until-done-hook refuses 「會一直跑到結束」 without a registration (test_live_capture)",
     "check_text": ("f1s_live", "def capture_due(")},
    # 2026-10-24 operator standing mandate: 「現在你的固定任務是整個f1s的發展程度來控制所有ai_workspace內所有行為 darkhero這台電腦的任務分配+硬體效能與穩定度」.
    {"id": "OP-curator-hardware-watch", "element": "the curator is woken when darkhero's sensor log stops recording", "verdict": "REFINE",
     "requires": None, "detail": "f1s_live.hardware_due: newest D:/__hwlog segment older than 300 s wakes an idle curator conversation (at most every 30 min); the log was empty 2026-10-21 04:03 .. 10-24 01:00 unnoticed (test_f1s_live)",
     "check_text": ("f1s_live", "def hardware_due(")},
    {"id": "OP-quiet-release", "element": "a release an idle conversation need not act on does not wake it", "verdict": "REFINE",
     "requires": None, "detail": "f1s_live.contract_sig = hot directive + standing rules + the seat's orders; a version-only release is recorded quietly (four releases woke every idle chat four times on 2026-10-24)",
     "check_text": ("f1s_live", "def contract_sig(")},
    {"id": "OP-pytest-live-guard", "element": "no hub test may start a detached live process", "verdict": "REFINE",
     "requires": None, "detail": "f1s_pytest_guard (pytest11 entry point on C:/Python312): subprocess.Popen raises for DETACHED_PROCESS while a test runs; an ai_theater test had started the real library-wide ja_finalize run at 11:47:31",
     "check_text": ("f1s_pytest_guard", "class GuardedPopen")},
    {"id": "OP-f1s-live-unattended", "element": "an unattended claude -p run never waits idle", "verdict": "REFINE",
     "requires": None, "detail": "f1s_live.wait returns at once when CLAUDE_CODE_SESSION_ATTENDED=0: f1s-evolve's curator run stayed alive behind the waiter and its caller hung 25 min past its 900 s timeout (2026-10-24)",
     "check_text": ("f1s_live", "CLAUDE_CODE_SESSION_ATTENDED")},
    {"id": "OP-pinned-shell-release-time", "element": "a shell write shipped in an earlier release is not today's drift", "verdict": "REFINE",
     "requires": None, "detail": "pinned_drift: a shell write counts only after the shipped copy's release time; a repeated copy without a timestamp takes the known time (test_pinned_drift)",
     "check_text": ("pinned_drift", "def _shipped_at(")},
    {"id": "OP-pinned-blame-by-content", "element": "an unshipped pinned edit is blamed on the session whose edit text is in the drift", "verdict": "REFINE",
     "requires": None, "detail": "2026-10-24: a session that had shipped its f1s_audit.py edit was blocked twice for another session's open edit; shell writes and unknown text stay blamed",
     "check_text": ("pinned_drift", "def _wrote_the_drift")},
    # 2026-10-24 ai_trader proposal: pre-registered hypothesis loop (c874f3bc7; v29 registration e0b85fbef 11:31:59 before report 11:32:19).
    {"id": "EVO-preregistered-claim", "element": "a fitted/tuned/picked 'X works' claim cites a registration commit older than its verdict receipt, else UNKNOWN", "verdict": "REFINE",
     "requires": None, "detail": "ztm-verify-before-done section: pin data, registration guard, family-wise correction, append-only ledger with forward Bonferroni, cumulative trial count; ai_trader engines as templates; no new skill and no PROOF phrase rule (phrase-matching FP ceiling)",
     "check_text": ("skill_verify", "要先登記再算")},
    # 2026-10-24 f1s-evolve tick: three harvested seat memories (ledger 984a5f25ed10, f6277c451c04, 0d656711de0e)
    {"id": "EVO-powerloss-zero-fill", "element": "ai_trader v30: files written just before Kernel-Power 41 were zero-filled (2 of 3,238), found by sha256 journal", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls 時間與資料新鮮度: sha256 journal for write-once data, full compare after a power loss, .CORRUPT-bak + re-pull; v30 verdict and correlation numbers stay seat-local",
     "check_text": ("skill_runtime", "斷電前幾分鐘寫的檔案可能大小正常但內容全是零")},
    {"id": "EVO-silent-param-fallback", "element": "ai_trader ipo-auction-source: TPEx ignores an unparsed date=yyyy/mm and answers the current month; TWSE intraday 09:00:00 row = previous close", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls: probe a new query with two parameter values; check the first row when mismatches cluster at the first checkpoint; auction fees and feasibility numbers stay in ai_trader",
     "check_text": ("skill_runtime", "伺服器看不懂的參數會靜默退回預設值")},
    {"id": "EVO-line-drive-createdtime", "element": "jci_taipei jci-meet-display-names: Drive webhook search by createdTime; image events file_size=0", "verdict": "REFINE",
     "requires": None, "detail": "line-oa-ingest interpret list gets the two capture facts; the Meet display-name -> member roster and LINE uid are personal data and stay in the jci_taipei memory",
     "check_text": ("skill_line_ingest", "filter by `createdTime`")},
    # 2026-10-27 f1s-evolve tick: ai_trader proposal (commit ee5e6e523); jci_taipei f6277c451c04 resent unchanged = already EVO-line-drive-createdtime
    {"id": "EVO-fsync-before-rename", "element": "ai_trader ee5e6e523: atomic .part -> replace without fsync lets a power cut commit the rename but not the data", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls zero-fill bullet gains the prevention half (flush + os.fsync before replace) and a re-hash verify command; detection half was EVO-powerloss-zero-fill",
     "check_text": ("skill_runtime", "原子寫入在 rename 前要先 fsync")},
    # 2026-10-27 f1s-evolve tick: ai_trader addendum to 1793047758 (commit 8b234c3ac, 66 passed)
    {"id": "EVO-fsync-grep-all-copies", "element": "ai_trader 8b234c3ac: three more write-then-rename copies in the same seat lacked fsync after ee5e6e523 fixed one", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls zero-fill bullet: grep the whole seat for os.replace/Path.replace/os.rename and fix every copy; write-once skip-if-exists stores first, per-tick state files self-heal so hot paths may skip fsync",
     "check_text": ("skill_runtime", "要全 seat 搜 `os.replace`／`Path.replace`／`os.rename`")},
    # 2026-10-27 f1s-evolve tick: ledger 4e0557dfcc97 (kyloren IG card 006f5f07) + 984a5f25ed10 resent
    {"id": "EVO-ig-900-to-900k-noise", "element": "kyloren card 006f5f07d1bd3ee6: IG reel 「從900美元創造超過90萬美元」 (keep learning, grow a small account)", "verdict": "INFO",
     "requires": None, "detail": "rejected as noise: untrusted trading self-promotion with no procedure, tool or verifiable claim; harvest score came from low coverage, not content; triage class noise",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    {"id": "EVO-v30-leadlag-resent-covered", "element": "ai_trader memory v30-cash-intraday-leadlag-20261024 re-harvested (ledger 984a5f25ed10)", "verdict": "INFO",
     "requires": None, "detail": "already in F1S: zero-fill/sha256 journal = EVO-powerloss-zero-fill, fsync before replace = EVO-fsync-before-rename, 09:00:00 prior-close row = windows-runtime-pitfalls; v30 verdict and correlations stay seat-local; no change",
     "check_text": ("skill_runtime", "盤中檔的第一列也可能是前一日收盤")},
    # 2026-10-26 operator (side session): measure the context every conversation pays and cut the measured duplicates.
    {"id": "OP-contract-once-per-conversation", "element": "a conversation receives each contract line once; skills idle 30 days leave the listing", "verdict": "REFINE",
     "requires": None, "detail": "claude_session_hook._contract_dedup drops FAMES CORE / TOKEN CORE / red-line lines the conversation already holds, SessionStart resets; audit-session-tax.py --replay over 32 ai_darkhero conversations: fixed 17,914 -> 16,502 tok, mid-turn 97,079 -> 17,946, later prompts 112,708 -> 45,367 (test_midturn_refresh)",
     "check_text": ("session_hook", "def _contract_dedup(")},
    # f1s-evolve 2026-10-27: ai_photo retouch-look-preferences (ledger fb28de79fa48) + burnin-subtitle-ocr-learning re-sent (ledger 42161c5cf4fd)
    {"id": "EVO-photo-retouch-taste-seat-local", "element": "ai_photo memory retouch-look-preferences: faces soft / background sharp, stronger sky+dehaze, crisp eyes, night coloured light keeps its colour, judge by ai_photo.compare face+sky crops", "verdict": "INFO",
     "requires": None, "detail": "rejected as seat-specific: operator aesthetic taste for one seat's develop pipeline (finish.py masks, ai_photo.compare), no fleet procedure or runtime trap; stays in the ai_photo memory; no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    {"id": "EVO-burnin-duplicate-20261027", "element": "hub-root burnin-subtitle-ocr-learning proposal re-sent 2026-10-27 (ledger 42161c5cf4fd, memory unchanged since 2026-10-18)", "verdict": "INFO",
     "requires": None, "detail": "already integrated 2026-10-19 as EVO-theater-cpu-thread-cap and EVO-theater-fansub-corpus (also EVO-burnin-duplicate-20261021); windows-runtime-pitfalls CPU 配額與批次負載 still holds the thread cap and HSV mask; no text added",
     "check_text": ("skill_runtime", "intra_op_num_threads")},
    # f1s-evolve 2026-10-27: ai_trader matrix-lane-v21 (ledger 6ce432243457) + credit-options-v23 (ledger 8fcbf62f78bb) re-sent
    {"id": "EVO-matrix-v21-duplicate-20261027", "element": "ai_trader matrix-lane-v21-two-boards-20261018 proposal re-sent again (ledger 6ce432243457)", "verdict": "INFO",
     "requires": None, "detail": "already integrated 2026-10-18 as EVO-trader-narrow-output (mtm-mto-first: find the parameter that produced the narrowness first) and EVO-trader-v21-seat-local; also EVO-matrix-v21-duplicate-20261022; memory unchanged (modified 2026-10-17T19:33Z); no text added",
     "check_text": ("skill_method", "先找出產生窄度的參數")},
    {"id": "EVO-credit-options-v23-duplicate-20261027", "element": "ai_trader credit-options-v23-20261021 proposal re-sent (ledger 8fcbf62f78bb)", "verdict": "INFO",
     "requires": None, "detail": "already decided 2026-10-23 as EVO-trader-credit-options-v23 (seat-local verdict + dataset inventory); the generic part (pre-register before the first number) is ztm-verify-before-done's registration rule; memory unchanged (modified 2026-10-20T20:27Z); no text added",
     "check_text": ("skill_verify", "早於結論收據")},
    # f1s-evolve 2026-10-27: youtube AI news card 0e98692f (ledger c1c71ed6e776) + threads Codex K-line card 7c41a9e8 (ledger ebb06cf6ee03)
    {"id": "EVO-openai-moonshot-distill-news-noise", "element": "f1s-sources card 0e98692fb21f5e29: AI新聞快報 2026/10/02, OpenAI accuses Moonshot of adversarial distillation of chain of thought", "verdict": "INFO",
     "requires": None, "detail": "rejected as noise: untrusted news report of an unresolved dispute (the card itself says no attribution evidence was disclosed); no procedure, tool or runtime trap for F1S; harvest score came from low coverage, not content; no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    {"id": "EVO-codex-kline-analog-seat-local", "element": "kyloren card 7c41a9e81787358a: threads post, ask Codex to find special TSMC K-line patterns and look up what followed historically instead of predicting up/down", "verdict": "INFO",
     "requires": None, "detail": "rejected as seat-specific: a 398-char trading idea with no code, data or measured result; historical-analog studies belong to ai_trader's own backtest lanes, and any trading use already needs pre-registration under ztm-verify-before-done; no text added",
     "check_text": ("skill_verify", "早於結論收據")},
    # f1s-evolve 2026-10-27: youtube Meta layoff card 01ec60a5 (ledger 19d552db5936) + ai_trader ipo-auction-source re-sent (ledger 0d656711de0e)
    {"id": "EVO-meta-layoff-training-news-noise", "element": "f1s-sources card 01ec60a55cd8f814: Meta layoff recording, employees' computer use collected to train AI", "verdict": "INFO",
     "requires": None, "detail": "rejected as noise: untrusted news report about another company's data policy; no procedure, tool or runtime trap for F1S; harvest score came from low coverage, not content; no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    {"id": "EVO-ipo-auction-duplicate-20261027", "element": "ai_trader ipo-auction-source-20261023 proposal re-sent (ledger 0d656711de0e)", "verdict": "INFO",
     "requires": None, "detail": "already integrated 2026-10-24 as EVO-silent-param-fallback (windows-runtime-pitfalls: unparsed parameters silently fall back to defaults); fees, 美國標 and the feasibility look are ai_trader lane data and stay in its memory; memory unchanged (modified 2026-10-23T01:45Z); no text added",
     "check_text": ("skill_runtime", "伺服器看不懂的參數會靜默退回預設值")},
    # f1s-evolve 2026-10-27: ai_trader forward-design-pins proposal (test eae82caba)
    {"id": "EVO-trader-forward-design-pins", "element": "ai_trader: pin a pre-registered design's gate files in a test, line endings normalized (tests/test_forward_design_pins.py, eae82caba)", "verdict": "REFINE",
     "requires": None, "detail": "adopted into ztm-verify-before-done registration step (2): committed-and-unmodified does not stop a shared gate file from moving a running forward test's design hash; verified 2026-10-27: test passes on HEAD, matrix_data_pull.py at ee5e6e523~1 hashes 24e9e047 vs pin 23e37846, cost_model.yaml at 014ed0474~1 eb256b49 vs pin 3735964c, cost_gate.py 65527dec vs pin f03902f9",
     "check_text": ("skill_verify", "CRLF 當 LF 讀")},
    # f1s-evolve 2026-10-27: threads Claude Code quota card 0427566a (ledger 61c2394ae62f) + youtube Karpathy bottleneck card 0e74e819 (ledger 913dc03fb1c2)
    {"id": "EVO-claude-quota-12-tips-covered", "element": "kyloren card 0427566a9579dd24: threads post, 12 Claude Code quota tips (/context for context hogs, CLAUDE.md slimming, MCP, prompt cache)", "verdict": "INFO",
     "requires": None, "detail": "already covered: token-preflight measures per-turn load with /context (system tools, MCP tools, memory files, skills) before trimming and prefers a fork because it shares the prompt cache; context-budget-measure memory holds the 10-26 cut; the card carries only headlines, the 12 tips themselves are not in it; no text added",
     "check_text": ("skill_preflight", "context categories: system tools, MCP tools, memory files, skills")},
    {"id": "EVO-human-absorption-bottleneck-covered", "element": "f1s-sources card 0e74e819b381a6f1: youtube, an OpenAI founding member says human absorption of knowledge is now the slowest part of the system", "verdict": "INFO",
     "requires": None, "detail": "rejected as already covered: the actionable part (report so the human absorbs it fast) is f1s-intake's conclusion-first two-sentence rule; the rest is commentary with a noisy ASR transcript, no procedure, tool or runtime trap; no text added",
     "check_text": ("skill_intake", "繁體中文、結論先行、兩句講完")},
    # f1s-evolve 2026-10-27: youtube Claude diary/police card 01421b13 (ledger 5e00e67a1974) + youtube OpenAI ChatGPT usage report card 0027884e (ledger ee67ec422819)
    {"id": "EVO-ai-chat-not-private-covered", "element": "f1s-sources card 01421b13c0b87286: AI新聞快報 2026/10/07, Claude conversations are reviewed and may be reported to police; flagged content retained up to 2 years", "verdict": "INFO",
     "requires": None, "detail": "rejected as already covered: the actionable part (whatever is typed to a hosted model leaves the machine) is the T1 金鑰 line plus mtm-api-pool-offload's do-not-send list (keys, account data, UT.xlsx, operator-private files; the query goes, the data does not); the rest is an untrusted news report of one case; no text added",
     "check_text": ("skill_pool", "查詢字串可以送，資料本身不送")},
    {"id": "EVO-chatgpt-usage-report-news-noise", "element": "f1s-sources card 0027884e1600c4cc: youtube summary of an OpenAI report on how people use ChatGPT (non-work share 53%->73%, decision support over execution)", "verdict": "INFO",
     "requires": None, "detail": "rejected as noise: consumer usage statistics of another product; no procedure, tool or runtime trap for F1S; harvest score came from low coverage, not content; no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    # f1s-evolve 2026-10-27: f1s-mesh proposals (ledger 0403262d441a, 8b26e1f75dca, 7102ae8d42ff, 608c3061b4d5, b86413a95291; edges 6f969a69f485, e2b6ae472191, 67402da0e27c, 78100f986603, dd9a9430a953)
    {"id": "EVO-file-timestamp-is-export-time", "element": "jci_taipei jci-minutes-web-pipeline-benchmark: LINE-exported m4a creation_time = export time (22:08:03-22:08:15), never the recording time", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls 時間與資料新鮮度: embedded file timestamps only compared against a trusted source and flagged past a threshold, never written as fact; per-stage minutes timings, provider failures and the quality backlog stay in jci_taipei memory",
     "check_text": ("skill_runtime", "檔案內嵌的時間戳記可能是匯出時間，不是事件時間")},
    {"id": "EVO-absence-refusal-is-a-lock", "element": "ai_trader manual-source-label-is-privileged: a refusal that held because a provider was missing was removed when the provider was bound; default source=manual skipped gates", "verdict": "REFINE",
     "requires": None, "detail": "independent-review step 4: list refusals that depend on a component's absence before adding it; check privileged default labels; LIVE high-water-mark semantics stay in ai_trader",
     "check_text": ("skill_review", "A refusal that holds only because a component is missing is also a lock")},
    {"id": "EVO-ai-career-google-sso-seat-specific", "element": "ai_career ztm-ai-career-google-sso-edge: GCP redirect slot swap, stale Google tab, /api/auth/login deep link", "verdict": "INFO",
     "requires": None, "detail": "rejected: client id, callbacks and slot map are one seat's data; the general part is already fleet text (ztm-oauth-redirect-fleet cites swap-gcp-oauth-redirect-uri-slots, browser-login-handoff owns the login lane); its 'Codex Edge ONLY' surface contradicts the built-in-browser policy; no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    {"id": "EVO-jci-minutes-stt-superseded", "element": "jci_taipei mtm-meeting-minutes-stt: memext Drive ids, distill-media local STT, clasp drive.file download blocker", "verdict": "INFO",
     "requires": None, "detail": "rejected: superseded by the seat's own mtm-meeting-minutes-pipeline; ids and format are jci data; its clasp claim is stale against jci-drive-line-web-transfer's measured scope table (drive.file reads any file's data); STT routing is mtm-api-pool-offload; no text added",
     "check_text": ("skill_jci_transfer", "讀任何檔案的資料、寫自己建立的檔")},
    {"id": "EVO-jci-minutes-pipeline-seat-specific", "element": "jci_taipei mtm-meeting-minutes-pipeline: IN/OUT folder contract, committee naming, 04 speaker attribution, /api/meetings/minutes/run", "verdict": "INFO",
     "requires": None, "detail": "rejected as seat-specific: committee minutes format and website route belong to jci_taipei; the one general rule (names outside the closed attendee set stay unresolved) is T1 嚴禁猜; no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    {"id": "EVO-jci-line-file-to-drive-covered", "element": "jci_taipei mtm-line-file-to-drive: LINE file -> meetings/drive/<date> + Drive upload; LINE cannot list past group files", "verdict": "INFO",
     "requires": None, "detail": "rejected as already covered: line-oa-ingest states LINE has no chat-history endpoint (webhook archive only) and jci-drive-line-web-transfer owns the LINE->Drive routes; layout and --nth are jci data; no text added",
     "check_text": ("skill_line_ingest", "LINE exposes an endpoint for arbitrary chat-history retrieval")},
    {"id": "EVO-dsh-handoff-parked", "element": "ai_trader dsh-deepseek-harness-handoff: DSH :3080 dispatch, iterate lane, A770 keep-alive contention", "verdict": "INFO",
     "requires": None, "detail": "rejected: DSH is parked since 2026-10-05 (riders off); the inspection-only / grade-on-tool-events lesson and the GPU arbitration are curator memory (dsh-qwen3-fabricates-tool-results, dsh-task-dispatch, ollama-resident-displacement) and load_grant owns load increases; no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    # f1s-evolve 2026-10-27: ai_darkhero SkillSpector install gate proposal (operator shared NVIDIA SkillSpector)
    {"id": "EVO-skillspector-install-gate", "element": "SkillSpector (f1s-mesh gate, --no-llm, hub-baseline.yaml) before a skill enters canon: fleet-skill-vet import + asu-verify promote", "verdict": "REFINE",
     "requires": None, "detail": "adopted at the real canon entry points: fleet-skill-vet.skillspector_gate stages the external SKILL.md and refuses on block or held; asu-verify adds skillspector_ok to the promote checks; tests in test_f1s_mesh.py",
     "check_text": ("skill_vet", "Fail closed: block (score >= 50 or a HIGH/CRITICAL finding) and held (scanner missing/failed) both refuse.")},
    {"id": "EVO-skillspector-promote-check", "element": "asu-verify verify_draft runs SkillSpector on the draft folder", "verdict": "REFINE",
     "requires": None, "detail": "a seat draft promoted into canon must pass the same gate as a lateral mesh edge",
     "check_text": ("asu_verify", "\"skillspector_ok\": spector[\"ok\"]")},
    {"id": "EVO-skillspector-deploy-absorb-not-gated", "element": "proposal parts: gate fleet-skill-sync _deploy_to_root and cmd_absorb", "verdict": "INFO",
     "requires": None, "detail": "rejected: every agent surface is link_mode=junction into canon, so a deploy-time refusal cannot stop content and fail-closed would only drop 13 skills (fames, token-preflight, agc-auto-goal-compact, ztm-git-ship) from new seats; cmd_absorb writes the incubator, which is never deployed; the 13 baseline findings stay for per-finding review, no baseline accepted",
     "check_text": ("skill_vet", "Deploy is not gated: every agent surface is a junction into canon, so canon itself is the install point.")},
    # f1s-evolve 2026-10-28: ai_darkhero SkillSpector review proposal (E1 api.typesafe.ai)
    {"id": "EVO-jev-paid-gate", "element": "jev_turn_router network path calls paid typesafe jev-1.13.0 whenever a key exists", "verdict": "REFINE",
     "requires": None, "detail": "adopted: T1 free-runtime forbids paid models at runtime; the real transport now needs LLM_ALLOW_PAID=1 (fleet convention, f1s-mesh PAID_GATE) before any credential read, else stop paid_provider_not_allowed and Jev stays local/free; injected test transports unaffected; test_paid_provider_needs_llm_allow_paid",
     "check_text": ("jev_router", "if os.environ.get('LLM_ALLOW_PAID') != '1':")},
    # f1s-evolve 2026-10-28: ai_photo quota-budget proposal (Cloudflare account cap exhausted 2026-10-27)
    {"id": "EVO-cf-request-budget", "element": "Worker deploy with polling/retries/self-fetch states requests/day, under 20% of the shared account cap; bulk media local->Drive via rclone, never a Worker", "verdict": "REFINE",
     "requires": None, "detail": "adopted (rules 1+4) into deploy-nextjs-cloudflare local-build-first policy: one ai-jci-taipei deploy spent 376,966 requests in a UTC day and took every seat's Worker down",
     "check_text": ("skill_deploy_cf", "must state its expected requests/day in the ship receipt and stay under 20% of the account cap")},
    {"id": "EVO-quota-rider-noop-fingerprint", "element": "periodic rider talking to a quota'd remote short-circuits on a local change fingerprint (zero remote calls on a no-change tick)", "verdict": "REFINE",
     "requires": None, "detail": "adopted (rule 3) into windows-runtime-pitfalls retry/lock/schedule section with the ai_photo drive_sync reference implementation and its test",
     "check_text": ("skill_runtime", "沒變就零遠端呼叫直接結束")},
    {"id": "EVO-cf-usage-alert-rider-not-armed", "element": "new HubClock rider (<=15m) reading workersInvocationsAdaptive, alerting at 50%/80% of 100k", "verdict": "INFO",
     "requires": None, "detail": "not armed: a new periodic rider needs operator authorization (T1 授權; HubClock rider arming = operator); cf-worker-health.py exists but is not in hosts.json; the request-budget rule is carried by EVO-cf-request-budget",
     "check_text": ("skill_deploy_cf", "Request budget before ship: every seat's Workers share one account cap")},
    # f1s-evolve 2026-10-28: ai_trader power-cut JSONL + keyless world-macro proposals (commits 00d2d65f8, ff5159dc6)
    {"id": "EVO-jsonl-powercut-torn-tail", "element": "append-only JSONL readers strip NUL debris and skip bad lines; appenders newline a torn tail first; design-pinned gate readers excepted", "verdict": "REFINE",
     "requires": None, "detail": "adopted into windows-runtime-pitfalls time/freshness section next to the Kernel-Power zero-file rule (7/17,065 files with NUL runs)",
     "check_text": ("skill_runtime", "新列才不會黏在殘骸上")},
    {"id": "EVO-keyless-world-macro-ladder", "element": "keyless FRED/IMF WEO/World Bank/OECD SDMX/BIS/ECB tier-1 sources, stooq excluded", "verdict": "REFINE",
     "requires": None, "detail": "adopted into mtm-api-pool-offload rules; not registered in api-matrix (keyless, and _secrets is out of scope); f1s-harvest api only catalogs keyed hosts",
     "check_text": ("skill_pool", "免金鑰世界總經第 1 層來源")},
    {"id": "EVO-honest-user-agent", "element": "fixed-pull scripts send an honest tool User-Agent, not a bare browser OS string", "verdict": "REFINE",
     "requires": None, "detail": "adopted into mtm-api-pool-offload rules (FRED timeout / IMF 403 on fake browser UA, measured 10 combinations)",
     "check_text": ("skill_pool", "不要裝成瀏覽器")},
    {"id": "EVO-publish-gate-remote-url", "element": "PROOF publish gate ignores a public path segment inside a remote URL unless the command uploads", "verdict": "REFINE",
     "requires": None, "detail": "claude-proof-hook _publish_gate drops URLs from shell text unless UPLOAD_FLAG; local public targets and uploads still denied (test_proof_publish_gate 4 new cases)",
     "check_text": ("proof_hook", "if not UPLOAD_FLAG.search(text):")},
    {"id": "EVO-new-source-own-store", "element": "a new data source that only adds columns to a store pinned hypotheses read gets its own store", "verdict": "REFINE",
     "requires": None, "detail": "adopted into mtm-mto-first reuse rule as its boundary",
     "check_text": ("skill_mto", "要另開\n  自己的 store")},
    # f1s-evolve 2026-10-28: three harvested seat corrections (ledger 8ccead0a12ad, 6f5362c554b8, 839f057e494d)
    {"id": "EVO-two-way-sync-newest-wins", "element": "ai_metadata 2026-10-27 (operator 「為何chrome的書籤列沒有反向被edge最新的書籤狀態更新?…對應的檔案應該移走刪除才對」): Chrome stayed un-synced because the seat assumed its encrypted bookmark file could not be written; orphan download folders were missed by substring name matching", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls 時間與資料新鮮度: two-store sync judges each item by newest state + its own timestamp, order move/duplicate/new/delete, both directions written; an untested 'cannot write' is UNKNOWN not a limit (test it on the sibling mechanism first); derived files of deleted source items go to _delete/<date> (permanent delete stays the operator's, T1 刪除); orphan matching by exact account name or id, never name fragments; evidence ai_metadata conversation 1f70d8d7 (commit 5d213312, 58 tests; P:/_delete/2026-10-26-deleted-bookmarks)",
     "check_text": ("skill_runtime", "兩個來源互相同步，逐項以最新狀態與時間戳判定")},
    {"id": "EVO-reference-is-a-measured-target", "element": "ai_photo 2026-10-27 (operator 「seth的眼睛修太多 不自然…大小眼不對勁…我講過理想上seth的眼睛狀態是C:\\scss\\janeliao\\20261010」): the seat pasted the reference set's eyes onto IMG_0054/0055 (asymmetric, wrong light) and only sharpened IMG_0063 (under-eye -15..-29 vs reference -10..-13)", "verdict": "REFINE",
     "requires": None, "detail": "ztm-verify-before-done new section: a named reference stays binding for every later edit of the task; measure the reference, move only the subject's own content toward the numbers with caps and paired-feature invariants, never paste the reference's pixels/passages; closure carries reference/before/after plus a side-by-side and names untouched parts; taste numbers stay seat-local (EVO-photo-retouch-taste-seat-local kept); evidence ai_photo conversation ddc955d5 (commit 990d901, 58 tests, open-eye ratio 0.365 from the 20261010 set)",
     "check_text": ("skill_verify", "參考樣本是量測目標，不是素材")},
    {"id": "EVO-theater-video-sort-task-spec", "element": "ai_theater 2026-10-27 harvest 'correction' 8d1987bd90df: operator task spec for P:/ai_download -> Q: video classification (>300 MB, >10 min, actress folders, learn rules from Q:)", "verdict": "INFO",
     "requires": None, "detail": "rejected as seat-specific: a task statement, not an operator correction (conversation d9626280 shows no rebuke; the seat reused ai_metadata star_registry/javlibrary_zct/q_drive_tidy, learned 186 prefix rules from the sorted corpus, moved 97 files with an undo ledger and left the rider un-armed); the generalizable parts already exist (mtm-mto-first reuse order + f1s-harvest tools catalog RL-tools-catalog, T1 HubClock authorization); no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    # f1s-evolve 2026-10-28 (second run): ai_photo 6f5362c554b8 + ai_theater 839f057e494d re-sent because the 04:06 run was held
    {"id": "EVO-reference-target-duplicate-20261028", "element": "ai_photo correction ac6594bf97f4 proposal re-sent (ledger 6f5362c554b8, same operator words as EVO-reference-is-a-measured-target)", "verdict": "INFO",
     "requires": None, "detail": "already adopted in the 2026-10-28 04:06 run as EVO-reference-is-a-measured-target (ztm-verify-before-done section 參考樣本是量測目標，不是素材); that run was held unshipped by a rider rewrite of STANDUP.md, not by a defect in the text; the skill text rides with this run; no text added",
     "check_text": ("skill_verify", "參考樣本是量測目標，不是素材")},
    {"id": "EVO-theater-video-sort-duplicate-20261028", "element": "ai_theater correction 8d1987bd90df proposal re-sent (ledger 839f057e494d)", "verdict": "INFO",
     "requires": None, "detail": "already rejected in the 2026-10-28 04:06 run as EVO-theater-video-sort-task-spec (a task statement, seat-specific; reuse order and HubClock authorization already in canon); re-send carries no new operator words; no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    {"id": "EVO-evolve-tick-rider-digest-not-concurrent", "element": "f1s-evolve-tick 2026-10-28 04:06 run held_for_curator with unclaimed=[_skill/engines/STANDUP.md]: curate-tick's a2a-standup (6h cadence) rewrote the digest at 04:12 while the run's tests took 5m37s", "verdict": "REFINE",
     "requires": None, "detail": "f1s-evolve-tick RIDER_OUTPUTS: digests under the package surface that HubClock riders rewrite are not concurrent session edits and never hold a ship; test test_a_rider_digest_rewritten_during_the_run_is_not_a_concurrent_edit; the held 04:06 package (ztm-verify-before-done, windows-runtime-pitfalls) is re-declared by this run",
     "check_text": ("evolve_engine", "p not in RIDER_OUTPUTS")},
    {"id": "EVO-trader-retire-after-verdict", "element": "ai_trader 2026-10-28 F1S proposal: code_reachability.py takes tests/ as roots (lines 109-111), so a research script imported only by its own test counts as reached; the v29/v30 NOT_QUALIFIED lanes each stayed 4 days", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls 程式可達性: the retire check is 'who imports or dispatches it besides its own test' == empty; script and its test leave in one commit, receipts and raw data stay in runtime, the puller that owns the store (incl. verify) stays; evidence ai_trader 7b9b59da0 (6 files, -1,921 lines, unreached 15->13, re-run 2026-10-28 = 13)",
     "check_text": ("skill_runtime", "除了自己的測試，還有誰")},
    # f1s-evolve 2026-10-28 (third run): ai_metadata 8ccead0a12ad re-sent + ai_photo fa83063cb679 (correction c6a21ad83c10)
    {"id": "EVO-two-way-sync-duplicate-20261028", "element": "ai_metadata correction b95734be558d proposal re-sent (ledger 8ccead0a12ad, same operator words as EVO-two-way-sync-newest-wins)", "verdict": "INFO",
     "requires": None, "detail": "already adopted in the 2026-10-28 04:06 run as EVO-two-way-sync-newest-wins (windows-runtime-pitfalls 時間與資料新鮮度 two-store sync bullet, present in the installed skill text); re-send carries no new operator words; no text added",
     "check_text": ("skill_runtime", "兩個來源互相同步，逐項以最新狀態與時間戳判定")},
    {"id": "EVO-derived-store-not-larger-than-source", "element": "ai_photo 2026-10-27 (operator 「C:\\scss\\_photo_index < 這裡為什麼可以有24GB的無意義重複垃圾?」): compare --write saved every full-size output twice (_pick + review/compare), kept every superseded _prev.png and trial PNG unbounded, and share zips outlived their link expiry; 24 of 25 GB in a derived index folder", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls 時間與資料新鮮度: a derived store (review page, cache, index, share bundle) may not outgrow its source; ask whether the destination already holds the bytes before writing a full-size copy, review pages keep crops plus a path/sha256 pointer, superseded versions and expired bundles move to _delete/<date> (permanent delete stays the operator's, T1 刪除), closure reports du derived/source and treats derived > source as a defect; seat fix commits ai_photo bbd9d92 + 039fc79 (57 tests, IMG_0054 --write leaves only _prev.png); evidence conversation a7c6b9f2 (review/compare 17 G = 7.31 copy + 7.40 prev + 1.09 trial, share 7.5 G, 5-file sha256 identical)",
     "check_text": ("skill_runtime", "衍生儲存（對照頁、快取、索引、分享包）不得比來源大")},
    {"id": "EVO-write-gate-quoted-gt", "element": "ai_theater 2026-10-28 F1S proposal (ledger 3bc4e14f7f74, tool-error d267fae82ad1 x3): PreToolUse write gate denied `sed -i 's#(runtime/lexicon_deltas/<id>.json)#(Q:/_subtitle/_lexicon/deltas/<id>.json)#'` as creating `.json)#(Q:/.../<id>.json` (conversation 246184a8 2026-10-27 04:20)", "verdict": "REFINE",
     "requires": None, "detail": "claude-proof-hook QUOTED_GT: a quoted argument containing `>` is blanked before the redirect scan in _bash_md_targets (a quoted redirect target never contains `>`); test_proof_write_gate.py replays the real command; the proposal's own rule (「嚴禁產生任何未經請求的冗餘檔案」) is already rule ⑥ and is not re-added",
     "check_text": ("proof_hook", "QUOTED_GT = re.compile")},
    {"id": "EVO-write-gate-side-session-notes", "element": "same proposal, the other 2 of 3 denials (ai_theater 035d9756 2026-10-26, 246184a8 2026-10-27; also ai_nuwa 10-23, hub 10-26): Write of a hand-over note into %APPDATA%\\Claude\\side-session-notes\\local_<id>\\ was denied; the dispatching prompt says 「Shared notes folder for this group of sessions (outside the repo; … leave hand-over notes or large findings there)」 but names the folder, not the file, so doc_requested() is false; the seat then wrote the note as .txt to pass the gate", "verdict": "REFINE",
     "requires": None, "detail": "md_allowed_dirs += side-session-notes (harness-designated, outside every repo, read back by sibling sessions = rule ⑥ (a)); appsscript.json / .clasp.json added to md_allowed_names (clasp-required manifests, the one real ai_darkhero 2026-10-16 ocr-bridge denial); ztm-verify-before-done ⑥: a denied write is either a hook false positive to fix with a test or content for the reply - re-writing under another name or extension is bypassing the gate",
     "check_text": ("proof_hook", "\"side-session-notes\"")},
    {"id": "EVO-daily-error-window", "element": "ai_darkhero 2026-10-28 F1S proposal (ledger 0db1318cbaaf, tool-error 4c14851c9c68 x4): 3 of the 4 Bash denials are the 2026-10-13 15:38-15:52 gate-probe session c65d0212 (hook self-test), 15 days old; f1s_daily.lessons() emitted every signature with n>=3 regardless of age while render_live already filtered on e[\"last\"] >= since", "verdict": "REFINE",
     "requires": None, "detail": "f1s_daily.lessons: tool-error lessons need e[\"last\"] >= since (same 24h window as render_live); test_lessons_skip_stale_error_signatures; the proposal itself is rejected as stale noise (no new rule), the one fresh denial is covered by EVO-write-gate-side-session-notes",
     "check_text": ("daily_engine", "e[\"n\"] >= 3 and e[\"last\"] >= since")},
    # f1s-evolve 2026-10-28: viral-tool intake (ai_trader day-trader-skill) + two curator tool evaluations (Moli, Graphify)
    {"id": "EVO-viral-tool-intake-ladder", "element": "ai_trader 2026-10-28 F1S proposal (commit 5f4d0a02c, src/research/first_touch.py, 36 tests, memory first-touch-sim-20261028): IG/LINE-forwarded GitHub tool -> gh repo view licence/created/stars, gh api raw read of the script, no plugin install, grep for an existing equivalent, rebuild on own data as a fail-open report block labelled 模擬不是勝率", "verdict": "REFINE",
     "requires": None, "detail": "adopted into mtm-mto-first next to the 最後才自動化 threshold as the 爆紅工具的接法 ladder ①正牌+授權 ②只讀不裝 ③查同等功能 ④本地重做+測試 report block; step ⑤ generalizes the two curator evaluations below: a binary/package that must be installed to compare goes through SkillSpector, project scope only (~/.claude global = T1 授權), no paid model in its semantic pass (T1 free-runtime), and replaces an incumbent only on a same-input A/B measurement written into the receipt",
     "check_text": ("skill_mto", "爆紅工具的接法")},
    {"id": "EVO-moli-headless-eval-not-installed", "element": "ai_darkhero 2026-10-28 F1S proposal: evaluate Moli (Rust headless browser) instead of Playwright Chromium for public-page capture (line-oa-ingest fetch_public_social.mjs, mandate c hardware load)", "verdict": "INFO",
     "requires": None, "detail": "step ① done this tick, nothing installed: canonical repo is lexmount/moli (Apache-2.0, created 2026-08-10, 21,196 stars 2026-10-28; ldm0/athul-22 variants are not it); its own README benchmark is Chrome 99.8% vs Moli 81.9% task success and 697 vs 92 MiB median peak memory, so the reel's 103-vs-101 figure is a different measure and the proposal's acceptance (same IG embed batch, success not below Chromium, RSS in the receipt) stays required; install is a prebuilt binary via `irm ... | iex`, which the ladder forbids as-is (download the release asset, SkillSpector/supply-chain check, project scope); fetch_public_social.mjs launches msedge via Playwright and Moli answers Playwright connectOverCDP, so the A/B needs no script rewrite; the A/B itself is a curator task outside this unattended tick (installs a binary and adds load), not an F1S text change",
     "check_text": ("skill_mto", "換掉現役工具只憑同一批輸入的 A/B 量測")},
    {"id": "EVO-graphify-open-token-eval-not-installed", "element": "ai_darkhero 2026-10-28 F1S proposal: evaluate Graphify (codebase knowledge graph) to cut per-seat session-open tokens vs mtm-github-ops snapshot + audit-session-tax.py --replay", "verdict": "INFO",
     "requires": None, "detail": "step ① done this tick, nothing installed: canonical repo is Graphify-Labs/graphify (Apache-2.0, created 2026-04-03, 137,053 stars 2026-10-28, PyPI name graphifyy); code pass is local tree-sitter with 0 LLM credits, but the docs/media semantic pass uses the assistant's model (paid at runtime unless a free-pool key is configured = T1 free-runtime) and `graphify install` registers a user-scope skill under ~/.claude (T1 授權; `--project` scope exists); README sells a Cloud trial, ignore it; acceptance stays as proposed (same seat, same task --replay, open tokens clearly lower, result unchanged) and the replay is a curator task outside this tick, not an F1S text change",
     "check_text": ("skill_mto", "只裝到專案範圍")},
    {"id": "EVO-new-consumer-source-freshness", "element": "ai_trader 2026-10-28 F1S proposal: first_touch was built on a 1-min K cache whose collector its owner retired 10-20; the report only said pool_through, so staleness was silent", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls 時間與資料新鮮度: a new consumer of an existing source checks the writer is alive first, emits age + stale flag (report-only for research, conservative mode stays for trading), threshold = the market's longest closure (TW Lunar New Year ~10 days); evidence ai_trader 1ada5c877, src/research/first_touch.py MAX_POOL_AGE_DAYS",
     "check_text": ("skill_runtime", "接上既有資料源的新消費者，先查寫入者還活著")},
    # f1s-evolve 2026-10-28: threads quant-intro card 14e27927 (ledger 86408fe31ab5) + youtube DHH card 0ddc4421 (ledger 4ef8a90c8d0c)
    {"id": "EVO-quant-data-over-guess-noise", "element": "kyloren card 14e279276af0be15: threads post 「用數據取代猜測／用規則取代情緒」 with a quantx.com.tw course link", "verdict": "INFO",
     "requires": None, "detail": "rejected as noise: untrusted trading self-promotion (course funnel) with no procedure, tool or verifiable claim; its only general sentence is already T1 嚴禁猜 + ztm-verify-before-done 主張要有本回合證據否則 UNKNOWN, and entry/exit/risk rules are ai_trader's domain, not F1S text; harvest score came from low coverage of trading vocabulary, not content; no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    {"id": "EVO-dhh-ai-convert-noise", "element": "f1s-sources card 0ddc442162bd72fa: youtube, DHH went from AI sceptic to advocate, hand-written code as 牛仔文化", "verdict": "INFO",
     "requires": None, "detail": "rejected as noise: untrusted opinion/testimonial about another person's attitude change; no procedure, tool or runtime trap for F1S (ambiguous requests already route through f1s-intake 不准曲解), and the card's own quotes are partly mistranscribed (「手寫城市」); harvest score came from low coverage, not content; no text added",
     "check_text": ("skill_reverse", "generalize（附一句繁中規則）／seat-specific／noise")},
    # f1s-evolve 2026-10-28: ai_metadata proposal "參考 ai_library 訂閱/更新機制，自動抓 AI 與投資資訊來源" (A-F)
    {"id": "EVO-sources-due-first-round-robin", "element": "ai_metadata D: one-due-target round robin (src/ai_metadata/resident.py) so a burst of sources cannot starve the rider budget", "verdict": "REFINE",
     "requires": None, "detail": "measured gap: every curated feed (claude-code-changelog, gh-releases-*, hn-*, openrouter, hf) last listed 2026-10-18/19 while two deep YouTube backfills (@bestpartners 359, @shasha77 241 pending) took max_new each tick (last-tick.json skipped_budget 16); f1s-sources tick now polls due backfilled sources first, then backfills least-recently-listed first; test_due_latest_first_then_backfill_round_robin fails on the old order",
     "check_text": ("sources_engine", "then backfills least-recently-listed first (round robin")},
    {"id": "EVO-sources-bookmark-channel-deferred", "element": "ai_metadata A+B: Edge folder P/ai_feeds/<ai|invest>/<source> as subscription + probe-unknowns audit", "verdict": "INFO",
     "requires": None, "detail": "rejected for now: no ai_feeds folder exists in the Edge Default Bookmarks (grep count 0 on 2026-10-28), so the reader would be code without input; B already exists as listing: unsupported reported by status; revisit when the operator creates the folder",
     "check_text": ("sources_engine", "reported, never faked")},
    {"id": "EVO-sources-dedupe-render-feeds-rejected", "element": "ai_metadata C+E+F: logical-key dedupe/permanent block, static library page, arXiv/HF papers/SEC EDGAR feeds", "verdict": "INFO",
     "requires": None, "detail": "C already covered (item_hash of canonical URL + read set skip duplicates across feeds; errors back off 6h; no permanently dead source measured); E rejected: new page/artifact nobody asked for, cards + BRIEF already are the browse surface; F rejected this tick: arXiv lists hundreds/day with no relevance filter on curated feeds, SEC EDGAR needs a contact address in the User-Agent and investment data is ai_trader's lane; re-evaluate after the round-robin fix shows the existing feeds fresh",
     "check_text": ("sources_engine", "drop what is already read")},
    # f1s-evolve 2026-10-28: ai_trader proposal "tests must pin module-level paths resolved from the real checkout"
    {"id": "EVO-trader-checkout-path-state-leak", "element": "ai_trader cockpit_ensure: a failure only in one checkout is leaked path state (.env, owner stop file), not logic", "verdict": "REFINE",
     "requires": None, "detail": "verified 2026-10-28: commit 979d7a5e6 exists (3 failures reproduced in a clean worktree by adding a flag-only .env + stop file, 52 passed after pinning ENV_FILE and SIM_STOP) and memory cockpit-ensure-tests-env-leak.md exists; added to the 修 bug section of ztm-verify-before-done (one place, not duplicated into mtm-mto-first); behaviour is never loosened, so no red line weakened",
     "check_text": ("skill_verify", "只在某一個 checkout 紅、乾淨 worktree 綠的失敗是路徑狀態")},
    # f1s-evolve 2026-10-29: ai_trader proposals "語音轉文字四條實測規則" + "六條通用資料／研究規則"
    {"id": "EVO-long-audio-stt-dedupe-chunk-diarize", "element": "ai_trader 2026-10-29 4h restaurant recording: PCM-diff same-source check, parallel whisper throughput, chunk+latest-first, offline wespeaker + ward clustering", "verdict": "REFINE",
     "requires": None, "detail": "mtm-api-pool-offload 規則: evidence scratchpad stt_seg.py/run_all.py/diar.py (linkage='ward' branch present) and full/run_log.jsonl exist, transcript_full.txt 208,787 B; the proposal's 'about 3x realtime aggregate' was corrected to the run_log measure (24 chunks, ~14,493 s audio in ~2.5 h, per-chunk wall 234-6,992 s) and the batch is tied to the existing load_grant rule; gender-by-pitch kept as 推定 only",
     "check_text": ("skill_pool", "max|A−B|=0 就是同源")},
    {"id": "EVO-watch-growing-file-not-run-log", "element": "ai_trader 2026-10-29: watchdog on a per-chunk run_log reported stale for 25 min while 8 workers were writing", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls 時間與資料新鮮度: watch the file that grows every segment (JSONL/heartbeat), not the per-block run_log; same evidence run_log.jsonl",
     "check_text": ("skill_runtime", "看守長任務要盯「每段都會長的檔」")},
    {"id": "EVO-source-empty-ok-names-nan-enumeration", "element": "ai_trader v30 memory: holiday ok+0 rows, parse by name, text in numeric = NaN, API contract enumeration bounds history", "verdict": "REFINE",
     "requires": None, "detail": "windows-runtime-pitfalls 時間與資料新鮮度: one bullet; evidence C:/Users/sc/.claude/projects/C--ai-workspace-ai-trader/memory/v30-cash-intraday-leadlag-20261024.md line 20 (shioaji lists only live TXO, 1 login + 2 kbars); proposal rule 1 (09:00:00 row = previous close) already present in the 伺服器看不懂的參數 bullet, no text added for it",
     "check_text": ("skill_runtime", "「ok、0 列」不等於完成")},
    {"id": "EVO-trader-universe-holdout-seat-specific", "element": "ai_trader rules 5+6: count the ranked universe before blaming it (v14 1,127 names, K=3 + 5,000 cap); split explore/holdout before scanning, close the line if nothing >=0.05 same-sign", "verdict": "INFO",
     "requires": None, "detail": "rejected as seat-specific: both are ai_trader research-lane methodology already recorded in its own memory matrix-lane-v21-two-boards-20261018.md; the general part (mine the data before answering a complaint, pre-register then stop on fail) is already T1 嚴禁猜 + memory no-diagnostic-questions; thresholds 0.05 / K / 2023-07 are trading parameters, not F1S text; no text added",
     "check_text": ("skill_runtime", "API 列得到的才算存在")},
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
