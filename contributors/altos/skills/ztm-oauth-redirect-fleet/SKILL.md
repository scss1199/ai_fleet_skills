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

## Who can edit — the agent can, via the seeded realm (do not hand this off by reflex)

There is still **no public API**. `gcloud alpha iam oauth-clients` is Workforce
Identity Federation (`Listed 0 items` on a project with live Web clients —
verified); `gcloud iap oauth-clients` is IAP brands only. Classic Web clients are
driven by the console's private `clientauthconfig` backend. Console UI only.

**What changed 2026-08-12 (operator directive: "以後自己想辦法登入進來處理").** The
UI is now driven by the agent, not the operator. `scripts/console_add_redirect.py`
is a **hub-shared entry point every seat calls directly** — no per-seat copy, no
handoff document:

```powershell
# AI_WORKSPACE is NOT set on this machine (Machine/User/Process all empty, checked
# 2026-08-12) — every `%AI_WORKSPACE%\…` line in fleet docs is aspirational. Use the
# literal hub path; the scripts fall back to it internally for the same reason.
$P = "C:\ai_workspace\_skill\fleet-skills\ztm-oauth-redirect-fleet\scripts"

python $P\console_add_redirect.py verify --from-state         # which projects am I in (read-only)
python $P\console_add_redirect.py verify --client <client_id> # one client, read-only
python $P\console_add_redirect.py add --client <id> --add <uri>
python $P\console_add_redirect.py sync --from-state           # fleet dry-run
python $P\console_add_redirect.py sync --from-state --apply   # fleet write
python $P\console_add_redirect.py sync --from-state --apply --only ai-busker
```

Router entry: `ztm-task-router.py "redirect_uri_mismatch"` → route
`oauth-redirect-uri` in `_registry/ztm-task-routes.json`. Every run writes
`scripts/console_access_report.json` (per-client access, current URIs, outcome,
screenshots). Exit 0 = all rows fine, 2 = a row failed or the UI did not match
(nothing written), 3 = realm not signed in.

**Seat copies are a discovery surface, not a second install.**
`fleet-skill-sync.py deploy --skill ztm-oauth-redirect-fleet` puts this skill into
33 seat roots (`<seat>/.claude/skills/…`) so every project can *find* it; the copies
exist to be read, and the commands above deliberately point at the hub path. Those
copies are **not** in git — every seat `.gitignore` excludes `.claude/`, so
distribution is the `fleet-skill-sync-tick.py` rider in `_registry/hosts.json`
(`@15m` per `_registry/aex-le-contract.json`), not a commit. After editing anything
here, re-run `deploy` or the seats keep serving the previous version — measured
2026-08-12: a seat copy deployed minutes before a hub edit still wrote its state
seat-locally, which is exactly the drift the hub anchoring above prevents.
`console_add_redirect.py` anchors `redirect_uri_state.json`,
`console_access_report.json` and `_console_shots/` to the hub `scripts/` directory
no matter which copy is executed — otherwise a seat copy would quietly maintain its
own state file, and "two places that can each be believed" is the single root cause
behind three of the entries in `known-failures.md`. The other scripts still resolve
next to `__file__`: **run the probe from the hub path**, and treat a
`redirect_uri_state.json` sitting under any `<seat>/.claude/skills/` as a stale
artifact of the copy, never as a measurement.

Three design decisions carry the safety, and each one is a measured failure that
would otherwise be silent:

1. **The project comes from the `client_id` numeric prefix, not from a registry.**
   That prefix *is* the GCP project number and `?project=<number>` opens.
   `_registry/fleet-oauth-clients.json` is a *plan*, not a measurement: it files
   `jci_taipei` under `iron-wave-466411-v5` (real: `jci-taipei`/576912529343) and
   its `ai_eatery` prefix does not match the live one. Trust the `client_id` the
   probe read off the live login redirect.
2. **Never a bare `/apis/credentials`.** The realm's `login_url` carries no
   project, so the console opens whatever the operator last used — measured: it
   opened `messages-fracdigi-com` while the target was `jci-taipei`. Clicking from
   there edits another project's client while the log still says the target.
3. **Fields are located by section heading, not by "the last blank input".** A
   client page has two sections — 「已授權的 JavaScript 來源」 and
   「已授權的重新導向 URI」 — **each with its own identical 「新增 URI」 button and
   identical placeholder** (measured on `ai-busker`). `btn.last` / `blanks[-1]`
   was only correct on `jci-taipei` because that client happens to have no JS
   origins. `_locate()` slices by `compareDocumentPosition` between the redirect
   heading and the trailing 「用戶端密鑰」/Additional-information heading, and the
   post-write audit asserts both `lost_existing == []` **and**
   `jso_untouched` — writing into the JavaScript-origins box would otherwise pass
   a redirect-URI check while breaking the client a different way.

Operator involvement is now **one login, once**, not one paste per client:

```powershell
python %AI_WORKSPACE%\_skill\engines\sso_browser.py check google.cloud.console   # ok:true?
python %AI_WORKSPACE%\_skill\engines\sso_browser.py seed google.cloud.console    # only if ok:false
```

`seed` opens a headful window; the operator completes Google sign-in. **The agent
must never type the account password** — still a prohibited action, and `ok:false`
is the only state that justifies asking for anything.

Fallback if the realm cannot be seeded: `redirect_uri_fix_handoff.md`, operator
pastes (~20 s per client). Keep generating it — it is the evidence trail either
way.

## Reach — which projects the agent can actually edit

Measured 2026-08-12 by `console_add_redirect.py verify --from-state`, signed in as
`scss1199@gmail.com` (`console_access_report.json` holds the rows). **Do not assume
this table; re-run `verify` — it is read-only and it is the whole point of the
subcommand.**

| GCP project | number | sites | access |
|---|---|---|---|
| `iron-wave-466411-v5` | 433379372607 | busker, career, darkhero, eatery, search, ut, ziyaoastro | OK |
| `jci-taipei` | 576912529343 | jci-taipei | OK |
| `messages-fracdigi-com` | 786327629029 | fracdigi | OK |
| *(unnamed)* | 178918414586 | heartlink | **NO_ACCESS** |

**Applied 2026-08-12 (`sync --from-state --apply`):** six clients took one ADD each —
busker, career, darkhero, search, ut, ziyaoastro — every row `lost_existing: []` and
`jso_untouched: true`. Fleet moved `OK=3 BLOCKED=7` → **`OK=9 BLOCKED=1 N/A=2`**,
control exit 0, and all six live `/api/auth/login` replays reach Google
consent/signin with no `authError`. `ai-eatery` and `ai-ut` are **different sites
sharing one client** (`433379372607-ra924imb7vsm…`): eatery's line was already on it
and stayed untouched, which is what the `lost_existing` audit exists to prove.

`ai-heartlink` is a **declared exception, not a bug in this skill**: the console
answers 「您必須取得「專案」的其他存取權：178918414586」 and `gcloud projects list`
for this account returns five projects that do not include it — the project belongs
to a different Google account. Two ways out, both operator decisions: grant
`scss1199@gmail.com` a role on 178918414586, or recreate heartlink's client inside
`iron-wave-466411-v5` and re-wire `ai_heartlink/config/gcp_oauth.json`. Until then
heartlink stays `NO_ACCESS`, and `NO_ACCESS` is graded separately from
`UI_UNRECOGNISED` on purpose: one accuses the account, the other accuses this
script's selectors.

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

Measured 2026-08-06: there was no Google realm. **Superseded 2026-08-12: there is
one.** `sso_browser.py list` now returns `google.cloud.console` (`mode=persistent`,
`browser=msedge`, `project=ai_darkhero`) alongside `gov.isso.tpbusker`,
`jci.line.console`, `social.instagram`, `social.twitter`. Once seeded,
`sso_browser.py check google.cloud.console` → `ok:true` and
`console_add_redirect.py` closes the loop without the operator.

`auth_check.py check console.cloud.google.com` still returns `UNKNOWN service` —
that is a gap in `auth_check`'s service table, **not** evidence that no session
exists. Ask `sso_browser.py check` instead; it is the one that knows.

To create the realm the sanctioned way: add it to `_registry/sso-realms.json` with
`mode: persistent` (profile lands in `_secrets\browser-profiles\<realm>\`), have the
**operator** complete the Google sign-in once in that profile, then reuse it.
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
