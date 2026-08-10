---
name: ztm-oauth-redirect-fleet
description: >-
  Fleet-wide redirect_uri_mismatch: measure registration state for every site
  with a 0-token probe (base64 authError decode + negative control), emit an
  ADD-ONLY per-client console work list, re-verify until BLOCKED=0.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: on-demand
    token_budget: low
    concept_id: VAR_AUTH
    species: VAR
    parent: ztm-cursor-edge-auth
    engine: fleet-skills/ztm-oauth-redirect-fleet/scripts/probe_redirect_uri.py
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# Fleet redirect_uri_mismatch — measure, list, fix, re-measure

> Scope: many sites × many GCP OAuth clients. For the single-portal case use
> `ztm-portal-google-sso-edge`; for the console click-path use
> `50-techniques/edit-google-oauth-redirect.md`. This skill is the **fleet loop**
> around those.

## Why a probe at all

`probe.ok=true` from an SSO verifier proves only that the OAuth **start** works
(302 → Google). It says nothing about whether the redirect URI is whitelisted.
The mismatch is only visible **inside Google's error payload**, and that payload
is base64. See "Detector rules" below — get this wrong and every site reports
REGISTERED while every login is broken.

## Loop

```powershell
# 0. offline suite — no network, runs in <0.1 s, covers every verdict combination
python <skill>\scripts\test_redirect_uri.py         # 92 tests; exit 0 required

# 1. measure (read-only, no console, no LLM tokens)
python <skill>\scripts\probe_redirect_uri.py        # writes redirect_uri_state.json

# 2. verify the verifier (mandatory, never skip)
python <skill>\scripts\control_redirect_uri.py

# 3. turn blocking rows into a per-client console work list
python <skill>\scripts\gen_redirect_handoff.py      # writes redirect_uri_fix_handoff.md

# 4. do the console edits (see "Who can edit" below)

# 5. re-measure — done when stderr reads BLOCKED=0 and the probe exits 0
python <skill>\scripts\probe_redirect_uri.py
```

Step 2's exit code is three-valued and the distinction is load-bearing:

| exit | meaning | who is accused |
|---|---|---|
| 0 | positive → REGISTERED **and** negative → MISMATCH | nobody; the probe can still tell them apart |
| 1 | a control returned the **opposite** verdict | the probe — its answers are suspect until explained |
| 2 | a control returned **no** verdict at all | the control itself — it never ran, and that is not a pass |

Exit 2 covers: no `REGISTERED`+`MATCH` row in state to build the positive case from,
Google unreachable, or Google rejecting the request *before* it ever compared the
`redirect_uri`. Only `REGISTERED` and `MISMATCH` count as conclusive.

## Detector rules (all five are load-bearing)

1. **Suppress redirects.** The `Location` header is the evidence; a following
   client swallows it.
2. **Decode `authError`.** Google 302s to
   `accounts.google.com/signin/oauth/error?authError=<urlsafe-base64 protobuf>`;
   the literal `redirect_uri_mismatch` exists only in the decoded bytes.
   Re-pad to a multiple of 4 before decoding.
3. **Send a Chrome User-Agent.** Cloudflare answers `Python-urllib` with error
   1010 before the request reaches the app.
4. **Negative control, self-maintaining.** Feed the same client one URI observed
   REGISTERED *in the current state file* and one certainly bogus. Never hard-code
   the positive case — the moment that site becomes the thing being fixed, the
   control fires a false alarm (this happened 2026-08-06 with `ai-career`).

   **The bogus host must be syntactically real.** Measured 2026-08-10: Google
   validates the host against its OAuth policy *before* comparing the URI against
   the client, so a host under the RFC 2606 reserved `.invalid` TLD answers
   `invalid_request`, not `redirect_uri_mismatch` — the negative control never
   reached the comparison it exists to exercise, and had been passing a policy
   rejection off as proof. `BOGUS_HOST` is now under `example.com`: IANA holds it
   permanently, so it is equally unacquirable, but it is a real domain.

   ```
   definitely-not-registered-xyz.invalid      -> invalid_request       (OAUTH_ERROR)
   definitely-not-registered-xyz.example.com  -> redirect_uri_mismatch (MISMATCH)
   ```

   Do not "harden" this back to a reserved TLD. The control goes silently inert.
5. **Registration and origin are orthogonal axes, not one verdict.** Google's
   approval is not the site's approval: compare the emitted `redirect_uri`'s
   normalized origin (scheme + hostname + effective port) with the service's
   declared `canonical_origin`. A URI left over from a previous host stays
   registered forever, so Google returns consent, issues a `code`, and strands the
   user on a dead deployment. `registration` grades
   `REGISTERED|MISMATCH|OAUTH_ERROR|UNREACHABLE|…` and `origin` grades
   `MATCH|STALE|INSECURE_SCHEME|CREDENTIALS|MALFORMED` **independently** — a
   MISMATCH row still reports its origin evidence rather than suppressing it,
   which is what makes the handoff able to say "register the canonical URI, not
   the one being emitted". The row-level `verdict` is `OK` / `BLOCKED` /
   `NOT_APPLICABLE`. (Measured 2026-08-09: `ai-ziyaoastro` emitted
   `ai-ziyaoastro.vercel.app`, answering 402 `DEPLOYMENT_DISABLED`; re-measured
   2026-08-10 its emit side had been flipped and the origin now reads `MATCH`.)

## Coverage and verdicts

Coverage comes from `inventory.json` (schema 1), read by `build_specs()`. Each
service declares `expects_login`, `login_paths`, `canonical_origin`, `client_id`,
and where the coverage claim came from — so "every site was checked" is a
statement about a reviewed file, not about whatever directories happened to exist
at run time. A deployed worker absent from the inventory is reported as
`undeclared`, never silently skipped.

`expects_login: false` (currently `ai-fleet-fly-hooks`, `ai-trader` — hooks-only,
no browser login) grades `NOT_APPLICABLE` and issues **no** Google request at all.
For every other service a missing or unreachable login endpoint is **blocking**
(`LOGIN_MISSING` / `LOGIN_UNREACHABLE`): a site that declares Google SSO and
serves no login is broken, and the old `NO_LOGIN` grade let exactly that state
sit outside the failure count.

The stderr summary is `OK=<n> BLOCKED=<n> N/A=<n> undeclared=<n>`, and the probe
exits 1 while `BLOCKED>0` (`--exit-zero` suppresses that for reporting runs).
Done means `BLOCKED=0`.

**Fix order for a stale origin is load-bearing:** register the new URI in the
console FIRST, then flip the app's emit side (`GOOGLE_REDIRECT_URI` or whatever
derives it). Reversed, a site that was broken *after* login becomes a site that
cannot reach consent at all. Flipping the emit side converts the row to
`MISMATCH` — that is the correct prerequisite state, not a regression.

## Configuring sites

Everything lives in `scripts/inventory.json` — there is no longer a `SITES` map or
a `BASES` override in the code. One entry per service:

```json
{
  "worker": "ai-jci-taipei",
  "expects_login": true,
  "login_paths": ["/api/auth/signin/google", "/login"],
  "canonical_origin": "https://ai-jci-taipei.kyloren.workers.dev",
  "coverage_source": "cf-deploy-configs/ai-jci-taipei"
}
```

`login_paths` is tried in order; the first path that 3xx's to accounts.google.com
wins. `canonical_origin` is what the redirect URI **should** be built from, and is
the only thing an `ADD:` line is ever derived from. **Probe the origin that
resolves, not the one `wrangler.jsonc` intends** — a `custom_domain` route whose
DNS is not cut over yet returns `getaddrinfo failed`, which grades
`LOGIN_UNREACHABLE`, not a mismatch.

## State file

`redirect_uri_state.json` is a schema-versioned envelope
(`{"schema": 2, "generated_at": …, "summary": {…}, "rows": [...]}`), written by a
temp-file + `os.replace` so a crashed run cannot leave a half-written file that the
next consumer reads as truth. Both `control_redirect_uri.py` and
`gen_redirect_handoff.py` refuse to run against a schema they were not written for
rather than treating absent fields as "fine". Do not hand-edit it; re-run the probe.

## Offline tests

`scripts/test_redirect_uri.py` — 92 `unittest` cases, no network, patching the
single I/O chokepoint `probe_redirect_uri.http_get` (and `control_redirect_uri.
check_google` one level up). Covers every registration × origin × login verdict
combination, the handoff generator's shared-client / stale-ADD / unfixable paths,
the state envelope's atomic-write and failure-rollback behaviour, and all three
control exit codes. Run it before touching anything here; it is the only part of
this skill that costs neither tokens nor network.

## ADD-ONLY discipline

Clients are shared across sites (`ai-ut` and `ai-eatery` sit on one client;
`433379372607-*` covers five). In **Authorised redirect URIs** — not JavaScript
origins — click **+ Add URI** and add a line. **Never edit or delete an existing
line**: that takes a currently-working site offline.

## Who can edit (do not route around this)

There is **no public API**. `gcloud alpha iam oauth-clients` is Workforce Identity
Federation (`Listed 0 items` on a project with live Web clients — verified);
`gcloud iap oauth-clients` is IAP brands only. Classic Web clients are driven by
the console's private `clientauthconfig` backend. Console UI only.

The auto-mode permission classifier **hard-denies** the agent editing OAuth
redirect URIs, and **operator authorization in chat does not lift it** — the gate
is at the harness layer and does not read the conversation. Retrying via
DOM-inventory or an alternate browser tool is a **ROUTE-AROUND — do NOT**.

Unblocks, in order of preference:

1. **Operator pastes** from `redirect_uri_fix_handoff.md` (~20 s per client).
2. Operator switches Claude Code to **bypass-permissions mode**, then "go".
3. A **logged-in browser surface** must exist either way — see "Browser surface".

## Browser surface (operator policy 2026-08-06)

**Only the Claude-internal browser** (`mcp__Claude_Browser__*`) may be driven.
The operator's own Windows Chrome is **off limits**: that rules out
`mcp__claude-in-chrome__*`, the `cdp` realm (attach to `localhost:9222`), and any
Playwright run that launches the operator's default profile. A session in *their*
browser is their session; borrowing it silently is what the policy forbids.

Shared-zone credentials **may** be used to log the internal browser in — via
`sso_browser.py`, never by reading the vault:

```powershell
python %AI_WORKSPACE%\_skill\engines\sso_browser.py list       # what realms exist
python %AI_WORKSPACE%\_skill\engines\auth_check.py check console.cloud.google.com
```

Measured 2026-08-06: **there is no Google realm.** `sso_browser.py list` returns
`gov.isso.tpbusker`, `jci.line.console`, `social.instagram`, `social.twitter`;
`auth_check.py check console.cloud.google.com` → `UNKNOWN service`; `key-health.py`
inventories API keys only. So "use the shared login" does not currently resolve to
a Cloud Console session — state that as measured, do not assume one is there.

To create one the sanctioned way: add a realm to `_registry/sso-realms.json` with
`mode: persistent` (profile lands in `_secrets\browser-profiles\<realm>\`), have the
**operator** complete the Google sign-in once in that profile, then reuse it headlessly.
The agent must never type the account password — prohibited action, hand off instead.

Before declaring "blocked", confirm the surface: the internal browser landing on
`accounts.google.com/signin` means no session, not a broken URL.

## Do not block delivery on this

If a URI cannot be registered now, ship the site behind a `kind:"passcode"`
session branch signed by a `SITE_PASSCODE` env set through the deploy CLI: it
bypasses the email allowlist, gives an access-controlled live site immediately,
and leaves Google SSO intact to auto-activate the moment the URI lands.

## CITE

`50-techniques/edit-google-oauth-redirect.md` ·
`50-techniques/automate-google-oauth-redirect-uri.md` ·
`50-techniques/add-missing-gcp-redirect-uris.md` ·
`50-techniques/swap-gcp-oauth-redirect-uri-slots-to-add-new-callb.md` ·
`ztm-portal-google-sso-edge`
