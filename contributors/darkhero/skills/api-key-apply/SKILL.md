---
name: api-key-apply
description: Audit, acquire, validate, rotate, and recover API keys without exposing values. Use for API-key inventory, free-tier onboarding, invalid or expired credentials, quota/account/integration failures, api-matrix repair, names-only fleet publication, or the HubClock key recovery rider.
---

# API Key Apply and Recovery

Treat the local credential store as data to verify, never as proof by itself.

## Boundaries

- Keep values only in _secrets/api-matrix.json, _secrets/vault.json, or a provider CLI store.
- Never put a key in chat, argv, git, _registry, logs, or generated reports.
- Accept values only through token-onboard.py ingest or key-onboard.py --key-stdin.
- Never sign up, accept Terms, bypass captcha, or invent account consent.
- Never claim automatic key creation unless a provider-specific mint adapter, management credential,
  explicit local policy, candidate validation, atomic consumer update, and rollback are all proven.
- Synchronize names and status only. Each of darkhero, scar3, and altos keeps its own values locally.

## Audit before action

Run read-only commands first:

\`\`\`powershell
python %AI_WORKSPACE%\_skill\engines\key-health.py summary
python %AI_WORKSPACE%\_skill\engines\api-matrix-report.py --gaps
python %AI_WORKSPACE%\_skill\engines\api_registry.py sync
python %AI_WORKSPACE%\_skill\engines\key-pool-tick.py status
\`\`\`

api_registry.py sync is preview-only. key-health.py with no subcommand prints help and exits;
--help cannot probe or write.

## Classify the failure

| Signal | Correct response | Do not do |
|---|---|---|
| invalid, expired, compromised | rotate the key | keep retrying the rejected value |
| quota0 | wait for reset or switch provider/account | mint another key in the same quota pool |
| restricted | repair the account or organization | churn keys in the same restricted org |
| http400, http404 | repair endpoint, model, or payload | call it a dead key |
| untested or stale evidence | run a bounded probe | claim it is currently callable |
| tombstone / local Ollama | retain the intentional record | send it to a key console |

Stored status=ok without a recent health.evidence=inference record is last-known state, not proof
that a completion ran today. Credential-only checks prove authentication, not inference.

## Acquire safely

\`\`\`powershell
python %AI_WORKSPACE%\_skill\engines\free_api_hunter.py --gaps
python %AI_WORKSPACE%\_skill\engines\token-onboard.py request <provider>
python %AI_WORKSPACE%\_skill\engines\token-onboard.py ingest
\`\`\`

For a direct matrix key:

\`\`\`powershell
python %AI_WORKSPACE%\_skill\engines\key-onboard.py <provider> --key-stdin
\`\`\`

The operator performs provider-side signup or consent. The engine performs storage and validation.

## Provider-only production keys

Production keys classified as `KEEP_PROVIDER_ONLY` must never pass through the matrix or a dotenv
file. A provider-specific adapter may hold the newly minted value in process memory long enough to
run a live probe and feed the deployment provider's secure stdin. It must use create-before-delete,
revoke an uninstalled candidate, and persist only a names-only receipt.

For a JCI Deepgram Worker binding:

```powershell
python %AI_WORKSPACE%\_skill\fleet-skills\api-key-apply\scripts\deepgram-provider-secret.py `
  --worker ai-jci-taipei `
  --cwd %AI_WORKSPACE%\jci_taipei\jci_taipei_website
```

Add `--rotate` only after the existing names-only receipt is present. The adapter refuses to claim
success unless a newly minted `member` key passes a real `whisper-medium` ASR request and Wrangler
accepts the value on stdin. Existing Deepgram credentials without `keys:write` are a permission
block, not a reason to copy a dev key into production.

When the management adapter lacks `keys:write`, invoke `ztm-web-auth-ops` with required
capabilities `authenticated_session`, `interactive_navigation`, `dom_interaction`, one safe secret
egress capability, and `provider_state_readback`. Any measured host adapter may satisfy the request.
If none does, report `HANDOFF / NO_CAPABLE_ADAPTER` with the missing capabilities; never require a
named AI platform.

Google Cloud has an additional trap: `gcloud services api-keys create` may print the complete key
inside its operation result even when a restrictive `--format` is requested. Capture that result
inside a value-safe adapter or process pipeline; never let the create command write directly to an
agent-visible terminal. Treat any such output as compromise and rotate immediately.

## Validate and publish

Read-only probe:

\`\`\`powershell
python %AI_WORKSPACE%\_skill\engines\key-health.py probe --provider <provider>
\`\`\`

Persist a bounded result only after reviewing the target:

\`\`\`powershell
python %AI_WORKSPACE%\_skill\engines\key-health.py probe --provider <provider> --write
python %AI_WORKSPACE%\_skill\engines\api_registry.py sync --apply
\`\`\`

Only the authority seat publishes the fleet catalog:

\`\`\`powershell
python %AI_WORKSPACE%\_skill\engines\api_registry.py sync --publish
\`\`\`

--publish writes the authority seat file and catalog. Without --apply or --publish, sync writes
nothing.

## Background recovery

The single background owner is HubClock rider keypool-tick:

\`\`\`powershell
C:\Python312\pythonw.exe C:\ai_workspace\_skill\engines\key-pool-tick.py run --stale-hours 168 --max-probes 8
\`\`\`

The tick performs:

1. bounded stale-only probes;
2. failure classification;
3. automatic recovery only where retry is valid;
4. a names-only queue under _registry/api-key-recovery/<seat>.json;
5. names-only publication when public state changed.

It never ingests onboard-inbox.txt, rewrites model rosters, discovers providers, or mints keys as an
unrelated side effect. NEEDS_KEY_ROTATION and NEEDS_FIRST_KEY remain explicit operator actions until
a provider adapter and local policy are armed.

## References

- references/api-matrix-schema.md — matrix schema and evidence fields.
- references/current-inventory.md — dated snapshot; always rerun the audit commands.
