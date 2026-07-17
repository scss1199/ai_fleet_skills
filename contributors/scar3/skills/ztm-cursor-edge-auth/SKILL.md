---
name: ztm-cursor-edge-auth
description: >-
  VAR-Skill: ALL OAuth/SSO/Console UI via Cursor in-IDE browser MCP only (Edge or
  Chrome tab inside Cursor). OOM-safe tabs. Never Windows Chrome/Edge or CDP.
  Species VAR. Required companion to ztm-web-auth-ops.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: vault-only
    scheduler: on-demand
    token_budget: low
    required: true
    concept_id: VAR_AUTH
    species: VAR
    parent: ztm-web-auth-ops
    registry: _registry/fleet-browser-auth-mandate.json
---

# VAR — Cursor 內建瀏覽器認證（全艦 OAuth 唯一表面）

> **Species:** `VAR` · 母 skill: `ztm-web-auth-ops` · SSOT: `fleet-browser-auth-mandate.json` · `auth-variants.json`  
> **2026-07-10 鐵律：** 所有 agent 的 OAuth / SSO / Console 權限 UI **只能**在 **Cursor IDE 內**的瀏覽器分頁完成。

## 什麼是「Cursor 內建瀏覽器」

| 是 | 不是 |
|----|------|
| Cursor **browser MCP**（`cursor-ide-browser`）開在 IDE 內的分頁 | Windows 工作列 Chrome / Edge |
| IDE 內 **Edge** 分頁（預設） | CDP `:9222` attach |
| IDE 內 **Chrome** 分頁（Edge 不可用時） | Playwright / Puppeteer |
| `browser_navigate` / `browser_snapshot` / `browser_click` | `launch_scss1199_cdp*` |

## When to use（強制）

- Google / Meta / LINE / Vercel / GCP OAuth 同意畫面
- GCP Console 改 redirect URI、OAuth client
- 任何需「點登入、選帳號、同意 scope」的 UI
- **開瀏覽器前** 先 `GetMcpTools` → `cursor-ide-browser`；缺則 `mcp_auth`

## OOM 硬規則

| 規則 | 動作 |
|------|------|
| 用完關 tab | `browser_tabs` close 非當前 |
| 單 wave | 同時 ≤1 `browser_auth` 登入流 |
| Meta/FB | 優先 **Edge** 分頁（Cursor 內） |
| 禁止外開 | Windows Chrome/Edge、CDP — **永不**用於 OAuth |

## Workflow

### 1 CLI 優先（0 browser token）

```powershell
python %AI_WORKSPACE%\_skill\engines\auth_check.py check <service>
python %AI_WORKSPACE%\_skill\engines\mtm-portal-sso-verify.py --brief
vercel whoami
gh auth status
```

### 2 需要 UI → Cursor browser MCP

1. `browser_tabs` list → 關無用 tab
2. `browser_navigate` → 目標 URL
3. `browser_lock` → `browser_snapshot` → 點擊/填表（禁密碼）
4. `browser_unlock`
5. 記 **SUMMARY** → `oauth-verify-ledger.md`
6. 關多餘 tab

### 3 MCP 不可用時

1. `CallMcpTool mcp_auth` → `cursor-ide-browser`
2. 仍缺 → `move_agent_to_root` 至有 browser MCP 的 seat（OAuth 目標 URL 不變）
3. **禁止**降級到 Windows Chrome / CDP

### 4 新 surface → variant 表

```json
{"id": "new-surface", "provider": "...", "surface": "cursor-edge", "forbidden_surfaces": ["windows-chrome", "cdp-9222"]}
```

編輯 `_registry/auth-variants.json` — 不複製整份 skill。

## Cross-links

| Skill | Role |
|-------|------|
| `ztm-web-auth-ops` | 母決策樹 + 場景速查 |
| `ztm-meta-oauth-console` | Meta pool |
| `ztm-portal-google-sso-edge` | ai-darkhero Google SSO |

## CITE

`_registry/fleet-browser-auth-mandate.json` · `_registry/auth-variants.json` · `oauth-verify-ledger.md`
