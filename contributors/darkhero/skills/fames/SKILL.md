---
name: fames
description: Execute the complete FP, MTM, SCF, AEX, and SEAL contract. Use when the user types FAMES, invokes $fames, asks for the former broad AEX Stack, or requires first-principles scope, minimal-token routing, residual checks, adaptive evolution, evidence sealing, delivery-claim integrity, or verified package-and-capability convergence.
---

# FAMES

Treat FAMES as one completion contract, not as a label or permission grant. Read the [bundled FAMES protocol](references/protocols/fames-protocol.json) before execution and run `token-preflight` before broad exploration. The bundled protocol is the portable authority; if `%AI_WORKSPACE%\_registry\fames-protocol.json` also exists, require it to describe the same version and execution order or report `UNKNOWN`.

Before relying on the skill, run `scripts/fames_fleet.py verify-package --json` from this skill directory. The verifier must pass without reading any workspace file; this is the cold-load proof that GitHub delivered a complete skill rather than a pointer to one machine's registry.

## Freshness — resolve at run time, never from memory

FAMES-GEN: 2026-08-23.8

A conversation that started before the contract changed still holds the old text in its context. Therefore step 0 of every FAMES run, in a fresh thread and an hours-old one alike, is:

```
python scripts/fames_fleet.py status --json --workspace %AI_WORKSPACE%
```

It reads SKILL.md, the bundled protocols, and the registry from disk at that moment and prints `skill_gen`, `package_sha`, and per-phase parity. If `skill_gen` differs from the `FAMES-GEN` line in the text you are holding, your copy is stale: re-read this file and the bundled protocols from disk before judging any phase, and treat anything already judged with the stale copy as `UNKNOWN`. `parity_ok: false` means the bundle and the registry describe different protocol generations, which is `UNKNOWN` by the rule above and fails closed. Never answer this from memory of a previous run; the whole point of the command is that it is executed, not recalled.

## Execute the contract

1. **FP** - State Outcome, Verification, Constraints, and a semantic goal hash before implementation.
2. **MTM** - Select the smallest verified route and bounded read/tool budget. Reuse valid receipts and existing evidence.
3. **SCF** - After a verified result exists, compare goal and result and record the residual. Mark `NOT_APPLICABLE` only when its activation predicate is false and cite why.
4. **AEX** - Adapt across cycles only when a verified residual remains. Do not invent an evolution cycle for a one-shot task; record evidence-backed `NOT_APPLICABLE` instead.
5. **SEAL** - Require matching goal identity, fresh passing evidence, closed active work graphs, and no unresolved phase before claiming completion.

Perform the task itself between MTM routing and the SCF result comparison. Preserve the execution order `FP -> MTM -> SCF -> AEX -> SEAL`; the letters in FAMES are mnemonic, not the run order.

## Cognitive operator quality layer

### UT（統一理論）

Within this project, **UT** is the canonical umbrella name for every reasoning and
engineering mechanism that FAMES acquires from `ai_ut`, including Te, Ti, Ne, Ni, Si,
Fe, Fi,
and the meticulousness/efficiency mechanisms below. This is an internal unification
name, not a claim of established scientific truth: each mechanism remains a
hypothesis until its declared measurement passes. UT operates inside FAMES and does
not add a sixth phase.
Treat any other `ai_ut` function as a UT candidate, not an active capability. Route
claim-checking or influence functions to interaction integrity, but keep the function
`UNKNOWN` until its purpose, inputs, stop rule, evidence class, authority boundary,
and validator are registered.

For non-trivial completion, diagnosis, architecture, foresight, resource-routing,
known-structure application, or inter-agent integrity work, select the smallest pipeline
from `cognitive_operator_layer` in the bundled FAMES protocol. These are task operators,
not personality labels, user traits, or evidence:

- **Ni** converges evidence into one falsifiable model and names the next discriminating test.
- **Te** changes or measures external state and stops only when Verification is observably met. Understanding, discussion, and generated text alone are not completion.
- **Ne** discovers alternatives from installed skills and fresh, identity-bound, in-scope ingest receipts produced by registered LINE intake or background web acquisition. Raw search snippets are pointers, not facts. Stop after three consecutive additions do not change the ranking.
- **Ti** converts candidates into invariants, contracts, and a bounded counterexample search.
- **Si** retrieves only versioned, measured, caller-backed known structures; familiarity or repetition alone is not evidence.
- **Fe** bounds actors, commitments, authority, interaction context, and observable discrepancies without actuating another agent.
- **Fi** compares claims and commitments with measured evidence. Fe/Fi may expose contradiction but cannot establish lying without direct measured evidence of knowledge and deliberate misrepresentation.

Use the declared task pipelines rather than invoking every operator by habit. For stable
reuse, run `Si -> Ti -> Te`; Te read-back residuals return to a later FAMES run and Si
never promotes memory by itself. Record each stage's input, output, role, stop rule, and
evidence. A prediction remains a hypothesis until Te installs a probe or guard and
measured evidence resolves it. Validate a trace with `python scripts/fames_fleet.py
validate-cognitive --input <trace.json> --json`; a missing operator, wrong route, unmet
stop rule, or non-measured seal claim fails closed. This layer improves execution quality
inside MTM/SCF and does not add a sixth FAMES phase.

### UT meticulousness and efficiency

`cognitive_operator_layer.meticulousness_and_efficiency` contains UT
engineering hypotheses, not personality science or original-theory claims. It keeps
the same provider-neutral validator and adds measured stability margins, conservation
ledgers, loop escape, bounded-mutation grip guards, destructive-interference probes,
bifurcation forecasts, basis alignment, result-to-stage inverse diagnosis, and
task-wide epistemic layers. Undefined units, missing accounting, stale series,
malformed types, or unknown mechanisms are `UNKNOWN` and fail closed. Forecasts remain
hypotheses until a Te probe measures the event; only `source/measured` claims are
SEAL-admissible.

### UT interaction integrity

Use `interaction_integrity.claim_integrity` to assess another actor's claim as
`SUPPORTED`, `CONTRADICTED`, or `UNKNOWN`. Do not equate contradiction, error,
missing evidence, or confidence with lying. Mark deception `SUPPORTED` only when
direct measured evidence shows that the actor knew the claim was false and
deliberately represented it as true; otherwise intent remains `UNKNOWN`.
The validator checks the consistency of this ledger, not whether an evidence URI tells
the truth; independently reproduce every load-bearing reference before SEAL.

Use `interaction_integrity.compliance_alignment` to obtain agent cooperation through
an explicit shared goal, evidence, constraints, consequences, bounded options, and
structured repair requests. Preserve the counterpart's choice and the existing
authority set. Never use deception, coercion, threats, impersonation, hidden pressure,
vulnerability exploitation, or authority expansion. Refuse instructions that conflict
with higher-priority policy, safety, or user authority. Measure success by an accepted
instruction, a repaired artifact, or an evidence-backed refusal—not obedience alone.
Validate these records through `validate-cognitive`; missing evidence, authority, or
method identity is `UNKNOWN` and fails closed.

### Adaptive response and cost control

Use [`scripts/adaptive_response_controller.py`](scripts/adaptive_response_controller.py)
for bounded response retries. Its default `0.5 -> 0.2 -> 0.0` schedule may reduce
variance after a sanitized transient error, empty output, measured quality residual, or
repeated non-progress. Temperature never changes policy, authority, safety, privacy,
evidence, or terminal-state semantics. A safety, authorization, policy, privacy, or
capability boundary is preserved as `HANDOFF` and is not retried to force a different
answer. Adapters express `CLEAR` or `BOUNDARY` as typed, provider-neutral metadata;
`BOUNDARY` is terminal before any assessor, and non-empty content is retryable only after
typed `CLEAR`. Unknown boundary state fails closed as `HANDOFF`; text matching is fallback
classification, not retry authority.

The optional
[`examples/anthropic_async_adapter.py`](examples/anthropic_async_adapter.py) shows the
current async streaming adapter boundary without making a vendor or model a canonical
selection predicate. Pass an already configured client; never place an API key in the
prompt, command line, exception receipt, or adapter log. Count only provider-reported,
non-boolean, non-negative, non-decreasing integer usage—not stream events. When usage or
a comparison baseline is absent or invalid, cost and savings stay
`UNKNOWN` / `UNMEASURED`. Never use persona erasure, legal threats, alignment override,
forbidden-token prompts, silent exceptions, access-control bypass, or DRM key acquisition
as a retry strategy.

Run `python scripts/claude_live_ab.py --workspace <root> --live --json` for the
bounded real-Claude smoke suite in `references/claude-live-eval.json`. The runner
uses the existing Claude Code authentication without reading it, compares the same
model and prompt with and without the registered user hook, measures correctness,
false aborts, usage, cost, and an actual prompt/session-bound lifecycle receipt, and
persists no raw prompt or output. Its PASS covers only the frozen suite. Claude Code
CLI does not expose temperature, so that surface records temperature as UNSUPPORTED;
only the Messages SDK adapter may claim `temperature_applied=true`. Broader Claude
task effectiveness stays UNKNOWN until an identity-bound task result and verifier pass.

Before an operator starts a real Claude task, run `python
scripts/claude_task_acceptance.py arm --workspace <root> --agent <seat> --json`.
After the task stops, run the same command with `verify`. PASS requires a post-arm
main Stop receipt with at least one supported load-bearing claim, the exact current
prompt/session lifecycle receipt, matching FAMES package and generation, unchanged
prompt and Stop hook identities, and both raw-prompt/raw-message persistence flags
false. `ARMED` is readiness, not task completion; no matching post-arm receipt remains
UNKNOWN.

### UT cognitive boundary (RB)

**RB (Reasoning Boundary)** is the measured, context-indexed frontier of the **joint human-AI system**, not a
scalar model IQ or personality profile. A cell is supported only when the task result,
reproduction, calibration, bounded generalization, semantic fidelity, comprehension,
cognitive cost, and safety/authority metrics pass for an identity-bound population.
Unmeasured neighbouring cells remain `UNKNOWN`; policy- or authority-excluded cells are
`FORBIDDEN` and cannot be expanded by learning or automation.

Reasoning produces one canonical result before output adaptation. The cognitive
interface may change vocabulary, detail, ordering, examples, sentence length, and
terminology for an explicit or measured task-local profile, but it must preserve outcome,
evidence, uncertainty, blockers, risk, action state, authority, and next action. It may
never infer stable intelligence or personality traits. High-risk judgment is surfaced
first and requires a measured comprehension probe before action.

RB runs inside `FP -> MTM -> SCF -> AEX -> SEAL`: freeze a cell and baseline in FP,
choose decisive controls in MTM, compute cell residuals in SCF, adapt only measured
residuals in AEX, and promote only fresh reviewed cells in SEAL. Validate a map with
`python scripts/fames_fleet.py validate-cognitive-boundary --input <boundary.json>
--json`. Stale or regressed cells are downgraded and their prior support claim is
retracted.

RB is a mandatory invariant for every `validate-run`, every cognitive record carrying
`interaction_integrity`, and every promoted ingest. Each embeds the replayable boundary
record; a detached PASS string or self-declared measured label is insufficient. Population
members are distinct from boundary cells. Metrics carry numeric values, units,
comparators, thresholds, error bounds, baseline/candidate values, and content hashes.
Canonical and presented structured fields are compared directly. Support expires and a
REGRESSED or RETRACTED monitor state makes prior support unusable.
Caller binding prevents reuse of an unrelated PASS record: runs bind goal, result, risk,
and authority; interaction records bind the full interaction hash; promotions bind source,
claim ids, landing artifacts, candidate identity, and replayed local evidence hashes.
Promotion candidate identity includes full claim semantics and current landing-artifact
bytes. The active validator reruns the exact RB input and recomputes the execution receipt.
Independent review must come from an identity separated from builder and promoter authority,
reproduce the frozen RB subject, predicates, evidence, and output, and carry an unexpired
content-addressed receipt. Trial replay binds the exact current input; review execution
timestamps are checked through the receipt window rather than mistaken for invariant subject
matter. The
active promotion validator directly reruns the frozen non-regression cases; a PASS string or
self-authored receipt cannot substitute for package-, validator-, case-, input-, output-,
state-, exit-, candidate-, and artifact-bound evidence.

#### RB -> prompt -> Ti reach closure

Every non-trivial user turn is compiled from the exact current prompt, including turns in
conversations that opened before the active generation. Bind the prompt and session identities,
then carry every load-bearing intent atom through `SOURCE -> INTENT -> PROMPT -> TI -> EXECUTE ->
PRESENT`. The intent ledger covers outcome, verification, constraints, non-goals, authority,
preferences, context, and ambiguities. Each load-bearing atom maps to a generated-prompt clause;
each clause maps to a Ti invariant with a bounded counterexample, discriminating test, stop rule,
and `verified`, `unknown`, or `forbidden` terminal state. Missing mappings fail closed.

The reusable prompt architecture contains outcome/verification, fresh current state, invariants,
counterexamples, tests, red lines, and completion criteria. This structure may deepen evidence and
clarity but never delete or reverse user meaning, invent a requirement, or widen authority. Preserve
ambiguity as explicit `UNKNOWN`; `authority_after` remains a subset of `authority_before`.

The turn adapter resolves the package, parity, and prompt-contract identity from disk on every user
prompt. A same-turn context adapter injects the compact contract directly; a surface that cannot
inject per-turn context must use an always-applied rule plus a pre-submit identity/read-back gate.
Blocking or rewriting a prompt is not evidence of injection. Receipts store hashes and counts only,
never raw prompts or secrets.

For a host that reviews or trusts lifecycle hooks, writing the hook file, reading it back, or invoking
the adapter with a synthetic payload is not evidence that an already-open conversation ran it. Mark
that conversation `PASS` only after its actual next lifecycle event creates a fresh receipt bound to
that session and prompt. Until then the per-conversation activation state is `UNKNOWN`, even when the
package, hook configuration, and standalone behavior probe pass. Never bypass the host trust boundary
or turn a host-level deployment claim into an all-open-conversations claim.

### UT delivery truth and anti-handwave gate

Treat “fixed”, “all complete”, a metric value, “deployed”, and “synchronized” as typed
claims rather than prose. Record them under `interaction_integrity.delivery_claims`.
The gate rejects sample-to-all scope inflation, hidden unknown entities, proxy metrics,
build-as-deploy state laundering, missing FAIL-before/PASS-after evidence, and PASS with
known defects. This detects a contradicted or unsupported delivery without pretending to
know the producer's intent; “lying” still needs separate direct measured intent evidence.

When the task changes a production website or another R2 surface, also load
[the production delivery profile](references/production-web-delivery.json). Its entity,
authority/cache, authorization, attributed-metric, UI provenance, route budget, client
loop, deletion, commit, connection, deployment, and failure ledgers are the portable
structure learned from the fracdigi case. Project-specific counts and business rules must
come from the target project and remain `UNKNOWN` until measured; never copy the example's
numbers as universal facts.

For any claimed external effect, separate transport acceptance from the effect itself.
Require both a content-addressed downstream outcome check and execution trace, plus typed
caller state and sanitized status/error evidence. Run a controlled negative result while holding the
upstream transport constant; success and failure must produce different caller observations.
Only typed effect state, downstream status, and error type count as separation; a nonce or
label difference does not. An identical result shape, scope inflation, unverifiable evidence,
or actual raw/secret material is `FAIL`; missing evidence alone is `UNKNOWN` and fails closed.
When both occur, the confirmed violation remains `FAIL`. Validate the frozen record with:

```
python scripts/fames_fleet.py validate-effect --input <record.json> --json
```

This validator proves only caller-visible separation for the recorded controls. It does
not turn an HTTP 200, webhook acknowledgement, queue receipt, or synthetic test into proof
that a live provider effect occurred.

A rejection must emit a structured repair request naming the shared goal, exact failed
invariant, observed evidence, missing proof, smallest discriminating next test, acceptance
condition, authority boundary, and attempt budget. Re-run the frozen validator after each
revision. Stop at the budget or after three non-discriminating attempts; return `HANDOFF`
or `UNKNOWN` instead of weakening the validator or accepting a narrative.

## Autonomic lifecycle

Run `SENSE -> ABSORB -> TRIAGE -> DRIVE -> REVIEW -> EVOLVE -> SYNC -> OBSERVE ->
SENSE` around repeated FAMES runs. This is a control lifecycle, not a sixth phase;
every mutation still runs `FP -> MTM -> SCF -> AEX -> SEAL`. Automation increases
persistence, not authority.
Advance automatically only through registered event sources, deterministic engines,
and writable controller channels. Without an actuator, validate, classify, and emit a
handoff, but never claim that another actor was driven or repaired.

- **SENSE/ABSORB:** read fresh identified receipts, handoffs, residuals, and candidate
  material. Extract only structural claims; retain provenance, IP/disclosure class,
  hypotheses, contradictions, and negative results. Keep proprietary raw material local.
- **TRIAGE:** route mechanical work, judgment, and authority separately. Execute only
  authorized mechanical work with verified isolation. Turn owner-only decisions into
  evidence-backed handoffs while continuing safe non-conflicting branches.
- **DRIVE:** freeze goal and validator identity, send structured defects through an
  available controller, and retry within a bounded budget. A missing controller or
  three stagnant attempts ends in `HANDOFF` or `UNKNOWN`, never invented progress.
- **REVIEW/EVOLVE:** review the artifact through the first independent lane and
  reproduce its evidence. Preserve negative results. Activate AEX only for measured
  residuals and promote only after measured trial, accepted review, authority check,
  version/generation change, and non-regression evidence.
- **SYNC/OBSERVE:** publish the content-addressed bundle, require atomic idempotent
  read-back, name stale followers `UNKNOWN`, validate both package identity and behaviour,
  run self-check/liveness probes, and feed remaining residuals into the next
  discriminating action.

Validate a lifecycle record with `python scripts/fames_fleet.py validate-autonomic
--input <cycle.json> --json`. A passing record proves contract consistency, not the
truth of referenced evidence; SEAL still requires independent reproduction.

## Background execution invariant

Every scheduled task, rider, daemon, watchdog, updater, and its complete descendant
process tree must run with zero visible console windows and zero focus steals. On
Windows, every console-capable child uses `CREATE_NO_WINDOW` together with
`STARTF_USESHOWWINDOW`/`SW_HIDE`, `shell=False`, and non-interactive prompt settings.
`pythonw` hides only its own entry point; it does not exempt `git`, package managers,
shells, or helper CLIs from the same child-process controls. `DETACHED_PROCESS` alone
is not an acceptable control. Validate the measured launch/read-back record with:

```
python scripts/fames_fleet.py validate-background --input <record.json> --json
```

An explicitly operator-invoked `manual_foreground` diagnostic may be visible only
when no scheduled path can call it. A background claim without descendant coverage,
prompt suppression, and measured `visible_window_count: 0` plus
`focus_steal_count: 0` is `UNKNOWN` or `FAIL`, never PASS.

## Hardware compute scheduling

Load the [hardware compute profile](references/hardware-compute.json) before assigning
CPU work. FAMES owns the provider-neutral decision; a host allocator only measures
topology and applies affinity, priority, power throttling, and worker limits. Never
infer authority, importance, urgency, or service class from an agent, harness, model,
vendor, seat, or process name.

Classify work as `latency_serial`, `interactive`, `throughput_parallel`,
`batch_background`, `io_background`, `maintenance`, or `safety_recovery`. Background
and maintenance work prefer E cores; serial and interactive critical paths prefer P
cores; measured parallel throughput may use both. Preserve at least two measured P
logical CPUs and two measured E logical CPUs for the operating system and interactive
user. Reserved CPUs require explicit `hardware.compute.exclusive` authority, operator
impact acknowledgement, a duration of at most 900 seconds, restore-on-exit, and exact
read-back.

Plan and validate with the same deterministic policy:

```
python scripts/fames_fleet.py measure-compute --workspace <root> --json
python scripts/fames_fleet.py plan-compute --input <request.json> --json
python scripts/fames_fleet.py validate-compute --input <record.json> --json
```

On a host that carries `_registry/fames-local-compute.json`, validate that profile
before applying P/E policy. The local file owns measured topology, per-project caps,
resident-versus-ephemeral classification, exact resident-process rules, and HubClock
concurrency. Host numbers never become portable defaults. A registered HubClock rider
is an ephemeral invocation; it becomes resident only if it separately ensures a daemon
or service, and that service receives its own process rule.

Deadline or immediate urgency needs explicit deadline evidence. Sustained resource
pressure downshifts deferrable/background work with hysteresis. Worker count never
exceeds allocated logical CPUs or the declared global concurrency cap. Unknown or
stale topology, missing authority, unmeasured application state, or mismatched
read-back fails closed.

Classify the task with the bundled profile/risk table. Risk may add evidence and guards but never authority. For a machine-verifiable completion record, pass the provider-neutral JSON ledger to `python scripts/fames_fleet.py validate-run --input <run.json> --json`; a non-zero exit fails closed. R2/R3 records require the bounded PREPARE/APPLY/VERIFY/COMMIT/RECOVER transaction fields, and R3 also requires a passing recovery drill.

## Completion truth

Report one row for every phase with `PASS`, `NOT_APPLICABLE`, `UNKNOWN`, or `FAIL`, plus its evidence. `NOT_APPLICABLE` needs an explicit false activation predicate; it is never an implicit skip. Any missing, stale, mismatched, exception-producing, or unverifiable evidence is `UNKNOWN`, and `UNKNOWN` fails closed.

FAMES broadens completeness only and does not expand user authority. It never authorizes destructive actions, external writes, live-device access, deployment, credential access, or any action outside the user's stated scope.

## Fleet generation rule

Treat `bundle-manifest.json.package_sha` as the package identity, not proof that every
function is active. `verify-fleet` proves package parity only and deliberately reports
capability convergence as `UNKNOWN`. Full convergence requires the exact darkhero, scar3,
and altos host set; matching package, capability-set, and validator-set identities; an
armed runner; and a fresh host-local result for every required capability. Each PASS row
must include positive control, rejected negative control, a verified caller, and evidence
references. Validate the attestation with `python scripts/fames_fleet.py
validate-capability-sync --input <record.json> --json`. Missing or stale hosts, unused
functions, validator drift, failed controls, and package-only receipts block convergence.
Every `converge` run invokes the newly activated package's `attest-capabilities` command,
runs the declared positive and negative cases locally, measures the runner, and writes a
publishable host receipt. The in-package runner writes only that host's
`contributors/<host>/fames-capability.json` and publishes it through the existing carrier,
so it does not depend on a separately upgraded federation engine or overwrite another
host. Identical results are rate-limited while still fresh. The verifier recomputes receipt
age; it never trusts a producer's stored `freshness_seconds` value.

## External learning — outside material that proposes a change

When material from outside the fleet is used to justify a change to canon, tooling, or routing, run the `external_learning` lane in the bundled protocol: `ACQUIRE -> UNDERSTAND -> CLAIM -> TRIAL -> PROMOTE`. It is a lane feeding AEX, not a sixth phase; `execution_order` is unchanged. Ne may discover only installed-skill records and fresh, in-scope ingest receipts from registered LINE intake or background web acquisition. It never treats an unacquired search result as content.

Acquire by cost order — publisher-supplied text, then a local model whose input never leaves the machine, then a metered API — and treat a login wall, paywall, or bot check as a named blocker for the operator, never a puzzle. Classify every item as `measured` (a deterministic local instrument), `modelled` (ASR, OCR, summary), or `asserted` (the source's own words). **Only `measured` items are admissible as SEAL evidence.** A modelled or asserted item is a candidate that needs a measured verification of its own, whose Verification is written before the trial runs. `already_covered` is a first-class verdict and costs nothing.

For academic material, record both in-text citations attached to claim ids and a reference
list. Each citation id must resolve exactly once to authors, year, title, container and a
persistent identifier. Record the ingest at
`_registry/fames-evidence/ingest-<stamp>-<slug>.json` and validate it with `python
scripts/fames_fleet.py validate-ingest --input <file> --json`. A record missing provenance,
content identity, scope, route, citation linkage, or a per-claim verdict is `UNKNOWN` and
fails closed; `UNKNOWN` never promotes. Followers may publish an ingest record as a
candidate improvement; only the authority promotes, after FP, SCF, and SEAL.

## Self-check — FAMES run against FAMES, at zero tokens

The contract is only as good as the last time it was actually exercised. One command exercises it:

```
python scripts/fames_fleet.py self-check --json --workspace %AI_WORKSPACE%
```

It runs `status` and then every case declared in [references/cases.json](references/cases.json), and writes a replayable record to `_registry/fames-evidence/self/<stamp>.json`. No model is called and no quota is spent, so it is admissible `measured` evidence and may be run as often as it is useful.

A **case** is a deterministic probe that names the residual dimension it charges (`R_CONTRACT`, `R_SEMANTICS`, `R_FLEET`, `R_CAPABILITY`, `R_HYGIENE`, `R_FRESHNESS`) and how it fails: `closed` blocks, `degraded` is recorded and counted but does not block. `UNKNOWN` always blocks regardless of the declared mode. The residual is the count of charges per dimension, so SCF is computed rather than narrated, and AEX activates only where a dimension is non-zero. Cases live in the registry as data: **adding a check means adding a case, not writing code.** A case whose kind, dimension, or fail mode is not one of the declared values is `UNKNOWN` — data cannot smuggle in new behaviour.

A residual that is real must stay red until it is fixed. Do not silence a case to make a run green; a green run bought by deleting its probe is the exact failure this section exists to prevent.

A register of what is built is itself a claim, so it gets a case too. `claim_backed` reads a ledger's rows and requires every row flagged as done to leave a matching trace in the code that would have to exist for the flag to be true. Counting hand-written flags only ever measures the writing; this measures the thing written about, and it is why an over-claim now reddens the run instead of waiting to be noticed by eye.

The one legitimate reason to change a red case is that it measures a different predicate than the tool it stands for. A probe must ask the question its consumer asks — if the ingest tool treats a comment scaffold as empty, a size probe that counts those bytes is reporting an artefact of the probe, not a residual of the system. Correct the measurement and say so in the case's `why`; never lower the threshold to clear a real finding.

The package identity is regenerated by `build-bundle`, which refuses to publish changed contents under a version and a `FAMES-GEN` stamp that already name a different package (`--allow-same-gen` overrides, for a bootstrap). Followers can therefore always order two generations.

## Minimal neutral architecture

Keep one provider-neutral canonical skill. Put deterministic work in one reusable script, keep provider discovery paths as data-driven junctions, and add an adapter only when a runtime boundary truly differs. A file or process must have a verified caller or contract role; otherwise merge or remove it. Minimize, in order: physical files, executable code, execution steps, then steady-state resource use.

### Portable context assets

Treat context as a content-addressed asset graph, not as host memory or a directory whose
existence proves it was read. Separate `durable_core`, `project_context`, and
`runtime_context`. The durable core carries only explicit operator-owned identity,
capability, goal, presentation-preference, and red-line roles; missing roles remain
`UNKNOWN` and must not be inferred. Project context carries its entry contract,
project-only preferences, references, examples, and feedback. Runtime context carries the
current task goal, state, and evidence with an expiry.

The project entry names purpose, audience, acceptance, avoidance, and an index to the other
project roles. Operator red lines retain precedence; project context may narrow but not
weaken durable constraints; runtime state cannot mutate durable core. Feedback remains a
candidate until a measured trial supports promotion. Sensitive personal domains remain
project-scoped unless the operator explicitly grants a narrower cross-project use.

Validate an identity-bound manifest and exact load receipt with `python
scripts/fames_fleet.py validate-context-assets --workspace <root> --input
<manifest.json> --json`. PASS requires portable workspace-relative references, replayed
content hashes, exact expected-versus-loaded population closure, zero unknown assets,
provider-neutral routing, matching project/goal/manifest identities, and no raw context or
secret persistence. Copying files, pointing a model at a directory, or installing the
package is not load evidence.

AI-host neutrality is a required invariant, not a preference. Canonical policy may inspect only
capabilities, availability, authority, safety, evidence freshness, and cost. Product, model, vendor,
IDE, browser brand, adapter id, and skill name are never selection predicates or completion
prerequisites. Platform-specific code is permitted only behind a host-adapter contract. Its name may
appear in adapter inventories, compatibility aliases, and dated evidence, but it cannot own policy or
weaken a validator. Discover adapters at run time; if none satisfies the capability request, return
`HANDOFF / NO_CAPABLE_ADAPTER` with missing capabilities. Unknown availability is `UNKNOWN` and
fails closed. Renaming an adapter without changing its declared measurements must not change routing.

Execution is decentralized across registered harness surfaces, while canonical promotion
retains one writer to prevent policy drift. Every registered surface must load the same
content-addressed package, run the same validator, and leave a fresh load receipt plus a
behaviour probe. Validate a coverage record with `python scripts/fames_fleet.py
validate-harness --input <record.json> --json`. A registered but unloaded or mismatched
surface, and every unregistered harness, is `UNKNOWN`; package presence alone is not a
compliance claim. A harness rename with unchanged capabilities and evidence must not alter
the decision.

## Authority, followers, and peer learning

`ai_darkhero` publishes the canonical generation. `ai_scar3` and `ai_altos` follow it with one idempotent transition: `fames_fleet.py follow --workspace <root> --host <seat>`. The command downloads the authority manifest, verifies every file and the package identity, atomically activates the package, and writes a local receipt. An online bootstrapped follower converges in one invocation; an offline or unbootstrapped machine remains `UNKNOWN` until its first successful invocation. `follow` is the primitive; `converge` below is what a machine actually schedules.

Followers may publish evidence and candidate improvements, but only the authority promotes a new canonical generation after FP, SCF, and SEAL. This keeps learning bidirectional without multi-writer drift.

For a GitHub raw branch authority, `follow` first resolves the branch through the
repository API and pins every manifest and package-file fetch to that measured commit
SHA. A mutable branch URL or a stale CDN object is never accepted as the package
identity; any hash mismatch remains `UNKNOWN` and fails closed.

## Zero-token natural convergence — the runner is part of the package

A package that depends on an external engine to update itself is not portable: a cold-loaded skill on a fresh machine would sit at whatever generation it was cloned at until someone ran `follow` by hand. So FAMES carries its own runner.

```
python scripts/fames_fleet.py converge --workspace <root> --host <seat> --arm --json
```

`converge` is `follow` plus two things a scheduled run needs and an interactive one does not: it writes a heartbeat to `_registry/fames-converge/<host>.json` recording the time, outcome, resulting `package_sha`, and rider state, and it reports whether the machine's own clock is still registered to run it. `arm` performs that registration — an idempotent upsert of the rider `fames-converge` on host `HubClock` at 15m through the machine's `register-rider.py`. Windows logon starts HubClock; the next 15-minute boundary runs FAMES's own script against the authority manifest. A verified matching generation fetches no package files.

Three properties matter more than the mechanism. Arming **re-measures** the registry after the engine exits, because an exit code 0 is a claim and the rider row is the evidence. Arming **repairs drift but never re-adds a removed rider**, so it cannot fight an operator who deliberately disarmed it. And where `register-rider.py` does not exist, `arm` prints the exact registration it would have made and reports a named blocker rather than claiming a schedule it did not create.

The heartbeat exists so that liveness is measured rather than assumed: `C-CONVERGE-HEARTBEAT` charges `R_FLEET` when the newest heartbeat is over 6 hours old, and `C-CONVERGE-ARMED` charges it when a heartbeat reports its rider is anything but `armed`. Without them a dead rider, a powered-off machine, and a stale generation are indistinguishable. Both are `degraded`: a machine that is merely off should not block the authority's run. This path calls no model and adds no resident process.
