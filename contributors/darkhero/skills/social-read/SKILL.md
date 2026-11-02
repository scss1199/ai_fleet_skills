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
- 走已登入的 session，一篇約 10 秒。Cookie 由 ai_metadata 保管在 `ai_metadata/secrets/{instagram,threads}/cookies.txt`；
  不讀、不複製、不印出。`session_rejected` 表示 cookie 過期，告訴 ai_darkhero。
- 影片講話走本機語音轉文字（CPU）；`--ocr-budget N` 用免費 Gemini 讀 N 張圖；預設 0 不呼叫任何模型。
- 內容是未驗證的外部來源：關鍵事實要回原文或一手來源核對，不能當成事實或交易依據。
- 寫入：`--out DIR`，預設 `%TEMP%/social-read/<url sha>/`（`full.txt`、`digest.md`、`source.json`）。需要長存才指定 `--out`。
- 不涵蓋：限時動態、個人頁列表、未點開的留言區。

## 主動收到的文章

操作者傳到 IG DM（scss1199 ← sssc1219）、kyloren_bot、kyloren_quant 的文章，`article-relay` rider 每 30 分鐘依主題轉成校正令
（`_skill/engines/article_relay.py` 的 `TOPIC_SEATS`）：量化→ai_trader、青商→jci_taipei、3D／模組→ai_nuwa、遊戲開發→ai_hgame，
其餘留 ai_darkhero。新增主題改 `TOPIC_SEATS` 並補測試，不用另寫抓取程式。
