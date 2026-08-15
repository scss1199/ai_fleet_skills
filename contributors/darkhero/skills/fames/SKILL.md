---
name: fames
description: Execute the complete FP, MTM, SCF, AEX, and SEAL contract. Use when the user types FAMES, invokes $fames, asks for the former broad AEX Stack, or requires a task to be first-principles scoped, minimal-token routed, residual-checked, adaptively evolved when warranted, and evidence-sealed without silently skipping a phase.
---

# FAMES

Treat FAMES as one completion contract, not as a label or permission grant. Read the [bundled FAMES protocol](references/protocols/fames-protocol.json) before execution and run `token-preflight` before broad exploration. The bundled protocol is the portable authority; if `%AI_WORKSPACE%\_registry\fames-protocol.json` also exists, require it to describe the same version and execution order or report `UNKNOWN`.

Before relying on the skill, run `scripts/fames_fleet.py verify-package --json` from this skill directory. The verifier must pass without reading any workspace file; this is the cold-load proof that GitHub delivered a complete skill rather than a pointer to one machine's registry.

## Freshness — resolve at run time, never from memory

FAMES-GEN: 2026-08-15.2

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

Classify the task with the bundled profile/risk table. Risk may add evidence and guards but never authority. For a machine-verifiable completion record, pass the provider-neutral JSON ledger to `python scripts/fames_fleet.py validate-run --input <run.json> --json`; a non-zero exit fails closed. R2/R3 records require the bounded PREPARE/APPLY/VERIFY/COMMIT/RECOVER transaction fields, and R3 also requires a passing recovery drill.

## Completion truth

Report one row for every phase with `PASS`, `NOT_APPLICABLE`, `UNKNOWN`, or `FAIL`, plus its evidence. `NOT_APPLICABLE` needs an explicit false activation predicate; it is never an implicit skip. Any missing, stale, mismatched, exception-producing, or unverifiable evidence is `UNKNOWN`, and `UNKNOWN` fails closed.

FAMES broadens completeness only and does not expand user authority. It never authorizes destructive actions, external writes, live-device access, deployment, credential access, or any action outside the user's stated scope.

## Fleet generation rule

Treat `bundle-manifest.json.package_sha` as the FAMES generation identity. A machine has FAMES only when its installed package verifies and its GitHub contributor manifest reports that exact `package_sha`. A missing contributor receipt, stale manifest, hash mismatch, or unreadable bundled protocol is `UNKNOWN`; never infer convergence from a matching folder name.

## External learning — outside material that proposes a change

When material from outside the fleet is used to justify a change to canon, tooling, or routing, run the `external_learning` lane in the bundled protocol: `ACQUIRE -> UNDERSTAND -> CLAIM -> TRIAL -> PROMOTE`. It is a lane feeding AEX, not a sixth phase; `execution_order` is unchanged.

Acquire by cost order — publisher-supplied text, then a local model whose input never leaves the machine, then a metered API — and treat a login wall, paywall, or bot check as a named blocker for the operator, never a puzzle. Classify every item as `measured` (a deterministic local instrument), `modelled` (ASR, OCR, summary), or `asserted` (the source's own words). **Only `measured` items are admissible as SEAL evidence.** A modelled or asserted item is a candidate that needs a measured verification of its own, whose Verification is written before the trial runs. `already_covered` is a first-class verdict and costs nothing.

Record the ingest at `_registry/fames-evidence/ingest-<stamp>-<slug>.json` and validate it with `python scripts/fames_fleet.py validate-ingest --input <file> --json`. A record missing provenance, content identity, route, or a per-claim verdict is `UNKNOWN` and fails closed; `UNKNOWN` never promotes. Followers may publish an ingest record as a candidate improvement; only the authority promotes, after FP, SCF, and SEAL.

## Self-check — FAMES run against FAMES, at zero tokens

The contract is only as good as the last time it was actually exercised. One command exercises it:

```
python scripts/fames_fleet.py self-check --json --workspace %AI_WORKSPACE%
```

It runs `status` and then every case declared in [references/cases.json](references/cases.json), and writes a replayable record to `_registry/fames-evidence/self/<stamp>.json`. No model is called and no quota is spent, so it is admissible `measured` evidence and may be run as often as it is useful.

A **case** is a deterministic probe that names the residual dimension it charges (`R_CONTRACT`, `R_SEMANTICS`, `R_FLEET`, `R_CAPABILITY`, `R_HYGIENE`, `R_FRESHNESS`) and how it fails: `closed` blocks, `degraded` is recorded and counted but does not block. `UNKNOWN` always blocks regardless of the declared mode. The residual is the count of charges per dimension, so SCF is computed rather than narrated, and AEX activates only where a dimension is non-zero. Cases live in the registry as data: **adding a check means adding a case, not writing code.** A case whose kind, dimension, or fail mode is not one of the declared values is `UNKNOWN` — data cannot smuggle in new behaviour.

A residual that is real must stay red until it is fixed. Do not silence a case to make a run green; a green run bought by deleting its probe is the exact failure this section exists to prevent.

The package identity is regenerated by `build-bundle`, which refuses to publish changed contents under a version and a `FAMES-GEN` stamp that already name a different package (`--allow-same-gen` overrides, for a bootstrap). Followers can therefore always order two generations.

## Minimal neutral architecture

Keep one provider-neutral canonical skill. Put deterministic work in one reusable script, keep provider discovery paths as data-driven junctions, and add an adapter only when a runtime boundary truly differs. A file or process must have a verified caller or contract role; otherwise merge or remove it. Minimize, in order: physical files, executable code, execution steps, then steady-state resource use.

## Authority, followers, and peer learning

`ai_darkhero` publishes the canonical generation. `ai_scar3` and `ai_altos` follow it with one idempotent transition: `fames_fleet.py follow --workspace <root> --host <seat>`. The command downloads the authority manifest, verifies every file and the package identity, atomically activates the package, and writes a local receipt. An online bootstrapped follower converges in one invocation; an offline or unbootstrapped machine remains `UNKNOWN` until its first successful invocation.

Followers may publish evidence and candidate improvements, but only the authority promotes a new canonical generation after FP, SCF, and SEAL. This keeps learning bidirectional without multi-writer drift.

## Zero-token natural convergence

Use the existing HubClock `fleet-skill-pulse` rider as the only event runner. Windows logon starts HubClock; the next 15-minute wall-clock boundary performs a provider-neutral GitHub manifest probe. A changed FAMES package is hash-verified and atomically activated, while a verified matching generation fetches no package files. The same event publishes content-changed contributor manifests. Network failures retry at the next boundary. This path calls no model and adds no resident process.
