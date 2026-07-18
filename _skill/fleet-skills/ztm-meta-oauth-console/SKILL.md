---
name: ztm-meta-oauth-console
description: >-
  psync Meta OAuth end-to-end: App 3843028145947505, business-login, App Domains,
  meta-pool routes. HARD RULE: Cursor Edge only; log every pass/fail to
  oauth-verify-ledger. Authorized accounts scss1199 / sssc1219 / raynor1219.
metadata:
  fleet:
    lane: zero-token-mechanism
    project: new.messages.fracdigi.com
    meta_oauth_browser: cursor-edge
---

# ztm-meta-oauth-console — psync Meta 池 OAuth

> **Cursor in-IDE browser MCP only**（IDE 內 Edge 分頁；禁 Windows Chrome / CDP）。  
> SSOT：`fleet-browser-auth-mandate.json` · `ztm-cursor-edge-auth`  
> Log every attempt: `node scripts/oauth-verify-log.mjs ...` · human SUMMARY:  
> `%AI_WORKSPACE%/_skill/fleet-skills/ztm-web-auth-ops/oauth-verify-ledger.md`  
> （seat 本地副本可留；SSOT 以 fleet-skills 為準）

**CITE:** `meta-oauth-ssot.mjs` · `appOrigin.ts` · digest `meta-use-case-oauth-redirect-uri-location.md`

---

## SSOT

| 維度 | 值 |
|------|-----|
| **Browser** | Cursor Edge (browser MCP) |
| **psync App ID** | `3843028145947505`（UI 名可能顯示 insights — 以 ID 為準） |
| **insights App** | `33551954441086090`（OAuth **不**用這支當 client_id） |
| **Console** | `…/apps/3843028145947505/business-login/settings/` |
| **Start** | `/api/admin/meta-pool/oauth/start` |
| **Callback** | `/api/admin/meta-pool/oauth/callback` |
| **UI** | `/admin/access` → Meta 資產池 |
| **L3** | `scss1199@gmail.com` |

**App Domains（必含）：** `insights.fracdigi.com`, `new.messages.fracdigi.com`, `new-messages-fracdigi-com.vercel.app`  
**Redirect URIs：** 見 `META_REQUIRED_OAUTH_REDIRECT_URIS` / `meta-oauth-ssot.mjs`

---

## 驗證

```powershell
npm run zct:meta-oauth:wave
# 每次手動/MCP 嘗試後：
node scripts/oauth-verify-log.mjs --provider=meta --account=scss1199@gmail.com --surface=meta-pool-oauth --result=pass --browser=cursor-edge --note="..."
```

### Cursor Edge 步驟（scss1199）

1. `/signin` → Google → 選 `scss1199@gmail.com`
2. `/admin/access` → 連結 Meta
3. 預期 `?meta_pool=ok`；記 ledger `pass` / `fail` / `blocked`
4. L2 負測：`sssc1219` 點連結 Meta → 應導 signin / 非 facebook（記 ledger）

---

## 禁止

- Chrome · `fb-login/settings` · 讀 secret 值 · raynor 開 Meta Developers
