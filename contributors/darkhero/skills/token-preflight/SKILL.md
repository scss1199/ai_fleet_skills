---
name: token-preflight
description: Route non-trivial coding, audit, research, deployment, or multi-step work through the smallest verified context path. Use before broad Read/Grep/Shell exploration, when a task may need parallel decomposition, when resuming a long Claude session, or when auditing token usage. FAMES is the complete public umbrella; FP, MTM, PFKT, SCF, AEX, and SEAL are bounded internal phases loaded only when active.
---

# Token Preflight

When the user invokes `FAMES`, load the `fames` skill and account for every phase under `_registry/fames-protocol.json`. Token Preflight remains the required first execution step; it is not a substitute for the full FAMES completion contract.

Run `python scripts/preflight.py --agent <seat> --task "<request>"` before broad exploration.

Keep only five fields hot: outcome, verification, state, next action, blocker.

Use this phase order:

1. FP defines Outcome and Verification.
2. MTM selects a bounded route and read budget.
3. PFKT activates only for multiple independently verifiable deliverables or explicit parallel work. Size each independent unit to fit one fresh context window, and resolve one unit per session or subagent (mattpocock to-tickets/wayfinder). Pick the helper by what it needs: a fresh subagent when only the result matters (run every test, report the broken ones); a fork when it needs this conversation's context or two approaches are tried side by side (it shares the prompt cache, so it costs less than re-briefing a subagent); an independent reviewer when direction or a repeated fix is in doubt. Start the subagents yourself in the same turn when the units are independent (the operator does not have to ask), and merge: when a subagent or a child session reports, read back its commit, tests or files, then fold the verified part into the parent's result and say what was not verified; a report is a lead, not evidence. A subagent's report is context tax too: its tool_result stays in the parent conversation for the rest of the task (`audit-session-tax.py` reports subagent calls and the tokens they put back per conversation; the F1S RECORD line reports subagents/turn), so a unit simple enough for the free pool goes to `mtm-api-pool-offload` instead of a Claude subagent, and a subagent gets a brief that asks for the conclusion, not the file dumps. Subagents inherit the session's effort; Claude Code ≥ 2.1.316 reads `CLAUDE_CODE_SUBAGENT_EFFORT` (e.g. `low`) for subagents whose definition names no effort, which would cut mechanical lanes (Explore, web-fetch, verifiers). Setting it is an environment-variable change, so it waits for the operator's authorization and for the Desktop bundle to reach 2.1.316 (`AppData/Roaming/Claude/claude-code`, 2.1.309 on 2026-11-02); never set it yourself.
   Looking for a fact across several files: `python %AI_WORKSPACE%\_skill\engines\f1s_map.py --seat <seat> --question "..." <paths>` before reading them. It returns file:line quotes checked against the source at 0 Claude tokens, and it is one command. A miss proves nothing; confirm what the decision rests on with a narrow Read.
   Code-search tool trial (XERJ, xerj-org/xerj, proposed 2026-11-05; not installed): a new search lane beside f1s_map/Grep/Everything is adopted only on a measured gap, never on stars or README numbers (its own README limits the gain to code the model has not memorized). Measure the tool_result bytes of the same recorded questions answered by Grep/Read versus the tool's CLI, with equal answers checked by hand; `audit-session-tax.py --replay` is not that measure (it replays hook injections only). Lexical mode on CPU only (no neural model on the A770), localhost dev mode only, and no MCP entry in ~/.claude without the operator's authorization. CodeGraph (colbymchenry/codegraph call-graph index, card a81897161291929c, 2026-11-05; not installed) joins the same trial under the same bar: it is the one shape f1s_map/Grep lack (who calls whom), but its 62 % token and 12 → 0 file-read figures are vendor numbers, so it is adopted only on a measured tool_result-bytes gap on the same recorded questions, CPU only.
   Script cost of injected text: `audit-session-tax.py --script-cost` fits Claude's own usage deltas (0 API calls); on 2026-11-12 (60 transcripts, 3989 kept pairs) one CJK char cost 1.23 tokens and one other char 0.45, so a zh-Hant hook line costs about what its English meaning does (a zh char carries ~3 English chars) and hook text was 14 % CJK by chars. Hook and directive bodies are not translated for token cost; operator quotes stay verbatim; re-measure before any such rewrite.
   The split itself is an engine, not a habit (operator 2026-11-01): `python %AI_WORKSPACE%\_skill\engines\f1s_parallel.py plan --seat <seat> --goal "<原話>" --task-class <slug> (--units UNITS.json | --auto --task-file T)` turns the task into units tagged template / retrieval / transform / judgment, each with a mechanical verifier (json_schema / regex / contains / command) where one exists; an extraction adds `"quote_key": "quote"` so every item must quote its own source text, which is what catches an invented fact (a shape check cannot); `run --seat <seat> --plan <id>` fans the verifier-bearing units out to the free pool in parallel, verifies every answer, escalates a rejected one up the ladder free → local → claude_sub → main, and leaves a brief for each unit that needs Claude (spawn that subagent yourself, then `close --unit <id> --evidence <file>`; a unit that passed its verifier but is wrong on your judgment gets `close --unit <id> --reject --reason "<why>"`, which cancels its accepted ledger row so `allocate` stops trusting that lane); concurrent `run`s of different plans on one seat are safe (each save merges only its own plan under a store lock); `merge` reports which units are accepted and how many Claude tokens the free lanes avoided. Every attempt lands in `_registry/f1s-parallel/ledger.jsonl` (seat, task class, difficulty, lane, model, params, latency, verified, accepted) and `allocate` reads it back, so the next plan for the same seat and task class picks the cheapest lane with ≥ 80 % acceptance over ≥ 3 attempts and explores otherwise. Judgment units never go to a free or local model; an unverified answer is never accepted; both are theorems in `_lean/fames/F1SParallel.lean`, bound by `parallel_conformance.py`. Who uses it is measured, not assumed: `python %AI_WORKSPACE%\_skill\engines\f1s_control.py status` shows each seat's new files, tool calls and real accepted units, and a seat over its limit gets one complete-prompt order that is judged by the re-measured number. A test of the pipeline uses a task class starting `probe-`, which never counts as adoption or as a track record for `allocate`.
4. SCF computes residual only after a verified result exists.
5. AEX activates only when a verified cross-cycle residual remains.
6. SEAL checks evidence, identity, and graph closure after any active AEX adaptation.

Treat probe/config errors as UNKNOWN. Never treat UNKNOWN as clear, consumed, healthy, or complete. Do not load linked protocols until their phase becomes active.

The script writes a receipt. A session touch without a receipt is not skill consumption. Reuse the receipt while the task fingerprint and referenced artifact hashes are unchanged.

Read [references/concept-map.md](references/concept-map.md) only when changing framework architecture.

## Session fan-out and merge (operator 2026-10-28)

Two habits, mechanised by `_skill/engines/session-consolidate.py`:

1. **Fan-out.** When intake yields two or more independent, separately verifiable problems — or a Claude Code
   home-page style suggestion such as 「繼續 `<branch>` 上進行中的工作：查看未提交的變更…」 — open one session per
   item in the same turn (`start_session`, `user_asked` when the operator asked, `own_initiative` card otherwise; a
   session opened for another seat's cwd is detached to top level right after it starts). The parent only folds
   results back in after reading the child's commit, tests or files. `session-consolidate.py wip` lists every repo's
   uncommitted / unpushed / unmerged-branch work as such suggestions, routed to the owning seat (cwd basename);
   `plan --seat <seat>` turns them plus the seat's pending sessions into briefs.
2. **Merge.** At session open, line "6. SESSIONS/WIP" of the ZCT plan reports the seat's idle sessions (from
   `_registry/session-consolidate/<seat>.json`). `session-consolidate.py absorb --seat <seat>` prints each idle
   session's recap, pending ask, files and commits; the curator folds them into `goal_compact.py park <seat>
   "<milestone>"`, then `archive_session` the ones classified `archive:*` / `merge:absorb-recap`. `keep:pending-operator`
   sessions stay open; `noise:automated` (1-turn probes) are ignored. The engine never archives anything itself.
3. **Children do, not ask (ai_nuwa, operator 2026-11-11 「子對話就不要問以下這種問題 就直接做…平行做完並檢驗」).**
   A child session that finds the next approach for its own brief runs it: no `own_initiative` card, no operator
   question. Independent per-item units inside the brief run as parallel background pipelines; a reviewer starts on
   each PASS and the seat's own ship route on ACCEPT. A child never ends a turn on a status-only "waiting for X" note
   (run-until-no-next-step applies to children: one background waiter, then continue). A child stopped by the same
   defect twice resumes only when the parent forwards a dated operator quote. The parent reads back each claimed
   deploy (live sha, receipt, acceptance file) before reporting it. Red lines and operator-only decisions still stop.
   Evidence: C:/Users/sc/Downloads/_quick_output/20261111_nuwa_progress.txt.

## Every wake is a full cache read (F1S 2026-11-03, f1s_waste.py)

A background command's notification, an order and a Stop hook each re-read the whole conversation (0.15 to 0.2M weighted on a long chat). Run a command in the background only when it takes over about 2 minutes, wait for several with one waiter, and never wait on a rider's result: read it when you next need it. Subagents default to Sonnet; pass opus only for judgment. `python f1s_waste.py status --seat <seat>` shows what your cwd spends by cause.

背景等待不超過快取壽命（ai_metadata 2026-11-05，7 天量測：距上則回覆 >65 分鐘 cold 18／warm 0，5–55 分鐘幾乎全 warm；背景通知逾 60 分鐘回來 11 次重建 795k）：預期超過 55 分鐘的工作切成每批 55 分鐘內回報，或啟動後交給 tick／rider 接手並結束本回合；沒有結束時間的事件（等登入、等 Chrome 關）不開 waiter，由 tick 接。這是 run-until-no-next-step 的窗口限制，不是把下一步交回使用者：交給 tick 的那一步不寫成「下一步是 X」。證據：C:/Users/sc/.claude/projects/C--ai-workspace-ai-metadata/memory/cache-ttl-wait-rule.md

## Resident context audit (kyloren_bot 7b4adc46, 003a6bd3)

When auditing token usage, measure what is loaded on every turn before trimming anything: the app's usage tool (context categories: system tools, MCP tools, memory files, skills) or `/context`, and `/doctor` / `/skill-doctor` when the user runs them. Join the skill list with `_registry/skill-audit/*.jsonl` (actual Skill invocations) and propose dropping always-loaded items that are never invoked. Turning off the 1M window (`CLAUDE_CODE_DISABLE_1M_CONTEXT`) or editing `~/.claude/settings.json` is a global-settings change: operator authorization first.

Note (2026-08-13): the pointer to `cca-token-governance` was removed with that skill when operator
instruction removed everything Codex-related from this machine (skill and the Claude-to-Codex review
route are quarantined in `_delete/2026-08-13-codex-purge`, hub-skills/ and hub-engines/). Cross-provider
token usage is no longer a route this hub can take.
