---
name: deploy-nextjs-cloudflare
description: Deploy existing Next.js applications to Cloudflare Workers with OpenNext using a shared, AI_WORKSPACE-only, local-build-first workflow, including workers.dev naming, isolated migration, environment-secret handling, local workerd checks, public smoke tests, and MTM/PFKT evidence. Use when any model or agent moves a Next.js project from Vercel or another host to Cloudflare Workers, creates a free workers.dev deployment, avoids hosted build-minute usage, or repairs and repeats that deployment workflow.
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

5. Run local workerd and verify real application routes. Prefer the process-safe wrapper so Windows child processes cannot retain `.open-next` locks:

   ```powershell
   python "%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\local_smoke.py" <isolated-app-root> --port 18790 --path / --path /api/places
   ```

   Then inspect the rendered page in the available in-app browser.

6. Authenticate interactively with Cloudflare. Never handle the user's password or OTP. Verify that the account-level workers.dev subdomain is the requested value before deployment.

7. Deploy and verify:

   ```powershell
   npx wrangler deploy
   python "%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\verify_deployment.py" --url https://<worker>.<account-subdomain>.workers.dev/ --path / --path /api/places --expect /api/private=401
   ```

   Treat a URL mismatch as failure even if deployment succeeded. Declare expected `401`/`403` statuses for protected routes; never weaken application authorization to make a smoke test pass.

## Dynamic skill update

For every new deployment failure:

1. Stop at the failed stage; do not skip or weaken it.
2. Classify it as account/policy, source compatibility, build, runtime, secret, OAuth, or DNS.
3. If the fix is deterministic and reusable, run `%AI_WORKSPACE%\_skill\fleet-skills\deploy-nextjs-cloudflare\scripts\record_failure.py` and patch the canonical shared skill or its scripts before retrying.
4. Run the skill validator after every material change.
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
- `quick_validate.py` passed for this skill.
- The PFKT fragment was completed with the public verification output as evidence.

Do not report completion without the final working URL.
