---
name: gas-google-sso-webapp
description: >-
  Google Apps Script Web App Google SSO (executeAs USER_ACCESSING). Use when
  GAS /exec login fails, 「無法開啟這個檔案」, sessionLogin errors, multilogin /u/N,
  adminMigrate, or deploying ai_accountancy-style hybrid login.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: schema-only
    scheduler: session
    token_budget: low
---

# GAS Web App — Google SSO（fleet 實戰版）

> 綜整 **ai_accountancy**、**jci_taipei** 與 hub KB（`2026-06-18-gas-migrate-to-executeAs-user-google-sso`、
> `2026-06-18-gas-anon-webapp-multilogin-cannot-open-file`、`manual-permission-handoff`）。
> **禁止用 Browser MCP 當第一診斷**；先 curl / 本 repo 工具 / `?op=login-diag`。

## 何時用

- `/exec` 出現 **「很抱歉，目前無法開啟這個檔案」**（Google Drive 錯誤頁）
- `sessionLogin` 失敗：`無法取得 Google 身分` / `不在使用名單`
- 部署後 SSO 白名單、Martyn 交接、`adminMigrate` 順序
- 與 **jci_taipei** / **ai_accountancy** 同型 GAS + Sheets + `google.script.run`

## 標準架構（ai_accountancy · 已上線）

| 項目 | 值 | 檔案 |
|------|-----|------|
| 執行身分 | `USER_ACCESSING`（存取者） | `apps-script/appsscript.json` |
| 存取 | `ANYONE`（需 Google 登入） | 同上 |
| SSO 入口 | `sessionLogin()` | `apps-script/Code.gs` |
| Email 解析 | `_sessionEmail_()`：`getEffectiveUser()` → fallback `getActiveUser()` | `Code.gs` |
| 白名單 | 試算表「使用者」：`email` + `啟用=是` | Sheets |
| 混合登入 | SSO 失敗 → Email/密碼（racauto 成員） | `Index.html` `bootSession()` |
| 部署 | `python tools/gas_deploy.py "note"` | ZCT |

**參考專案（同 fleet 模式）**

| 專案 | SSO 模式 | 可抄 |
|------|----------|------|
| **ai_accountancy** | USER_ACCESSING + 共用 Martyn 試算表 + `adminMigrate` | `Code.gs`, `DEPLOYED.md`, `tools/handoff.py` |
| **jci_taipei** | SSO 白名單 JSON + `_activeEmail_()` | `jci_taipei_70/apps-script/Code.gs`, `AuthMigrate.gs`, `PARITY.md` |

## 診斷順序（必按序，禁止猜）

### Step 0 — 匿名探針（0-token）

```powershell
python tools/gas_deploy.py --probe-only
# 或手動：curl -sL "<execUrl>" -o %TEMP%\gas.html -w "HTTP %{http_code}\n"
# 檢查：有 <title>內帳系統</title> 或 302→accounts.google.com = 部署活
```

| 探針結果 | 意義 |
|----------|------|
| `200` + 真 HTML title | 部署 OK；瀏覽器問題多半是 **多帳號**（Step 1） |
| `302` → `ServiceLogin` | USER_ACCESSING + ANYONE 正常（需 Google 登入） |
| `200` + 「無法開啟這個檔案」**僅 curl 也中** | 擁有者 **未授權 Drive/Sheets scope**（Step 2） |

### Step 1 — 「無法開啟檔案」= 90% 多帳號良性 bug

**來源**：KB `2026-06-18-gas-anon-webapp-multilogin-cannot-open-file` · 影響 ai_accountancy / ai_hr / ai_heartlink / ai_ut 等。

- 症狀：URL 變 `/macros/u/N/s/.../exec` 或 `script.google.com/accounts?authuser=N`
- **curl 200 但 Chrome 不行** → 不是部署問題，**不要重部署**
- 解法（client 端）：
  - **Chrome 無痕** + 只登入目標 Gmail
  - **專屬 Profile**（本 repo：`Profile 3` = scss1199，見 `tools/handoff.py`）
  - 避免同一視窗多 Google 帳號

### Step 2 — 擁有者一次性 OAuth（manual-permission-handoff）

**來源**：KB `manual-permission-handoff` · `2026-06-18-gas-email-auth-shared-book-owner-execute`

在 **GAS 編輯器**（scss1199 擁有者）：

1. 選一個**真的碰 Drive/Sheets** 的函式（**不是 doGet**）→ 執行 → 審查權限 → **進階 → 允許**
2. 建議跑：`ocrSelfTest()` 或任意 `getSS_()` 路徑
3. 「管理部署作業」確認：**執行身分 = 使用者正在存取**、**誰可以存取 = 所有人**

> 未授權前，**所有人**（含 doGet）都可能看到「無法開啟這個檔案」。clasp **無法代授權**。

### Step 3 — 登入診斷 URL（scss1199 · 已部署）

用 **scss1199 單一帳號** Chrome 開：

```
<execUrl>?op=login-diag&fix=1
```

預期 JSON：

```json
{
  "activeUser": "scss1199@gmail.com",
  "sessionLoginWouldFail": null,
  "scss1199": { "active": "是", "role": "管理員" }
}
```

| `sessionLoginWouldFail` | 原因 | 修復 |
|-------------------------|------|------|
| `no_google_identity` | 未完成 App OAuth 或多帳號 | Step 1 + 2 |
| `user_disabled` | `completeHandoff` 把 scss1199 設 `啟用=否` | `?fix=1` 自動修復或 `enablePlatformDevAdmin()` |
| `not_in_user_sheet` | 使用者表無此列 | `?fix=1` 或編輯器跑 `enablePlatformDevAdmin()` |

本機觸發（**必須在 repo 根目錄** `C:\ai_workspace\ai_accountancy`，不可在 `C:\Users\sc`）：

```powershell
cd C:\ai_workspace\ai_accountancy
python tools/handoff.py enable-dev-admin
python tools/check_login.py
```

**空白登入框**（標題有、白框內無按鈕）：`bootSession(false)` 自動 SSO 中；等 12s 會出現「登入」按鈕，或加 `?login=manual` 跳過自動 SSO。

### Step 4 — USER_ACCESSING 資料分裂（Martyn 交接）

**來源**：KB `2026-06-18-gas-migrate-to-executeAs-user-google-sso` · `DEPLOYED.md`

**順序錯 = 另建空試算表**：

1. **先**（scss1199 編輯器）跑 `adminMigrate()` / `completeHandoff()`  
   → 把 `內帳資料庫` **分享給 martyn9154（編輯）**  
   → 可把 scss1199 App 登入設 `啟用=否`（營運隔離）
2. **再** Martyn 首登 → 未驗證 → 進階 → 允許
3. 開發者恢復：`enablePlatformDevAdmin()` 或 `?op=login-diag&fix=1`

Martyn 正式資料夾：`DATA_FOLDER_ID` in `Code.gs` · 試算表 `1A-e1dDZDAepT2n6pJbdYt6eBwRvMbIqdOIzvBABMhgE`（scss1199 owner，martyn writer — verify via Drive API）

## jci_taipei 可抄片段

```javascript
// jci_taipei_70/apps-script/Code.gs — 白名單 SSO
function sessionLogin() {
  var email = _activeEmail_();
  if (!email) throw new Error('無法取得 Google 身分。請確認部署為「使用者正在存取」…');
  if (!_isAllowedEmail_(email)) throw new Error('未授權…（你目前是 ' + email + '）');
  return { ok: true, email: email, role: … };
}
function _activeEmail_() {
  try { return (Session.getActiveUser().getEmail() || '').trim().toLowerCase(); }
  catch (e) { return ''; }
}
```

ai_accountancy 已升級為 `_sessionEmail_()`（**優先 `getEffectiveUser()`**），新專案應抄 ai_accountancy 版。

Bootstrap 遷移（jci）：`?op=migrate&secret=...&dry=1` → 確認 spreadsheet / drive steps 全 ok → 去掉 `dry` 寫入。見 `AuthMigrate.gs`。

## 程式 Checklist（新 seat / 修 SSO）

- [ ] `appsscript.json`: `executeAs: USER_ACCESSING`, `access: ANYONE`
- [ ] `_sessionEmail_()` 用於 `sessionLogin` 與所有 `?op=` 管理端點
- [ ] 前端 `bootSession()` → `gcall('sessionLogin')` → fallback 密碼登入
- [ ] 白名單在 Sheets「使用者」；`啟用=否` 等同封鎖
- [ ] `adminMigrate` **先分享試算表** 再切 executeAs
- [ ] 部署：`python tools/gas_deploy.py`；probe HTTP 200
- [ ] 瀏覽器失敗時 **先 curl**，再查多帳號

## 禁止

- 未 curl / login-diag 就宣稱「部署壞了」或「沒授權」
- **`getSS_()` 初始化期間呼叫 `rows()`**（`ensureInventoryCategories_` 曾因此無限遞迴 → `sessionLogin` 永遠卡住；jci 登入不讀 Sheet 所以沒事）
- 用 Cursor Browser MCP 當第一診斷（fleet browser-ban；見 `web-ops-router`）
- 對 USER_ACCESSING app 用 `clasp run` 代替使用者 session（owner run ≠ 存取者 run）
- 跳過 `adminMigrate` 順序直接讓 Martyn 首登

## KB / 路徑索引

| 文件 | 路徑 |
|------|------|
| executeAs 遷移 | `%AI_WORKSPACE%/_inbox/_digested/.../2026-06-18-gas-migrate-to-executeAs-user-google-sso.md` |
| 多帳號「無法開啟」 | `.../2026-06-18-gas-anon-webapp-multilogin-cannot-open-file.md` |
| OAuth 假警報 | `.../apps-script-webapp-deploy-benign-oauth-error.md` |
| 手動授權 | `%AI_WORKSPACE%/_skill/technique_output/50-techniques/manual-permission-handoff.md` |
| execute-as-user 概論 | `.../gas-webapp-execute-as-user.md` |
| 本專案部署 | `DEPLOYED.md`, `HANDOFF.md` |
| 本專案工具 | `tools/check_login.py`, `tools/handoff.py enable-dev-admin` |

## 2026-10-16 補充（f1s-reverse-learning 升為 F1S canonical）

- `clasp push` 回「Requested entity was not found」：先用 clasp token 查 Drive（`files/<scriptId>`、`q=trashed=true`）。
  在垃圾桶就到 drive.google.com/drive/trash（內建瀏覽器）還原；**不要先重建**——重建會換掉正式 /exec 網址、
  指令碼屬性全空、每個使用者要重新授權（ai_accountancy 1Ng2v424 事件）。
- 新專案沒有 `SS_ID` 時，`getSS_()` 預設開回既有資料表（程式常數 `DEFAULT_SS_ID`），不要讓第一位使用者建出新空帳。
- 擁有者授權（USER_DEPLOYING web app、編輯器「審查權限」）會開彈窗，內建瀏覽器會擋代理點出的彈窗：從 /exec 的
  「Authorization needed」頁讀出 `accounts.google.com/o/oauth2/auth?...` 網址，在同一分頁開，進階 → 前往 → 繼續
  （技能 browser-login-handoff 4b）。
- hub 要讀寫試算表時，clasp 的 Google 用戶端要求 spreadsheets 範圍會被 Google 封鎖：改用擁有者名下的小型
  Apps Script 橋接（USER_DEPLOYING + ANYONE_ANONYMOUS，只放密鑰的 sha256，範例 `ai_accountancy/tools/ocr_bridge.gs`）。
