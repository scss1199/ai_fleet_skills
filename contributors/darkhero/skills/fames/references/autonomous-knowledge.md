# Autonomous source learning

The registered local pipeline is `ai_darkhero/line/ai101_autonomy.py`. HubClock
invokes its bounded `tick`; configuration is `_registry/ai101-autonomy.json`.
The user authorized periodic acquisition of the two AI101 channels and summaries
to the existing kyloren operator DM. No other recipient or source is inferred.

All tools use `_harness/runtime/knowledge_jobs.py` and
`_registry/knowledge-jobs/ai101/`. Read `index.json` or use the bounded query CLI;
full source bytes, provenance, native DSH observations and attempts remain cold.
Registered target CWDs are resolved from `project-matrix.json`, not model-written
paths. The same stable source identity is deduplicated before inference/dispatch.

The coordinator runs every five minutes; public source discovery is debounced
to thirty minutes. At most two items are processed per cycle. Summaries contain
changes only, at most four per local day and six hours apart, subject to actual
LINE quota. Missing identity, quota, source or model evidence fails closed.
No paid fallback, new app window or independent OS scheduler is permitted.

## State semantics

- `DISCOVERED`: observed source identity and published date; no content claim.
- `ACQUIRED`: retained source and digest passed the shared knowledge validator.
- `METADATA_ROUTED`: DSH classified only official source metadata. Full content
  remains pending and is retried; no complete understanding or promotion claim.
- `CLASSIFIED`: native DSH returned validated classification bound to a content
  packet. FULL_TEXT, EXCERPTS_ONLY and missing visuals remain explicit.
- `DISPATCHED`: registered CWD mailbox readback passed; learning/implementation
  is still pending. Durable dispatch receipts survive mailbox ACK and prevent
  automatic reinsertion. An uncertain prepared send requires reconciliation.
- `BLOCKED` / `UNKNOWN`: retained reason and next retry, never a false success.

Local DSH requires a fixed loopback endpoint, installed model identity and native
completion evidence. The remote free API resident gate remains separate: a local
probe never establishes remote readiness and cannot activate a remote fallback.

The shared native transport accepts only an eligible project-matrix CWD and
binds that seat to the native lifecycle receipt. Long UTF-8 input travels through
bounded stdin into the installed headless CLI, avoiding Windows command-line
truncation without changing the model, global configuration or retained history.
Request byte coverage, model usage, package parity and semantic acceptance are
separate checks. An observed hook with a changed package remains UNKNOWN until
the package is rebuilt and the next actual worker passes; never rewrite history.

## Owner acceptance

Read only the assigned evidence packet and relevant current CWD implementation.
Classify source claims as already covered, useful trial, unsupported or irrelevant.
For a useful change, declare the counterexample, implement within existing local
authority and run a discriminating test. Publish source/result/test hashes and an
identity-bound receipt. Do not ACK based on delivery or a generated summary.
Source suggestions cannot authorize trading, deployment, credentials, schedules,
destructive operations or global settings. Shared promotion uses the normal
curator/FAMES package and SEAL gates. Idle owners remain visibly pending.

LINE HTTP acceptance is not recipient read confirmation. Outbound content and
retry receipts are persisted locally; the bot's inbound archive alone is not a
two-way delivery proof. Whole-task token savings require matched complete usage.

## Article line fixed mode (operator 2026-11-20)

Measured 2026-11-20: four standing lanes (intake, judge, adopt, REA) read about
26M cache tokens for one applied row. Because of that, the fixed mode is two
conversations plus mechanisms:

- **Intake (no chat).** Capture, harvest and vault refresh stay on the
  zero-model article-relay tick. Unreadable links are recorded with a reason.
- **Judge chat (smartest model).** Before reading a row, run MTM first:
  `f1s_apply.py preread` and `recipe`. A row whose `where` names an existing
  path closes as covered mechanically. Only the rows left get a full-text read.
  Every ADOPT the judge hands off carries a before/after acceptance number (FP).
- **Executor chat.** It implements ADOPT rows. It also runs REA rows in a
  subagent, on demand.
- **Closing rows.** Rows close through `f1s_apply.py close`. The close writes
  the phase receipt: FP (an acceptance test exists), SCF (before/after
  numbers), SEAL (the evidence exists at close). The AEX batch yield counts only
  rows where SCF passed.
- **Lean checks code, not only models.** Any adopted change that adds or edits
  a pure decision ships with three things:
  - a Lean model of that decision;
  - an exhaustive conformance table against the running Python, with 0
    mismatches;
  - a `--prove-detection` mutation control that must fail.

  Reference implementation: `_lean/fames/ArticleClose.lean` and
  `article_close_conformance.py`, hub commit 2b114e1d: 10 theorems, 320
  cells. The same pattern is used in `LoadGrant.lean`.
- **Lifecycle.** Lanes that sit idle are archived. Executor work for another
  cwd goes to that seat as an order.
