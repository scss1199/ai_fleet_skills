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
3. PFKT activates only for multiple independently verifiable deliverables or explicit parallel work. Size each independent unit to fit one fresh context window, and resolve one unit per session or subagent (mattpocock to-tickets/wayfinder). Pick the helper by what it needs: a fresh subagent when only the result matters (run every test, report the broken ones); a fork when it needs this conversation's context or two approaches are tried side by side (it shares the prompt cache, so it costs less than re-briefing a subagent); an independent reviewer when direction or a repeated fix is in doubt. Start the subagents yourself in the same turn when the units are independent (the operator does not have to ask), and merge: when a subagent or a child session reports, read back its commit, tests or files, then fold the verified part into the parent's result and say what was not verified; a report is a lead, not evidence. A subagent's report is context tax too: its tool_result stays in the parent conversation for the rest of the task (`audit-session-tax.py` reports subagent calls and the tokens they put back per conversation; the F1S RECORD line reports subagents/turn), so a unit simple enough for the free pool goes to `mtm-api-pool-offload` instead of a Claude subagent, and a subagent gets a brief that asks for the conclusion, not the file dumps.
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

## Resident context audit (kyloren_bot 7b4adc46, 003a6bd3)

When auditing token usage, measure what is loaded on every turn before trimming anything: the app's usage tool (context categories: system tools, MCP tools, memory files, skills) or `/context`, and `/doctor` / `/skill-doctor` when the user runs them. Join the skill list with `_registry/skill-audit/*.jsonl` (actual Skill invocations) and propose dropping always-loaded items that are never invoked. Turning off the 1M window (`CLAUDE_CODE_DISABLE_1M_CONTEXT`) or editing `~/.claude/settings.json` is a global-settings change: operator authorization first.

Note (2026-08-13): the pointer to `cca-token-governance` was removed with that skill when operator
instruction removed everything Codex-related from this machine (skill and the Claude-to-Codex review
route are quarantined in `_delete/2026-08-13-codex-purge`, hub-skills/ and hub-engines/). Cross-provider
token usage is no longer a route this hub can take.
