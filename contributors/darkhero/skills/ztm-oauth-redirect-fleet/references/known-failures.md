# ztm-oauth-redirect-fleet — known failures

Rule 13 log. Every entry is a failure that was actually measured while running
this skill, written as: symptom → root cause → safe fix → retry rule.

Keep this file limited to reproducible, secret-free facts discovered during real
runs. Never paste an OAuth `code`, `state`, client secret, or cookie here — those
are short-lived credentials and this file is committed.

---

## A registered redirect_uri can still be dead (false GREEN, `STALE_ORIGIN`)

**Symptom.** The probe reported the site green. The operator then demonstrated
the opposite from the browser: `https://ai-ziyaoastro.kyloren.workers.dev/login/`
sent them to Google, Google accepted the sign-in and issued a `code`, and the
callback landed on `https://ai-ziyaoastro.vercel.app/api/auth/google/callback`,
which is not the app any more. Login was impossible while every automated check
said REGISTERED (measured 2026-08-09).

**Root cause.** The detector asked Google one question — "is this URI on the
client?" — and treated the answer as the verdict. Google only checks
registration; it has no opinion about whether the host still serves the app. A
URI left over from a previous deployment stays registered indefinitely, so the
stale host produces a *successful* OAuth flow into a 402
`DEPLOYMENT_DISABLED` page. Google being happy is a necessary condition, never a
sufficient one.

**Safe fix.** Add an origin-match test to every row: compare
`urlparse(redirect_uri).netloc` with `urlparse(probed_base).netloc`. Downgrade a
would-be `REGISTERED` with a foreign netloc to `STALE_ORIGIN`. Do the downgrade
*after* the Google verdict and only on `REGISTERED` — a `MISMATCH` is already BAD
and naming the registration gap is the more actionable message.

Repairing a `STALE_ORIGIN` needs two edits and **the order is load-bearing**:

1. console: ADD the new URI (never edit or delete the old line — see below);
2. then flip the app's emit side.

Reversed, a site that was broken *after* login becomes a site that cannot reach
consent at all. For `ai-ziyaoastro` the emit side turned out to be one Fly secret
on the backend, not the Worker — the Worker is an assets+proxy shim and the
FastAPI app derives the URI from `GOOGLE_REDIRECT_URI` or, failing that, from
`x-forwarded-host`. No source edit was needed.

**Retry rule.** After flipping an emit side, expect the row to move
`STALE_ORIGIN → MISMATCH`, and report it that way. Both states are broken, so
this is not a regression: it is the correct prerequisite state, and it collapses
the site onto the same single console step as everything else. Do not "fix" it by
re-registering the dead origin.

**Family.** This is the second false GREEN this same probe has produced. The
first: the initial run reported 9/9 REGISTERED because it substring-matched the
URL for `redirect_uri_mismatch`, which Google never spells out in the clear (it
lives inside the base64 `authError` payload — detector rule 2). Both failures
share one shape: a check that confirms what it hoped to see. Cross-reference the
same class in `cca-token-governance/references/known-failures.md`.

---

## A hand-maintained site list under-reports, silently

**Symptom.** The task was "every site must be checked". The probe ran eight
times, reported cleanly each time, and had never once looked at `ai-trader` or
`ai-fleet-fly-hooks` (measured 2026-08-09). Nothing errored; the two workers were
simply not in the `SITES` dict.

**Root cause.** Coverage was a human memory, so "every site was checked" actually
meant "every site someone remembered to add". A missing row is indistinguishable
from a passing row in the output — the failure mode is invisible by construction.

**Safe fix (2026-08-09).** `discover_workers()` unions `SITES` with every
directory under `_registry/cf-deploy-configs`, giving discovered workers a default
candidate path list. Coverage becomes a property of what is deployed rather than
of what was typed.

**Superseded 2026-08-10 — the 08-09 fix was still under-specified.** Directory
discovery makes coverage a property of *whatever happens to be on disk at run
time*, which is not reviewable and not stable: two services (`ai-busker`,
`ai-eatery`) have no `cf-deploy-configs` directory at all and would have gone back
to being invisible. `SITES`/`BASES`/`discover_workers()` are gone. Coverage is now
`scripts/inventory.json` — one reviewed entry per service carrying
`expects_login`, `login_paths`, `canonical_origin`, `client_id`, and
`coverage_source`. A deployed worker with no inventory entry is counted and
printed as `undeclared`; it cannot be absent and clean at the same time.

The same trap had a second instance in the same skill: `gen_redirect_handoff.py`
carried a hand-written `PENDING_ADDS` list of stale-origin sites. Once the real
fix landed, the row became a genuine `MISMATCH` *and* the stale hand entry kept
printing, so the handoff told the operator to redo finished work. It now derives
from the probed rows.

**Retry rule.** Before claiming fleet-wide coverage, check `undeclared=0` in the
stderr summary and that every service in `inventory.json` appears in exactly one
of `OK / BLOCKED / N/A`. A worker missing from all of them is the bug this entry
describes.

---

## `NO_LOGIN` must be printed, not filtered

**Symptom.** Filtering non-OAuth workers out of the summary made the report
tidier and the coverage claim weaker.

**Root cause.** `OK / BAD` is a two-bucket verdict over a three-state world. A
worker with no login endpoint is neither; dropping it means a site that *lost*
its login endpoint would silently leave the report exactly when it broke.

**Safe fix (2026-08-09).** Third bucket. Print `OK=<n> BAD=<n> NOLOGIN=<n>`, list
the `NO_LOGIN` rows with the HTTP status that justified the verdict, and keep the
loop gated on `BAD=0` only. Confirmed by hand for both current rows:
`ai-trader` `/` → 200 with no Google marker and `/login` → 404;
`ai-fleet-fly-hooks` `/` → 404. Genuinely nothing to register.

**Superseded 2026-08-10 — a non-gating third bucket is the same bug wearing a
different hat.** "Neither pass nor fail" is exactly the state a broken site lands
in when its login endpoint disappears, so the retry rule below was asking a human
to notice, every run, what the exit code refused to say. The distinction that
actually matters is not *does it have a login now* but *is it supposed to have
one* — which is a declaration, not an observation. `inventory.json` carries
`expects_login`. `false` (hooks-only: `ai-trader`, `ai-fleet-fly-hooks`) grades
`NOT_APPLICABLE` and skips the Google request entirely; for `true`, a missing or
unreachable login endpoint is `LOGIN_MISSING`/`LOGIN_UNREACHABLE` and **blocking**.
The summary is now `OK=<n> BLOCKED=<n> N/A=<n> undeclared=<n>`.

**Retry rule.** A worker moving `BLOCKED → NOT_APPLICABLE` between runs is not a
fix and is no longer even possible by accident — it requires someone editing
`expects_login` to `false` in `inventory.json`. Treat such a diff as a claim that
the service dropped Google SSO by design, and make it prove that.

---

## `fleet-skill-vet.py` reports `base64-exec` on this skill — accepted, not fixed

**Symptom.** `fleet-skill-vet.py scan ztm-oauth-redirect-fleet` →
`FAIL hits=1 frontmatter=True / base64-exec: base64.b64decode` (2026-08-09).

**Root cause.** `DANGER_PATTERNS` matches the bare string `base64.b64decode` to
catch decode-then-execute payload smuggling. The only hit here is
`_decode_auth_error()` in `probe_redirect_uri.py`, which decodes Google's
`authError` parameter so the literal `redirect_uri_mismatch` can be read. It is
detector rule 2, it is load-bearing, and its output is compared against a string
and then discarded — nothing is executed, imported, or written. The finding
predates the 2026-08-09 changes; it is a false positive, and the vet has no
per-finding waiver (`ALLOWLIST_REPOS` only governs SKILL.md import).

**Safe fix.** None — leave it. Removing the hit would mean decoding base64 by a
spelling the scanner does not recognise (`binascii.a2b_base64`, a manual
alphabet, …), which changes nothing about what the code does and only defeats the
check. Editing `DANGER_PATTERNS` to admit this skill is the same move one level
up. A security scan that gets quietly reworded until it passes stops being a
scan.

**Retry rule.** Expect `hits=1 base64-exec` on this skill and treat it as the
known baseline; report it rather than hiding it. Any *additional* hit, or a hit
in a file other than `probe_redirect_uri.py`, is real and must be investigated.
If the noise ever needs to stop, the correct route is a SUBMIT proposing a
per-finding waiver mechanism in the engine — an operator decision, not a
generator's edit to its own judge.

---

## The console edit cannot be automated, and must be ADD-ONLY

**Symptom.** Repeated attempts to close the loop programmatically, all dead ends.

**Root cause.** There is no public API for classic Web OAuth clients:
`gcloud alpha iam oauth-clients` is Workforce Identity Federation (returns
`Listed 0 items` on a project with live Web clients — verified) and
`gcloud iap oauth-clients` covers IAP brands only. The console drives a private
`clientauthconfig` backend. Separately, the harness permission classifier
hard-denies the agent editing OAuth redirect URIs, and **operator authorization
in chat does not lift it** — the gate is below the conversation. Retrying through
a DOM inventory or a different browser tool is a route-around, not a fix.

**Safe fix.** Generate `redirect_uri_fix_handoff.md`, grouped by `client_id` so a
shared client is visited once, and hand it over. In **Authorised redirect URIs**
(not JavaScript origins) click **+ Add URI** and add a line. **Never edit or
delete an existing line** — clients here are shared (`433379372607-*` covers
several sites), and rewriting a line takes a currently-working site offline.

Do not let this block delivery: a site can ship behind a `kind:"passcode"`
session branch signed by a `SITE_PASSCODE` set through the deploy CLI via stdin,
which leaves Google SSO intact to auto-activate the moment the URI lands.

**Retry rule.** The agent must never type the account password — prohibited
action, hand off instead. Re-measure with the probe after the operator's edits;
`BLOCKED=0` with the probe exiting 0 is the only completion signal, and the
negative control (`control_redirect_uri.py`) must be run alongside it — and must
exit **0**, not merely run — so a green report is not itself the third false GREEN.

---

## The negative control was passing a policy rejection off as proof

**Symptom.** `control_redirect_uri.py` had exited 0 on every run since it was
written. The first run after it was changed to actually *assert* its outcomes
(2026-08-10) reported `negative expect=MISMATCH got=OAUTH_ERROR ... FAIL`.

**Root cause.** `BOGUS_HOST` was `definitely-not-registered-xyz.invalid`, chosen
because RFC 2606 reserves `.invalid` so the host can never be acquired or
registered. Measured against Google with the same client and the same query:

```
definitely-not-registered-xyz.invalid      -> invalid_request       (OAUTH_ERROR)
definitely-not-registered-xyz.example.com  -> redirect_uri_mismatch (MISMATCH)
definitely-not-registered-xyz.kyloren.workers.dev -> redirect_uri_mismatch (MISMATCH)
```

Google validates the redirect URI's host against its OAuth policy **before**
comparing it against the client's registered list. The `.invalid` request died at
the policy gate and never reached the comparison the negative control exists to
exercise. The control had never once tested what it claimed to test — and this was
invisible only because the old version printed both results and returned 0
unconditionally. Two independent defects, and the second hid the first.

**Safe fix.** `BOGUS_HOST = "definitely-not-registered-xyz.example.com"` — RFC 2606
§3, held by IANA permanently, so equally impossible to acquire or register, but a
syntactically valid publicly-resolvable domain that reaches the comparison. Plus a
three-valued exit code, because "the control failed" and "the control did not run"
are different accusations: only `REGISTERED` and `MISMATCH` are `CONCLUSIVE`;
anything else returns **2** (the control is broken) instead of **1** (the probe is
broken). `test_redirect_uri.py` pins all three codes offline.

**Retry rule.** Do not "harden" `BOGUS_HOST` back to a reserved TLD — it reads
like an improvement and silently makes the control inert. The offline test asserts
`.example.com` specifically, with the measurement in the comment. And treat the
general shape as the lesson: a control that cannot fail is not a control, so any
verifier whose self-check has never once returned non-zero should be assumed
untested until someone makes it fail on purpose.
