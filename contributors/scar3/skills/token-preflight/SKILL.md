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
3. PFKT activates only for multiple independently verifiable deliverables or explicit parallel work. Size each independent unit to fit one fresh context window, and resolve one unit per session or subagent (mattpocock to-tickets/wayfinder). Pick the helper by what it needs: a fresh subagent when only the result matters (run every test, report the broken ones); a fork when it needs this conversation's context or two approaches are tried side by side (it shares the prompt cache, so it costs less than re-briefing a subagent); an independent reviewer when direction or a repeated fix is in doubt.
4. SCF computes residual only after a verified result exists.
5. AEX activates only when a verified cross-cycle residual remains.
6. SEAL checks evidence, identity, and graph closure after any active AEX adaptation.

Treat probe/config errors as UNKNOWN. Never treat UNKNOWN as clear, consumed, healthy, or complete. Do not load linked protocols until their phase becomes active.

The script writes a receipt. A session touch without a receipt is not skill consumption. Reuse the receipt while the task fingerprint and referenced artifact hashes are unchanged.

Read [references/concept-map.md](references/concept-map.md) only when changing framework architecture.

## Resident context audit (kyloren_bot 7b4adc46, 003a6bd3)

When auditing token usage, measure what is loaded on every turn before trimming anything: the app's usage tool (context categories: system tools, MCP tools, memory files, skills) or `/context`, and `/doctor` / `/skill-doctor` when the user runs them. Join the skill list with `_registry/skill-audit/*.jsonl` (actual Skill invocations) and propose dropping always-loaded items that are never invoked. Turning off the 1M window (`CLAUDE_CODE_DISABLE_1M_CONTEXT`) or editing `~/.claude/settings.json` is a global-settings change: operator authorization first.

<!-- 2026-08-13: the line that pointed at `cca-token-governance` was removed with that skill.
     operator instruction: remove everything Codex-related from this machine; the skill and the
     Claude-to-Codex review route it governed are quarantined in
     _delete/2026-08-13-codex-purge (hub-skills/, hub-engines/). Cross-provider token usage is
     no longer a route this hub can take. -->
