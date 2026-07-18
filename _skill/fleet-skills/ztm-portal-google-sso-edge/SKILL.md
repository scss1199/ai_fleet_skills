---
name: ztm-portal-google-sso-edge
description: >-
  Cursor Edge ONLY: Google SSO for ai-darkhero.vercel.app portal + optional GCP
  redirect URI. Pairs with mtm-portal-sso-verify.py TR0 probe. OOM-safe tabs.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: vault-only
    scheduler: on-demand
    token_budget: low
    required: false
    concept_id: VAR_AUTH
    species: VAR
    parent: ztm-cursor-edge-auth
    engine: _skill/engines/mtm-portal-sso-verify.py
    registry: _registry/portal-sso-edge-protocol.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# Portal Google SSO — Cursor Edge（ai-darkhero.vercel.app）

> **Surface:** Cursor 內建 Edge · **browser MCP only**  
> **禁止：** Windows Chrome、CDP :9222、Playwright chrome、`launch_scss1199_cdp*`  
> **Account allowlist：** `scss1199@gmail.com`

## When to use

- 驗證 / 完成 `https://ai-darkhero.vercel.app` Google 登入
- GCP OAuth client 缺 redirect URI（`redirect_uri_mismatch`）
- 被動 digest 需確認登入後可讀 JSON

## TR0 先跑（禁先開瀏覽器）

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-portal-sso-verify.py --brief
python %AI_WORKSPACE%\_skill\engines\mtm-portal-sso-verify.py --write-runbook
```

`probe.ok=true` → OAuth **起點**正常（302→Google）；**不代表** redirect URI 已白名單。  
若 Phase A 出現 `redirect_uri_mismatch` → 走 **Phase B**（實際 mismatch 只在 Google 錯誤頁可見，TR0 探針可能 false negative）。

## Browser MCP 閘（ai_darkhero 常見）

若 `GetMcpTools` 無 `cursor-ide-browser`：

1. `CallMcpTool mcp_auth` → `cursor-ide-browser`
2. 仍缺 → `move_agent_to_root` 至有 browser MCP 的 seat（如 `ai_career`），OAuth 目標仍為 ai-darkhero.vercel.app
3. 完成後 `browser_unlock` + 關多餘 tab（OOM）

## Phase A — Portal 登入（browser MCP）

1. `browser_tabs` list → 關閉無用 tab（OOM）
2. `browser_navigate` → `https://ai-darkhero.vercel.app/login.html`
3. `browser_lock`
4. `browser_snapshot` → 點 **用 Google 帳號登入**
5. Google 選帳 → **scss1199@gmail.com**（chooser / Continue）
6. `browser_snapshot` → URL 應為 `https://ai-darkhero.vercel.app/`（非 login）
7. `browser_navigate` → `https://ai-darkhero.vercel.app/fleet-skills-digest.json`
8. 確認 JSON 含 `"required"` 陣列（≥9 項）
9. `browser_tabs` close 非當前 tab
10. `browser_unlock`

## Phase B — GCP redirect（僅 mismatch 時）

1. `browser_navigate` → `config/gcp_oauth.json` 的 `console` URL（iron-wave 專案）
2. 開啟 **ai-hr-match-app** OAuth client（client_id `433379372607-vi35…`）
3. **Authorized redirect URIs** → 新增：
   `https://ai-darkhero.vercel.app/api/auth/callback`
4. Save → ledger 寫 SUMMARY（`oauth-verify-ledger.md`）
5. 重跑 Phase A

## Verify + ledger

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-portal-sso-verify.py --brief
```

Ledger 範本（禁密碼）：

```markdown
| date | step | account | result | note |
| 2026-07-09 | portal-sso-edge | scss1199 | PASS | digest required>=9 |
```

## CITE

`_registry/portal-sso-edge-protocol.json` · `ztm-cursor-edge-auth` · `mtm-portal-sso-verify.py`
