# redirect_uri_mismatch — console fix list

Source of truth: `redirect_uri_state.json` (probe run), 7 site(s) failing, 7 OAuth client(s) to edit.

Rule: in the **Authorised redirect URIs** section (NOT JavaScript origins), click **+ Add URI**, paste the line, Save. **Only add** — never edit or delete an existing line; several of these clients are shared with live sites.

Already REGISTERED — no console action (verified by the same probe run): `ai-fracdigi`, `ai-eatery`, `ai-ziyaoastro`

## ai-jci-taipei

- console: https://console.cloud.google.com/auth/clients/576912529343-2gam6k5g6piafgbhcijl3v20mms0980d.apps.googleusercontent.com?project=576912529343
- ADD: `https://ai-jci-taipei.kyloren.workers.dev/api/auth/callback`

## ai-busker

- console: https://console.cloud.google.com/auth/clients/433379372607-df1p2qlag8er16jkv9agfffbe9qhmgsg.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-busker.kyloren.workers.dev/api/auth/callback`

## ai-career

- console: https://console.cloud.google.com/auth/clients/433379372607-vi35m4avraj0dlg7j0895983iatvd3ok.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-career.kyloren.workers.dev/api/auth/callback`

## ai-darkhero

- console: https://console.cloud.google.com/auth/clients/433379372607-anspie07iub0b86lealvnsqu4qdvdc1f.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-darkhero.kyloren.workers.dev/api/auth/callback`

## ai-heartlink

- console: https://console.cloud.google.com/auth/clients/178918414586-n9us1mi03n3pavumtt1t2abham7an2fb.apps.googleusercontent.com?project=178918414586
- ADD: `https://ai-heartlink.kyloren.workers.dev/api/auth/callback`

## ai-search

- console: https://console.cloud.google.com/auth/clients/433379372607-droj6ku1416v8jsc3iri4lig0e9jhvfa.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-search.kyloren.workers.dev/api/auth/callback`

## ai-ut

- console: https://console.cloud.google.com/auth/clients/433379372607-ra924imb7vsm9b8fng7nmnr5t8e864sb.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-ut.kyloren.workers.dev/api/auth/callback`

## ai-ziyaoastro (pre-add, then flip the backend env)

- console: https://console.cloud.google.com/auth/clients/433379372607-rde329v31tp5mslqjbj2p6tj8231h1ki.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-ziyaoastro.kyloren.workers.dev/api/auth/google/callback`
- after the add: set the Fly backend `GOOGLE_REDIRECT_URI` to the same value

## Verify

```bash
python C:/ai_workspace/_temp/cf-migrate/probe_redirect_uri.py
```

Done when the stderr summary reads `BAD=0`. The probe is self-checking: `control_redirect_uri.py` proves it can still tell a registered URI from an unregistered one.
