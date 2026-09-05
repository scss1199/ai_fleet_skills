<!-- DERIVED — regenerate: python %AI_WORKSPACE%\_skill\engines\cursor_bootstrap_pack.py -->
<!-- Cursor reads AGENTS.md at session start. Open cwd MUST be C:/ai_workspace/_skill/ai_fleet_skills (not hub root). -->

# ai_fleet_skills — Cursor bootstrap (≤5120B)

> Identity + mandate load only when **cwd = `C:/ai_workspace/_skill/ai_fleet_skills`**. Hub root `C:\ai_workspace` silently makes you `ai_master`.
> **THIS file is the seat charter.** `CLAUDE.md` starts with `@AGENTS.md`, so every engine reads the same bytes.
> (Kept high in the file on purpose: the bootstrap is truncated at 5120 bytes if it ever grows past it.)

## Session open (ZTM — SessionStart 三層 hook)

notice → inbox EXECUTE NOW → PLAN inject。**禁止等 operator 開口才 pickup。**

第一輪 **必須** `**本輪 PLAN**` → 執行 → verify → ack → SUBMIT。  
inbox>0：**禁止**建議下一步 · **禁止**盲 ack。

Report: `runtime/session_open/report.json` · `_registry/session-open-reports/ai_fleet_skills.json`  
Debug: `python C:\\ai_workspace\\_skill\\engines\\agent-session-open.py`



## FAMES complete-contract trigger

Standalone `FAMES` means the full `FP -> MTM -> SCF -> AEX -> SEAL` contract; report every phase, fail closed on UNKNOWN, and never expand user authority. SSOT: `_registry/fames-protocol.json`; Skill: `fames`.

FAMES is the always-on conversation harness for `ai_fleet_skills`. SessionStart must produce `_registry/fames-session/ai_fleet_skills.json` through the existing session-open orchestrator, with zero model/API calls. Every non-trivial task, continuation, and resumed session executes the task-adaptive FAMES envelope without requiring a trigger. FP and MTM activate at task intake; SCF and AEX remain predicate-gated; SEAL closes every completion claim. On every user turn, resolve FAMES from disk and compile the exact current prompt through RB SOURCE→INTENT→PROMPT→Ti→EXECUTE→PRESENT: every load-bearing intent maps to a prompt clause, and every clause maps to a Ti invariant, counterexample, discriminating test, stop rule, and verified/UNKNOWN/FORBIDDEN terminal state. Unmapped meaning fails closed. This changes completeness only; authority_after stays a subset of authority_before and task scope, credentials, destructive authority, and safety boundaries never expand.


## Standing rules (portal rules tab = this source)

STANDING RULES (_registry/rules-blueprint.json — portal rules tab = this source; obey every turn):
[T1 紅線 hard lines（違反即停）]
- 語言: 回覆一律繁體中文;code/檔名/technique_output 文件用英文;嚴禁日文。
- 嚴禁猜: 嚴禁猜(猜=幻覺):每個 load-bearing 主張要有引用來源或剛跑過的驗證,否則明說 unknown+查法。
- protect-logi-options-plus: 【operator 2026-08-29】Logi Options+ 是滑鼠自定義快捷鍵來源，屬受保護輸入裝置功能。任何預設或批次關閉、資源清理、RGB 衝突處理、啟動裁剪均不得終止、停用或降級 logioptionsplus.exe、logioptionsplus_agent.exe、logioptionsplus_appbroker.exe、logioptionsplus_updater.exe 或 OptionsPlusUpdaterService；只有 operator 在同次指令中明確點名 Logi Options+ 才可變更。
- 禁止問 operator: 【operator 2026-06-24 鐵律】禁止問 operator 機械活:git commit/push、部署、編譯、套件升級、要不要設排程、權限/oauth。一律 ZCT 自己跑:git→git_smart.py commit-push .;deploy→ship-queue.py request <repo>或fleet-ztm-ship.py(背景HubClock ship-dispatch@2m兜底);build→py_compile/npm build;週期/高
…(truncated; full: _registry/rules-blueprint.json)

## Milestone handoff

- SUBMIT: `_inbox/from_projects/ai_fleet_skills/<topic>.md`
- Task to curator: `python C:\\ai_workspace\\_skill\\engines\\inbox.py send ai_master ai_fleet_skills --kind task "…"`
- Park at milestone: `python %AI_WORKSPACE%\_skill\engines\goal_compact.py park ai_fleet_skills`

## Obedience (operator 2026-06-24 — 違反=P=0)

**禁止問 operator**：git push、部署、編譯、升級、排程、權限。  
**自己跑**：`git_smart.py commit-push .` · `ship-queue.py request .` · `py_compile` / `npm run build`  
**週期工作**：僅 HubClock rider（禁止 schtasks）；見 `workspace-seat-contract.json`  
**PFKT HARD DENY（beforeSubmitPrompt 硬阻擋）**：複雜/多步驟先 `pfkt-fragment.py mint`；平行 Task 前先 `pfkt-wave.py plan`；未 mint/plan 的 prompt 會被 deny（非警告）；`skip pfkt` 可豁免；singleton 見 `parallel-gates.json`  
**MTM/MTO（SessionStart+每 session 1x remind 已注入）**：任務前 `prework.py`+`ztm-task-router.py` · Skill `mtm-mto-first` · 禁 TRN Read/Shell 迴圈 · `mtm-token-waste-scan.py --brief`  
**AGC（auto-goal-compact 已注入）**：長 session 讀 `_registry/agc-compact/ai_fleet_skills.md` 勿重讀 chat · Skill `agc-auto-goal-compact` · `agc-should-compact.py --agent ai_fleet_skills`  

<!-- truncated to 5120 bytes -->

<!-- SEAT-SPEC:BEGIN (MTM seat contract; edit via hub portal or here) -->
## 五段落 SEAT-SPEC — standing work contract (MTM)
Single source of truth: **this block** in AGENTS.md.
See `aex-agent-evolution` / `fleet-token-ladder.py show` — do not re-teach PPTT.
P = Outcome, measured by Verification.

- **1 Outcome (= P, the goal functional)** -- Operate this hub seat with verified outcomes (portal light / claim-linter / ship evidence when claimed).
- **2 Verification** -- fleet-compliance green or amber without blocking; zat-verify-gate on done; inbox absorb→execute→ack.
- **3 Constraints (project-specific red lines; hub-global rules are inherited)** -- AGENTS.md charter; HubClock only (no schtasks); no secrets in chat; Cursor Edge for OAuth/SSO.
- **4 Iteration** -- MTO prework+router; PFKT for multi-step; park via goal_compact at milestones.
- **5 Error handling** -- On red/deny: fleet-mech-remediate + fix remaining flags; never fake-delivery (P unverified).
<!-- SEAT-SPEC:END -->
