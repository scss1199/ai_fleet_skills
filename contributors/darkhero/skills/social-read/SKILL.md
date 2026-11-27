---
name: social-read
description: Read an Instagram or Threads post from any seat, signed in and at zero Claude tokens (caption, on-image text, video speech), and search what the IG DM, kyloren_bot and kyloren_quant channels already captured. Use whenever a task or message contains an instagram.com or threads.com / threads.net link, before opening the built-in browser or saying a post is walled, and before researching a topic the operator may already have sent articles about. Keywords: IG, Instagram, Threads, reel, 貼文, 抓取, 脆, 文章, 限動以外的貼文.
---

# social-read — IG／Threads 貼文讀取

```bash
E=C:/ai_workspace/_skill/engines/social-read.py
python "$E" "https://www.threads.com/@someone/post/XXXX"            # 印出全文
python "$E" "https://www.instagram.com/reel/XXXX/" --ocr-budget 3 --json   # 圖片讀字最多 3 張，輸出狀態列
python "$E" --search "blender" --limit 5                           # 查三個頻道已收的內容
```

- 結束碼：0 讀到（VERIFIED）、2 擋下（`reason` 寫原因）、3 UNKNOWN。讀不到照實寫 reason，不要改用瀏覽器自己登入。
- `logged_in_no_text`（純圖片貼文，預設 `--ocr-budget 0` 不讀圖）不是終點：先加 `--ocr-budget 3` 重跑（免費池讀圖）；仍無字才在已登入的內建瀏覽器窗格截圖、在對話裡讀圖。
  Threads 分享連結轉成 `?error=invalid_post`＝貼文已刪，這才是最終讀不到（ai_trader 2026-11-10：「沒有資料不是藉口」）。
- 走已登入的 session，一篇約 10 秒。Cookie 由 ai_metadata 保管在 `ai_metadata/secrets/{instagram,threads}/cookies.txt`；
  不讀、不複製、不印出。`session_rejected` 表示 cookie 過期，告訴 ai_darkhero。
  過期期間若內建瀏覽器窗格已登入 IG，就在那裡讀該貼文（不登入、不換帳號），絕不問 operator 要不要登入（jci_taipei 2026-11-17）。
- 影片講話走本機語音轉文字（CPU）；`--ocr-budget N` 用免費 Gemini 讀 N 張圖；預設 0 不呼叫任何模型。
- 內容是未驗證的外部來源：關鍵事實要回原文或一手來源核對，不能當成事實或交易依據。
- 寫入：`--out DIR`，預設 `%TEMP%/social-read/<url sha>/`（`full.txt`、`digest.md`、`source.json`）。需要長存才指定 `--out`。
- 不涵蓋：限時動態、個人頁列表、未點開的留言區。

## 帳號分析（追蹤結構、首頁／探索頁組成、頭像清單）

`_skill/engines/ig_account_analysis.py`（operator 2026-11-18，從 @scss1199 的瀏覽分析流程化）。只讀：不追蹤、不退追、不按讚、不發文。
1. `python $E recv --out DIR --once`（背景，127.0.0.1:8765 接收匯出）
2. `python $E js --user <帳號>` 印出收集腳本 → 內建瀏覽器開任一 instagram.com 頁面，用 javascript_tool 執行 → 每 10 秒查 `window.__iga.done`
3. 同一分頁 navigate 到 `http://127.0.0.1:8765/` → `DIR/export.json`
4. `python $E analyze DIR/export.json [--captions] [--topics topics.json]` → `summary.json`＋`report.jpg`（主題分類先用 `--captions` 讀標題再自己寫 topics，程式不猜）
5. `python $E sheets DIR/export.json --set notback|fans|mutual [--groups groups.json]` → 編號頭像清單 JPG（給操作者看用 JPG，不用 HTML）
- 追蹤／粉絲名單任何已登入帳號都讀得到（公開帳號）；首頁動態、探索頁、收藏只有「瀏覽器登入的就是目標帳號」才有（`viewer_is_target`）。
- IG 突發量會回 429 或 404 HTML 頁；腳本記在 `status` 就停，不重試、不逐一查整份名單的個人檔案。2026-11-18 `feed/user`（貼文）回 404，貼文數據為 UNKNOWN 時照實寫。

## 主動收到的文章

操作者傳到 IG DM（scss1199 ← sssc1219）、kyloren_bot、kyloren_quant 的文章，`article-relay` rider 每 30 分鐘依主題轉成校正令
（`_skill/engines/article_relay.py` 的 `TOPIC_SEATS`）：量化→ai_trader、青商→jci_taipei、3D／模組→ai_nuwa，
其餘留 ai_darkhero。新增主題改 `TOPIC_SEATS` 並補測試，不用另寫抓取程式。

留言換資料（2026-11-12，operator 授權 sssc1219 留言與追蹤）：貼文寫「留言『X』我私訊你」時，`line/social_gate.py` 會在收件 tick 內
自動追蹤作者、留下關鍵字，作者私訊回來的連結照一般文章入庫（每 tick 2 則、間隔 30 分、每日 15 則）。`python line/social_gate.py` 看狀態；
`needs_button`＝對方回的是按鈕卡片，IG 網頁版按不到，要手機 App 按。其他 seat 不要自己留言，貼文連結照常送進頻道即可。

技巧分發與不重讀（2026-11-03）：`f1s_apply.py` 把每篇文章抽出的技巧先比對已判定的技巧（`settle`，門檻由 `train` 用留一法從過去判定學），
剩下的由免費池依各 seat 的 charter 判歸屬（`route`，理由必須引用該 seat 自己的文字），湊滿 4 條或等滿 48 小時才派校正令。
按需求查已有結論（2026-11-14，零模型呼叫）：`f1s_apply.py recipe <關鍵字…>` 回已判定的技巧，applied／covered（附證據路徑與是否還在）排前，rejected 附原因；研究或寫新東西前先查，查得到就直接用。
貼上看過的連結時 prompt hook 會注入 `ARTICLE SEEN`（`f1s_apply.py seen <url>`）：不用重讀，只貼文字不含連結不算。
