---
name: cca-token-governance
description: Govern Claude-to-Codex reviews with explicit provider accounting, deterministic admission, cooldowns, deduplication, circuit breakers, and a bounded low-cost reviewer profile. Use when a task proposes CCA review, audits Claude or Codex tokens, changes cca-gate or codex-shadow-review, or investigates repeated cross-provider review spend.
---

# CCA Token Governance

Start with local evidence. A paid Codex review is never a zero-token action.

1. Identify the provider whose tokens will be spent.
2. Reuse an unchanged passing artifact hash when available.
3. Run deterministic checks and inspect existing receipts before requesting a model.
4. Require the caller's explicit `--allow-paid-review` opt-in.
5. Apply target cooldown, per-target/day cap, raw-token/day budget, and observe-mode would-block circuit breaker.
6. Pin model, reasoning effort, and service tier; never inherit global defaults.
7. Record input, cached input, cache-write input, output, and reasoning output separately.
8. Report missing telemetry as `UNKNOWN`, never as zero, healthy, or saved.

Use:

- `python %AI_WORKSPACE%\_skill\engines\cca-gate.py inventory` for verified wiring.
- `python %AI_WORKSPACE%\_skill\engines\cca-gate.py ledger --days 30` for the observe ledger.
- `python %AI_WORKSPACE%\_skill\engines\cca-gate.py check <gate-id> --target <path> --claim <claim>` for a local-only observe check.
- Add `--allow-paid-review` only when the task explicitly authorizes a paid review and the configured policy admits it.

Read [references/policy.md](references/policy.md) only when changing policy values, replaying historical reviews, or interpreting token buckets.

Read [references/known-failures.md](references/known-failures.md) when a review is refused, when the free pre-screen returns no voters, or before changing a budget knob to admit a review.
