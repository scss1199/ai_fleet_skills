---
name: browser-login-handoff
description: >-
  F1S login procedure for any site the task needs while signed in (claude.ai settings, provider
  consoles, dashboards). Reuse an existing session first, probe the built-in browser for a real
  signed-in state, and hand the sign-in to the user exactly once with the pane visible and one tab
  named; then re-probe and continue the task. Use before asking the user to sign in anywhere, when a
  page redirects to /login, or when the user says they already signed in but the page still asks.
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
session、讀回才算完成）。本技能是「內建瀏覽器」這個 adapter 的固定流程。登入／OAuth 是使用者專屬的
步驟（F1S ⑤），其餘每一步都自己做。

## 1 先找不用登入的路

```powershell
python %AI_WORKSPACE%\_skill\engines\site-login-inventory.py check <domain>
```

有 `fetch` adapter（`_registry/site-fetch-adapters.json`）或 CLI 權杖能拿到目標狀態 → 走那條，不叫使用者登入。

## 2 探測真實登入狀態

- 內建瀏覽器開一個「需要登入」的頁（例：`https://claude.ai/new`），等 3–4 秒再讀 `location.href`。
- 被導到 `/login`、`reauth=1`、或標題是 Sign in → 判定 `NOT_SIGNED_IN`，證據是那個網址。
- 使用者說「已登入」不算證據；只有探測結果算。

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

## 5 登入後的動作

- 只做任務需要的事；不登出、不改帳密、不碰付款資料。
- 會花錢、要接受新的付費條款、或不可逆的按鈕 → 停下，問使用者一次。
- 每個結果都讀回網頁狀態才回報（`get_page_text`），沒讀回寫 UNKNOWN。
