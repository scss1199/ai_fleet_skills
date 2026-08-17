---
name: deploy-nextjs-cloudflare
description: Deploy existing Next.js applications to Cloudflare Workers with OpenNext using a shared, AI_WORKSPACE-only, local-build-first FAMES workflow, including versioned uploads, CPU-tail gates, rollback, workers.dev naming, isolated migration, environment-secret handling, local workerd checks, and public smoke tests. Use when any agent deploys or repairs a Next.js Worker without hosted build minutes.
metadata:
  fleet:
    lane: ZTM
    secrets: vault-schema-only
    scheduler: on-demand
    token_budget: low
---

# Deploy Next.js to Cloudflare Workers

Produce a working public URL, not a placeholder page. Preserve the application's real routes and behavior while keeping the source repository safe.

## Hard gates

- Use this canonical shared skill at `%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare`. Treat copied per-agent installations as discovery mirrors, never as the editable source of truth.
- Keep source projects, isolated deployment workspaces, generated evidence, and reusable prompts under `%AI_WORKSPACE%`. Never place an active deployment workspace under a user-profile Documents, Desktop, Downloads, or OS temp directory.
- Read the repository `AGENTS.md` before acting.
- If `%AI_WORKSPACE%\_skill\engines` exists, run MTO prework and task routing, then mint a PFKT fragment whose verification command checks the final public URL.
- Never edit a dirty user worktree. Copy the deployable application or create an isolated worktree, recursively excluding every `.env*` and `.secrets` path plus `.next`, `.open-next`, `.vercel`, `.wrangler`, `.firebase`, `node_modules`, `test-results`, verification screenshots, and build caches.
- Before installing dependencies, scan the isolated tree and require zero `.env*` files and zero directories named `.secrets`. If anything was copied, remove it only from the verified isolated destination and re-scan.
- Require an explicit Cloudflare account subdomain. A public URL is `https://<worker>.<account-subdomain>.workers.dev/`.
- Require Worker names to match `[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?`; underscores are invalid.
- Never print, commit, or place secret values in arguments. Logs may contain environment key names and counts only.
- Stop before purchasing a plan, changing production DNS, or editing OAuth provider consoles unless the user explicitly authorized that action.

## Local-build-first policy

- Treat Cloudflare as the deployment target, runtime, edge asset host, DNS/custom-domain layer, and `workers.dev` provider. Build the application and OpenNext artifact on the local workstation by default.
- Do not enable Cloudflare Workers Builds, Git integration, or Deploy Hooks unless the user explicitly requests hosted CI or the local toolchain cannot produce a valid artifact. A local `wrangler deploy` uploads the locally generated artifact and does not consume Workers Builds minutes.
- Record wall-clock time for dependency installation when needed, `cf:build`, Wrangler dry-run, and upload. On `darkhero` (i9-14900K, 96 GiB RAM, Samsung 990 Pro), the measured fracdigi baseline on 2026-08-04 was 59.67 seconds for `npm run cf:build`, 3.52 seconds for `wrangler deploy --dry-run`, and 21.31 seconds for the incremental upload/deploy.
- Prefer CPU, RAM, and NVMe capacity. Next.js/SWC/esbuild/OpenNext builds do not normally use a discrete GPU; do not install GPU tooling or claim A770/A310 acceleration without project-specific evidence.
- Keep hosted build quota separate from deployment/runtime limits. Local compilation avoids Cloudflare build-minute use, but it cannot bypass the compressed Worker bundle cap, startup-time cap, runtime CPU/memory limits, static-asset limits, or request limits. Wrangler still validates these during upload or dry-run.
- If the compressed Worker exceeds the current plan limit, reduce or split the artifact: remove unused dependencies, tree-shake and minify, move static/binary/config data to Workers Static Assets/R2/KV/D1 as appropriate, or split functionality into separately verified Workers with service bindings. Never describe local compilation as a way around an upload-size limit.

## Workflow

This is an R2 external-write workflow. Execute FAMES in order `FP -> MTM -> SCF -> AEX -> SEAL`; a build-only result is not deployment evidence. Before mutation, copy `fames-ship-receipt.template.json` into the project's evidence directory and bind it to the current semantic goal hash.

### FAMES transaction states

1. **FP / PREPARE** — define outcome, public verification, authority, non-goals, old deployment/version, exact rollback, and Free-plan CPU budget. Run fresh FAMES status/package/parity checks.
2. **MTM / APPLY** — use an isolated clean worktree; build on local CPU; run local workerd and Wrangler dry-run; commit and push the verified source; then upload a Worker Version with `wrangler versions upload`, never an unversioned blind deploy.
3. **SCF / VERIFY** — first deploy old version at 100% and new version at 0%. Verify the preview URL, expected auth statuses, immutable assets, and a version-scoped tail. CPU evidence must use Wrangler's millisecond `cpuTime` value without dividing by 1000.
4. **AEX** — PASS only when comparable prior-run evidence changed the workflow. Otherwise record `NOT_APPLICABLE` with `activation_predicate=false`; iteration inside one deployment is not AEX.
5. **SEAL / COMMIT** — move the new version to 100% only after VERIFY passes, read the deployment back, re-run public and CPU checks, and validate the completed receipt with `fames_ship_gate.py` plus FAMES `validate-run`.
6. **RECOVER** — on any post-upload failure, deploy the recorded old version back to 100%, read it back, record recovery evidence, and leave the failed new version at 0%. Never call a rollback command that was not prepared before APPLY.

Run the fleet receipt gate before reporting completion:

```powershell
python "%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\fames_ship_gate.py" --input <completed-receipt.json>
python "%AI_WORKSPACE%\_skill\fleet-skills\fames\scripts\fames_fleet.py" validate-run --workspace "%AI_WORKSPACE%" --input <completed-receipt.json> --json
```

The first gate verifies deploy-specific evidence; the second verifies the canonical FAMES ledger. Both must exit 0.

1. Run the deterministic preflight:

   ```powershell
   python "%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\preflight.py" <app-root> --worker-name <worker> --account-subdomain <subdomain> --check-auth
   ```

2. Create an isolated copy, then prepare it:

   ```powershell
   python "%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\prepare_project.py" <isolated-app-root> --worker-name <worker> --apply --install
   ```

   The preparer queries the current OpenNext peer range. It may select a compatible patch release in the same Next.js minor line. Stop for major or minor upgrades.

3. Build locally in increasing-cost order:

   ```powershell
   npm run build
   npm run cf:build
   npx wrangler deploy --dry-run --outdir .wrangler-dry-run
   ```

   Record elapsed time and the gzip upload size. Workers Free requires the compressed Worker bundle to remain within the current Free limit; verify the current limit from official Cloudflare documentation. Do not confuse that bundle-size limit with Workers Builds minutes or environment-variable size.
   If OpenNext reports `Could not resolve` for a package with a `workerd` conditional export (notably `jose`), add that exact package to Next.js `serverExternalPackages` and rebuild. This lets OpenNext resolve the Worker-specific entrypoint; do not mark it external only at the final esbuild stage.

4. Handle environment values:

   - Extract key names only from source and `.env` files.
   - Provide `NEXT_PUBLIC_*` values during the OpenNext build because Next.js may inline them.
   - Upload private runtime values with Cloudflare encrypted secrets. Confirm the target account and Worker immediately before transmission.
   - Do not embed secrets in `wrangler.jsonc`, source files, shell history, or chat.
   - Update OAuth callbacks to the exact public URL only after the Worker itself passes public smoke tests.
   - Select the OAuth provider client by the deployed runtime `GOOGLE_CLIENT_ID`; do not assume a preferred client named in repository metadata is active.
   - Inspect the redirect URI emitted by the deployed login button. For Firebase same-origin auth, register the hostname in Firebase Authentication `authorizedDomains` and add `https://<host>/__/auth/handler` to the matching Google web client. If the application also runs a server OAuth route, separately add its exact emitted callback such as `https://<host>/api/auth/google/callback`.
   - Do not trust a `prompt=none` or signed-out OAuth probe as final proof: Google may reach an account chooser and still reject the URI after account selection or while configuration propagates. Verify the exact URI is visible in the provider console, then run a secure authenticated browser flow through account selection and back to the application.
   - Reaching the account chooser proves only the initial authorization request. Claim full SSO only after the browser returns to the application with a valid application session; if secure browser authentication is unavailable, report that boundary without requesting credentials in chat.
   - Firebase Admin remote Auth operations may fail inside workerd even when the same service-account key succeeds locally. If `setCustomUserClaims`, `createSessionCookie`, or `verifySessionCookie(..., true)` fails after the OAuth callback, keep RSA signing local and call the documented Identity Toolkit REST endpoints with a short-lived service-account access token. Preserve security by verifying the session signature and checking `disabled` plus `validSince`; never bypass verification merely to make login appear successful.

5. Run local workerd and verify real application routes. Prefer the process-safe wrapper so Windows child processes cannot retain `.open-next` locks:

   ```powershell
   python "%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\local_smoke.py" <isolated-app-root> --port 18790 --path / --path /api/places
   ```

   When the deployment uses a non-default Wrangler target, pass its exact config
   with `--config wrangler.workers-dev.jsonc`; the smoke test must exercise the
   same bindings and public vars that will be deployed.

   Then inspect the rendered page in the available in-app browser.

6. Authenticate interactively with Cloudflare. Never handle the user's password or OTP. Verify that the account-level workers.dev subdomain is the requested value before deployment.

7. Upload a version, stage it at 0%, then verify and commit traffic:

   ```powershell
   npx wrangler versions upload -c wrangler.jsonc --keep-vars
   npx wrangler versions deploy <old-version>@100 <new-version>@0 --name <worker> -y
   python "%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\verify_deployment.py" --url https://<worker>.<account-subdomain>.workers.dev/ --path / --path /api/places --expect /api/private=401
   npx wrangler versions deploy <new-version>@100 <old-version>@0 --name <worker> -y
   ```

   Treat a URL mismatch as failure even if deployment succeeded. Declare expected `401`/`403` statuses for protected routes; never weaken application authorization to make a smoke test pass.

   If the site had an auth gate on Vercel, a root probe expecting `200` is the WRONG check and will
   score a missing gate as healthy — measured 2026-08-08 on `ai-darkhero`, where the Vercel Edge
   Middleware gate was never ported and `GET / -> 200` read as GREEN while the portal was public.
   Verify gated sites per path with `%AI_WORKSPACE%\_skill\engines\mtm-portal-gate-parity.py`
   (every path classified gated/open, exit 0 only at full parity) and the SSO hop chain with
   `mtm-portal-sso-verify.py`. Both send a browser User-Agent; a Cloudflare-fronted host answers
   `Python-urllib` with 403.

## Dynamic skill update

For every new deployment failure:

1. Stop at the failed stage; do not skip or weaken it.
2. Classify it as account/policy, source compatibility, build, runtime, secret, OAuth, or DNS.
3. If the fix is deterministic and reusable, run `%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\record_failure.py` and patch the canonical shared skill or its scripts before retrying.
4. Run the skill validator after every material change:

   ```powershell
   python "%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\quick_validate.py"
   python "%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\selftest_fames_ship_gate.py"
   ```

   It checks the frontmatter contract AND that every `.py`/`.md` file named in a SKILL.md code
   span actually exists — this file itself was named in the completion evidence below for months
   while no copy existed anywhere outside a quarantined `skill-creator` plugin, so the evidence
   line asserted a run nobody could have performed. `scripts\selftest_quick_validate.py` mutates a
   throwaway copy once per check and must stay at 8/8, otherwise a passing validator proves nothing.
5. Retry from the failed stage and preserve before/after evidence.

Read `%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\references\known-failures.md` for observed fixes. Add only reproducible facts; never store credentials.

For fleet-wide non-fracdigi migrations, start from `%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\assets\claude-cloudflare-migration-prompt.md` and keep its exclusions and account naming rules intact.

## MTM completion evidence

- Original `npm run build` passed.
- OpenNext build passed.
- Wrangler dry-run passed and bundle size was recorded.
- Local workerd routes passed.
- Public routes returned expected statuses and Cloudflare served the response.
- A browser inspection showed the actual application UI.
- If authentication exists, a real signed-in browser returned to the application and remained signed in after reopening the root URL, and `mtm-portal-gate-parity.py` reported `PARITY_BAD=0` — a signed-in browser cannot show that the gate rejects a signed-OUT visitor.
- `quick_validate.py` exited 0 for this skill, and `selftest_quick_validate.py` reported 8/8.
- `fames_ship_gate.py` accepted the completed R2 receipt, and `selftest_fames_ship_gate.py` rejected every negative control.
- The final deployment read-back names the expected version; version-scoped tail has at least one route, zero non-ok outcomes, zero `exceededCpu`, and p99 at or below the prepared budget.
- The PFKT fragment was completed with the public verification output as evidence.

Do not report completion without the final working URL.
