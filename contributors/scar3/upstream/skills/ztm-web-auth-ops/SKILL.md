---
name: ztm-web-auth-ops
description: >-
  Mandatory before ANY web login, SSO, OAuth, LINE/Vercel/Git setup, webhook, or
  form automation across the fleet. ALL OAuth/SSO/Console UI via Cursor in-IDE
  browser MCP only (Edge/Chrome tab inside Cursor). Consolidates USE vs AVOID.
  Use when touching accounts.google.com, GCP console, LINE Developers, Vercel env,
  GitHub deploy, Firebase auth, GAS /exec, broker portals.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: schema-only
    scheduler: session
    token_budget: zero
    required: true
    engine: _skill/engines/auth_check.py
    registry: _registry/fleet-browser-auth-mandate.json
    sub_skills:
      - ztm-cursor-edge-auth
      - ztm-meta-oauth-console
      - sso-browser-session
      - ztm-webapp-verify
---

# ztm-web-auth-ops — 全艦網頁登入／設定（必讀）

> **強制**：任何 agent（含未來新 seat）在碰「網頁登入、SSO、OAuth、後台設定、webhook、表單連動、Vercel/Git 部署憑證」之前，**先讀本 skill**，再執行 Step 0。未讀就開瀏覽器 = 採坑、浪費 operator 時間（P=0）。

**CITE:** `auth_check.py` · `fleet-browser-auth-mandate.json` · `auth-variants.json` · `oauth-verify-ledger.md`

---

## 鐵律（2026-07-10 · 全艦 agent 強制）

> **OAuth / SSO / 任何需瀏覽器 UI 的權限設定** → **僅能**用 **Cursor 內建瀏覽器 MCP**（IDE 內 Edge 或 Chrome 分頁）。  
> SSOT：`_registry/fleet-browser-auth-mandate.json`

| 允許 | 禁止（P=0） |
|------|-------------|
| `cursor-ide-browser` MCP：`browser_navigate` / `browser_snapshot` / `browser_click` / `browser_lock` | Windows 本機 Chrome / Edge |
| Cursor IDE 內 **Edge** 分頁（預設） | CDP `:9222`、`launch_scss1199_cdp*` |
| Cursor IDE 內 **Chrome** 分頁（Edge 不可用時） | Playwright / Puppeteer 登入流 |
| CLI 探針：`vercel whoami`、`gh auth status`、LINE REST | 讀 `%LOCALAPPDATA%\Google\Chrome\User Data` |
| 0-token：`auth_check`、curl、`mtm-portal-sso-verify.py` | 未記 ledger 宣稱 OAuth 完成 |

**開瀏覽器前：** `GetMcpTools` → `cursor-ide-browser` 必須可用；缺則 `mcp_auth` 或換有 MCP 的 seat cwd。

**子 skill（必讀）：** `ztm-cursor-edge-auth` · OAuth 變體見 `ztm-meta-oauth-console` / `ztm-portal-google-sso-edge`

---

## Step 0 — 0-token 閘（每次必跑）

```powershell
python %AI_WORKSPACE%\_skill\engines\auth_check.py check <service-or-domain>
python %AI_WORKSPACE%\_skill\engines\zct-task-router.py "<keywords>"
```

| `auth_check` 結果 | 意義 |
|-------------------|------|
| `AUTHORIZED agent-side` | vault/CLI 已有路徑 → **禁止問 operator** |
| `HANDOFF` | agent 做完 0-token 前置 → operator **只點一次** consent |
| exit `3` + open debt | 已追蹤待辦 → **禁止重複問** |
| 無紀錄 | 走下方決策樹；仍無路徑才 `auth_check.py debt` **一次** |

**平行閘**：`browser_auth` singleton（`parallel-gates.json`）— **Cursor browser MCP** 登入同一時間只有 **1** 條 lane。

---

## 決策樹（CLI-first，禁止跳級）

```
需要網頁/登入／OAuth／權限設定？
  ├─ 1) CLI / REST / vault token 能完成？ → 做（vercel, gh, LINE API PUT, clasp, curl）
  ├─ 2) 專案已有腳本（0 UI）？ → 跑腳本（見 reference.md）
  ├─ 3) 需要瀏覽器 UI（OAuth 同意、GCP Console、Meta、LINE Developers、Vercel 後台）？
  │     → **僅 Cursor in-IDE browser MCP**（Edge 優先；見 ztm-cursor-edge-auth）
  │     → ledger：oauth-verify-ledger.md
  ├─ 4) cookie_jar / 隔離 profile 批次任務（無 OAuth UI）？ → sso_browser.py（非產品 OAuth 首選）
  └─ 5) 仍不可約 → HANDOFF（operator 一鍵）；禁 CDP / 外開 Chrome 試錯
```

**優先序**：API/CLI **>** 專案腳本 **>** **Cursor browser MCP（Edge/Chrome in IDE）** **>** `sso_browser.py`（非 UI）  
**RETIRED（禁 agent 使用）**：Windows Chrome/Edge · CDP attach · Playwright · `launch_scss1199_cdp*`

---

## Cursor 內建瀏覽器 MCP — OAuth／權限 UI（全艦唯一表面）

> 凡「選帳號、同意範圍、App Domains、Redirect URI、OAuth 白名單」→ **Cursor IDE 內** Edge/Chrome 分頁 + browser MCP。  
> **不是** Windows 工作列上的 Chrome/Edge。

| 步驟 | 動作 |
|------|------|
| 0 | `auth_check.py check <provider>` · `GetMcpTools cursor-ide-browser` |
| 1 | `browser_tabs` list → 關無用 tab（OOM） |
| 2 | `browser_navigate` → 目標 · `browser_lock` |
| 3 | `browser_snapshot` → 點登入／改 Console 白名單 |
| 4 | Operator 密碼：**agent 不輸入**；沿用已登入 session |
| 5 | ledger + `browser_unlock` + 關多餘 tab |

**可做 / 不可做**

| 可做 | 不可做 |
|------|--------|
| 點登入磁磚、跟同意畫面、改 Console 白名單 | 讀／印／寫密碼、OTP、app secret、token 值到 chat |
| 沿用 operator 已登入的 Cursor Edge session | 要求 operator 在 chat 提供密碼 |
| 記 provider + account + surface + result | headless 探針結果當唯一真相（可能 false positive） |

**密碼邊界**：Password 只在 operator 瀏覽器密碼管理器；**永不**進 agent memory / Chat / ledger / Cursor rules。

---

## 場景速查（有用 vs 沒用）

### Meta / Facebook OAuth（產品池 · Console）— fracdigi absorb

| 做法 | 判定 | 說明 |
|------|------|------|
| Cursor Edge + Meta Developers `business-login/settings` | **USE** | App Domains + Redirect URI；見 `ztm-meta-oauth-console` |
| Cursor Edge `/admin/access` → Meta 池連結 | **USE** | 同意全部 pages+businesses 後驗證 `connected=true` |
| 每次嘗試 `oauth-verify-log.mjs` + ledger.md | **USE** | 有 pass/fail evidence 才算完成 |
| Chrome 做 Meta/FB OAuth（含 Windows Chrome） | **AVOID** | reCAPTCHA 死循環；僅 Cursor in-IDE Edge |
| `fb-login/settings` 舊路徑 | **AVOID** | 用 `business-login/settings` |
| raynor 帳開 Meta Developers Console | **AVOID** | 僅產品登入；Console 用 scss1199 |
| headless probe 自稱 URI OK | **AVOID** | 以 Console UI「此 URI 有效」為準 |

**psync App 速查**（細節：`ztm-meta-oauth-console`）：client `3843028145947505`；insights App `33551954441086090` **不作** meta-pool client_id。

### Google SSO — 產品端（使用者登入 App）

| 做法 | 判定 | 說明 |
|------|------|------|
| Firebase `signInWithRedirect` + same-origin `/__/auth` rewrite | **USE** | fracdigi new.messages；禁止 popup |
| Cursor Edge 完成 Google 產品登入後沿用 session | **USE** | 與 Meta 同 session；agent 不打密碼 |
| NextAuth + 獨立 GCP OAuth client + `vercel-env-sync.py` | **USE** | ai_hr / ai_heartlink；client 不混用 |
| GAS `USER_ACCESSING` + `sessionLogin()` + curl 探針 | **USE** | ai_accountancy / jci_taipei；讀 `gas-google-sso-webapp` |
| Browser MCP 第一診斷 GAS `/exec` | **AVOID** | 先 `gas_deploy.py --probe-only` / curl |
| 改 OAuth redirect 到舊 firebaseapp.com | **AVOID** | fracdigi 紅線；只用 new 網域 |

### Google SSO — 後台（GCP / OAuth client / Console）

| 做法 | 判定 | 說明 |
|------|------|------|
| Cursor browser MCP（GCP Console、OAuth client 編輯） | **USE** | 全艦唯一 UI 表面；見 `ztm-cursor-edge-auth` |
| `mtm-portal-sso-verify.py` TR0 探針 | **USE** | 開瀏覽器前先跑 |
| `ensure_gcp_login.py` + CDP / `launch_scss1199_cdp*` | **RETIRED** | 2026-07-10 起禁 agent；改 Cursor MCP |
| `edit-google-oauth-redirect.md`（CDP） | **RETIRED** | 改 Cursor MCP 點 Console UI |
| 裸開 GCP Console SPA 等 `document_idle` | **AVOID** | 45s timeout |
| 修 operator Chrome `Web Data` autofill | **AVOID** | DPAPI/鎖定 |

### LINE（OA / webhook / Messaging API）

| 做法 | 判定 | 說明 |
|------|------|------|
| LINE REST：`oauth/accessToken` + PUT `/webhook/endpoint` | **USE** | 0-token 優先 |
| Developers Console UI（啟用 Messaging API） | **USE** | **Cursor browser MCP only** |
| `webhook_selftest.py`（22 項無網路） | **USE** | 驗簽/HMAC 邏輯 |
| CDP 開 Developers Console | **RETIRED** | 2026-07-10 起禁 agent |
| `jci.line.console` realm + 外開 Chrome Profile | **RETIRED** | 改 Cursor MCP |
| 手動複製 Channel Secret 進 chat | **AVOID** | 寫 `.env` / vault；schema only in logs |

### Git / GitHub / Vercel

| 做法 | 判定 | 說明 |
|------|------|------|
| `git_smart.py` + `ship.py` / `zct-ship.ps1` + `vercel --prod --yes` | **USE** | heartlink / fracdigi / ziyaoastro |
| `vercel-env-sync.py`（stdin 白名單 key） | **USE** | OAuth env 進 Vercel production |
| `vercel whoami` / `auth_check check vercel` | **USE** | 部署前 0-token 探針 |
| 只 `git push` 以為已上線 | **AVOID** | fracdigi 教訓：push ≠ deploy |
| 在 argv 傳 secret 給 vercel CLI | **AVOID** | 用 stdin pipe |

### Webhook（LINE / FB / Stripe…）

| 做法 | 判定 | 說明 |
|------|------|------|
| HMAC 驗簽 + env secret 缺失 → 401 | **USE** | fracdigi new.messages |
| cloudflared tunnel + PUT LINE endpoint | **USE** | KyloRen ingest |
| `webhook_selftest` / 本地 curl 假簽章 | **USE** | 先證邏輯再上線 |
| 無 secret 仍 bind 公網 webhook | **AVOID** | `line/service.py` OPERATOR-GATE |

### 表單 / Google Forms / Sheets 連動

| 做法 | 判定 | 說明 |
|------|------|------|
| GAS Web App + Sheets 白名單 | **USE** | ai_accountancy |
| `clasp` + headless Drive token | **USE** | 見 `headless-drive-write-via-clasp-token.md` |
| `google.script.run` 後台迁移 | **USE** | 非瀏覽器填表 |
| Browser 填 Google Forms 當 CI | **AVOID** | 脆、難維護；改 API/Apps Script |

### 通用瀏覽器自動化

| 做法 | 判定 | 說明 |
|------|------|------|
| `_secrets/browser-profiles/<realm>/` + `sso_browser.py` | **USE** | 與 operator 日常 profile **隔離** |
| `social-login.py` cookie_jar（IG/X） | **USE** | ai_metadata |
| `web-page-atlas` lookup 再導航 | **USE** | ai_trader 券商後台；0-token |
| Cursor MCP browser 驗 UI / OAuth | **USE** | 全艦 auth UI 唯一入口 |
| 讀 `%LOCALAPPDATA%\\Google\\Chrome\\User Data` | **AVOID** | 鎖定 + DPAPI |
| 新裝 Puppeteer / Playwright 登入 | **AVOID** | 用 Cursor MCP |
| Windows 本機 Chrome/Edge 開 OAuth | **AVOID** | fleet-browser-auth-mandate |
| `pywebview` 登入窗 | **USE** | operator 手動工具（fracdigi `fb_pull.py`）；agent 不自動跑 |

---

## 全艦紅線（採坑清單）

1. **未跑 `auth_check`** 就問 operator 登入/權限 → P=0  
2. **OAuth/SSO/Console UI 不用 Cursor browser MCP**（改開 Windows Chrome/CDP/Playwright）→ P=0  
3. **碰 operator 本機 Chrome/Edge profile** → 禁  
4. **Google 長 SPA** → Cursor MCP 分段 snapshot；不等外掛 CDP idle  
5. **Firebase popup SSO** → 只用 redirect（fracdigi）  
6. **push 不 deploy** → 必 `vercel --prod` 或 seat ship 腳本  
7. **browser_auth 平行** → 同 wave 只有一個登入 task  
8. **secret 進 chat / git** → vault + schema-only logs  
9. **無 evidence 宣稱登入成功** → curl/探針/ledger  
10. **GAS 先用 Browser MCP** → curl/`?op=login-diag` 先  
11. **重複問已 AUTHORIZED 服務** → 讀 `auth-inventory.json`  
12. **Meta/FB 用 Windows Chrome** → 僅 Cursor in-IDE Edge  
13. **OAuth 權限 UI 不記 ledger** → 禁止宣稱完成

---

## 子 skill / KB（深入時才開）

| 資源 | 何時讀 |
|------|--------|
| [reference.md](reference.md) | 各 seat 路徑與腳本對照表（canonical：`%AI_WORKSPACE%/_skill/fleet-skills/ztm-web-auth-ops/reference.md`） |
| [oauth-verify-ledger.md](oauth-verify-ledger.md) | Cursor Edge OAuth 每次嘗試的 SUMMARY + 密碼邊界（fracdigi absorb） |
| `ztm-meta-oauth-console` | Meta App Domains / Redirect URI / meta-pool 步驟 |
| `ztm-cursor-edge-auth` | **必讀** — Cursor in-IDE browser MCP 工作流 |
| `sso-browser-session` | cookie_jar / 隔離 profile（**非** OAuth UI 首選） |
| `gas-google-sso-webapp` | GAS `/exec` SSO 故障 |
| `ztm-webapp-verify` | 本地 UI smoke |
| `ztm-fracdigi-psync` | fracdigi room ship/OAuth 紅線 |
| `web-page-atlas`（ai_trader） | 重複造訪的券商/後台 |
| `_skill/technique_output/INDEX.md` grep | `OAuth`, `CDP`, `webhook`, `vercel`, `playwright` |

**KB 精選**：`cli-first-hub-ops` · `avoid-claude-chrome-google-spa` · `edit-google-oauth-redirect` · `manual-permission-handoff` · `computer-use-as-one-shot-bootstrap` · `chrome-dpapi-cookies-2025` · `no-proactive-auth-popups`

---

## 新增/變更流程

1. 實測得到可複用路徑 → 更新 `_registry/auth-inventory.json`（schema only）  
2. 新 SSO realm → `_registry/sso-realms.json` + SUBMIT  
3. 可推廣 workflow → `ztm-skill-submit` → curator 收錄本 skill 或 `reference.md`  
4. `python %AI_WORKSPACE%\_skill\engines\fleet-skill-sync.py tick` 後各 seat 同步

---

## 快速指令

```powershell
# 登入債務 / 授權盤點
python %AI_WORKSPACE%\_skill\engines\auth_check.py list

# SSO realm
python %AI_WORKSPACE%\_skill\engines\sso_browser.py check gov.isso.tpbusker

# Meta OAuth（Cursor Edge）— 見 ztm-meta-oauth-console
cd C:\ai_workspace\fracdigi\GitHub\new.messages.fracdigi.com
npm run zct:meta-oauth:wave
node scripts/oauth-verify-log.mjs --provider=meta --account=scss1199@gmail.com --surface=meta-pool-oauth --result=pass --browser=cursor-edge

# Vercel 探針
vercel whoami

# fracdigi 上線（push+deploy 一條龍）
cd C:\ai_workspace\fracdigi\GitHub\new.messages.fracdigi.com
.\scripts\zct-ship.ps1 -Sync
```
