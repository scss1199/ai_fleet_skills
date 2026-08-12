# CCA review-lane known failures

Keep this file limited to reproducible, secret-free facts discovered during real reviews.
Token counts, policy knobs, provider names and verdict strings are observable; prompt bodies,
transcripts and hidden reasoning are not — see [policy.md](policy.md) "Safety and observability".

---

## The review lane can be down at two independent layers, and the cheap diagnostic is not the one you reach for first

**Symptom** — `codex-shadow-review.py review` exits 2 without contacting the reviewer:

```
SHADOW-REVIEW SKIPPED
```

```json
{"schema": 1, "deterministic": true, "third_party_calls": 0,
 "target": "_registry/cf-deploy-configs/ai-darkhero/src/index.mjs",
 "fingerprint": "36f22859ac5215fe84e391b86d7d3f65", "files": 1,
 "mode": "observe", "allowed": false, "action": "observe",
 "reason": "raw_token_budget_24h", "reused_verdict": "",
 "policy": {"cooldown_minutes": 1440, "max_reviews_per_target_24h": 1,
   "raw_token_budget_24h": 100000, "estimated_raw_tokens_per_review": 100000,
   "would_block_min_calls": 20, "would_block_observe_threshold": 0.5},
 "raw_tokens_used_24h": 19850, "raw_tokens_used_24h_fully_observed": true,
 "would_block_calls_24h": 0, "would_block_rate_24h": null,
 "estimated_next_raw_tokens": 100000}
```

The escalation documented in the `codex-review-cost-discipline` memory — fall back to the free
pre-screen `cca-triage.py` — then also produced nothing:

```
CCA-TRIAGE index.mjs  voters=0/3  bytes=11169  blockers=0  concerns=0  echoed=0
  (no vote) nvidia-nim/deepseek: nvidia-nim circuit-open
  (no vote) gemini/gemini: gemini circuit-open
  (no vote) cerebras/gpt-oss: cerebras circuit-open
CCA-TRIAGE: NO voter returned a usable answer — this is NOT a clean result.
```

**Root cause** — two unrelated mechanisms that happen to fail on the same day:

1. **Admission arithmetic, not a quota you can wait out inside the day.**
   `estimated_raw_tokens_per_review` (100000) **equals** `raw_token_budget_24h` (100000), and the
   estimate is **flat** — it did not scale down for an 11,169-byte single-file target. Admission
   step 6 in [policy.md](policy.md) compares `raw_tokens_used_24h + estimated_next` against the
   budget, so **once any nonzero spend is on the clock, the next review of any target is refused**.
   Measured spend was `19,850` against a `100,000` budget: 80% of the budget was unspent and the
   review was still refused. Note this is not a token-accounting bug — `19,850` is the gate
   converting the prior review's legacy CLI-only `tokens used 14,346` per policy.md admission
   rule 6 ("uncached input plus output, not raw total"). The accounting is working; the
   *estimator* is roughly 5x pessimistic and self-blocking.
2. **Free-pool circuit breakers, all open at once.** `_llm.py` short-circuits any provider whose
   breaker is open and returns `__ERR__ <p> circuit-open` without a call, so `panel_chat()` drops
   every answer and the voter count collapses to zero. The breaker is
   `_free_api_supervisor.py:CircuitStore(threshold=2, cooldown=900)` — **two consecutive failures
   open a 900-second circuit**, one success resets it. State lives in
   `_registry/free-api-health.json`.

**Safe fix** — there is no fix for (1) inside the window; there is a correct *diagnosis order*, and
two readings that must not be made:

```powershell
# 30-second, zero-token pre-check. Run this BEFORE spending a triage launch.
python C:\ai_workspace\_skill\engines\_free_api_supervisor.py status
```

Read the cumulative `failures` count, not just the state word. Measured here:

```
cerebras    open   failures 2    retry_after 542s
gemini      open   failures 2    retry_after 851s
mistral     CLOSED failures 68   retry_after 0
nvidia-nim  open   failures 108  retry_after 774s
openrouter  open   failures 43   retry_after 174s
sambanova   open   failures 30   retry_after 776s
```

`failures 2` is a transient blip worth a 900 s wait. `failures 108` is chronic — the key is
exhausted or expired, and waiting out the cooldown just re-trips it on the next call. Chronic
counts route to `token-onboard.py`, never to a chat-pasted key.

Two misreadings to refuse explicitly:

- **`blockers=0 concerns=0` with `voters=0` is not a clean result.** Zero voters answered, so the
  zeros are the absence of evidence, not evidence of absence. The tool says so in its own output;
  believing it anyway is the false-GREEN class. Also note triage is never a verdict even at full
  strength — `cca-triage.py --help`: "Codex remains the only judge".
- **Do not widen `raw_token_budget_24h` (or lower `estimated_raw_tokens_per_review`) to admit your
  own review.** Editing the judge's admission gate so that it admits you is the generator judging
  itself by another route, which is the whole thing the CCA split exists to prevent. Recalibrating
  a 5x-pessimistic estimator is a legitimate change — but it is the operator's call, made as its
  own reviewed change, not as a side effect of wanting a verdict today.

**Retry rule** — one Codex attempt per 24 h window (`cooldown_minutes: 1440`), one triage attempt,
then stop escalating and **substitute direct measurement of the artifact in production**. For a
claim shaped like "status and Location are unchanged, this header is now present", an anonymous
live probe is stronger evidence than a reviewer's opinion, because it observes the deployed
artifact rather than the source. Measured substitute for the refused review above:

```
ai-darkhero  /  302  cache_control="private, no-store"  cf_cache_status=""  age=""
                     location=https://ai-darkhero.kyloren.workers.dev/login.html
```

Report the blocked lane in the operator report. A change verified by production measurement and
**not** reviewed is honest; the same change described as reviewed is not.

**Two adjacent traps hit while doing this**

- A `--claim` passed through PowerShell must contain **zero `"` characters**, including inside a
  `@'…'@` here-string. A claim containing `302 -> /login.html` in quotes was word-split and
  argparse answered `unrecognized arguments: -> /login.html …` (exit 2), burning a launch. Write
  the claim in a single-quoted string with no double quotes at all.
- `cca-triage.py` publishes source to **third-party** endpoints, so run `policy --target <glob>`
  before `run`. Paths are deny-by-default via `_registry/cca-triage.json`; the measured deny list
  (`*/_secrets/*`, `*/ai_ut/*`, `*/fracdigi/*`, `*.env`, `*/vault.json`) mechanically encodes the
  charter's prose boundaries, and an unreadable config refuses the run rather than sending
  anything. Verify the target clears it — do not assume from the file's location.
- `codex-shadow-review.py show` takes **no** `--agent` flag; only `review` does.
- The pinned profile in [policy.md](policy.md) "Review profile" ignores caller model flags, so
  `--model` / `--reasoning-effort` / `--service-tier` on the command line do not change what runs.
  (Documented there, not measured here — this run never reached the model.)
