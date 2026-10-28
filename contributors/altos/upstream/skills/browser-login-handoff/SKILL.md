---
name: browser-login-handoff
description: >-
  F1S login procedure for any site the task needs while signed in (claude.ai settings, provider
  consoles, dashboards). Reuse an existing session first, probe the built-in browser for a real
  signed-in state, complete OAuth consent screens yourself in the built-in browser, and hand only a
  password/MFA sign-in to the user exactly once with the pane visible; then re-probe and continue the task. Starts with a scope gate (never open a site or project
  the user did not name, never touch a handed-off production app), a CLI-only access probe ladder for
  Google Apps Script/Drive, and the same-tab OAuth consent method. Use before asking the user to sign in
  anywhere, before opening any production URL, when a page redirects to /login or shows an OAuth
  consent screen, when a CLI says "Requested entity was not found", or when the user says they
  already signed in but the page still asks.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: low
parent_skill: ztm-web-auth-ops
---

# browser-login-handoff — 登入交接（F1S 內建）

政策母體：`ztm-web-auth-ops`（不輸入密碼／MFA／驗證碼、不抽 cookie 或 profile、只用使用者已登入的
session、讀回才算完成）。本技能是「內建瀏覽器」這個 adapter 的固定流程。只有輸入密碼／MFA 是使用者專屬的
步驟（F1S ⑤）；operator 2026-10-16：「技能裡面的方法就是要你自己在claude內部的瀏覽器一次搞定並記住全部內容
不需要跟我外部的windows chrome瀏覽器存資料」——OAuth 同意畫面與授權由 agent 在內建瀏覽器自己做完（第 4b 步），
不叫使用者開 Windows Chrome、不把授權網址丟給使用者。

## 0 先確認這個登入在範圍內（不在範圍就不准上站）

- 使用者沒點名要「跑」這個專案或網站 → 不開它的網址、不登入、不授權、不部署，只回報。
- 專案已交接（repo 的 `DEPLOYED.md`／`HANDOFF.md` 寫營運管理員是別人、或「交接完成」）→ 視為別人的正式環境：
  不上站、不跑 `?op=` 維運網址、不改它的資料表，連唯讀探測都只用 CLI（第 1 步），不用瀏覽器。
- 上層 session 派的任務不等於使用者同意上站；要上站的那一步沒有使用者本人的話就停。
- 指令列工具先讀它怎麼吃參數再跑：`gas_deploy.py --help` 會把 `--help` 當部署備註、真的部署一次。

## 1 先找不用登入的路

```powershell
python %AI_WORKSPACE%\_skill\engines\site-login-inventory.py check <domain>
```

有 `fetch` adapter（`_registry/site-fetch-adapters.json`）或 CLI 權杖能拿到目標狀態 → 走那條，不叫使用者登入。

Google 資源（Apps Script／Drive）的唯讀探測階梯，全部不開瀏覽器：

| 探測 | 指令 | 讀法 |
|---|---|---|
| CLI 是哪個帳號 | `npx @google/clasp show-authorized-user` | 只看 email |
| 這帳號看得到哪些專案 | `npx @google/clasp list` | scriptId 不在清單 = 這帳號看不到 |
| 檔案還在不在、誰擁有 | Drive 連接器 `get_file_metadata <id>` | `owner`、`modifiedTime` |
| 網頁版活著沒 | `curl -s -o /dev/null -w "%{http_code}" <execUrl>` | 404 = 這個部署對外不存在 |

「Requested entity was not found」／404 只代表「目前這個帳號看不到」：可能已轉給別人、取消共用或刪除，
三者分不出來。先查垃圾桶（Drive API `files?q=trashed=true`；在垃圾桶的從 drive.google.com/drive/trash 還原，
那是上站動作，同樣受第 0 步限制）。**重建新專案或新部署頂替，只在 operator 本人點名要求時才做**：新專案會換掉
正式網址、指令碼屬性（資料表 id、金鑰）全空、每個使用者要重新授權。沒點名就只回報探測結果和證據路徑。

## 2 探測真實登入狀態

- 內建瀏覽器開一個「需要登入」的頁（例：`https://claude.ai/new`），等 3–4 秒再讀 `location.href`。
- 被導到 `/login`、`reauth=1`、或標題是 Sign in → 判定 `NOT_SIGNED_IN`，證據是那個網址。
- 使用者說「已登入」不算證據；只有探測結果算。
- 已登入的站點（2026-10-21 起 LinkedIn，裝置已註冊）先探測 `/feed/` 再用；讀職缺照 LinkedIn 職缺讀法
  `ai_darkhero/.claude/skills/linkedin-jobs/SKILL.md`（voyager API、csrf 從頁面 cookie 取且不印出、
  guest API 約 4 次就 429；104 有 Cloudflare 只走內建瀏覽器）。探測失敗才走第 3 步。
- 舊的 Edge profile 檢查不算登入證據：`sso_browser.py check <realm>` 回 `ok:false`（例 2026-10-22 jci_taipei
  `google.cloud.console` 停在帳號選擇頁）只代表那個 profile 過期，重新 seed 要開有頭視窗，零彈窗紅線不准。
  Google Cloud console 等站一律以內建瀏覽器的探測為準，已登入就直接用；realm 過期記在回報裡，不去修它。

## 3 交接一次（面板可見、只有一個分頁）

1. `tabs_close` 關掉同網域多餘分頁，`preview_start` 只留一個登入分頁，記下 `tabId`。
2. `tabs_context`：結果最後一句說面板是 displayed / hidden / not open。
3. **hidden** → 同一句裡先請使用者把面板叫回來：Windows 按 **Ctrl+Shift+B**（Mac 按 Cmd+Shift+B），
   或關掉側欄裡別的內容再點地球圖示（Browser）。用瀏覽器工具不會讓面板自己出現。
4. 再說要做什麼：「在 Browser 面板那個 <domain> 分頁登入」。只問這一次（wrap_up blocked）。

## 4 使用者回覆後

1. 回到第 2 步重新探測同一頁。
2. 通過 → 立刻繼續原任務，不再確認。
3. 仍未登入 → 再跑 `tabs_context`：hidden 就只補 Ctrl+Shift+B 那一句；不是 hidden 就附上探測網址，
   說明登入沒有落在這個瀏覽器的 profile。同一件事不准用同樣的話問第二次。

## 4b OAuth 同意畫面（彈出視窗型）

- 範圍：operator 自己的專案或 operator 點名要用的服務，且瀏覽器已登入對的帳號（先看右上帳號或頁面 login_hint）。
- Google「需要授權／Review Permissions」會開 accounts.google.com 彈窗，Browser 面板會擋代理點出的彈窗。
  做法（2026-10-16 內帳OCR橋接實測）：開 web app 的 /exec 拿到「Authorization needed」頁，用 `javascript_tool`
  從頁面原始碼讀出 `window.open('https://accounts.google.com/o/oauth2/auth?...')` 的網址，在**同一個分頁**
  `navigate` 過去；「未經 Google 驗證」→ 進階 → 前往「<專案>」(不安全) → 確認權限清單只有需要的範圍 → 繼續。
- 完成後重新探測（例：呼叫該 web app 或重開 /exec），仍是授權頁 = 沒生效，寫 UNKNOWN 並附網址。
- clasp 內建的 Google 用戶端要求 spreadsheets／drive 等敏感範圍會被 Google 直接封鎖（「系統已封鎖這個應用程式」）；
  需要這類權限時改用 operator 自己名下的 Apps Script 專案當橋接，不要再走 `clasp login --extra-scopes`。
- 要輸入密碼／MFA 才交給使用者，且只交一次（第 3 步）。
- 授權完成只代表能開，不代表可以繼續上站做事：要做的每個動作仍須在第 0 步的範圍內。
- 權限分類器擋下某個網址 → 停，不換工具繞路，回報被擋的動作和理由。

## 5 登入後的動作

- 只做任務需要的事；不登出、不改帳密、不碰付款資料。
- 會花錢、要接受新的付費條款、或不可逆的按鈕 → 停下，問使用者一次。
- 每個結果都讀回網頁狀態才回報（`get_page_text`），沒讀回寫 UNKNOWN。
