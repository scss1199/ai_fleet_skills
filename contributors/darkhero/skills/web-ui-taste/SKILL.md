---
name: web-ui-taste
description: >-
  F1S route for building or changing any fleet web UI (jci website, ziyaoastro, accountancy GAS app,
  portals, tray/console pages) so it does not look cheap and passes the Web Interface Guidelines: pick a
  design system (DESIGN.md), apply taste/art direction, turn a reference image into code, run the
  mechanical guideline lint, and verify with phone + desktop screenshots in the built-in browser. Use
  before claiming any frontend change done, when asked to "make it look better", review UI/UX or
  accessibility, or when a reference screenshot/design is given.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: low
parent_skill: ztm-webapp-verify
---

# web-ui-taste — 前端品味與規範（F1S）

來源：operator 2026-10-16 轉來的 kyloren IG reel DeicLoFhs5O（五個讓 Claude Code 做網頁不再廉價的工具）。
原始出處 2026-10-16 核對：Taste Skill = `Leonxlnx/taste-skill`（MIT）、Web Design Guidelines =
`vercel-labs/agent-skills` 的 `web-design-guidelines`（規則本體 `vercel-labs/web-interface-guidelines`，MIT）、
Awesome Design = `VoltAgent/awesome-design-md`（MIT，品牌設計系統的 DESIGN.md）、Image to Code = 模型視覺讀參考圖、
Playwright CLI = `microsoft/playwright-cli`（Apache-2.0）。F1S 只取做法，不常駐安裝任何一個。

## 五步（做 UI 時依序）

1. **設計系統**：專案已有設計 token／DESIGN.md 就照它。沒有才從 awesome-design-md 挑**一份**最接近的
   DESIGN.md（配色、字型、間距、按鈕），放進該 repo 既有的設計檔位置；不要在同一頁混兩套。
2. **品味／方向**：先寫三句 art direction（用途、氣氛、一個參考），再動手；避免預設灰底卡片＋藍按鈕的通用樣子。
   Taste Skill 的原則：明確層級、留白一致、只用一到兩個強調色、互動要有狀態。
3. **參考圖轉程式**：使用者給截圖或設計圖時，先用視覺讀出版面區塊與尺寸，再寫程式；完成後對照同尺寸截圖。
4. **機械規範檢查（0 token）**：
   ```bash
   python %AI_WORKSPACE%\_skill\engines\ui-guideline-lint.py <changed files or app dir> --summary
   ```
   規則是 Vercel Web Interface Guidelines 裡能從原始碼判定的部分（禁縮放、`transition: all`、拿掉 outline 沒補
   focus-visible、圖片沒 alt、div/span 當按鈕、表單欄位沒 label、純圖示按鈕沒 aria-label、擋貼上、動畫沒有
   reduced-motion）。改動前後各跑一次，數字只能下降；新增的 finding 要修或寫明理由。其餘要判斷的規則
   （層級、文案、深色模式、i18n）依 `https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md`
   逐條人工檢查，用 `file:line` 回報。
5. **截圖驗證（取代 Playwright CLI，不安裝）**：在 Claude 內建瀏覽器開頁面（本機檔案先用
   `python -m http.server <port> --bind 127.0.0.1` 起站），`resize_window` 375×812 與桌面各截一次；
   `javascript_tool` 量 `document.documentElement.scrollWidth === innerWidth`（不可橫向捲動），並在頁面上查
   執行時才產生的欄位（JS 字串組出來的，lint 看不到）：
   `[...document.querySelectorAll('input,select,textarea')].filter(e=>e.type!=='hidden'&&!e.labels?.length&&!e.getAttribute('aria-label')&&!e.getAttribute('aria-labelledby')).length`
   必須是 0（2026-10-16 ziyaoastro 的聊天輸入框就是這樣抓到的）。
   GAS 前端用專案自帶的 `local-gas-mock.js` 預覽；測試帳號只用專案 mock 檔裡的值。

## 來回點擊驗證（反向學習自 ai_ziyaoastro 2026-10-29「來回按幾次不同功能就在那轉圈圈」）

站內換頁（Astro ClientRouter／View Transitions、任何 SPA router）只在第一次整頁載入執行一次頁面腳本：
沒有掛在 `astro:page-load`（或該 router 的 page-load 事件）上重新初始化的頁面，第二次進來載入資料的程式不會再跑，
畫面永遠停在「載入中…」，而 API 本身 249 ms 就回了 200。所以**轉圈圈先查前端生命週期，不要先怪後端**：
DevTools 看到 API 已回 200 但列表是 0 筆＝初始化沒再跑。規則：① 每頁的初始化不是綁 page-load 事件，就是對這頁
取消站內換頁改整頁載入（含瀏覽器上一頁）；② 寫一個測試掃所有頁面，「有 page-load handler」必須等於「允許站內換頁」，
新頁漏掉直接紅（`ai_ziyaoastro/tests/client_router_reload_guard_test.mjs`、`frontend/src/layouts/Base.astro`
的 `REINIT`，b806548）；③ 宣稱前端修好前，在正式站用內建瀏覽器做至少三條來回路徑（A→B→A、A→B→上一頁→上一頁、
A→C→A），每一站都要看到真資料，不是只截首頁；沒驗到的頁面要點名（synthesis 那輪就沒驗到）。

## 讀取速度（反向學習自 jci_taipei jci-web-fast-read，源頭 fracdigi psyncClientCache）

資料多的後台頁一律「先畫、後驗、不清空」：① 先用 localStorage 裝置快取立刻畫面（帶版本 key 與 TTL）；
② 背景 `fetch(..., {cache:"no-store"})` 重新驗證；③ 合併時 API 回空也不把畫面清掉，等真資料到了再換。
API 端加 `Cache-Control: private, stale-while-revalidate=<秒>`。範例：`jci_taipei_website/lib/jci-inbox-cache.ts`。

## 紅線

- 零彈窗：不准 alert/confirm/prompt/window.open（`zt-popup-gate.py gate <repo>` 出貨前跑）。
- 不碰別人的正式環境（技能 browser-login-handoff 第 0 步）；部署走該 repo 的 ship 流程。
- 外部設計檔只取 MIT／Apache 授權的內容，並在檔頭註明來源。

## 2026-10-16 實測效果

- 全艦基線（`ui-guideline-lint --summary`）：ai_accountancy 127、ai_metadata 85、ai_ziyaoastro/frontend 50、
  ai_darkhero.html 34、jci_taipei_website 31、ai_nuwa 26、ai_hgame 24、ai_eatery 19、ai_demo 16、ai_heartlink 10、
  ai_theater 10。
- 內帳 App（`ai_accountancy/apps-script/Index.html`）套用第 4 步：53 → 0（連結 37 個 label、18 個 aria-label、
  3 個 alt、恢復縮放、加 reduced-motion）；無障礙樹裡欄位從無名稱變成「日期」「Email」「密碼」等。
- 第 5 步在 375px 截圖抓到 lint 抓不到的問題：標題「雨田國際」被擠成一字一行（改版前就有）；修正後不換行、
  無橫向捲動。已部署 GAS @v5（commit ff8ef10）。

## 2026-10-16 全艦清零（「Bring fleet frontends to zero UI-guideline findings」）

- lint 範圍只算出貨的 UI 原始碼：`fixtures`（擷取的第三方頁）、`_temp`、`.profiles`/`chrome-data`、`runtime`、`output`
  （產生的報告與圖庫）不算。產生器產出的頁面要改產生器（例：入口網頁改 `_skill/engines/hub-portal-gen.py`、
  lilith 頁改 `ai_metadata/person_page.py`），不只改產出檔。
- `ui-guideline-lint.py --fix` 只做安全修正（連結 label、placeholder→aria-label、alt=""、恢復縮放、reduced-motion），
  其餘要人判斷；改完一定跑該 repo 的 tsc／build（2026-10-16 舊版 fixer 曾把 aria-label 寫進 JSX 的 `=>`，tsc 抓到，已修並加測試）。
- 結果（前→後）：ai_metadata 32→0、ai_ziyaoastro 50→0、jci_taipei_website 31→0、ai_accountancy 68→0、
  入口網頁 ai_darkhero.html／ai_master.html 68→0、ai_heartlink 10→0、ai_theater 10→0、ai_eatery 7→0、ai_demo 1→0。
  驗證：ziyaoastro astro build 12 頁、jci／heartlink tsc 0、ai_metadata pytest 73 passed、各頁 inline JS `node --check` 通過。
