---
name: token-preflight
description: Route non-trivial coding, audit, research, deployment, or multi-step work through the smallest verified context path. Use before broad Read/Grep/Shell exploration, when a task may need parallel decomposition, when resuming a long Claude session, or when auditing token usage. This is the single entry point; FP, MTM, PFKT, SCF, SEAL and AEX are internal phases loaded only when active.
---

# Token Preflight

Run `python scripts/preflight.py --agent <seat> --task "<request>"` before broad exploration.

Keep only five fields hot: outcome, verification, state, next action, blocker.

Use this phase order:

1. FP defines Outcome and Verification.
2. MTM selects a bounded route and read budget.
3. PFKT activates only for multiple independently verifiable deliverables or explicit parallel work.
4. SCF computes residual only after a verified result exists.
5. SEAL checks evidence, identity, and graph closure.
6. AEX activates only when a verified cross-cycle residual remains.

Treat probe/config errors as UNKNOWN. Never treat UNKNOWN as clear, consumed, healthy, or complete. Do not load linked protocols until their phase becomes active.

The script writes a receipt. A session touch without a receipt is not skill consumption. Reuse the receipt while the task fingerprint and referenced artifact hashes are unchanged.

Read [references/concept-map.md](references/concept-map.md) only when changing framework architecture.

Load `cca-token-governance` only when the route proposes a Claude-to-Codex review or audits cross-provider token usage.
