# redirect_uri — console fix list

Source of truth: `redirect_uri_state.json` schema 2, probed 2026-08-10T05:46:41+0800.
8 site(s) need a console ADD across 8 OAuth client(s); 0 blocked site(s) cannot be fixed in the console.

Rule: in the **Authorised redirect URIs** section (NOT JavaScript origins), click **+ Add URI**, paste the line, Save. **Only add** — never edit or delete an existing line; several of these clients are shared with live sites.

Every `ADD` value below is derived from the service's declared `canonical_origin` in `inventory.json`, not from the URI the app currently emits. Where those differ the app's emit side must be flipped too, and the row says so.

Green — registered, origin matches, verified by this probe run: `ai-eatery`, `ai-fracdigi`

No Google SSO by design (`expects_login: false`) — nothing to register: `ai-fleet-fly-hooks`, `ai-trader`

## ai-jci-taipei

- console: https://console.cloud.google.com/auth/clients/576912529343-2gam6k5g6piafgbhcijl3v20mms0980d.apps.googleusercontent.com?project=576912529343
- ADD: `https://ai-jci-taipei.kyloren.workers.dev/api/auth/callback`
  - ai-jci-taipei: registration=MISMATCH origin=MATCH
  - reason: registration_mismatch

## ai-busker

- console: https://console.cloud.google.com/auth/clients/433379372607-df1p2qlag8er16jkv9agfffbe9qhmgsg.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-busker.kyloren.workers.dev/api/auth/callback`
  - ai-busker: registration=MISMATCH origin=MATCH
  - reason: registration_mismatch

## ai-career

- console: https://console.cloud.google.com/auth/clients/433379372607-vi35m4avraj0dlg7j0895983iatvd3ok.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-career.kyloren.workers.dev/api/auth/callback`
  - ai-career: registration=MISMATCH origin=MATCH
  - reason: registration_mismatch

## ai-darkhero

- console: https://console.cloud.google.com/auth/clients/433379372607-anspie07iub0b86lealvnsqu4qdvdc1f.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-darkhero.kyloren.workers.dev/api/auth/callback`
  - ai-darkhero: registration=MISMATCH origin=MATCH
  - reason: registration_mismatch

## ai-heartlink

- console: https://console.cloud.google.com/auth/clients/178918414586-n9us1mi03n3pavumtt1t2abham7an2fb.apps.googleusercontent.com?project=178918414586
- ADD: `https://ai-heartlink.kyloren.workers.dev/api/auth/callback`
  - ai-heartlink: registration=MISMATCH origin=MATCH
  - reason: registration_mismatch

## ai-search

- console: https://console.cloud.google.com/auth/clients/433379372607-droj6ku1416v8jsc3iri4lig0e9jhvfa.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-search.kyloren.workers.dev/api/auth/callback`
  - ai-search: registration=MISMATCH origin=MATCH
  - reason: registration_mismatch

## ai-ut

- console: https://console.cloud.google.com/auth/clients/433379372607-ra924imb7vsm9b8fng7nmnr5t8e864sb.apps.googleusercontent.com?project=433379372607
- **shared client** — 2 services depend on it (ai-eatery, ai-ut). ADD ONLY.
  - already working on this client, do NOT touch their lines: `ai-eatery`
- ADD: `https://ai-ut.kyloren.workers.dev/api/auth/callback`
  - ai-ut: registration=MISMATCH origin=MATCH
  - reason: registration_mismatch

## ai-ziyaoastro

- console: https://console.cloud.google.com/auth/clients/433379372607-rde329v31tp5mslqjbj2p6tj8231h1ki.apps.googleusercontent.com?project=433379372607
- ADD: `https://ai-ziyaoastro.kyloren.workers.dev/api/auth/google/callback`
  - ai-ziyaoastro: registration=MISMATCH origin=MATCH
  - reason: registration_mismatch

## Verify

```bash
python C:/ai_workspace/_skill/fleet-skills/ztm-oauth-redirect-fleet/scripts/probe_redirect_uri.py
```

Done when the stderr summary reads `BLOCKED=0` and the process exits 0. The probe is self-checking: `control_redirect_uri.py` proves it can still tell a registered URI from an unregistered one, and exits non-zero when it cannot.
