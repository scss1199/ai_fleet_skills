# API matrix schema

Observed locally on 2026-08-18: version 2, 14 endpoints, 26 key rows. The file is
_secrets/api-matrix.json and is never federated.

## Top level

```json
{
  "version": 2,
  "updated": "YYYY-MM-DD",
  "user_agent": "browser-like user agent",
  "endpoints": {},
  "keys": []
}
```

Each endpoint requires url and schema. Existing schemas include openai, openai-local,
openai_vision, gemini, deepgram, and cursor-cloud. A schema is supported only if the current
probe engine has a matching adapter; presence in JSON is not proof of support.

## Key row

```json
{
  "provider": "provider-id",
  "key": "SECRET VALUE",
  "status": "untested",
  "account": "non-secret local label",
  "model": "optional override",
  "health": {
    "checked_at": "ISO-8601 UTC",
    "result": "ok",
    "evidence": "inference"
  }
}
```

The health object is written only by an explicit key-health.py probe --write:

- evidence=inference with result=ok proves a provider returned an inference result.
- evidence=credential with result=auth-ok proves authentication only.
- result=ratelimited proves the request did not complete; retry with backoff.
- result=http*, neterr, or cf-blocked is UNKNOWN and must not destroy last-known status.

Legacy rows without health are last-known state. They cannot support a claim that a probe ran
today.

## Status and recovery

| Status/result | Meaning | Recovery |
|---|---|---|
| ok + inference/ok evidence | currently verified | none |
| ok without inference evidence | last-known only | validate |
| auth-ok | credential recognized | run a provider-appropriate inference probe |
| ratelimited | transient throttling | bounded retry |
| quota0 | account/project quota unavailable | wait, add credits, or switch provider/account |
| restricted | account/org restricted | repair account/org |
| invalid, expired, compromised | credential rejected | rotate key |
| http400/http404/http410 | endpoint/model/payload failure | repair integration |
| disabled with no value | tombstone | retain; do not reacquire |

A second key in the same account does not replenish quota or remove an organization restriction.

## Safe commands

```powershell
python %AI_WORKSPACE%\_skill\engines\key-health.py summary
python %AI_WORKSPACE%\_skill\engines\key-health.py probe --provider <provider>
python %AI_WORKSPACE%\_skill\engines\key-health.py probe --provider <provider> --write
python %AI_WORKSPACE%\_skill\engines\api_registry.py sync
python %AI_WORKSPACE%\_skill\engines\api_registry.py sync --apply
python %AI_WORKSPACE%\_skill\engines\api_registry.py sync --publish
```

No arguments and --help never probe. Probe is read-only unless --write is explicit. Bare registry
sync is preview-only.

## Provider-specific facts

- Deepgram: first key requires Console; later keys can be created through its API only when an
  existing credential has keys:write and the project id is known. This is not currently armed.
- xAI: programmatic minting requires a separate Management API key and team permissions. This is
  not currently armed.
- Cloudflare Workers AI: REST use requires an API token plus Account ID.
- Local Ollama at localhost requires no API key; absence of a key console is not a federation gap.

Official sources:

- https://developers.deepgram.com/docs/create-additional-api-keys
- https://docs.x.ai/developers/management-api-guide
- https://developers.cloudflare.com/workers-ai/get-started/rest-api/
- https://docs.ollama.com/api/authentication
