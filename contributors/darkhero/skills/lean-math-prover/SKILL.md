---
name: lean-math-prover
description: >-
  Machine-checked mathematics with the hub's local Lean 4 + Mathlib install (C:/ai_workspace/_lean).
  One command, JSON out, zero model tokens: the Lean kernel accepts a proof or reports where it
  breaks. Use when a task needs a claim PROVED rather than argued (algebraic identity, inequality,
  number theory, logic, combinatorics, bit-vector facts), when checking a model-written proof, or
  as an exact calculator (#eval on big integers and rationals). Keywords: lean, mathlib, theorem,
  prove, proof, formal verification, 數學證明, 定理, 形式化驗證, 證明檢查.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: on-demand
    token_budget: zero
    required: false
    engine: _lean/leanctl.py
    registry: _lean/evidence/
    seat: ai_darkhero
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# lean-math-prover

> **One-liner:** `python C:/ai_workspace/_lean/leanctl.py check --file proof.lean --out receipt.json`
> Full contract: `C:/ai_workspace/_lean/README.md`. No PATH, elan or environment setup is needed;
> any agent with a shell can call it (Claude Code, Codex, Cursor, DSH local models, scripts).

Lean checks proofs; it does not invent them. You write the statement and the proof, the kernel
decides. Iterate on the error messages until the verdict is `PROVED`, or report that you could not
prove it.

## Commands

```
python C:/ai_workspace/_lean/leanctl.py check --file proof.lean [--out receipt.json]
python C:/ai_workspace/_lean/leanctl.py check --stdin < proof.lean
python C:/ai_workspace/_lean/leanctl.py --ascii check --file proof.lean    # cp950 / legacy consoles
python C:/ai_workspace/_lean/leanctl.py info                                # versions, Mathlib readiness
python C:/ai_workspace/_lean/leanctl.py selftest --require-mathlib          # 31 live controls
python C:/ai_workspace/_lean/leanctl.py exec --cwd C:/path/proj lake -- build
```

Write the source to a **UTF-8 file** and pass it with `--file`. Avoid `--code` and avoid piping
from Windows PowerShell 5.1: both turn `ℝ ∀ ≤ ⟨` into `?`, and Lean then fails on syntax. A file
written by PowerShell `>` / `Out-File` (UTF-16 with BOM) is accepted; a cp950 file is refused
with `INPUT_ERROR`. `import Mathlib…` in the source turns Mathlib on by itself. stdout is always
one JSON document, whatever goes wrong.

## Minimal file

A longer working sample (induction, a Mathlib lemma) is at `C:/ai_workspace/_lean/examples/demo.lean`.

```lean
import Mathlib

theorem sq_sum (a b : ℝ) : (a + b) ^ 2 = a ^ 2 + 2 * a * b + b ^ 2 := by ring

theorem amgm2 (x y : ℝ) : 2 * x * y ≤ x ^ 2 + y ^ 2 := by nlinarith [sq_nonneg (x - y)]
```

## Reading the result (fail closed)

| verdict | exit | what you may say |
|---|---|---|
| `PROVED` | 0 | "formally verified" — quote `audit.theorems[].statement` (an entry with `synthetic: false`), pass on `cautions`, cite the `--out` receipt |
| `CHECKED` | 0 | "Lean computed this" (`#eval`/`#check` output is in `messages[]`); nothing was proved. A file with only `def`s or a `structure` lands here too |
| `FAILED` | 1 | not proved; `messages[]` holds the error and the unsolved goal (1-based `line`) |
| `INCOMPLETE` | 1 | `sorry`/`admit` present: nothing was proved |
| `UNSOUND_AXIOMS` | 1 | own `axiom`, `native_decide`, `decide +native`, or a SAT-backed `bv_decide` |
| `UNVERIFIED` | 1 | `example`, `#guard_msgs`, `set_option debug.*`, `#exit`, a Lean crash, or a broken audit |
| `UNSUPPORTED` / `TIMEOUT` / `ELABORATED` | 1 | not a proof verdict; see README |
| `INPUT_ERROR` | 2 | the call was unusable (bad arguments, unreadable or non-UTF-8 file): nothing was checked — fix the call, read `error` |
| `SETUP_ERROR` | 2 | install problem: run `info`, then README "Rebuild / upgrade" |
| `INTERNAL_ERROR` | 2 | a leanctl bug: nothing was checked; report `error` to the curator |

Exit 2 says nothing about the mathematics. With `--out`, an exit-2 error overwrites the receipt,
so an older `PROVED` at that path never stands in for the current run.

## What exactly was proved — read these before you repeat a statement

`audit.theorems[]` is what the kernel accepted, printed by the checker itself (default options,
root namespace, nothing opened). Per entry:

| field | read it as |
|---|---|
| `statement` | the proposition. Quote this, never your own prompt |
| `statement_typed` | same statement with the type of every numeral: `(2 : ℝ) ^ (1 / 2 : ℕ) = (1 : ℝ)` shows that `1 / 2` was natural-number division. Check it whenever numerals, `/` or `-` appear |
| `local_deps` | definitions of **your file** the statement mentions. `theorem rh : RH` with `def RH : Prop := True` proves nothing about Riemann: quote those definitions with the claim |
| `shadow_instances` | your file redefined `+`, a numeral, … for an imported type (`instance : Add Nat`). The statement does not mean what it looks like; do not report it as ordinary arithmetic |
| `statement_form` | `pretty` normally; `no_notation` / `kernel` when the file registers its own notation or printing code, or uses a shadow instance. `statement_pretty` then holds the rendering not to trust |
| `synthetic: true` | Lean generated it (`Foo.mk.injEq`); it is not your result |

`cautions` says the same in words and never changes the verdict: empty for a plain file, and
whatever it holds goes into your report next to the claim. On `FAILED` / `INCOMPLETE` the list
still shows what the file declares — none of it is proved. At most 40 theorems are listed
(`theorems_total`, `theorems_truncated`): split a larger file.

## Red lines

- **Only `PROVED` may be reported as proved or formally verified.** Every other verdict,
  `CHECKED` included, proves nothing. Never paraphrase a failed run as "mostly verified".
- **State each result as a named `theorem`. `example` is refused even when correct**: it leaves
  nothing to audit or cite.
- **Never "fix" a failing proof with `sorry`, a new `axiom`, `native_decide`, a `debug.*` option
  or `#guard_msgs`.** The checker refuses all of them. Report the failure instead.
- **`PROVED` covers the Lean statement, not your informal claim.** Read the statement back from
  `audit.theorems[]` (section above). Traps: `ℕ` subtraction truncates (`2 - 3 = 0`), `/` on
  `ℕ`/`ℤ` floors, `1 / 0 = 0` in a field, a contradictory hypothesis proves anything.
- **Prove facts about Mathlib's definitions, not about look-alikes you define yourself.** Do not
  declare `notation`/`infix`, unexpanders, delaborators, or instances for imported types
  (`instance : Add Nat`) in a file you want verified: the receipt unmasks them (`local_deps`,
  `shadow_instances`, `pp_extensions`, `cautions`) and the claim becomes worthless.
- The checker guards against sloppy or hallucinated proofs, not against a source that ships its
  own macros or metaprograms (`text_flags` lists those keywords). Do not write them to get a pass.
- `_lean/` is shared by the whole fleet: do not edit the toolchain, `hubmath/` or `state/` from
  a task. Upgrades go through `install_lean.py` + `setup_mathlib.py` (curator lane).

## Tactics worth trying first

`decide` (small decidable facts) · `omega` (linear ℕ/ℤ arithmetic) · `norm_num` (numerals) ·
`ring` (commutative ring identities) · `linarith` / `nlinarith [sq_nonneg (x - y)]` (ordered
fields) · `positivity` · `field_simp` · `simp` · `gcongr` · `aesop` · `exact?` (searches Mathlib;
slow, the suggestion arrives in `messages[]`).

## Cost

Core check 2–3 s; `import Mathlib.Tactic` ~10 s; full `import Mathlib` 16–23 s (import time
dominates, so put several theorems in one file). Keep parallel Mathlib checks to two or three:
each maps several GB of `.olean` files. Default timeout 600 s.

## CITE

`_lean/leanctl.py` · `_lean/README.md` · `_lean/tests/test_leanctl.py` (offline verdict tests) ·
`_lean/evidence/selftest.json` (live controls) · Lean v4.34.0 + Mathlib `v4.34.0`
