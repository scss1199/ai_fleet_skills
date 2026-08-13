---
name: fames
description: Execute the complete FP, MTM, SCF, AEX, and SEAL contract. Use when the user types FAMES, invokes $fames, asks for the former broad AEX Stack, or requires a task to be first-principles scoped, minimal-token routed, residual-checked, adaptively evolved when warranted, and evidence-sealed without silently skipping a phase.
---

# FAMES

Treat FAMES as one completion contract, not as a label or permission grant. Read the [bundled FAMES protocol](references/protocols/fames-protocol.json) before execution and run `token-preflight` before broad exploration. The bundled protocol is the portable authority; if `%AI_WORKSPACE%\_registry\fames-protocol.json` also exists, require it to describe the same version and execution order or report `UNKNOWN`.

Before relying on the skill, run `scripts/fames_fleet.py verify-package --json` from this skill directory. The verifier must pass without reading any workspace file; this is the cold-load proof that GitHub delivered a complete skill rather than a pointer to one machine's registry.

## Freshness — resolve at run time, never from memory

FAMES-GEN: 2026-08-12.1

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

## Completion truth

Report one row for every phase with `PASS`, `NOT_APPLICABLE`, `UNKNOWN`, or `FAIL`, plus its evidence. `NOT_APPLICABLE` needs an explicit false activation predicate; it is never an implicit skip. Any missing, stale, mismatched, exception-producing, or unverifiable evidence is `UNKNOWN`, and `UNKNOWN` fails closed.

FAMES broadens completeness only and does not expand user authority. It never authorizes destructive actions, external writes, live-device access, deployment, credential access, or any action outside the user's stated scope.

## Fleet generation rule

Treat `bundle-manifest.json.package_sha` as the FAMES generation identity. A machine has FAMES only when its installed package verifies and its GitHub contributor manifest reports that exact `package_sha`. A missing contributor receipt, stale manifest, hash mismatch, or unreadable bundled protocol is `UNKNOWN`; never infer convergence from a matching folder name.
