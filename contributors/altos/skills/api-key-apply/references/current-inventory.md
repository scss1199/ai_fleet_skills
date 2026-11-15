# Current API inventory

Snapshot: 2026-08-18, seat ai_darkhero. Rerun the commands below; do not treat this file as live
state.

```powershell
python %AI_WORKSPACE%\_skill\engines\api-matrix-report.py
python %AI_WORKSPACE%\_skill\engines\key-pool-tick.py status
```

## Independently reproduced counts

- Matrix: 14 endpoint providers, 26 key rows, 23 rows containing values.
- Joined inventory: 20 providers across matrix, vault, CLI recipes, catalog, and console map.
- Fresh inference success: Cerebras 4/4 only.
- Credential-only success: Deepgram 4/4, NVIDIA NIM 1/1, SambaNova 1/1.
- Not currently inference-verified: Deepgram is auth-only; NVIDIA inference returned HTTP 410;
  SambaNova inference returned HTTP 429.
- xAI identity endpoint identified the team but reported no credits/licenses; this is quota/account
  capacity, not a reason to mint another same-team key.

Claude's prior claim of four callable providers and ten live keys was a stored-status count. It was
not a reproducible current-inference result because the matrix had no per-key timestamp or evidence
type. The corrected validator fails closed.

## Provider verdicts

| Provider | Current evidence verdict | Recovery |
|---|---|---|
| cerebras | VERIFIED inference (4) | none |
| deepgram | AUTH-ONLY (4) | run a bounded STT probe before a callable claim |
| nvidia-nim | UNKNOWN, HTTP 410 inference; identity OK | repair current model/endpoint |
| sambanova | DEGRADED, HTTP 429; identity OK | backoff and retry |
| cursor | UNTESTED | add/repair a provider adapter before judging |
| gemini | quota0 (3) | wait/switch project; do not churn same-project keys |
| groq | restricted (5) | repair organization/account |
| huggingface | quota0 (1) | wait/switch provider |
| mistral | quota0 (1) | wait/switch provider |
| openrouter | quota0 (1) | wait/switch provider |
| xai | quota0/account capacity (1) | add credits/license or switch provider |
| cf_ai | no first key | operator creates token and provides Account ID |
| fireworks | retired tombstone | none |
| together | retired tombstone | none |
| ollama | local retired tombstone; no local key required | none |
| github | CLI store | verify with provider CLI |
| claude_code | vault missing | provider-specific OAuth/setup flow |
| cloudflare | vault missing | request token safely |
| fly | vault missing | request token safely |
| vercel | vault missing | request token safely |

## Console and federation state

Deepgram, xAI, and Cloudflare Workers AI now have explicit console mappings. Local Ollama is excluded
from the no-console gap because localhost access does not require a key. Remaining joined gap:
cf_ai has a recipe and console mapping but no locally captured value.

Names and availability can federate. Values cannot:

- darkhero, scar3, and altos each maintain a local _secrets store;
- each seat writes _registry/api-availability/<seat>.json;
- only ai_darkhero publishes _registry/api-capability-manifest.json;
- no process copies secret values between seats.

## Probe receipt

The 2026-08-18 corrected pass used:

```powershell
python key-health.py probe --provider cerebras --provider nvidia-nim --provider sambanova --provider deepgram --provider xai --max-probes 11 --write
```

The engine emitted provider/row/result/evidence only. It emitted no key or account identifier.
