# ztm-web-auth-ops — 各 seat 對照表

> 詳細路徑與腳本 SSOT。主 skill：[SKILL.md](SKILL.md)

## 圖例

| 判定 | 意義 |
|------|------|
| **USE** | 直接複用 |
| **AVOID** | 已知踩坑，勿用 |
| **GATE** | operator 一次性 consent / 人手點擊 |
| **N/A** | 該 seat 無此場景 |

---

## 總表

| Seat | Google SSO (App) | Google SSO (Console) | LINE | Git/Vercel | Webhook | Forms/Sheets | 主要方式 | 判定 |
|------|------------------|----------------------|------|------------|---------|--------------|----------|------|
| **ai_hr** | NextAuth → hr-tw.vercel.app | `ensure_gcp_login.py` + CDP :9222 | N/A | `ship.py`, `vercel-env-sync.py` | N/A | N/A | CLI + CDP | USE |
| **ai_heartlink** | NextAuth 專用 GCP 178918414586 | 同 ai_hr 模式 | N/A | `scripts/ship.py`, `vercel-env-sync.py` | N/A | N/A | CLI | USE |
| **fracdigi** | Firebase redirect `/__/auth` | GCP OAuth client 註冊 new 網域 | Messaging API env | `daily-push.ps1`, `zct-ship.ps1` | FB/LINE HMAC | N/A | CLI + env | USE |
| **ai_accountancy** | GAS USER_ACCESSING | clasp / GCP 部署 | N/A | `tools/gas_deploy.py` | N/A | Sheets 白名單 | curl + clasp | USE |
| **jci_taipei** | GAS SSO 白名單 | N/A | `chrome_ctx.py` CDP + LINE Console | N/A | N/A | Sheets | CDP + GAS | USE |
| **ai_darkhero** | N/A | N/A | `line/*` tunnel/webhook/reconfigure | N/A | LINE HMAC selftest | N/A | API + CDP | USE |
| **ai_news** | N/A | N/A | ingest webhook（fork line 殼） | N/A | `webhook_selftest.py` | N/A | API | USE |
| **ai_busker** | Next.js dedicated `ai-busker-web` / iron-wave | Cursor MCP GCP Console | N/A | `vercel-env-sync.py` + npx vercel | N/A | N/A | Google SSO + gov iSSO realm | USE |
| **ai_metadata** | N/A | N/A | N/A | N/A | N/A | N/A | `login_webview.py` + `social-login.py` | USE |
| **ai_trader** | N/A | N/A | N/A | N/A | N/A | N/A | `web-page-atlas` + 手動 Chrome | USE |
| **ai_ziyaoastro** | FastAPI OAuth2（產品端 SSO） | N/A | N/A | `ztm-ziyaoastro-vercel` skill | N/A | N/A | vercel CLI | USE |
| **ai_zonghe** | N/A | N/A | N/A | 標準 git ship | N/A | N/A | CLI | USE |
| **ai_fintrend** | N/A | N/A | N/A | 標準 git ship | N/A | N/A | CLI | USE |
| **ai_ut / ai_demo / ai_wallpaper / ai_network / ai_search** | 各 app 自有 | N/A | N/A | 標準 git ship | N/A | N/A | CLI | USE |
| **ai_portal** | N/A | N/A | N/A | N/A | N/A | N/A | :7821 API smoke | USE |

---

## 各 seat 關鍵路徑

### ai_hr

| 場景 | 路徑 | 判定 |
|------|------|------|
| GCP OAuth client | `match-app-web/scripts/ensure_gcp_login.py` | USE |
| CDP Chrome 啟動 | `tools/launch_scss1199_cdp_junction.py` | USE |
| Chrome profile 設定 | `config/chrome_profile.json` → Profile 1 / scss1199 | USE |
| Vercel env | `match-app-web/scripts/vercel-env-sync.py` | USE |
| 錯誤 autofill 修復 | `tools/fix_gmaill_autofill.py` | AVOID 日常用；僅 emergency；勿碰 operator Profile 3 日常 |
| Live URL | https://hr-tw.vercel.app/ | — |

### ai_heartlink

| 場景 | 路徑 | 判定 |
|------|------|------|
| Ship | `scripts/ship.py` | USE |
| Vercel env | `scripts/vercel-env-sync.py` | USE |
| OAuth SSOT | `config/gcp_oauth.json` (GCP 178918414586) | USE |
| Vercel token 失效 | 跑 `vercel login` / auth_check | GATE |

### fracdigi (new.messages)

| 場景 | 路徑 | 判定 |
|------|------|------|
| Room charter | `GitHub/new.messages.fracdigi.com/AGENTS.md` | USE |
| Push+deploy | `scripts/daily-push.ps1`, `scripts/zct-ship.ps1` | USE |
| SSO | `signInWithRedirect` only | USE |
| `signInWithPopup` | — | AVOID |
| **Meta pool OAuth skill** | `_skill/fleet-skills/ztm-meta-oauth-console/SKILL.md` | USE |
| **OAuth ledger SUMMARY** | `_skill/fleet-skills/ztm-web-auth-ops/oauth-verify-ledger.md` | USE |
| Machine ledger | `GitHub/.../runtime/oauth-verify-ledger.jsonl` | USE |
| Log writer | `npm run oauth:log` / `scripts/oauth-verify-log.mjs` | USE |
| Wave verify | `npm run zct:meta-oauth:wave` | USE |
| Meta App ID (pool) | `3843028145947505` | USE |
| insights App | `33551954441086090` | AVOID as client_id |
| Meta/FB via **Chrome** | — | AVOID |
| Meta/FB via **Cursor Edge** | browser MCP | USE |
| FB operator 工具 | `tools/fb_pull.py` (pywebview) | GATE；agent 不自動 |
| Webhook secrets | Vercel env `FACEBOOK_APP_SECRET`, `LINE_CHANNEL_SECRET` | USE |

### ai_accountancy

| 場景 | 路徑 | 判定 |
|------|------|------|
| GAS SSO skill | `.cursor/skills/gas-google-sso-webapp/SKILL.md` | USE |
| 部署 | `tools/gas_deploy.py` | USE |
| 探針 | `tools/gas_deploy.py --probe-only` | USE |
| Browser 第一診斷 | — | AVOID |

### jci_taipei

| 場景 | 路徑 | 判定 |
|------|------|------|
| LINE CDP | `_line/chrome_ctx.py`, `_line/fix_oa_settings.py` | USE |
| GAS | `jci_taipei_70/apps-script/` | USE |
| Realm | `_registry/sso-realms.json` → `jci.line.console` | USE |

### ai_darkhero (line / KyloRen)

| 場景 | 路徑 | 判定 |
|------|------|------|
| Handbook | `line/KYLOREN-LINE-HANDBOOK.md` | USE |
| Webhook 服務 | `line/service.py`, `line/webhook.py` | GATE 公網 |
| Tunnel + PUT | `line/tunnel.py` | USE |
| 重配 | `line/reconfigure_kyloren.py` | USE |
| Console CDP | `line/enable_and_wire_828jbbuy.py` | USE |
| Selftest | `line/webhook_selftest.py` (22/22) | USE |

### ai_busker

| 場景 | 路徑 | 判定 |
|------|------|------|
| Product Google SSO | https://ai-busker.vercel.app/ + dedicated client `ai-busker-web` | USE |
| OAuth SSOT | `web/config/gcp_oauth.json` (GCP `iron-wave-466411-v5`) | USE |
| Vercel env | `web/scripts/vercel-env-sync.py` | USE |
| GCP Audience/URI | Cursor browser MCP → Console（禁 Windows Chrome/CDP） | USE |
| Meta / LINE product OAuth | — | N/A（本 seat 無 Meta 池／LINE Messaging） |
| tpbusker.gov lottery iSSO | `sso_browser.py` realm `gov.isso.tpbusker` | USE |
| Profile | `_secrets/browser-profiles/gov.isso.tpbusker/` | USE |
| Lottery browser | Playwright `channel=msedge`（政府站自動化；**非** Google product OAuth UI） | USE |
| Windows Chrome 做 Google SSO | — | AVOID |

### ai_metadata

| 場景 | 路徑 | 判定 |
|------|------|------|
| 社群 cookie（pywebview） | `src/ai_metadata/login_webview.py` | USE |
| 引擎封裝 | `_skill/engines/social-login.py` | USE |
| Realms | `sso-realms.json` → `social.instagram`, `social.twitter` | USE |
| Chrome cookie 直接讀取 | — | AVOID（DPAPI） |

### ai_heartlink

| 場景 | 路徑 | 判定 |
|------|------|------|
| Drive owner OAuth（無瀏覽器） | `scripts/drive_oauth_owner.py` | USE |
| clasp profile | `ingest-clasp-owner-profile.py` | USE |

### ai_accountancy

| 場景 | 路徑 | 判定 |
|------|------|------|
| 登入診斷（API 先） | `tools/check_login.py` | USE |
| UI 修復 CDP | `tools/fix_scss_login.py` | GATE；API 失敗後才用 |

### ai_ziyaoastro

| 場景 | 路徑 | 判定 |
|------|------|------|
| 產品端 Google SSO | `backend/app/api/auth_google.py` | USE（app auth 參考） |
| Vercel bootstrap | `_skill/fleet-skills/ztm-ziyaoastro-vercel/SKILL.md` | USE |

### fracdigi — auth 細節

| 場景 | 路徑 | 判定 |
|------|------|------|
| Admin allowlist | `src/lib/server/authAllowlist.ts` | USE |
| 新增外部 admin email | — | GATE（owner 核准） |

### ai_trader

| 場景 | 路徑 | 判定 |
|------|------|------|
| 站點地圖 | `.claude/skills/web-page-atlas/` + `atlas.py` | USE |
| 券商後台 | lookup → 導航；owner 手動登入 Chrome | GATE |
| LINE webhook | `sinopac-trading-system/src/services/line_bot_webhook.py` | USE |

---

## Hub 共用引擎

| 引擎 | 用途 |
|------|------|
| `_skill/engines/auth_check.py` | 登入前 0-token 閘 |
| `_skill/engines/sso_browser.py` | realm persistent/cookie/cdp |
| `_skill/engines/social-login.py` | IG/X cookie 擷取 |
| `_skill/engines/fleet-skill-sync.py` | 全艦 skill 部署 |
| `_registry/auth-inventory.json` | 已授權服務 SSOT |
| `_registry/sso-realms.json` | 瀏覽器 realm SSOT |
| `_registry/login-debt.json` | 待 operator 一次性 consent |

---

## 已知無用／高成本做法（fleet 共識）

| 做法 | 為何沒用 |
|------|----------|
| 掃描/修改 operator `%LOCALAPPDATA%\\Google\\Chrome` | 鎖定、DPAPI、幽靈 autofill、Profile 混用 |
| Playwright 全新 profile 登 Google | 每次 2FA；應 CDP 或 persistent realm |
| 在 agent 內 hardcode OAuth secret | 違反 vault；用 vercel-env-sync / .env.local |
| 只修 Web Data 以為清掉 Google 登入建議 | 可能來自 cookies/accounts.google.com 快取 |
| 多 agent 同時 CDP 登入 | parallel-gates browser_auth max=1 |
| Puppeteer 全量安裝只驗一頁 | 用 MCP browser 或 CDP attach |

---

## 更新紀錄

| 日期 | 變更 |
|------|------|
| 2026-07-07 | 初版：全艦 web auth 對照，curator 自 ai_workspace 各 seat 盤點 |
