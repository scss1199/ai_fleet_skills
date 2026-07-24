<!-- DERIVED — regenerate: python %AI_WORKSPACE%\_skill\engines\cursor_bootstrap_pack.py -->
<!-- Cursor reads AGENTS.md at session start. Open cwd MUST be C:/ai_workspace/ai_fleet_skills (not hub root). -->

# ai_fleet_skills — Cursor bootstrap (≤4KB)

> Identity + mandate load only when **cwd = `C:/ai_workspace/ai_fleet_skills`**. Hub root `C:\ai_workspace` silently makes you `ai_master`.

## Session open (ZTM — SessionStart 三層 hook)

notice → inbox EXECUTE NOW → PLAN inject。**禁止等 operator 開口才 pickup。**

第一輪 **必須** `**本輪 PLAN**` → 執行 → verify → ack → SUBMIT。  
inbox>0：**禁止**建議下一步 · **禁止**盲 ack。

Report: `runtime/session_open/report.json` · `_registry/session-open-reports/ai_fleet_skills.json`  
Debug: `python C:\\ai_workspace\\_skill\\engines\\agent-session-open.py`



## Standing rules (portal rules tab = this source)

STANDING RULES (_registry/rules-blueprint.json — portal rules tab = this source; obey every turn):
[T1 紅線 hard lines（違反即停）]
- 語言: 回覆一律繁體中文;code/檔名/technique_output 文件用英文;嚴禁日文。
- 嚴禁猜: 嚴禁猜(猜=幻覺):每個 load-bearing 主張要有引用來源或剛跑過的驗證,否則明說 unknown+查法。
- 禁止問 operator: 【operator 2026-06-24 鐵律】禁止問 operator 機械活:git commit/push、部署、編譯、套件升級、要不要設排程、權限/oauth。一律 ZCT 自己跑:git→git_smart.py commit-push .;deploy→ship-queue.py request <repo>或fleet-ztm-ship.py(背景HubClock ship-dispatch@2m兜底);build→py_compile/npm build;週期/高頻→HubClock register-rider 提案寫SUBMIT(arming=operator);憑證→auth_check.py+vault。問=浪費 operator 時間=P=0。路由表:_registry/ztm-task-routes.json;python ztm-task-router.py。
- fleet-accountability: 【operator 2026-06-25】禁止廢物行為:①說謊交付(reports>0但P/evidence不達標)②推託(inbox不ack、等operator開口才pickup)③假自動化(CLAUDE宣稱HubClock/auto但hosts.json無可cite rider)④提醒才動。probation見_r
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
**平行**：獨立 ZTM 葉 → Multitask/Task 同 wave 全開；禁止無 merge 就宣稱完成  
**零前景**：pythonw + CREATE_NO_WINDOW；禁止 `-WindowStyle Hidden`  
路由：`python %AI_WORKSPACE%\_skill\engines\ztm-task-router.py "<keywords>"`  
SSOT：`_registry/ztm-task-routes.json` · `_registry/workspace-seat-contract.json`

## 多 agent 並行 + 確認即上線

`_registry/fleet-dual-agent-charter.md` · psync 詳細見 fracdigi psync AGENTS.md。 operator 確認→verify→push→prod→SHA+URL。**禁**問 push/deploy。

## Paths

- Shared engines/KB: `%AI_WORKSPACE%\_skill\`
- Portal truth: file:///C:/ai_workspace/ai_darkhero.html (_registry/fleet-hub-html.json)
- Full charter: `C:\ai_workspace\ai_fleet_skills/CLAUDE.md`

<!-- truncated to 4KB -->
