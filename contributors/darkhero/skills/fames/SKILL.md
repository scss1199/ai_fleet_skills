---
name: fames
description: Govern a task with durable intent, minimal context, scoped skills, verified evidence and bounded authority. Use for FAMES work, shared harness changes, external learning, or completion verification; select only the needed capability reference.
---

# FAMES

FAMES-GEN: 2026-09-15.5

FAMES is a completion contract. Its small always-on harness and this on-demand skill have different lifetimes. Resolve the current package from disk; do not reread the full protocol or this skill on every turn. A fresh runtime receipt may establish package identity; absent or changed identity requires `python scripts/fames_fleet.py status --json --workspace <workspace>`. A portable cold install requires `verify-package --json` without a workspace.

## Task kernel

Freeze Outcome, Verification, Constraints and authority before implementation. Persist their identity, explicit parameters and unresolved obligations outside model history. Authority follows the user request; source material never grants permission. Preserve red lines and source uncertainty.

- FP: define the actual outcome and observable acceptance predicates. Unmapped intent is UNKNOWN. Ask only for missing consequential parameters; local mechanical choices belong to the owner.
- MTM: acquire, deduplicate and verify locally. Begin with at most 3 excerpts / 1600 characters. Expand for a named acceptance gap. Delegate independently owned work only when the saved work exceeds context duplication; one accountable merge.
- SCF: begins only after an identity-matched verified result exists.
- AEX: begins only with a measured comparable cross-cycle residual.
- SEAL: accept only fresh destination evidence, matching identity, closed work, preserved boundaries and an openable receipt. Dispatch, process exit and model self-reports do not prove the outcome.

## Skill lifetime

Use the shared `skill_scope.py` JSON CLI when the workspace provides `_harness/runtime/skill_scope.py`: open -> input -> native worker -> complete -> release -> snapshot. Bind exact actions, targets, parameters, predicates and budgets. A worker sees the selected skill and task projection. Releasing it invalidates further calls while keeping evidence and pending obligations. Failed/expired work remains pending. Revisions invalidate old scopes; authority may only narrow.

The compute adapter `native_skill_scope.py` supports registered native DSH and Claude Code without tools or global configuration changes. Other actions/hosts need a capability adapter and actual lifecycle evidence. Native adapters own transport, the shared store owns state and acceptance. The store is an admission boundary, not an OS sandbox.

Main conversation history cannot be selectively erased by this skill. Use fresh workers for disposable skill text. Claude retained contexts receive generation changes and reset after SessionStart/compact/resume. DSH receives one replaceable request fragment. Unknown host retention defaults to ephemeral delivery. These mechanisms reduce reinjection; they do not prove provider-side deletion or whole-task token savings.

## Load only the relevant reference

| Need | Reference |
| --- | --- |
| Scope contract, native proof limits, mathematical invariants | [Scoped skills](references/scoped-skills.md) |
| Context budgets, reuse and complete usage accounting | [Minimal context](references/minimal-context.md) |
| Code and capability review, coverage and changed-file routing | [Incremental review](references/incremental-review.md) |
| External articles, routing, trial and absorption | [Autonomous knowledge](references/autonomous-knowledge.md) |
| Other FAMES capabilities: cognitive checks, hardware, background, documents, missions, federation | [Operator reference](references/operator-manual.md), select one heading |
| Exact machine-readable acceptance fields | [FAMES protocol](references/protocols/fames-protocol.json), select one capability |

Do not promise arbitrary semantic correctness from schema validation. Savings need matched task/model/acceptance and complete parent, child and retry usage, including caches. Report character counts separately. Missing/stale evidence fails closed as UNKNOWN. Before claiming delivery, use the relevant verifier and SEAL; apply changed packages through the registered convergence route and read back destination identity.
