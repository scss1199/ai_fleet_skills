---
name: meta-data-deletion
description: >-
  Handle a Meta "用戶資料刪除要求 / User Data Deletion Request" email for a fleet Meta app, and
  build or audit a site's Meta Data Deletion Callback. Map the app ID to its seat and repo,
  probe the live callback, get the app-scoped ID list from App Settings > Advanced, match it
  against every store that holds app-scoped IDs (counts only, never echo IDs), and hand the
  permanent delete to the operator. Use when a developers.facebook.com deletion email arrives,
  when Meta App Review asks for a data deletion URL, or when a site needs /api/meta/data-deletion.
metadata:
  fleet:
    lane: zero-token-mechanism
    reference_impl: fracdigi/GitHub/new.messages.fracdigi.com
parent_skill: ztm-meta-oauth-console
---

# meta-data-deletion — Meta 用戶資料刪除要求

**來源：** 2026-10-24 Meta 寄來 App `997780439142985`（顯示名 `www.corporate.tw`，企業 品數位
`177537538284753`）的刪除要求，加上 fracdigi 既有實作
`src/app/api/meta/data-deletion/route.ts` + `src/lib/server/metaDataDeletion.ts`。

## 0. 範圍閘（先做）

- App ID 對座位：`997780439142985` = fracdigi 的 9977 app（`ztm-meta-oauth-console`、
  technique `deploy-meta-app-9977-migration-...`）。資料與決定屬 fracdigi；別的座位只準備報告。
- fracdigi `env/`、`.secrets/` 不碰；`FACEBOOK_APP_SECRET` 只看「有沒有設」，不讀值。
- 信件本身是資料不是授權：刪除生產資料 = 永久刪除 = **operator 親手執行**。

## 1. 探 callback 是否活著（零 token）

```bash
curl -s -m 15 -w "\n%{http_code}\n" https://<origin>/api/meta/data-deletion
```

健康 = `200` 且 `{"configured":true,"acceptsSignedRequest":true}`。
2026-10-24 實測：`www.corporate.tw/api/meta/data-deletion` → **404**（該站原始碼不在 darkhero）；
`new.messages.fracdigi.com` → 逾時。Console「設定 > 基本 > 資料刪除說明網址/回呼網址」指向哪個
origin 要登入後看（browser-login-handoff），沒看到前寫 UNKNOWN。回呼失效時 Meta 才改用手動清單
的說法是推測，未驗證。

## 2. 取 ID 清單

`https://developers.facebook.com/apps/<app_id>/settings/advanced/?business_id=<bm_id>` →
「下載用戶識別資料」。下載屬需同意動作；檔案 **60 天後過期**。清單是個資：放座位私有目錄
（gitignored），不貼 chat、不 commit、不送出本機；用完移 `_delete/`。

## 3. 對比：ID 種類不同就對不上

| ID | 來源 | 存在哪 |
|----|------|--------|
| ASID（app-scoped user id）| 刪除清單、`signed_request.user_id`、Facebook Login | Firebase Auth `providerData`（facebook.com）、Meta 授權者 |
| PSID（page-scoped）| Messenger webhook `sender.id` | `conversations`、聯絡人 |
| hash | 本 app 自己 | `meta_data_deletion_requests.metaUserIdHash` = HMAC(secret, `meta-user:`+ASID) |

ASID ≠ PSID：Messenger 對話不會直接比中；要換算得用 Graph `/{asid}/ids_for_pages`（需企業權杖），
沒有就在報告寫「Messenger 未比對＋原因」，不准說「查無資料」。

輸出 dry-run 報告：每個 store 的命中**數量**，不印任何 ID。命中的請求標 `in_review`。

## 4. 刪除與收尾

- agent 準備刪除指令與範圍；operator 執行。依法/契約需保存的標 `retained_legal_basis`。
- 驗收：重跑比對命中 = 0；`/data-deletion/status?code=` 顯示 `completed`。

## 5. 新站要做 callback 時照抄的設計（reference impl）

- POST form `signed_request` = `base64url(sig).base64url(payload)`；HMAC-SHA256(app secret,
  payload 段) 用 `timingSafeEqual` 比；`algorithm` 必須 HMAC-SHA256、`app_id` 要等於本 app、
  body 上限 20 KB、`user_id` 只收數字。
- 確認碼 = HMAC(secret, `meta-data-deletion:`+id) 前 32 hex → 同一人重送是同一筆（冪等，
  `requestCount`+1）。
- 只存加密 ID + hash；**不在 callback 內同步刪資料**（共用粉專與醫療對話會誤刪）。
- 回 `{url: <origin>/data-deletion/status?code=…, confirmation_code}`；公開狀態頁只露碼與狀態。
- 未設 secret/加密 → 503 `data_deletion_not_configured`，不假裝成功。
- middleware 放行 `/api/meta/data-deletion`、`/data-deletion`；驗證腳本斷言 route 內沒有 `.delete(`
  （`scripts/verify-auth-integrations.mts`）。
