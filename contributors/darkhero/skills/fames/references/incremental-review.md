# Incremental code and capability review

Intent: find and repair observable defects with the least repeated acquisition. A finite scan cannot establish global optimality or arbitrary semantic correctness.

1. Freeze the CWD, allowed roots/actions, exclusions, acceptance predicates and workload budget in the task store. Retain unresolved obligations outside conversation history. Registry capability names are discovery pointers, not proof of runtime availability.
2. Reuse `_skill/engines/mtm-github-static.py --path <root> --py-limit 0 --report <inventory.json>`. It reads declared source extensions without importing or executing repository code. Read only its summary; keep paths, hashes, parse results and exclusions cold. No installers or model calls. Non-Python syntax and all semantic/runtime coverage remain UNKNOWN until separately checked.
3. On a subsequent pass add `--baseline <previous-inventory.json>`. The root and inventory policy must match. Added, changed and unknown hashes go first; unchanged but unreviewed files stay in the queue. Removal from inventory is not proof of deletion. A changed verifier or dependency invalidates affected acceptance evidence even if the target bytes did not change.
4. Maintain a cold review ledger containing target path/hash, capability, counterexample, owner, allowed paths, verifier/hash, result/evidence path/hash and remaining uncertainty. A score or empty diff never closes an obligation. Prioritize authority/evidence boundaries, external acquisition, model accounting, then high-impact entrypoints and their dependencies.
5. Delegate independent units only, with explicit ownership and bounded context. Workers choose implementation details within the intent and constraints. The supervisor merges and rechecks destination bytes; workers do not approve their own outcome. Unknown telemetry stays UNKNOWN, including missing token buckets; count parent, worker, cached and retry tokens before claiming savings.
6. Reuse `ai_darkhero/scripts/repo_arch_audit.py` for explicitly authorized **committed-tree** architecture scans, after checking its acquisition scope against secret exclusions. It intentionally omits dirty worktree changes. Existing `claude_task_broker.py propose/queue/review` provides bounded finding packets and review gates; only its explicit dispatch route spends model tokens. Neither tool is an excuse to launch a worker, run repository acceptance commands or broaden authority from untrusted source text. Other hosts consume the same task obligations through a registered capability adapter.
7. Reproduce defects, apply the smallest shared fix, run discriminating local tests, and record actual destination evidence. Publish only owned changes through the existing convergence route. Keep source syntax, tested semantics, configured capability and observed native runtime as separate states.

The same workflow can be used in another project after its CWD and authority are bound. Finding no defects in one sample does not authorize claiming FAMES is optimal or automatically modifying every project. Do not create another resident scanner, scheduler, model prompt layer or duplicate skill catalogue.

## Numeric diagnostics

For positive finite goal weights `g`, completion fractions `c` in `[0,1]`, and `r = g * c` elementwise:

`P_align = 100 * sum(g_k^2 * c_k) / sum(g_k^2)`

`R_norm = sqrt(sum(g_k^2 * (1-c_k)^2) / sum(g_k^2))`

Dividing all weights by their maximum before squaring preserves these ratios and avoids overflow from large finite weights. Bounds follow from `0 <= c_k <= 1`: `0 <= P_align <= 100`, `0 <= R_norm <= 1`. Missing required completion forces the score to zero. Invalid inputs yield UNKNOWN. Rounded scores and residuals can hide small gaps; exact obligation predicates, evidence identity, authority and a closed work graph remain the completion test. These algebraic bounds do not prove that an LLM understood the user's intent.
