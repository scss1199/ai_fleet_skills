# Scoped skill contract

The shared task store is independent of model providers. A host adapter supplies an observed result, not a completion verdict. Full skill text stays cold until selected. Avoid building another per-model state machine.

## State and conditional guarantees

Let the durable state be S = (G, A, C, P, O, r, E), for goal, authority, constraints, parameters, obligations, revision and evidence. A scope selects K = (skill, O_K, P_K, A_K, deadline, input budget), where O_K is a subset of O, P_K selects known parameters and A_K is a subset of A. Its input is projection(S, K), never the transcript of another scope.

The transition rules are finite and locally checkable:

1. OPEN validates the fixed schema, subset relations, revision and input budget. Reusing a request id requires identical content.
2. ADMIT requires active scope, current revision, unexpired deadline, allowed action and an allowed target when applicable.
3. OBSERVE requires identity-bound artifacts and registered predicates against freshly read destination bytes. A JSON field saying PASS is insufficient.
4. RELEASE forbids future scope input/actions; it preserves the durable task and pending obligations. Expiry also denies action, without implying success.
5. UPDATE uses compare-and-swap revision and invalidates active old scopes. Constraints cannot be removed and authority cannot expand within a task.
6. SNAPSHOT is VERIFIED iff every obligation has fresh valid evidence and no active unexpired scope remains. Changed destination bytes reopen the obligation.

By induction over these transitions, an admitted action cannot exceed the declared authority, a released/stale/expired scope cannot be admitted again, and an unsatisfied obligation cannot disappear on release. These are guarantees of callers using the wrapper and supported predicates. They are not an OS security sandbox, a proof that the initial goal captured all human intent, or a proof of arbitrary model correctness. The initial formalization remains a separate obligation requiring discriminating tests and review.

Minimize J = w_T * measured_total_tokens + w_L * measured_latency + w_C * maintained_code, subject to acceptance, authority and freshness invariants. Choose weights and units explicitly before comparisons. There is no proof of a global optimum from one fixture. Count all parent/child/retry/cache usage. Moving text to cold references reduces active input, not total source size.

## Shared JSON CLI

Resolve `<runtime>` from the registered workspace, not a guessed CWD. Use an absolute private state/output path. The existing shared Python runtime has no provider dependency.

```text
python <runtime>/skill_scope.py open --root <state> --contract <task.json> --skill <skill.json> --request-id <id>
python <runtime>/skill_scope.py input --root <state> --scope <scope-id>
python <runtime>/native_skill_scope.py --host dsh --root <state> --scope <scope-id> --output <empty-output>
python <runtime>/skill_scope.py snapshot --root <state> --task <task-id>
```

The native runner verifies one compute result at `<empty-output>/result.json`, releases the scope even on failure, and writes `native-scope.json`. The task's registered predicate must point to that exact result path. Unsupported hosts/actions/predicates fail closed. Do not fabricate a generic semantic verifier.

Task fields: `schema:1`, `task_id`, `goal`, absolute existing `cwd`, `authority:{actions,targets}`, `parameters`, `constraints`, nonempty `obligations:[{id,predicate,parameters}]`, optional bounded `budgets`. The first predicate is `json_file_equals`, with absolute `path`, RFC6901-style `pointer`, and exact finite JSON `expected`. Skill fields: `id`, `body`, `obligation_ids`, `parameter_keys`, `actions`. Evidence fields: `schema`, `scope_id`, `task_id`, `task_revision`, `goal_hash`, `artifacts:[{path,sha256}]`. Unknown fields are rejected.

Use local deterministic work first. Scoped compute is appropriate only for authorized model judgments; a sorting fixture measures lifecycle conformance, not the economic benefit of outsourcing sorting.

## Host capabilities and observation limits

| Host | Context delivery | Evidence boundary |
| --- | --- | --- |
| Claude Code | Fresh UUID, tools/skills/MCP disabled for compute; main retained hook context deduplicated until generation/reset | Native CLI user replay, session identity, FAMES hook, provider usage; full provider request UNKNOWN |
| DSH | Fresh task profile with existing local model, tools disabled, canonical FAMES plugin; one current request fragment | Native `llm/stream` content hash/marker observation and lifecycle receipt; no model-global forgetting claim |
| Codex / Cursor | Shared files, capability contract and generated rules; use native fresh workers where supported | Configuration read-back is not an actual native lifecycle trial |
| Future host | Implement a thin declared-capability transport | Must supply actual observed lifecycle before claiming support |

Unknown retention defaults to ephemeral delivery; never omit the core simply because a previous hook ran. Retained Claude contexts reset on SessionStart, compaction or resume. A failed/unknown intake reinjects the core. DSH filters earlier same-plugin fragments in its request projection. Neither mutates the user's historical transcript.

Keep native raw synthetic logs on disk and surface only checksums, usage and necessary results. Never log provider configuration, auth, cookies or secrets. Headless children need process-tree containment and deadlines; no visible windows, service restarts, new schedules, model downloads or paid fallback are implied.

## Acceptance checklist for a new adapter

## Optional Jev skill advice

The shared `turn_context()` invokes `_harness/runtime/jev_turn_router.py` after core-context deduplication. DSH, Claude Code and Codex/Open Agent adapters share this route. SessionStart remains zero-provider. A registered host path or passing offline test does not prove that a resident host invoked Jev.

`_registry/jev-advisor.json` selects enabled seats and shadow/advisory mode. It does not authorize a skill action. Provider use also requires a fresh `typesafe` inference receipt in the existing names-only availability registry, an allowed credential source and explicit provider authorization. Never transfer subscription-session tokens, guess credentials or publish keys. The current direct adapter is pinned to `jev-1.13.0`; thresholds are provisional and not calibrated for local tasks.

Before a host may send task data, a trusted local caller prepares `_registry/jev-task-projections/<agent>/<prompt-sha256>.json`. Bind `schema:1`, `approved_for_provider:true`, `prompt_identity`, `session_identity`, allowed `surfaces`, exact `config_sha256`, `provider_policy_sha256`, and `catalog_sha256`, plus timezone-aware `expires_at` within one hour, `task_projection` of at most 1600 characters, `allowed_skill_ids` and `mandatory_skill_ids`. These fields are local caller assertions, not new authority. Use only task-relevant, permitted data; raw conversation and credentials are excluded. The bridge never constructs a projection by copying the raw prompt. Expired or mismatched input falls back without inference.

The advisor ranks registered canonical skills, checks at most three candidates and may return NONE. It validates the selected candidate's own fit and re-reads the installed body hash; a different candidate's high score is insufficient. Advice cannot carry executable commands, arbitrary paths, expanded actions or expected verifier results. A returned ID is only a recommendation. Load the canonical skill through the host's existing capability path, then apply scope and outcome verification. Keep exact local rules and required multi-skill stages; Jev does not replace Lean, policy, risk gates or SEAL.

Repeated identical approved turns reuse hash-bound advice instead of repeating provider calls. Record recommendation, actual skill loading, execution and verified outcome separately. A generic tool-using executor or cross-host adoption requires its own observed lifecycle evidence. For ai_trader the initial consumer is research-checklist selection before its existing DSH proposal prompt; it does not change order, risk, reconciliation or strategy acceptance logic.

Measure Chinese/mixed-language selection, abstention, mandatory-stage recall and complete task cost before promotion. The installed bridge and offline transport tests alone do not establish semantic accuracy or savings. See `ai_darkhero/evidence/jev-adoption-20260922` for the implementation boundary and current coverage.

## Native adapter acceptance checks

- A-only skill marker is present in A input and absent from B input; B-only marker behaves conversely.
- Releasing A retains the goal, authority and pending B obligation; B success closes only its matched obligations.
- Changed artifacts, wrong identity, unknown predicates, expired/released scopes, outside targets and expanded authority are rejected.
- Ten unchanged retained turns add no full core, reset/generation changes bootstrap again; ephemeral requests still receive one core.
- Report actual observation layer. Model claims of forgetting do not prove context disposal.
- Native success never substitutes for package parity, destination read-back or the task's required SEAL.
