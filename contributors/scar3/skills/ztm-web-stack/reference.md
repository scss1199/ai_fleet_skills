# ztm-web-stack · reference

Generated from fleet scan `2026-07-15` (`_temp/web-stack-scan-20260715.json`).
Paths are exemplars — always CONSUME live files; do not copy secrets.

## Registry / engines

| SSOT | Path |
|------|------|
| Matrix | `_registry/web-stack-matrix.json` |
| OAuth clients | `_registry/fleet-oauth-clients.json` |
| Face naming | `_registry/fleet-deploy-naming.json` |
| Entrances | `_registry/github-links.json` |
| Browser mandate | `_registry/fleet-browser-auth-mandate.json` |
| Theme JS | `_skill/static/fleet-theme-toggle.js` |
| Theme inject | `_skill/engines/fleet_theme_toggle.py` |
| Router | `_skill/engines/web-stack-route.py` |
| Auth probe | `_skill/engines/auth_check.py` |
| Key schema | `_skill/engines/key-health.py` |
| SSO verify | `_skill/engines/mtm-portal-sso-verify.py` |

## Google SSO — clone & env

**Prefer clone:** `ai_search/web` · `ai_ut/web` · `ai_busker/web`

Typical files:

- `app/route.ts` — login wall + inject theme
- `app/api/auth/login|callback|logout|me`
- `lib/auth.ts` / `lib/fleet-theme.ts`
- `scripts/vercel-env-sync.py`
- `config/gcp_oauth.json`（names + prefixes only）

Env **names** (never print values):

`GOOGLE_CLIENT_ID` `GOOGLE_CLIENT_SECRET` `AUTH_SECRET` `SSO_ALLOWED_EMAILS`

Callback patterns in wild:

- `/api/auth/callback` （search/ut/career/busker/darkhero）
- `/api/auth/google/callback` （ziyaoastro）

Canonical face: `https://{folder_with_hyphens}.vercel.app/`

## Meta OAuth

- Skill: `ztm-meta-oauth-console`
- Ledger: `ai_darkhero/.cursor/skills/ztm-web-auth-ops/oauth-verify-ledger.jsonl` / `.md`
- Accounts (roles in ledger): scss1199 / sssc1219 / raynor1219
- Exemplars: `fracdigi` meta-pool · darkhero oauth skill copies

## LINE webhook

- Skill: `zct-fleet-fly-line`
- Prefer Fly compute; Vercel rewrite thin
- Exemplars: `ai_ziyaoastro` · `ai_darkhero/compute.manifest.json` · `ai_darkhero/api/line/*`
- Env names: `LINE_BOT_CHANNEL_SECRET` `LINE_BOT_CHANNEL_ACCESS_TOKEN` `LINE_BOT_CHANNEL_ID`

## Maps / Places / food seats

- `ai_eatery` — ingest docs (`docs/AUTHORITY_INGEST.md`)
- `ai_foodie` · `ai_gourmet` — SSO + theme + vercel faces （foodie mandate）
- Env names: `GOOGLE_MAPS_API_KEY` / Places key — vault only

## LLM / AI providers（fallback chain）

Authoritative writeup: `ai_ziyaoastro/docs/LLM_PROVIDERS_SETUP.md`  
Code: `ai_ziyaoastro/backend/app/liuyao/ai.py`

| Priority (typical) | Provider | Env name |
|--------------------|----------|----------|
| 1 | Anthropic Claude | `ANTHROPIC_API_KEY` |
| 2 | OpenAI | `OPENAI_API_KEY` |
| 3 | Cerebras | `CEREBRAS_API_KEY` |
| 4 | Groq（user「gork」常指這） | `GROQ_API_KEY` |
| 5 | Cloudflare Workers AI | project-specific |
| 6 | Gemini | `GEMINI_API_KEY` / `GOOGLE_API_KEY` |
| optional | xAI Grok | `XAI_API_KEY` |

Bulk offload skill: `mtm-api-pool-offload`

Darkhero / metadata also call Groq／Gemini in insight／OCR pipelines — reuse, don’t fork client wrappers.

## Theme toggle

- SSOT JS: `_skill/static/fleet-theme-toggle.js`
- localStorage key: `portalTheme`
- Inject helper: `fleet_theme_toggle.py` / seat `lib/fleet-theme.ts`
- Exempt from forced collapse only: fracdigi · jci_taipei（faces）; theme still optional

## Seat coverage snapshot（2026-07-15）

See `web-stack-matrix.json` → `seat_coverage_2026_07_15`.  
Highlights: 21 seats hit web/auth/api patterns; Google SSO common on product faces; LINE+Fly on ziyao/darkhero; LLM strongest on ziyaoastro + darkhero insight.

## Webhook / deploy shapes

- Vercel env sync scripts under each `*/scripts/vercel-env-sync.py`
- After env change: **new** `vercel deploy --prod` then **alias** canonical host（redeploy alone may leave alias on old dpl）
- ship: `python %AI_WORKSPACE%\_skill\engines\ship-queue.py request <repo_dir>`

## Anti-patterns（scan-derived）

- Sharing one Google OAuth client across many seats long-term（career interim）
- Multiple vercel faces per seat in portal HTML
- LINE heavy work on Vercel serverless when Fly exists
- Printing env values in chat / ledger / SUBMIT
