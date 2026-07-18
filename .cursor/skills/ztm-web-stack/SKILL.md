---
name: ztm-web-stack
description: >-
  Unified fleet website + OAuth/webhook + Maps + LLM/API kit. Scan-backed
  router for Google/Meta/LINE SSO, Vercel/Fly, Groq/Gemini/OpenAI. Use when
  bootstrapping any seat website or wiring external APIs/data.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: schema-only
    scheduler: session
    token_budget: low
    required: false
    concept_id: WEBSTACK
    engine: _skill/engines/web-stack-route.py
    registry: _registry/web-stack-matrix.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# ztm-web-stack — 全艦網站／OAuth／Webhook／API 統整

> **North star:** 任何 seat 架站 + 串 Google／Meta／LINE／Maps／LLM，先本 skill + TR0 router，禁止重造 auth。  
> **Scan evidence:** `_temp/web-stack-scan-20260715.json` · matrix `_registry/web-stack-matrix.json`

## When to use（強制）

- 新座 `ai_*` 要上 Vercel／Fly 對外網站
- Google SSO／Meta OAuth／LINE webhook／Maps／Places
- 串 Groq／Gemini／OpenAI／Cerebras／Anthropic／xAI(Grok)
- 升級既有 seat 的 auth／env sync／theme／deploy 流程

**Companion（勿重複發明；開任務先讀）：**

| 需求 | Skill |
|------|--------|
| 任何網頁登入／OAuth Console | `ztm-web-auth-ops` + `ztm-cursor-edge-auth` |
| Meta / Facebook OAuth | `ztm-meta-oauth-console` |
| LINE webhook → Fly | `zct-fleet-fly-line` |
| Portal Google SSO Edge | `ztm-portal-google-sso-edge` |
| Fluid layout | `fleet-fluid-ui` |
| LLM bulk offload | `mtm-api-pool-offload` |
| Promote 本 skill | `adus-auto-deploy-upgrading-skill` |

## Step 0 — TR0 route（先跑）

```powershell
python %AI_WORKSPACE%\_skill\engines\web-stack-route.py "<keywords>"
python %AI_WORKSPACE%\_skill\engines\web-stack-route.py --list
python %AI_WORKSPACE%\_skill\engines\auth_check.py check <service>
python %AI_WORKSPACE%\_skill\engines\key-health.py
```

Keywords examples: `google sso vercel` · `line webhook fly` · `meta oauth` · `groq gemini llm` · `maps foodie`

輸出：必讀 skills、clone 骨架、env key **名稱**、boot checklist。

## Decision tree（一句）

1. **只有 Google SSO 網頁** → clone `ai_search/web` or `ai_ut/web`；dedicated `ai-*-web` OAuth；face=`https://{seat}.vercel.app/`（`_`→`-`）  
2. **LINE inbound** → `zct-fleet-fly-line` + Fly；Vercel 僅薄 rewrite  
3. **Meta** → Cursor Edge + `ztm-meta-oauth-console`；verify → oauth-verify-ledger  
4. **Maps／美食** → clone patterns from `ai_eatery`／`ai_foodie`；Places key schema-only  
5. **LLM** → read `ai_ziyaoastro/docs/LLM_PROVIDERS_SETUP.md` fallback chain；keys via vault／Vercel env NEVER print values  

## New website boot（機械順序）

1. PFKT mint + `mtm-mto-first` prework  
2. Seat folder = cwd = identity；`AGENTS.md`  
3. Clone SSO skeleton（见 router `prefer`）  
4. Register `_registry/github-links.json`（**單一** vercel face）+ `fleet-oauth-clients.json`  
5. Cursor Edge：GCP Auth client `{seat}-web` + origins/redirects  
6. `scripts/vercel-env-sync.py`（GOOGLE_* AUTH_SECRET SSO_ALLOWED_EMAILS）  
7. Embed `_skill/static/fleet-theme-toggle.js`（淺色／深色）  
8. `ship-queue` / `vercel deploy --prod` + **alias** canonical host（避免掛舊 dpl）  
9. Probe：login `client_id` match dedicated · redirect_uri_mismatch=false  
10. SUBMIT `_inbox/from_projects/<seat>/boot-web-stack.md`

## Hard lines

- OAuth／SSO Console UI = **Cursor Edge ONLY**（禁止本機 Chrome/Edge）  
- **Never print** secret／cookie／API key **VALUES**（schema/counts only）  
- Dedicated Google OAuth per seat（SSOT `fleet-oauth-clients.json`）；勿長期共用 career interim  
- 一 seat 一對外 face（`github-links` + portal collapse）；fracdigi／jci 不擅自改  
- 猜店名／coords／OAuth URI = P=0  

## Rescan（升級本 skill 時）

```powershell
python %AI_WORKSPACE%\_temp\scan_web_stack.py
# refresh _registry/web-stack-matrix.json seat_coverage_* from scan output
```

## Detail

See `reference.md`（exemplar paths · LLM env names · webhook shapes）.

## CITE

`web-stack-route.py` · `web-stack-matrix.json` · `ztm-web-auth-ops` · scan `2026-07-15`
