---
name: independent-review
description: Perform an evidence-backed independent code or delivery review across Codex, Cursor, Claude, and other agent hosts. Use for code review, delivery acceptance, supervised-build checkpoints, evidence-bundle verification, or whenever a named reviewer/subagent is unavailable and the review must continue without weakening independence.
---

# Independent Review

Review the artifact, not the builder's narrative. Never require one vendor-specific agent type.

## Select a review lane

Use the first available lane:

1. A dedicated read-only review tool or reviewer agent exposed by the current host.
2. A general-purpose independent subagent exposed by the current host, with no write authority and only raw artifacts in its prompt.
3. The current reviewing agent in a fresh evidence pass. Re-read source artifacts, recompute hashes and tests, and do not rely on prior summaries.

Missing lanes are capability facts, not blockers. Record the selected lane and unavailable preferred lanes in the receipt. Never call an unadvertised agent type or pretend a fallback was the unavailable reviewer.

## Review procedure

1. Read the governing contract and exact review target.
2. Resolve the repository root and changed-path set mechanically. Then triage before reviewing (kyloren_bot bb489c62, OpenCoreReview): classify each changed hunk by risk and category (auth/secrets, data loss, concurrency, parsing, tests-only, docs), and review the flagged hunks with that category's checklist instead of sending the whole diff with a generic prompt. Record which hunks were triaged out and why; a triaged-out hunk is not "reviewed".
3. Verify bundle identity, hashes, command receipts, test output, and dirty-worktree isolation from source artifacts.
4. Inspect every load-bearing implementation path and test for false positives, fail-open behavior, omitted inputs, and host-specific assumptions. A refusal that holds only because a component is missing is also a lock (ai_trader manual-source-label-is-privileged, 2026-09-21): when a change adds a provider, observer or adapter, list the refusals that depended on its absence and check each one still holds. Also check privileged labels that are a field's default value (a default `source="manual"` skipped capability, session and cost gates for every programmatic order).
5. Re-run safe checks independently. Never trigger live financial, deployment, credential, or destructive paths merely to review them.
6. Review on two separate axes, as separate passes or separate subagents (mattpocock code-review): (a) Standards — code quality and the repo's own rules; (b) Spec — the diff against the operator's own words and the acceptance criteria bound by `f1s-intake`. A pass on one axis says nothing about the other.
7. Emit findings before verdict. Any load-bearing UNKNOWN fails closed.
8. Write a machine-readable receipt only when the governing contract authorizes the reviewer to do so.

## Verdict rules

- `ACCEPTED`: required claims independently reproduced; no blocking finding or UNKNOWN remains.
- `REJECTED`: at least one correctness, safety, evidence-integrity, or contract defect blocks acceptance. A governing contract may refine this to values such as `REJECTED_FIXABLE` or `REJECTED_INTEGRITY`.
- `UNKNOWN`: evidence cannot be reproduced safely or target identity cannot be established. Treat as rejected for progression.

Include reviewer identity, selected lane, target identity, commands rerun, findings, verdict, and receipt hash inputs. A passing builder-authored claim is evidence to test, never proof.

For supervised-build bundles, run `scripts/verify_bundle.py` before judging claims. Validate the final receipt with `scripts/validate_receipt.py`.
