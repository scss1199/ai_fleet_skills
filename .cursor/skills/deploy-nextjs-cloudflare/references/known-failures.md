# Known deployment failures

Keep this file limited to reproducible, secret-free facts discovered during real deployments.

## workers.dev URL shape

- Symptom: The requested URL is `<worker>.workers.dev` or contains an underscore.
- Cause: Cloudflare uses `<worker>.<account-subdomain>.workers.dev`, and DNS labels permit letters, digits, and dashes only.
- Fix: Confirm the account subdomain and normalize the Worker name to hyphen-case before deployment.
- Verify: The public deployment URL exactly matches the expected hostname.

## 2026-08-04 — dependency-resolution

- Symptom: npm install failed with ERESOLVE for Next 16.2.7 and OpenNext 1.20.2
- Cause: OpenNext requires Next >=16.2.11 for the Next 16 line
- Fix: upgrade the isolated copy to Next 16.2.12 and rerun both builds
- Verify: `npm run build; npm run cf:build; npx wrangler deploy --dry-run`

## 2026-08-04 — windows-local-runtime

- Symptom: OpenNext rebuild failed with EPERM while removing .open-next
- Cause: Wrangler dev child workerd and esbuild processes survived parent-shell termination
- Fix: run local smoke through local_smoke.py so the exact Wrangler process tree is terminated
- Verify: `python scripts/local_smoke.py PROJECT --path /; npm run cf:build`

## 2026-08-04 — windows-wrangler-oauth

- Symptom: wrangler login with OS keyring failed because @napi-rs/keyring was missing
- Cause: noninteractive Windows login does not auto-install the optional keyring package
- Fix: install `@napi-rs/keyring@1.3.0` globally on Windows before retrying noninteractive keyring login; a project-local install is not resolved by Wrangler.
- Verify: `npx wrangler whoami`

## 2026-08-04 — public-route-verification

- Symptom: protected API returned 401 after secrets enabled and the verifier marked deployment failed
- Cause: the verifier assumed every healthy route must return 200
- Fix: declare expected status per route and preserve the application authorization policy
- Verify: `python scripts/verify_deployment.py --url URL --path / --expect /api/private=401`

## 2026-08-04 — google-oauth-cutover

- Symptom: Google returns redirect_uri_mismatch for the new workers.dev callback
- Cause: The OAuth client matching the deployed GOOGLE_CLIENT_ID did not contain the exact workers.dev origin and callback; a repository config referenced a different preferred client
- Fix: Select the provider client by the runtime GOOGLE_CLIENT_ID, then add the exact https workers.dev origin and /api/auth/callback URI
- Verify: `Open /api/auth/login and confirm Google reaches the account chooser for the exact workers.dev callback without redirect_uri_mismatch; claim full login only after a secure authenticated browser session returns to the application`

## 2026-08-04 — windows-preflight

- Symptom: preflight crashed with UnicodeDecodeError when wrangler whoami emitted UTF-8 under a CP950 Python locale
- Cause: subprocess.run text mode inherited the Windows locale decoder
- Fix: decode subprocess output explicitly as UTF-8 with replacement for non-UTF-8 bytes
- Verify: `run preflight.py --check-auth on a Traditional Chinese Windows host and confirm JSON output`

## 2026-08-04 — isolated-copy

- Symptom: a nested scripts/.secrets directory and generated Firebase artifacts were copied into the isolated deployment workspace
- Cause: the copy exclusion list covered build directories and root secrets but not recursively named .secrets or generated Firebase/test directories
- Fix: exclude every .secrets and .env* path recursively, plus .firebase, test-results, verification screenshots, and build caches; verify zero secret/env paths before install
- Verify: `scan the isolated tree and require SECRET_DIRS=0 and ENV_FILES=0 before preparing the project`

## 2026-08-04 — opennext-bundle

- Symptom: OpenNext failed to resolve jose because the copied package contained only Node CJS files while workerd selected the browser export
- Cause: Next.js bundled/traced jose under Node conditions even though jose publishes a workerd-specific conditional export
- Fix: add jose to next.config serverExternalPackages so OpenNext resolves and copies the workerd entrypoint
- Verify: `rerun npm run cf:build and require OpenNext build complete with .open-next/worker.js`

## 2026-08-04 — Firestore protobuf code generation

- Symptom: routes that import Firebase Admin / Firestore return 500 in workerd with `EvalError: Code generation from strings disallowed for this context`, even with Firestore `preferRest: true`.
- Cause: `google-gax` and `protobufjs` lazily compile reflection serializers on the first request. Cloudflare permits dynamic code generation during Worker startup, not while handling requests. OpenNext also embeds its own protobuf module inside the server-function bundle, so warming a separate copied `protobufjs` package does not affect the failing instance.
- Fix: in a post-OpenNext build patch, warm the embedded handler's Firestore, GAX, status, and `protobufjs/google/protobuf/descriptor.json` roots at module startup; cache `Root.fromJSON` by serialized JSON; make OpenNext's top-level main-handler creation lazy; then statically import that patched handler from the Worker entrypoint. Keep the patch version-controlled and fail closed when expected OpenNext bundle markers change.
- Verify: `npm run cf:build`; run `local_smoke.py` against one Firestore-backed route; require status 200; run `wrangler deploy --dry-run` and confirm gzip remains below the plan limit; deploy and require the same public route to return real Firestore data.

## 2026-08-04 — custom domain belongs to another Cloudflare account

- Symptom: custom-domain deployment returns code `10082` (cannot infer zone) and, after specifying `zone_name`, code `10083` (zone does not exist on your account).
- Cause: the authenticated Workers account does not own or have access to the DNS zone, even when the domain already uses Cloudflare nameservers.
- Fix: keep `workers_dev: true` so a partially failed trigger update cannot remove the fallback URL. Stop the cutover, authenticate an account that owns the zone or grant that account zone access, then redeploy the custom-domain route. Do not update provider webhooks to an unresolved hostname.
- Verify: `wrangler whoami` lists the account that owns the zone; the custom-domain deploy succeeds; public DNS resolves; HTTPS smoke tests pass on both the company hostname and the workers.dev fallback before provider callbacks are changed.

## 2026-08-04 — multi-channel LINE webhook uses one global secret

- Symptom: a service has multiple LINE channel access tokens and webhook endpoints, but verifies every event with one `LINE_CHANNEL_SECRET` environment variable.
- Cause: each LINE Messaging API channel owns a different channel secret. A single global HMAC secret cannot authenticate a multi-channel webhook safely, and a channel access token cannot be used to retrieve the channel secret.
- Fix: inventory live channels through their stored access tokens before cutover. Store each channel secret server-side by destination/channel ID, parse only the untrusted `destination` needed for secret lookup, then verify the raw request body with that channel's secret before processing any event. Do not redirect live endpoints until every active channel has a verified secret.
- Verify: for each active channel, send a provider verification/test event to the new endpoint; require valid signatures to return 200 and a signature generated with any other channel's secret to return 401.

## 2026-08-04 — Firebase handler registered but real Google callback still mismatches

- Symptom: `https://<worker>.<subdomain>.workers.dev/__/auth/handler` passes a signed-out OAuth probe, but clicking Google login and choosing an account still returns `redirect_uri_mismatch`.
- Cause: the deployed login button emits a separate server callback such as `https://<worker>.<subdomain>.workers.dev/api/auth/google/callback`. Registering only Firebase's `__/auth/handler` does not authorize that route. A `prompt=none` probe without an authenticated account can also produce a false positive before Google performs the account-selection validation.
- Fix: add the workers.dev hostname to Firebase Authentication `authorizedDomains`; add both the exact Firebase handler and the exact callback observed from the live login request to the Google web client; preserve all existing URIs; wait for provider propagation.
- Verify: reopen the Google client and confirm both exact values are present. In an authenticated browser, start from the deployed sign-in page, choose an account, and require the browser to return to the application without `redirect_uri_mismatch`; do not treat the account chooser alone as completion.

## 2026-08-04 — Firebase Admin Auth succeeds locally but session creation or revocation checks fail in workerd

- Symptom: Google returns to the Worker, then the application reports a stage such as `session_failed_allowlist_claims` or `session_failed_create_session_cookie`; a session may briefly redirect into the app but disappear when server identity verification runs.
- Cause: Firebase Admin's remote Auth calls use a transport path that is not reliably compatible with workerd. Local `verifyIdToken` or RSA signing can succeed while `setCustomUserClaims`, `createSessionCookie`, or `verifySessionCookie(cookie, true)` fails.
- Fix: create Firebase custom tokens with local RS256 signing and exchange them through `accounts:signInWithCustomToken`; create the session through `projects/{projectId}:createSessionCookie` using an OAuth access token minted from the same service account; verify the cookie signature with `verifySessionCookie(cookie, false)`, then reproduce the revoked/disabled check through `projects/{projectId}/accounts:lookup` and compare `auth_time` with `validSince`.
- Guardrail: do not silently fall back to accepting an unverified or potentially revoked cookie. Fail closed when the REST revocation check is unavailable, and never log the service-account key, OAuth access token, Firebase ID token, custom token, or session cookie.
- Verify: run a real Google account flow, require the application to show the expected user and role, reopen the Worker root URL, and confirm it stays inside the authenticated application rather than returning to `/signin`.

## 2026-08-04 — local workerd smoke (Git Bash)

- Symptom: local_smoke.py aborts with http.client.InvalidURL: URL can't contain control characters. '/Program Files/Git/'
- Cause: MSYS argument path conversion rewrites a bare '/' CLI argument into the Git installation path before Python sees it, so the probe path becomes a Windows directory string
- Fix: Invoke the script from PowerShell, or export MSYS_NO_PATHCONV=1 / MSYS2_ARG_CONV_EXCL='*' before calling it from Git Bash
- Verify: `python scripts/local_smoke.py http://127.0.0.1:8788 / (run from PowerShell)`

## 2026-08-04 — wrangler secret bulk

- Symptom: wrangler reports 'No content found in file, or piped input' even though the generator prints valid JSON
- Cause: the secret-payload generator shells out to helper scripts that inherit fd 1 and print progress lines, so the pipe delivered progress text mixed with JSON
- Fix: Redirect fd 1 to fd 2 at OS level (os.dup/os.dup2) around the collection phase and write the JSON to the saved stdout only at the end
- Verify: `python cf_env_jci.py --dry-run then python cf_env_jci.py | npx wrangler secret bulk --name <worker>`

## 2026-08-04 — LINE webhook endpoint re-point

- Symptom: PUT /v2/bot/channel/webhook/endpoint returns 401 for every channel; tokens are 172-char opaque strings with no decodable channelId
- Cause: long-lived channel access tokens had already expired and the vault stores only LINE_BOT_CHANNEL_SECRET, never LINE_BOT_CHANNEL_ID, so client_credentials re-issue is impossible offline
- Fix: Store LINE_BOT_CHANNEL_ID next to the secret at provisioning time; then re-mint with POST /v2/oauth/accessToken grant_type=client_credentials. Without the channel ID the only route is the OA Manager console, which needs an interactive logged-in browser
- Verify: `python line_endpoint_sync.py https://<worker>.workers.dev <code> (expect before.status 200 not 401)`

## 2026-08-04 — local-smoke (workerd)

- Symptom: CompileError: WebAssembly.compile(): Wasm code generation disallowed by embedder, thrown from .open-next/server-functions/default/handler.mjs on first request
- Cause: A dependency imports the bare specifier 'undici' (e.g. @vercel/blob 2.x does import { fetch } from 'undici'); Next resolves it to next/dist/compiled/undici, whose llhttp parser boots through a runtime WebAssembly.compile(). workerd forbids dynamic Wasm compilation, so the module throws at import time and every route 500s.
- Fix: Alias the specifier to the Workers-native global fetch. Add lib/undici-shim.ts re-exporting globalThis.fetch/Headers/Request/Response/FormData, then in next.config.ts set turbopack.resolveAlias = { undici: './lib/undici-shim.ts' } (Next 16 builds with Turbopack, so a webpack alias is ignored). Do NOT add the package to serverExternalPackages - that keeps the Wasm copy.
- Verify: `Re-run cf:build, then grep .open-next/server-functions/default/handler.mjs for 'WebAssembly.compile' (must be absent), then local_smoke.py must return ok:true. After deploy, exercise a route that actually uses the dependency (for @vercel/blob: an API route that reads a blob) and require HTTP 200.`

## 2026-08-04 — secrets (wrangler secret bulk)

- Symptom: wrangler aborts with 'No content found in file, or piped input' even though the producing command printed valid JSON
- Cause: PowerShell pipes .NET objects, not OS bytes. npx.ps1 therefore receives an empty $input and wrangler sees no stdin. Same command works in cmd/bash. This is distinct from the earlier stdout-pollution class (helper printing progress on fd 1).
- Fix: Never rely on a shell pipe. Drive wrangler from Python: build the payload in-process and call subprocess.run(['npx','wrangler','secret','bulk'], cwd=..., input=json.dumps(payload).encode('utf-8'), shell=True, capture_output=True). See _temp/cf-migrate/push_secrets.py. Route all helper diagnostics to stderr so no secret value ever reaches a console.
- Verify: `Helper prints only {count, keys}; wrangler reports 'Finished processing secrets JSON file' with the uploaded count equal to that count; npx wrangler secret list shows the key names.`

## 2026-08-04 — public verification (immediately post-deploy)

- Symptom: One route returns HTTP 404 with body 'error code: 1042' and content-type text/plain; charset=UTF-8, while every other route is healthy
- Cause: Cloudflare edge error served before the Worker runs - the new Version had not finished propagating to that colo. It is not an application 404 (the app's own 404 is text/html or the route's own 'Not Found' body).
- Fix: Do not change compatibility_flags or bindings. Wait and re-probe: any edge error page (text/plain 'error code: NNNN') is a platform-side response, so re-run the probe 30-60s later before diagnosing the app.
- Verify: `curl -i the same path again: it returned 307 to accounts.google.com with the correct https redirect_uri on the first retry, with no redeploy and no config change.`

## esbuild `[commonjs-variable-in-esm]` silently drops every export

- Symptom: `wrangler deploy --dry-run` succeeds but prints, per CommonJS file, `▲ [WARNING] The CommonJS "module" variable is treated as a global variable in an ECMAScript module ... [commonjs-variable-in-esm]` pointing at `module.exports = {...}`, citing `package.json:"type":"module"`.
- Cause: `"type": "module"` makes esbuild parse every sibling `.js` as ESM, so `module.exports = ...` becomes a write to a stray global and the exports vanish. `require()` of that file then yields `{}` at runtime. This is a correctness bug, not cosmetic - the build still exits 0.
- Fix: Do NOT add `"type": "module"` to a Worker package that carries hand-written CommonJS (ported Vercel `(req,res)` handlers, shared `lib/*.js`). Instead drop the field and rename only the Worker entry + its ESM-only helpers to `.mjs`, updating `wrangler` `main` and the relative import. esbuild then keys format off the extension: `.mjs` = ESM entry, plain `.js` = CommonJS.
- Verify: `wrangler deploy --dry-run --outdir .wrangler-dry-run` emits zero warnings and reaches the `Total Upload: ... / gzip: ...` line; then probe a route whose handler lives in one of the CommonJS files and confirm it is not a 500.

## Cloudflare 1010 blocks scripted verification (not an app fault)

- Symptom: A public probe that passed under `curl` returns HTTP 403 with the plain-text body `error code: 1010` when the same request is replayed from Python `urllib`/`requests`.
- Cause: 1010 is the Cloudflare edge browser-integrity check rejecting the client's TLS/UA signature. It fires before the Worker, so it says nothing about the deployment. Python's default `User-Agent: Python-urllib/3.x` is the trigger.
- Fix: Set an explicit non-default `User-Agent` on the scripted probe (any realistic provider/tool UA). Never conclude the Worker is broken from a 1010, and never disable a security setting to make a test pass.
- Verify: Re-issue the identical request with a `user-agent` header set - it returned 200 where the header-less call returned 403.

## `wrangler secret bulk` is an upsert, so multi-source secrets need no merge step

- Symptom: Uncertainty about whether pushing a second `.env` file wipes the secrets uploaded by the first pass.
- Cause: N/A - behaviour question, verified rather than assumed.
- Fix: Run one `secret bulk` per source file. When the same key name means different things in two sources (e.g. one LINE channel token per bot), rename on the way in - `push_secrets.py --rename OLD=NEW --only NEW` - rather than editing either source `.env`.
- Verify: `wrangler secret list` after three passes of 4 + 13 + 1 keys returned exactly 18 distinct names, so later passes add without deleting.

## `(req,res)` shim wired wrong — 500 at runtime, clean at build

**Symptom.** `wrangler deploy --dry-run` exits 0 with no warnings, but every
request to a ported Vercel handler returns 500 with
`TypeError: res.setHeader is not a function` (or `res.end is not a function`).

**Root cause.** `makeRes()` returns the *pair* `{ res, toResponse }`, not the
response object. `const res = makeRes()` therefore hands the handler a wrapper
that has neither `setHeader` nor `end`. esbuild cannot catch it: the shape is
only resolved at call time.

**Safe fix.** Always destructure:
```js
const { res, toResponse } = makeRes();
const done = handler(req, res, env);
return toResponse(done);
```

**Retry rule.** A green dry-run proves the bundle links, never that the shim is
wired correctly. Run `wrangler dev --local` and probe one route per handler
*before* `wrangler deploy` — this class of bug is invisible until first call.

## OpenNext refuses the pinned Next version (ERESOLVE at install)

**Symptom** — `npm i -D @opennextjs/cloudflare` exits before anything is built:
`peer next@">=15.5.21 <16 || >=16.2.11" from @opennextjs/cloudflare@1.20.2`
against a project pinned at `next@16.2.7`.

**Root cause** — the adapter blacklists the 16.0.0–16.2.10 window, not just old
majors. The pin is a Vercel-era artifact: Vercel builds the app with its own
Next, so the exact pin never had to be adapter-compatible.

**Safe fix** — bump the pin inside the isolated copy to the nearest release the
peer range accepts (16.2.7 → 16.2.12) and rebuild. Do NOT reach for
`--legacy-peer-deps` or `--force`: the range is a real compatibility
statement about internal Next APIs the adapter patches, so overriding it moves
the failure from install time to a silent runtime break.

**Retry rule** — read the peer range off the error, run `npm view next@<major>
version` to pick the lowest accepted release, edit package.json, reinstall.
Re-run `next build` afterwards; a passing TypeScript pass is the signal the
bump did not change app semantics.

## `wrangler kv key put --path` dies at exit when its output is piped (Windows)

**Symptom** — a scripted upload of a large value reports
`Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), file src\win\async.c,
line 76` and exit code 3221226505 (0xC0000409). Running the identical command
by hand in the terminal succeeds. `kv key list` afterwards shows the key was
never written, so the crash is not merely a noisy teardown.

**Root cause** — wrangler's stdout was not a console. A pipe (`subprocess.run(...,
capture_output=True)`) triggers it, and so does a file redirect: the same script
crashed identically when run as a detached background task logging to a file, even
after `capture_output` had been removed. Anything other than a real console handle
while wrangler streams a multi-MiB `--path` body trips a libuv handle-close race in
the Node build on Windows, and the process dies before the PUT reaches the API.

**Safe fix** — run these puts in the foreground with wrangler attached to the
terminal, looping in the shell (`for k in ...; do npx wrangler kv key put ...;
done`) rather than from a Python driver, and never from a background/detached
runner. Verified: 6 × 20 MiB puts, exit 0 each.

**Retry rule** — any wrangler subcommand that streams file bytes (`kv key put
--path`, `r2 object put`) runs in the foreground on a console. Verify with `kv key
list`, never with the exit code alone: the Python wrapper reported exit 0 for a run
in which five of six puts never happened. And never read a crash whose text looks
like a shutdown warning as "it uploaded anyway".

## Worker → Worker `fetch()` on the same zone is blocked (`error code: 1042`)

**Symptom** — a front Worker proxies to a backend Worker and every request comes
back as a Cloudflare HTML error page containing `error code: 1042`, with a 5xx
status. The backend Worker answers the identical URL correctly when called from
outside. Retrying does not help: observed persisting through 12 retries × 6 s,
which rules out post-deploy propagation.

**Root cause** — both Workers live on the same zone (here `*.kyloren.workers.dev`),
and an ordinary `fetch()` subrequest from one Worker to another on that zone is
rejected at the edge. The failure only appears once the origin *moves onto* the
same zone — the same code worked while the origin was on Fly.io, so it reads like
a regression in the front Worker when nothing in the front Worker changed.

**Safe fix** — a service binding, which routes internally by RPC and never leaves
the edge (available on the free plan). In `wrangler.jsonc`:

```jsonc
"services": [{ "binding": "BACKEND", "service": "<backend-worker-name>" }]
```

then dispatch through it, keeping plain `fetch` as the fallback for the case where
the origin is genuinely external:

```js
const dispatch = env.BACKEND ? env.BACKEND : { fetch };
const upstream = await dispatch.fetch(target.toString(), { method, headers, body });
```

`deploy` prints `env.BACKEND (<name>)  Worker` in the binding table — that line is
the confirmation the binding is live. Body bytes pass through untouched, so
signature verification (LINE, Stripe) still works.

**Retry rule** — before deploying, grep the source *and* the `vars` for the account's
own `workers.dev` subdomain. Every hit that is not a self-reference is a 1042 waiting
to happen, including ones inside `scheduled()` cron handlers, which fail silently.
Convert each to a service binding. Never read 1042 as transient.

## `const X = process.env.Y` at module top level silently ignores `vars`

**Symptom** — a `vars` entry is re-pointed in `wrangler.jsonc`, the deploy succeeds
and the dashboard shows the new value, but the Worker keeps using the old default.
No error anywhere.

**Root cause** — Workers do not reliably populate `process.env`; the values arrive on
the `env` argument of each invocation. A module-top-level read is evaluated once at
isolate load, before any invocation, so it always sees `undefined` and freezes the
`||` fallback into the module for the isolate's whole life. Carried-over Vercel/Node
handlers are full of this pattern (`const TARGET = flyWebhookUrl(...)`).

**Safe fix** — hydrate per invocation, and make every env read lazy:

```js
function hydrateEnv(env) {
  for (const [k, v] of Object.entries(env)) {
    if (typeof v === "string") process.env[k] = v;
  }
}
const TOPICS_URL = () => process.env.AEX_TOPICS_URL || "<default>";
```

Call `hydrateEnv(env)` first in *both* `fetch()` and `scheduled()`. Bindings
(services, KV, R2) cannot be hydrated this way — they are objects, not strings; pass
`env` down explicitly or stash it in a module-scoped setter called per invocation.

**Retry rule** — after any `vars` change, grep for `process.env` outside a function
body. Verify the change took effect by observing behaviour (the request actually
reaching the new origin), never by reading the config back.

## `redirect_uri_mismatch` is invisible to a scripted probe (base64 `authError`)
**Symptom** - A verifier replays a site's `accounts.google.com/o/oauth2/v2/auth?...`
URL and reports every site REGISTERED, including sites the operator can see failing
in a real browser.

**Root cause** - Google does not return a plain 400 page to a non-browser client. It
302s to `https://accounts.google.com/signin/oauth/error?authError=<urlsafe-base64
protobuf>`. The literal string `redirect_uri_mismatch` exists *only inside the decoded
payload*. Substring-matching the response body or the visible URL therefore matches
nothing and the probe falls through to its success branch - a false REGISTERED for
every input.

**Safe fix** - Suppress redirects (`HTTPRedirectHandler.redirect_request -> None`) so
the `Location` header is the evidence, then urlsafe-b64decode the `authError` query
param (re-pad to a multiple of 4) and search the decoded bytes. Also send a Chrome
User-Agent: Cloudflare answers `Python-urllib` with error 1010 before the request ever
reaches the app.

**Retry rule** - Never ship an OAuth-registration detector without a negative control.
Feed it the same real `client_id` with one URI believed registered and one certainly
bogus; if both come back the same, the detector is broken, not the sites. Run the
control again after every change to the detector.

## No scripted path exists to add a redirect URI to a classic OAuth Web client
**Symptom** - Migration is complete and every Worker serves, but all logins die at
`redirect_uri_mismatch`, and there is no CLI that can fix it.

**Root cause** - Classic OAuth 2.0 Client IDs (APIs & Services -> Credentials) are
managed by the Cloud Console private clientauthconfig backend. `gcloud iap
oauth-clients` covers IAP brands only; `gcloud alpha iam oauth-clients` is Workforce
Identity Federation and returns `Listed 0 items` for a project whose Web clients are
in active use - verified, not assumed. There is no public API.

**Safe fix** - Treat the console edit as an operator step with a machine-generated work
list: group the failing sites by `client_id` (clients are often shared between two
sites), emit one deep link per client, and state ADD-ONLY explicitly - editing or
deleting an existing line on a shared client takes a working site offline.

**Retry rule** - Check the browser surface *before* planning any console work:
`list_connected_browsers` empty and `sso_browser.py list` without a Google realm means
no logged-in session exists, and entering the account password is not an agent action.
Stop and hand off with the deep links rather than burning turns on a login wall.

## PowerShell `>` writes a UTF-8 BOM, so the next module block cannot read the state file
**Symptom** - `python probe.py > state.json` succeeds, then every downstream script dies
with `json.decoder.JSONDecodeError: Unexpected UTF-8 BOM (decode using utf-8-sig)`.

**Root cause** - PowerShell 5.1 redirection encodes as UTF-8 **with BOM**. `json.load`
rejects the BOM. The producing script looks fine, so the failure is attributed to the
consumer.

**Safe fix** - A module block writes its own state file:
`pathlib.Path(__file__).with_name("state.json").write_text(json.dumps(rows), encoding="utf-8")`.
Never hand the shell responsibility for a machine-read artifact.

**Retry rule** - Any file that another script parses must be written by Python, not by
`>` / `Out-File` / `Set-Content`. Reading with `encoding="utf-8-sig"` is a patch on the
consumer and leaves the BOM for the next reader.

## A hard-coded positive case turns a negative control into a false alarm
**Symptom** - The control prints `expect REGISTERED -> MISMATCH`, implying the detector
is broken, while the detector is in fact correct.

**Root cause** - The control pinned its "known good" pair to one specific site
(`ai-career`). That site was itself in the set being repaired, so its URI was legitimately
unregistered. The control was asserting a fact that the task had invalidated.

**Safe fix** - Derive the positive case from the *current* measurement:
`next(r for r in rows if r["google"] == "REGISTERED")`, and synthesise the negative case
from it (`url.replace("://", "://definitely-not-registered-xyz.", 1)`). The control then
follows the fleet instead of drifting from it.

**Retry rule** - Before believing a control failure, ask whether the control's fixture is
part of the change under test. A control must depend only on facts the task cannot alter.

## Probe the origin that resolves, not the one `wrangler.jsonc` intends
**Symptom** - A deployed, working site probes as `NO_OAUTH_REDIRECT(0)`; the underlying
error is `ERR URLError: getaddrinfo failed`.

**Root cause** - The probe took its base URL from the `routes[].pattern`
(`custom_domain: true`) in `wrangler.jsonc`. The Worker is deployed and the route is
declared, but DNS for that hostname is not cut over, so the name does not resolve. The
live origin was the `workers.dev` one all along.

**Safe fix** - Resolve the base URL by measurement: try `https://<worker>.<subdomain>.workers.dev`
and the declared custom domain, and probe whichever answers. Keep the override in an
explicit `BASES` map with a dated comment on why.

**Retry rule** - A `0` status with `getaddrinfo` is a **name** failure, never an OAuth
verdict. Never fold it into the MISMATCH set - it would send an operator to the console
to fix something that is not broken.

## `vercel env pull` blanks every encrypted value, so a bulk tool legitimately reports 0 secrets
**Symptom** - `secrets_bulk.py --dry-run .env.vercel.production` prints `count: 0` while
the parser demonstrably returns 38 keys. Looks like a broken parser or a UTF-16 file.

**Root cause** - `vercel env pull` writes `KEY=""` for every variable marked
*Encrypted/Sensitive*. The file is structurally complete (all names present) but
value-blank: measured `total 38, empty_after_quote_strip 29`. The generator's
`if v == "": continue` is correct behaviour, not a bug. Head bytes were `23 20 43 72`
(`# Cr`, plain ASCII), so the UTF-16 hypothesis is wrong — check bytes before chasing it.

**Safe fix** - Treat `.env.vercel.*` as an *inventory of key names only*. Take values from
the developer-machine `.env.local` (real values, often UTF-8 BOM — parse with
`utf-8-sig`) and from per-service files such as `functions/.env.<project>`. Cross-check
the resulting count against `wrangler secret list --name <old-worker>` before pushing.

**Retry rule** - Before debugging a producer that yields zero rows, print
`{total_parsed, empty_after_quote_strip}`. Measure length *after* quote-stripping — a
length check on the raw token reports `""` as 2 chars and hides the whole failure.

## A renamed Worker is a NEW Worker with zero secrets
**Symptom** - `wrangler.jsonc` `name` is changed and deployed; the site builds and serves
but every server route fails on missing credentials.

**Root cause** - Worker names are immutable. Changing `name` creates a second Worker. Its
secret store starts empty, `wrangler` has no cross-worker secret copy, and secrets are
write-only (`wrangler secret list` returns names + types, never values). The old Worker
keeps its secrets and keeps running, which masks the problem during testing.

**Safe fix** - Before deploying under the new name: `wrangler secret list --name <old>` to
get the target set, re-source the values from the original secure files, and push with
`scripts/cf_secret_push.py --worker <new> --env A --env B --only …`. `secret bulk` on a
name that does not exist yet creates the Worker shell first (non-interactive answers
*yes*) — that is expected and lets secrets land before the first deploy. Any key with no
readable on-disk source is an operator handoff, never an exfiltration from the live Worker.

**Retry rule** - Diff the new Worker's `secret list` against the old one's and require the
difference to be exactly the documented handoff set. Do not delete the old Worker —
deletion is operator-performed, and it is the only rollback.

## A dead Vercel deployment (402) silently kills the whole scheduled-data pipeline
**Symptom** - The site renders but every aggregate panel shows `—` / empty. Auth works;
nothing in the UI reports an error.

**Root cause** - Two independent breaks in series. (1) External schedulers (Firebase Cloud
Functions `onSchedule`) still POST `/api/cron/*` at the retired Vercel origin, which
answers `402 Payment required · DEPLOYMENT_DISABLED` on *every* path — so no rollup has
run since the cutover. (2) Even repointed at the Worker, `isAuthorizedCron()` fails closed
when `CRON_SECRET` is unset, and a freshly-named Worker has no secrets. Meanwhile the
read path swallows errors (`countOrNull` → `catch` → `null` → UI renders `—`), so a read
failure is visually identical to a true zero.

**Safe fix** - Repoint the scheduler's `APP_ORIGIN` to the live Worker **and** provision
`CRON_SECRET` on it, then redeploy the functions so the new default takes effect. Also
re-subscribe provider webhooks (Meta app-level) from the new origin.

**Retry rule** - "Empty data" is never one bug. Probe the scheduler's target origin
directly (a 402/404 there is decisive), then confirm the auth secret exists on the
receiving Worker, then check whether the read path converts failures into nulls. Never
report "no data" as a data problem before all three are measured.

## Same-origin Firebase Auth proxy needs a per-host `/__/auth/handler` registration
**Symptom** - Google SSO works on the old host and dies with `redirect_uri_mismatch` on
the new one immediately after a Worker rename, with no code change to auth.

**Root cause** - `next.config.ts` `rewrites()` reverse-proxies `/__/auth/:path*` to
`<project>.firebaseapp.com`, and the client sets `authDomain` to
`window.location.hostname`. The redirect_uri therefore becomes
`https://<new-host>/__/auth/handler` — a URI the OAuth web client has never seen.

**Safe fix** - ADD (never replace) `https://<new-host>/__/auth/handler` to the *login*
client's Authorised redirect URIs, and add the host to Firebase Auth `authorizedDomains`.
Keep the old host listed so the previous Worker keeps a working login during cutover.

**Retry rule** - Any change to the origin a user's tab sits on — rename, custom domain,
preview host — invalidates the auth handler registration. Register the new host before
flipping traffic, and confirm with a real signed-in browser round-trip, not a probe.

## `npm run cf:deploy` skips the mandatory post-build bundle patch
**Symptom** - A deploy that "succeeded" serves Next's generic `_error` HTML with HTTP 500
on every server route, while `npm run cf:build` locally is green.

**Root cause** - `cf:deploy` is defined as `opennextjs-cloudflare build && wrangler deploy`
(or similar) and does **not** run the project's own post-build patch step, so the deployed
bundle is the unpatched OpenNext output. Any fix implemented as a bundle patch (Firestore
protobuf warmup, gax transport swap) is silently absent from production only.

**Safe fix** - Deploy with `npm run cf:build` followed by `npx wrangler deploy`. Delete or
re-define `cf:deploy` so it cannot be the convenient path.

**Retry rule** - Grep the build log for every patch script's success line *before*
deploying. Absent line = do not deploy. A green `cf:build` in an earlier shell is not
evidence about the bundle `wrangler` is currently uploading.

## HTML `_error` body vs JSON error body tells you whether the handler ever ran
**Symptom** - A route 500s and the instinct is to blame credentials or the database.

**Root cause** - Two different failure classes produce a 500. A **text/html** Next `_error`
page means the request never reached the route's own `try/catch` — module load, bundle
patch, or handler creation failed. A **JSON** `{"ok":false,"error":…}` body means the
handler ran and the application caught something.

**Safe fix** - Read the content-type first. For HTML, investigate the bundle/startup path.
For JSON, prove the credential independently (mint a JWT locally and exchange it at
`oauth2.googleapis.com/token`) and prove the datastore independently (a second route that
touches it), before touching either.

**Retry rule** - Never change a secret in response to a 500 whose body is HTML. The secret
is not in the call path yet.

## `firebase-admin` `credential.getAccessToken()` fails in workerd
**Symptom** - Routes backed by Cloud Monitoring / any Google REST API return
`"Could not refresh access token."`; the same service-account key works locally.

**Root cause** - firebase-admin's credential refresh uses a Node transport path that is not
workerd-compatible. The key is valid; the transport is not.

**Safe fix** - Hand-roll the token: build an RS256 JWT with `node:crypto` `createSign`,
POST it to `https://oauth2.googleapis.com/token` with
`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, scope `cloud-platform`. Keep it
in one helper (here `resolveGoogleServiceAccountAccessToken()`) and route every caller
through it.

**Retry rule** - After writing the helper, grep **all** of `src/` for
`getAccessToken(`/`credential.` — the call sites are scattered across admin routes, cron
handlers and lib modules, and one missed caller leaves a whole panel empty with no error
in the UI.

## `"minify": false` pushes the OpenNext bundle past the Worker size limit
**Symptom** - `wrangler deploy` is rejected outright with
`Your Worker failed validation because it exceeded size limits.` right after minification
was disabled to make a stack trace readable.

**Root cause** - An OpenNext Next.js bundle is already near the plan's compressed-size
ceiling; unminified it exceeds it. The deploy never happens, so it looks like a regression
in whatever was changed just before.

**Safe fix** - Keep `"minify": true` permanently. Debugging does not need it off: workerd's
`node-internal:` frames are never minified, and application frames still carry file and
line.

**Retry rule** - Before blaming a code change for a rejected deploy, diff `wrangler.jsonc`.
Size-limit rejection is a config fact, not an application fault.

## google-gax picks node-fetch when `window` is undefined, so `Firestore.getAll` dies in workerd
**Symptom** - Firestore **queries** (`collection().get()`) return real data, but any route
using `getAll` / `batchGet` (document-reference fan-out) fails with
`TypeError: Cannot read properties of null (reading 'has')` thrown from workerd's
`processHeader`. The site therefore renders *some* panels and leaves most internal data
empty — which reads like a permissions or data problem, not a transport one.

**Root cause** - `google-gax/build/src/fallbackServiceStub.js` selects its fetch
implementation as `hasWindowFetch() ? window.fetch : node_fetch.default`. workerd has no
`window`, so it takes `node-fetch` → `node:http` `ClientRequest`, whose header handling
workerd rejects. Queries use a different (streaming gRPC-fallback) path and are unaffected.

**Safe fix** - Patch the *bundled* handler after the OpenNext build, rewriting the ternary's
fallback to `globalThis.fetch`. That is byte-for-byte gax's own supported browser branch:
the same `stream_1.pipeline(response.body, streamArrayParser, cb)` consumes a web
`ReadableStream` there. Match with a regex (`hasWindowFetch\)\(\)\?window\.fetch:[A-Za-z0-9_$]+\.default`)
because the minified local name is not stable, and throw if it matches nothing.
**Never** define `globalThis.window` to force the browser branch — Next/React would then
believe they are running in a browser.

**Retry rule** - A working query proves nothing about `batchGet`. Probe a `getAll` code path
explicitly before declaring Firestore healthy in workerd, and require the patch script's
own success line (`… switched to native fetch (N site(s)).`) in the build log.

## `error code: 1102` is the Worker CPU/resource limit, not an application error
**Symptom** - One route returns HTTP 503 with the plain-text body `error code: 1102` while
every sibling route on the same Worker returns 200 with real data.

**Root cause** - 1102 is the Cloudflare edge reporting that the invocation exceeded the
Worker's CPU-time/resource budget. Typically a backfill or migration loop that iterated a
whole collection in one request — fine on a Node host with a 300 s function timeout, fatal
under a per-invocation CPU cap.

**Safe fix** - Chunk the work: bound the loop by batch size and a wall-clock/CPU budget,
persist a cursor, and return `{done:false, cursor}` so the scheduler drives repeated small
invocations. Do not raise `maxDuration` — it is a Node/Vercel concept and does not govern
the workerd CPU cap.

**Retry rule** - 1102 on exactly one route while others are healthy is decisive: stop
looking for a transport, credential, or data bug. Also note the neighbouring Next trap —
App Router treats `_`-prefixed directories as private, so a temporary
`src/app/api/**/_diag/route.ts` 404s and looks like a routing failure.

## workerd's `util.debuglog` is always live, so bundled `readable-stream` logs every chunk
**Symptom** - A Firestore-heavy route returns `error code: 1102`. `wrangler tail` capture
balloons to hundreds of KB of `STREAM: readableAddChunk { document: {...} }` /
`STREAM: ondata` / `STREAM: dest.write true`, and the tail reports
`Log size limit exceeded: More than 256KB of data ... during a single request`.

**Root cause** - `readable-stream` picks its logger with
`debugUtil && debugUtil.debuglog ? debug = debugUtil.debuglog("stream") : debug = function(){}`.
On Node this returns a no-op unless `NODE_DEBUG` contains `stream`. workerd's `nodejs_compat`
`util.debuglog` is **not** gated on `NODE_DEBUG`, so it hands back a real logger and every
Firestore document chunk is `console.log`-ed. Setting/clearing `NODE_DEBUG` does nothing;
neither `wrangler.jsonc` `vars` nor `wrangler secret list` ever contained it.

**Safe fix** - In the post-build bundle patch, rewrite the whole ternary to an unconditional
no-op (`debug = function(){}`), matching with a regex over the minified local names and
throwing if it matches nothing. This restores Node's default (NODE_DEBUG-off) behaviour.

**Retry rule** - Before blaming application code for 1102, check the *size* of one tail
capture. 256 KB of `STREAM:` lines is the log-limit failure mode, not a CPU failure mode;
they need different fixes and can mask each other. Verified fix = tail capture drops to a
few KB with `"logs": []`.

## `wrangler tail` on Windows: positional name, and stdout must be a file handle
**Symptom** - `npx wrangler tail --name <worker>` fails with `Unknown argument: name`.
Piping tail's stdout in PowerShell crashes with
`Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), file src\win\async.c, line 76`
(exit 9), so no log is ever captured.

**Root cause** - The worker name is a **positional** argument, not a flag. And libuv on
Windows asserts when wrangler's tail stream is attached to a pipe that the parent closes.

**Safe fix** - Redirect to a real file and let the process own its own console:
`Start-Process cmd.exe -ArgumentList "/c npx wrangler tail <worker-name> --format json"`
`-WorkingDirectory <repo> -RedirectStandardOutput <file> -RedirectStandardError <file>`
`-PassThru -WindowStyle Hidden`, then `Stop-Process -Id $p.Id -Force` when done.
`--format json` emits concatenated pretty-printed objects, so parse with
`json.JSONDecoder().raw_decode` in a loop rather than `json.loads` on the whole file.

**Retry rule** - Always `Stop-Process` the tail before finishing a task; orphaned tails keep
a websocket open against the account.

## Workers **Free** plan: 10 ms CPU and 50 subrequests per invocation - not tunable
**Symptom** - A route intermittently returns 200 and intermittently `error code: 1102`.
`wrangler tail` shows `outcome=exceededCpu` with wildly different `cpuTime` values for the
same code path (observed: 456 ms **ok**, 744 ms **ok**, then 10 ms **exceededCpu** on the very
next request; also 1175 ms and 2010 ms exceededCpu). Adding
`"limits": { "cpu_ms": 60000 }` to `wrangler.jsonc` makes `wrangler deploy` fail with
`CPU limits are not supported for the Free plan ... [code: 100328]`.

**Root cause** - Cloudflare's documented per-invocation limits are **10 ms CPU and 50
subrequests** on Workers Free (Paid: 30 s default, up to 5 min, and 10,000 subrequests).
The docs also say each isolate "has some built-in flexibility to allow for cases where your
Worker infrequently runs over the configured limit", and that a Worker "hitting the limit
consistently" gets terminated. That flexibility is exactly what produces the misleading
mixed 200/1102 pattern, and it is why a `cpuTime` of 456 ms can succeed while 10 ms fails.
cite: https://developers.cloudflare.com/workers/platform/limits/

**Safe fix** - There is no code-only fix for a handler whose steady-state cost is orders of
magnitude over 10 ms CPU / 50 subrequests (a Firestore batch job is). Either move that
workload off the Worker (Cloud Functions / a scheduled host with no per-invocation CPU cap)
or move the account to Workers Paid. Under migration Rule 14 this is a
"needs payment" decision that belongs to the operator - escalate, do not silently degrade.

**Retry rule** - Never conclude "it works" from a single 200 on a Free-plan Worker doing
non-trivial work: the first request after an idle period rides the burst flexibility.
Probe the same route **twice back-to-back in one tail capture**; if the second is
`exceededCpu` with a tiny `cpuTime`, the limit is being enforced and the route is not viable.

## Wall-clock budgets cannot bound CPU on workerd
**Symptom** - A handler is given a 5 s wall-clock budget and still dies with
`outcome=exceededCpu`; the tail reports `cpuTime=2010 wallTime=18324`. Tightening the
wall-clock budget changes `wallTime` and leaves `cpuTime` pinned at the cap.

**Root cause** - Wall time and CPU time are different resources, and on a Firestore-heavy
handler they diverge by more than an order of magnitude (measured on one prologue:
**16035 ms wall vs 744 ms CPU**) because almost all wall time is network round-trips.
Worse, workerd freezes `Date.now()` between I/O operations, so a `Date.now()`-based budget
is structurally blind to pure-CPU work - the only thing it can bound is the number of I/O
round-trips.

**Safe fix** - Bound the work in **units** (documents, connections, batches), not in
milliseconds, and persist a cursor so a scheduler drives repeated small invocations.
Keep a wall-clock budget only as a secondary guard against slow I/O.

**Retry rule** - Localise CPU with an **in-handler stage probe that returns its timings in
the HTTP response body** (`?probe=stages[&stop=N]` behind the same auth gate), then read the
single `cpuTime` for that request from one tail capture. This is far cheaper than
`console.log` + tail parsing, and the per-stage wall times immediately show whether a stage
is I/O-bound (safe) or CPU-bound (fatal). Do not conclude a stage is the CPU hog because it
is slow - measure both numbers.

## `.env*` exists only in the source tree, never in the isolated deploy copy
**Symptom** - A verification/health tool that reads a token out of
`<isolated-copy>/functions/.env.<project>` reports `no_credential` and the auth-gated route is
never actually probed. `Test-Path` on that path returns `False` even though the deployment
itself works and the same file plainly exists somewhere on disk.

**Root cause** - Migration Rule 3 forbids `.git`, `.env*`, `.secrets`, credentials, tokens,
caches and build output inside the isolated deploy copy. The exclusion is doing its job: the
env file lives **only** in the GitHub source tree
(`<hub>\<project>\GitHub\<repo>\functions\.env.<project>`), not under `<hub>\<project>\Cloudflare\<worker>\`.
This is structural, not a path typo - it will reproduce for every migrated project.

**Safe fix** - Point every `secret_sources` / env-file reference at the **GitHub source tree**
path and say so in a `_note` beside it, so the next reader does not "correct" it back to the
deploy copy. Resolve the real path with a glob (`<hub>/<project>/**/.env.<name>`) instead of
assuming it sits next to `wrangler.jsonc`. The value is read at run time and handed to the
request in memory only - never copied into the isolated tree, never logged (Rule 9).

**Retry rule** - When a health check reports `no_credential`, do **not** treat it as a broken
route or a missing secret: first glob for the env file, because the most likely cause is that
the tool is pointed at the isolated copy, where Rule 3 guarantees it can never be.

## A fleet-wide hostname rewrite corrupts hosts that are suffixes of other hosts
**Symptom** - After a bulk `*.vercel.app` -> `*.workers.dev` substitution, a file contains
`ai-ai-ziyaoastro.kyloren.workers.dev`. Nothing errors, the build stays green, and the bad host
only surfaces as a failed request much later.

**Root cause** - `ziyaoastro.vercel.app` is a **suffix substring** of `ai-ziyaoastro.vercel.app`.
A plain `re.sub(re.escape(host), target, text)` iterated in dict order matches the short host
*inside* the long one and rewrites its tail, stranding the `ai-` prefix in front of the new
target. Sorting each file's hosts longest-first is **not sufficient**: an alias that is on `hold`,
or absent from the map entirely, never enters the per-file host set, so it can never be ordered
relative to the host that contains it.

**Safe fix** - Do both, and know which half is load-bearing:

```python
for host, info in sorted(f["hosts"].items(), key=lambda kv: -len(kv[0])):
    new = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(host), info["to"], new, flags=re.I)
```

The negative lookbehind is the essential half - it anchors the match to a DNS label boundary and
therefore protects against hosts the tool has never heard of. Longest-first ordering is only the
cheap belt to that braces.

**Retry rule** - After any bulk host rewrite, re-read the written bytes and assert **two**
properties per file: zero residual old-domain hosts, **and** zero doubled prefixes
(`grep 'ai-ai-'`). A post-apply rescan reporting `pending: 0` proves only the first - a corrupted
host no longer matches the old-domain pattern, so it counts as clean.

## Rewriting a generated artifact fixes nothing and hides the real defect
**Symptom** - A sweep reports hundreds of stale hostnames concentrated in a handful of files under
`public/` (measured 2026-08-07: 216 occurrences across 9 files - `index.html` 75, `portal.html` 75,
`portal-data.json` 61). Rewriting them turns the sweep green; the next generator run puts every
stale host straight back.

**Root cause** - Those files are build output, not source. The stale host lives in the
**generator**, or in the registry the generator reads. The sweep was measuring the symptom.

**Safe fix** - Classify any path under a generated directory into a separate `DERIVED` lane the
writer refuses to touch, and report it as *fix the GENERATOR*. Put the directory check **before**
the suffix check, so a generated `.json` or `.html` cannot fall through into the writable lane on
the strength of its extension.

**Retry rule** - Before rewriting a file, ask what writes it. If the answer is "a script in this
repo", the edit belongs in that script. Precedent in this fleet: `gen_redirect_handoff.py` once
emitted a stale `_temp/cf-migrate/` path, and patching the generated markdown would have regressed
on the very next run.

## The mapping SSOT contains every host as a literal, so an unguarded sweep rewrites itself
**Symptom** - The first `plan` run lists the mapping file itself among the files to rewrite (11
hits), and a second run would re-map already-migrated targets.

**Root cause** - A host-to-host map necessarily stores every source hostname as a literal key. Any
scanner that walks the tree by content will therefore match its own configuration, its own state
file, and any probe state file that records measured URIs.

**Safe fix** - An explicit `exclude_files` lane checked by **basename, in the first branch of the
classifier**: the map file, the sweep's own state file, and `redirect_uri_state.json`. Basename and
not full path, so a copy under a different root stays excluded too.

**Retry rule** - Any content-walking tool whose configuration is data of the same shape it searches
for must exclude its own artifacts before anything else. Read the first `plan` output for the
tool's own filenames before trusting a single number in it.

## Rewriting a hostname inside a dated DEPRECATED comment falsifies the record
**Symptom** - A sweep flags `ut.vercel.app` at `ai_ut/web/fly.toml:1` and `seth-match-app.vercel.app`
in `ai_career` workflows. Both look like ordinary stale references.

**Root cause** - Both sit inside dated deprecation notes (`# DEPRECATED 2026-07-04 - Fly retired;
LIVE = https://ut.vercel.app`). The hostname is not a live reference, it is the *content of a
historical statement*. Rewriting it produces a note asserting that a Worker existed on a date it
did not.

**Safe fix** - Route them to a `hold` map with a written reason per entry - `"no worker exists"` is
a reason, `"probably fine"` is not. The same reasoning protects `_inbox`, `technique_output`,
`_logs` and every other append-only record directory: rewriting history is falsification, not
migration.

**Retry rule** - Read the **line**, not just the match, before rewriting any hostname. A match
preceded by a comment marker, or sitting inside a `_note` / `_doc` field, is a record; the correct
action is to add a new line beside it, never to edit the old one.

## A mojibake source file must not be silently "repaired" by an unrelated rewrite
**Symptom** - `ai_ut/web/fly.toml` carries encoding damage (`??` where an em-dash belongs, stray
CJK on line 2). A read-modify-write through Python would normalise or worsen those bytes as a side
effect of changing an unrelated hostname on the same line.

**Root cause** - `path.read_text(encoding="utf-8")` + `write_text` round-trips the **whole file**,
so every byte the decoder guessed at is re-encoded from that guess. The diff then contains changes
the task never intended, in a file the task was only passing through.

**Safe fix** - Keep the file out of the writable set (here: `hold`, since its only match was inside
a deprecation comment anyway). When a damaged file genuinely must be edited, fix the encoding as a
separate single-purpose commit first, so the two changes stay reviewable apart.

**Retry rule** - Before a bulk rewrite, scan the target set for replacement characters and
CP950/UTF-8 confusion. Any hit is a file the bulk tool must skip: its diff will not be reviewable,
and the damage will be attributed to the migration.

## Substituting a host in a console attestation silently deletes a live login
**Symptom** - A host-migration sweep rewrites `config/gcp_oauth.json` and the
`redirect_uris` / `js_origins` blocks of `_registry/fleet-oauth-clients.json`. Nothing errors,
the tree is consistent, and every Google SSO login in the fleet breaks at the next sign-in with
`redirect_uri_mismatch`.

**Root cause** - Those files are not configuration that *drives* the console; they are a mirror of
what the console **contains**. The console still holds only the vercel URI, because no API exists
to add the worker one (classic Web OAuth clients have no public write API). Substituting turns the
mirror into a lie and, worse, removes the record of the one URI that currently works — so the next
person "reconciles" the console to the file and takes the login offline for real.

**Safe fix** - Give the sweep an **ADDITIVE lane**: matched, reported, never written. The tool
prints the exact `+ https://<worker-host>/<callback-path>` lines to paste into the console, and the
substitution is deferred until after the console add. Encoded as `lanes.additive_files` plus a
line-level `guards.attest_keys` / `guards.attest_value_paths` in
`_registry/vercel-to-workers-map.json`. Strip trailing punctuation off any URL extracted from prose
(`url.rstrip(".,;:)]}'\"")`) — a callback registered as `…/api/auth/callback.` never matches.

**Retry rule** - Before widening a rewrite to a new file class, ask what the file *asserts*. If it
asserts the state of an external system you cannot write to, it is ADD-only. Verify by re-running
the plan and confirming the ADDITIVE bucket's occurrence count went **up** while the writable count
went **down**; if both fell, the guard silently swallowed live config.

## A lane is a property of a path, but a shared registry file mixes three kinds of content
**Symptom** - Path-level classification (LIVE / RECORD / DERIVED) is correct on every project
directory and still wrong on `_registry/*.json`. One file holds live config
(`portal-sso-edge-protocol.json:8` `"portal": "https://ai-darkhero.vercel.app"` — must move),
console attestation (`:22` `"redirect_uri"` — ADD-only) and dated probe evidence
(`fleet-google-objects.json:10-30` `"website_probe_20260721": {"vercel_ok": [...]}` — must never
move) within a few lines of each other. Any whole-file verdict is wrong for two of the three.

**Root cause** - Lanes assume one file = one kind of content. Shared SSOT registries violate that.
Three distinct ways the guard was found under-specified, all on 2026-08-07:
1. **Key spelling** — `attest_keys` was written from Google's canonical field names, so
   `javascript_origins` was guarded but the abbreviated `js_origins` actually used at
   `fleet-oauth-clients.json:26,46,75,97,119,146,185` was not. Seven live registered origins sat in
   the writable set.
2. **Date in the filename** — `_registry/mtm-audit/portal-sso-*-2026-07-09T*.json` are dated
   snapshots, but nothing *inside* them carries a date key, so no key-based guard can see them.
3. **Platform-named keys** — `vercel_canonical` / `vercel_live` / `vercel_url` / `vercel_api_proxy`
   hold the URL being migrated. The value must move; the key name then lies about it.

**Safe fix** - Add a **line-level guard layer** below the path lane, and make `apply` rewrite
**lines, not files** (`splitlines(keepends=True)` + touch only recorded line numbers). A line's
label comes from three sources, because one is never enough: the enclosing JSON key (tracked by
indentation, not by parsing — re-emitting parsed JSON would reformat a hand-maintained file and
destroy the original line numbers the report cites), the key on the line itself, and the **value**
(`attest_value_paths`, since `auth-inventory.json:39` states its callback inside a prose field).
For (2) add the directory to `record_dirs`. For (3) rewrite the values and book the
`vercel_* -> workers_*` rename as debt **with a measured consumer list**, not as a vague TODO.

**Retry rule** - Build the guard key list from the files, never from the vendor's documentation.
Grep the actual population (`"vercel[a-z_]*"\s*:`) before exercising a lane. Verify the write with
an **independently reimplemented** guard predicate — code that imports the sweep engine proves only
self-consistency. The checkable property is "every guarded line is byte-identical to its backup";
measured after the 2026-08-07 apply: 31 files, 115 lines rewritten, 193 guarded lines, 0 guarded
lines touched, 0 `ai-ai-` doubled prefixes.

## A generator that SYNTHESISES the host from a folder name re-manufactures dead hosts
**Symptom** - The sweep reports the LIVE lane clean (0 files / 0 occurrences) while `public/*`
still carries 216 occurrences of the dead host, and two seats (`ai_busker`, `ai_eatery`)
reappear in `public/portal-data.json` after every single sweep. Grepping every registry for
those hosts finds nothing to fix. Worse, re-running the generators pushed the LIVE lane
*backwards*, from 0 pending files to 3: `_registry/insight_portal.json`, `fathom_portal.json`
and `calendar_portal.json` were rewritten back to the vercel host by their own producers.

**Root cause** - Two different shapes of the same defect, both at the generator, not the data.
1. **Synthesis.** `hub-portal-gen.py:_canonical_vercel_url()` built
   `"https://%s.vercel.app/" % agent.replace("_","-")` as the fallback whenever no registry
   supplied an explicit canonical. Nothing anywhere needs to *contain* the dead host for the
   generator to emit it, so no amount of registry rewriting can ever converge.
2. **Hard-coded literals.** `brain/insight/insight_portal_data.py:164`,
   `brain/fathom/fathom_portal_data.py:176` and `brain/calendar/calendar_portal_data.py:210`
   each carried a literal `"vercel_url": "https://ai-darkhero.vercel.app/<page>"` inside the
   built document, so each run re-polluted both `_registry/*.json` and `public/*-latest.json`.

A third artifact, `public/aex-harvest-topics.json`, is in the DERIVED lane but has **no**
generator at all (no writer found across `*.{js,mjs,json,yml,yaml,toml}`). It is a 195-line
mirror of `fleet_fly_hooks/data/darkhero/aex_harvest_topics.json` differing at exactly one
line, and the fly copy was already correct.

**Safe fix** - Point the fallback at the migration SSOT
(`_registry/vercel-to-workers-map.json`) instead of at string formatting, and keep the
vercel face for seats in the `hold` bucket on purpose: a `hold` seat has **no deployed
worker**, so synthesising a `workers.dev` URL for it would assert a deployment that was
never made. Fix the three literals at source. Sync the generator-less mirror **from its
SSOT**, never by hand-editing the value into it. Two follow-on call sites break the moment
canonicals start resolving to `workers.dev`: `_is_public_deploy_face()` did not recognise
`workers.dev`, so collapse-to-one-public-face stopped applying to every migrated seat, and
`_deploy_info()` matched neither `vercel.app` nor `fly.dev` and fell through to the `"."`
placeholder, dropping the URL from the dashboard.

**Retry rule** - Before declaring a host sweep done, **run every generator and re-scan**. A
sweep that has not survived a regeneration cycle is unverified, not clean. Read the bucket
counts out of the state JSON: the console summary printed `LIVE pending: 0` while 7 files
and 30 occurrences sat unmentioned in `derived_fix_the_generator`. Grep generator sources
for the host as a **format string**, not only as a literal (`%s.vercel.app`, `${x}.vercel.app`,
`+ ".vercel.app"`). Measured arc on 2026-08-07: DERIVED 9 files/216 occ -> 7/30 after running
two generators -> **0/0** after fixing the sources and running all five; LIVE `pending_files`
3 -> **0**; portal faces afterwards: 0 `"."` placeholders, 0 seats with more than one public
web face, 8 seats resolving to `workers.dev`, and the only 11 `vercel.app` hosts left are
exactly the `hold` bucket.

## A verifier assertion that SURVIVES an architecture migration unchanged silently inverts

**Symptom** - After the vercel -> workers.dev cutover, `verify-fly-routing.py` reported
`face_fly_fail=4`: every migrated LINE face "failed". The sites were live, the routes
answered 200, and `cf-worker-health.py` was green on the same seats. Meanwhile
`verify-line-e2e.py` reported `fail=5`, three of them `403 error code: 1010` against hosts
that a browser loads normally.

**Root cause** - Two independent defects, both in the *test*, neither in the deployment.
1. **Obsolete assertion.** Pre-migration the public face was a thin Vercel route that
   proxied to `fleet-line-hooks.fly.dev`, so the verifier asserted "the face must reach
   Fly" by looking for `via: 1.1 fly.io` / `fly-request-id` / a `"mode":"fly"` body. The
   migrated Worker does not proxy: it **ports** the handler and verifies the LINE HMAC at
   the edge. The assertion kept running, kept its old meaning, and therefore scored a
   correct migration as a total failure. Only the hostnames had been updated in the
   earlier pass; the predicate they were fed to had not.
2. **Missing User-Agent.** `http()` passed `headers or {}`, so urllib sent its default UA,
   and Cloudflare's browser-integrity check answered `403 error code: 1010`. The sibling
   verifier had always sent `User-Agent: verify-fly-routing/1` and never saw a single 1010
   - the contrast is the proof. Worse, one row asserted only the status code
   (`code in (401, 403, 302)` = "needs SSO") and so **PASSED on a 1010 body**: right
   status, wrong reason, a green row for a request that never reached the app.

**Safe fix** - Decide proxy-vs-local with an **unsigned POST**, not a GET: a proxying edge
forwards it and the origin stamps its marker on the 401, a local handler 401s clean. Then
make the assertion a disjunction over both legal shapes -
`served = fly_hit or edge_handler(...)` - because at least one seat (`ai-ziyaoastro`)
genuinely still proxies (`401` + `via: 1.1 fly.io`) and replacing the old assertion instead
of widening it would just invert which seats break. `edge_handler()` must still catch the
case worth catching, a **missing route swallowed by the SPA catch-all**: `405` proves the
router matched the path and rejected the verb (a catch-all never 405s), and a JSON
content-type carrying the handler's own `"ok":` proves the handler ran, while `text/html`
means the request fell through to `index.html`. Test that with a substring, not
`json.loads` - the fetch reads a 400-byte prefix and a longer body is legitimately
truncated. Send an explicit `User-Agent` on every probe, seeded first so caller headers
(`Authorization`, `X-Line-Signature`) still win. Finally, resolve hosts through the
migration SSOT and **SKIP** rows whose map entry is `hold` + T0: asserting a public face
for a seat the map declares not-public manufactures a permanent failure out of a
deliberate decision.

**Retry rule** - When an architecture changes, the migration is not done until every
assertion *about* that architecture has been re-read, and an assertion that still compiles
is not an assertion that still means what it says. Grep the verifiers for the old
mechanism's fingerprints (`via`, `fly-request-id`, `"mode":"fly"`) before trusting a red
result, and treat "the test is red but health is green" as a claim about the test first.
Never assert on a status code alone against a Cloudflare-fronted host - pair it with a body
predicate, or an edge rejection will pass as an application response. Measured 2026-08-07:
`verify-fly-routing.py` `face_fly_fail=4` -> `direct_fail=0 face_fail=0 face_skip=1`,
EXIT=0; `verify-line-e2e.py` `fail=5` -> `fail=3` (UA) -> `fail=2 total=9 skip=1` (T0 skip),
with the residual 2 being expired LINE channel access tokens, an operator-side console item
unrelated to the migration. The positive evidence the rewrite bought: a correctly
HMAC-signed LINE event POSTed to `ai-darkhero.kyloren.workers.dev/api/line/webhook` returns
**HTTP 200 `OK`**, byte-identical to the Fly origin, which proves the edge handler executes
signature verification and accepts real events - something the old "did it reach Fly?"
assertion could never have shown.

## A skip-list honoured by one code path and not its sibling silently reverses a quarantine

**Symptom** - `mtm-claude-quarantine.py --apply` moved 39 Claude remnants (38 of them redeployed
skill copies under `ai_master/.cursor/skills/`) into `_delete/claude-remnant-20260808/` with a SHA
manifest, and `mtm-claude-sweep.py` confirmed `remaining_hits: 0`. Immediately afterwards
`fleet-skill-sync.py verify` returned `VERIFY FAIL missing=27`, every row `ai_master
.cursor/skills/<name>`, and `verify --seats-only` returned the **identical** 27 rows.

**Root cause** - two independent defects in `_skill/engines/fleet-skill-sync.py`. (1) `SKIP_SEATS`
(line 110, containing `ai_master`) was consulted only by `_seats()`, which feeds `deploy
--seats-only`. The all-folders path `_all_deploy_roots()` builds its root set by walking the
`_projects` matrix and never looked at `SKIP_SEATS`, so it kept `ai_master`. `cmd_tick()` calls
`cmd_deploy(all_folders=True)`, and `cmd_tick` is what the `fleet-skill-pulse` HubClock rider
(`_registry/hosts.json`, cadence 15m, `fleet-skill-sync-tick.py`) executes - so the next tick
would have re-written all 38 quarantined skill files and reversed the quarantine within 15
minutes, with no error anywhere. (2) `cmd_verify(all_folders=..., only=...)` accepted
`all_folders` and never read it; the body always called `_all_deploy_roots()`. That is why
`--seats-only` changed nothing, and it is what made the first defect look like a mode artifact
instead of a real skip-list hole.

**Safe fix** - make the skip list authoritative at the enumeration, not at one caller: `continue`
on `_name in SKIP_SEATS` inside the matrix loop, plus a second gate on the first path segment of
the relative root in the final filter (a skipped seat can also surface as another entry's
component/sub-root, where the matrix key no longer identifies it). Then make `cmd_verify` honour
its own parameter: `all_folders` -> `_all_deploy_roots()`, otherwise the seat roots from
`_seats()`. Measured 2026-08-08: `missing=27` -> `VERIFY OK 34 root(s)` EXIT=0 (all-folders) and
`VERIFY OK 20 root(s)` EXIT=0 (seats-only).

**Retry rule** - after any quarantine or removal, identify every scheduled writer that could
re-create the removed paths and read the code path that scheduler actually calls, not the one
documented in the skill. A rider is a background writer with the same authority as a manual run.
When a constant like `SKIP_SEATS` exists, grep every use of it and confirm no sibling enumeration
bypasses it - a skip list applied at one of two enumerations is worse than none, because the
half that honours it makes the system look correct. And a keyword argument that is accepted but
never referenced in the body is a silent no-op: when two CLI modes return byte-identical output,
suspect a dead parameter before concluding the modes are equivalent.

## `git add -A -- <dir>` after a quarantine commits the deploy artifacts you meant to leave alone

**Symptom** - a quarantine moved 8 git-tracked worker sources out of `ai_darkhero/cf/` and the
follow-up commit was staged with `git add -A -- cf` to record the deletions. The commit landed as
`68 files changed, 4847 insertions(+), 3558 deletions(-)`: the deletions were right, but 60
previously-untracked files under `cf/.agents/` and `cf/.cursor/` were newly **added** to the repo.
Those are fleet-skill deploy artifacts whose SSOT is `_skill/fleet-skills/`, and a seat repo must
never track them. It was pushed before the stat line was read.

**Root cause** - `-A` means "stage additions, modifications and deletions", so scoping it to a
path scopes *where* it looks, not *what class of change* it stages. A quarantine leaves a
directory whose remaining contents are exactly the untracked residue you deliberately did not
move, which is the worst possible input for `-A`. The intent was deletions only.

**Safe fix** - to record moves-out, stage removals only: `git add -u -- <dir>`, or
`git rm -r --cached <specific paths>` for anything already tracked. Read `git diff --cached
--stat` *before* committing and confirm the insertion count is 0 when the commit is supposed to
be a removal. If it has already been pushed, do not rewrite history on a shared branch: move the
wrongly-added files into the same dated `_delete/` directory, extend `manifest.json` with their
SHA-256s, re-stage, and commit the correction with the reason. Confirm with `git ls-files <dir>`
returning nothing.

**Retry rule** - before quarantining a directory, check whether it is a fleet-skill deploy root,
because that decides whether the skill trees inside it will come back. `_all_deploy_roots()`
promotes a sub-directory to a root when `_has_project_marker()` matches (`package.json`, other
MARKER_FILES, or `.git`). Here `cf/package.json` was the only reason `cf` was a root; moving the
worker source removed the marker, `_all_deploy_roots()` went 34 -> 33 roots with `verify` EXIT=0,
and the skill trees became safe to quarantine too. Had the marker survived, quarantining them
would have been undone on the next `fleet-skill-pulse` tick - the same failure mode as entry #10.

## PowerShell 5.1 `Set-Content -Encoding utf8` puts a BOM in the commit subject

**Symptom** - a commit message file written with `... | Set-Content msg.txt -Encoding utf8` and
passed to `git commit -F msg.txt` produced `git log --oneline` showing an invisible zero-width
character before the first word of the subject: `<U+FEFF>docs(known-failures): ...`.

**Root cause** - "utf8" in Windows PowerShell 5.1 means UTF-8 **with** BOM, for `Set-Content`,
`Add-Content` and `Out-File` alike. Git does not strip a BOM from a `-F` message file, so the
three BOM bytes become the first characters of the subject line.

**Safe fix** - write commit messages and any file another tool will parse with a writer that does
not add a BOM: the agent's own file-write tool, or Python `io.open(p, "w", encoding="utf-8",
newline="\n")`. PowerShell 5.1 alternatives are `[IO.File]::WriteAllText($p, $s)` (UTF-8 no BOM)
or `-Encoding utf8NoBOM`, which exists only in PowerShell 6+.

**Retry rule** - do not amend and force-push a shared branch to remove a BOM from a subject
already pushed; the damage is cosmetic and a force-push on a branch other agents pull is not.
Check `git log --oneline -1` after any `-F` commit. The same BOM rule already applies to
appending to Markdown - see the `known-failures.md` append path, which is Python for exactly this
reason.

## An ack-then-persist webhook cannot be verified by status code, so sign an EMPTY batch

**Symptom** - the migrated jci_taipei face needed proof that its LINE webhook still worked after the
move off Vercel. `GET /api/line/webhook/<code>` returns `mode: "vercel"` hard-coded in the route
source, so it cannot discriminate proxy from worker, and the obvious next step - POST a signed event
- would have written into the committee's live inbox.

**Root cause** - two independent properties of the handler. (1) `processLineWebhook` maps
`persistEvent` over `body.events` with **no filtering** (`lib/line-webhook-server.ts:187-190`), so any
signed event is a real dual-write into the committee's Drive+GAS inbox: a smoke test would have
appended a fake message to real organisation data. (2) The route acks *before* it persists (`void
processLineWebhook(...)` then `return NextResponse.json({ ok: true })`,
`app/api/line/webhook/[code]/route.ts:59-63`), so a 200 asserts only "a signed event was accepted",
never "Drive+GAS were written". No response code can report the dual-write.

**Safe fix** - sign `{"events": []}`. The HMAC check must still pass, which proves the deployed face
holds the same channel secret as the committee's local `.env`, while `events.map(...)` over an empty
array persists nothing. Pair it with **one** unsigned POST as a negative control: a face that never
reached the HMAC check (static catch-all, missing binding) cannot answer `401 bad_signature`, and
without that row a blanket-401 or blanket-200 face reads as a PASS for the wrong reason. Measured:
four provisioned OAs answer `200 {"ok":true}` signed and `401 bad_signature` unsigned.

**Retry rule** - state in the verifier what the assertion does *not* cover. Here the dual-write
itself stays out of scope by construction; reading it back needs an SSO session on `/api/inbox`,
which answers `401 unauthorized` unauthenticated. Do not let a later reader mistake "signature
accepted" for "persisted". Check the transport registration too: the Fly gateway registers the jci
routes for POST only (`fleet_fly_hooks/src/gateway.js:119`), so a Fly GET row would 404 and prove
nothing - it was deliberately not added.

## A verifier row for a deliberately unprovisioned subject is a permanent FAIL, not a finding

**Symptom** - `jci calndr face GET [T2]` failed with `404 {"ok":false,"error":"unknown_code"}`. The
row was correct about the observation and wrong about its meaning: the committee OA was simply never
provisioned.

**Root cause** - the loop guarded only the signed POST behind "has a channel secret" and probed the
GET unconditionally. `calndr` has `LINE_BOT_CHANNEL_SECRET` of length 0 in its `line/.env`, and the
deployed face agrees - `lineOaCodes()` omits it, hence the 404. A deliberate state was being asserted
as a defect, so the suite could never go green and the two real failures (expired LINE tokens) would
be lost in the noise.

**Safe fix** - skip the subject **whole**, not partially: move the `if not secret: skipped.append(...)
; continue` above the GET probe, and say in the skip line *why* it is absent. This is the precedent
already in the same file for T0 seats, whose comment states the principle: probing a public face for
a seat the map declares not-public "turns a deliberate decision into a permanent FAIL".

**Retry rule** - after adding rows to a suite, read the skip list as carefully as the fail list. Any
FAIL that a registry entry or an absent credential already *predicts* belongs in `skipped` with the
prediction quoted. Measured after the fix: `fail=2 total=19 skip=2`, and both remaining failures are
operator-side expired LINE channel access tokens.

## A crashed background rider leaves a zero-byte `.git/index.lock` that blocks every later commit

**Symptom** - `git add` in the hub repo died with `fatal: Unable to create
'C:/ai_workspace/.git/index.lock': File exists.` Waiting 90 s, then another 60 s, did not clear it;
the lock's `LastWriteTime` never advanced while its age climbed past 380 s.

**Root cause** - a HubClock rider spawns `git` in this repo every couple of minutes, so
`Get-Process git` alternates between 0 and 2 hits and *looks* like an owner is holding the lock. It
is not: the file was 0 bytes and never rewritten, i.e. residue from an earlier git that was killed
mid-operation. The transient processes are later riders failing on the same stale lock.

**Safe fix** - do not delete a lock on the strength of a single sample. Poll until `Get-Process git`
returns 0 **and** the lock's age exceeds a threshold well past a normal git operation (120 s was
used), then in that same iteration **move it aside** into the dated scratchpad rather than deleting
it - `.git/index` itself is untouched, so the move is reversible. Then stage and commit immediately,
before the next rider tick.

**Retry rule** - never `Remove-Item` a lock in a repo other agents write to, and never on age alone
while a git process is live. If the lock keeps being recreated with a *fresh* timestamp, it has a
real owner: wait, do not intervene.
