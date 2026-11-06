---
name: line-oa-send
description: Send text, any file (PDF, docx, zip, …) or an image to the operator's own LINE (or a named user/group) through the kyloren_bot LINE Official Account, from any seat, with one command and a receipt. Use whenever the user says "傳給我 / 用 LINE 傳 / 用 kyloren_bot 傳 / 傳到我的 LINE", or a task result, report or generated file must reach the operator's phone. Outbound only; for reading saved inbound LINE events use line-oa-ingest.
---

# LINE OA Send (kyloren_bot outbound)

One engine, one credential path. Never write a new push script and never read
`LINE_BOT_CHANNEL_ACCESS_TOKEN` yourself: the dotenv value is dead (401 since
2026-08-21). `_line_auth.LineToken` reuses a valid token or mints a short-lived one,
verifies it belongs to kyloren_bot, and revokes it after the push.

```bash
E=C:/ai_workspace/_skill/engines/line-oa-send-media.py
python $E text "訊息內容"                                   # text
python $E file "C:/path/report.pdf" --text "說明一行"       # any file -> private Drive link
python $E link "C:/path/report.pdf" --text "說明一行"       # any file -> one-shot private link (no Drive, nothing public)
python $E send "C:/path/chart.png" --text "說明一行"        # image shown inline in chat
python $E verify                                            # token + media gate probes
```

`--to` defaults to `owner` (first id in `LINE_ALLOWED_USER_IDS`); pass a LINE user or
group id to send elsewhere.

## Which lane

| Content | Lane | Where the bytes go |
|---|---|---|
| Text, status, short result | `text` | LINE only (≤4900 chars; put long results in a file) |
| Personal or non-image file (CV, PDF, docx, xlsx, zip) | `file` | Owner's own Google Drive, folder `kyloren_outbox`, **not shared**; the link opens only for the signed-in owner |
| Same, but **no Drive** (the operator said so) | `link` | Nowhere: served from the local file through a cloudflared quick tunnel at `/<random token>/<name>`; closes after `--ttl` (1800 s) or `--max-get` (5) downloads; wrong token = 404 |
| Image meant to be seen in the chat | `send` | Public `ai-darkhero.kyloren.workers.dev/media/` (anyone with the URL can fetch it) |

LINE has no outbound document message type, so a file always travels as a link — that is a route choice, never a
reason to refuse. "No Drive" means `link`; it is not a dead end and not a reason to ask again.
Never put a personal document through `send` or any public folder: that lane is public, and since 2026-10-18 the
PROOF publish gate denies a non-image file headed for a public location unless the operator's own prompt says 公開.

## Done means

- Exit 0 and `"ok": true` with `push.status` 200.
- `link`: `link.verified.ok` true (token URL 200, wrong token 404 measured before the push).
- `file`: `drive.md5_match` true and `drive.mime` is the file's real type
  (a PDF shows `application/pdf`, so Drive opens it as a PDF, not as a Word doc).
- Report the receipt path printed as `receipt_path`
  (`_registry/line-media-sends/<stamp>-<kind>.json`).

## Failure map

| Error | Meaning | Fix |
|---|---|---|
| `no_usable_token` | channel id/secret missing or LINE refused minting | check `ai_darkhero/line/.env` key names (names only, never values) |
| `target_unresolved` | no `LINE_ALLOWED_USER_IDS` and no `--to` | pass `--to <uid>` |
| `drive_credentials_missing` | `GOOGLE_DRIVE_*` keys absent | same dotenv; do not fall back to the public `send` lane for personal files |
| `drive_upload_unverified` | md5 or MIME read-back mismatch | rerun; do not push an unverified link |
| push 400/403 | the user blocked the bot or the id is wrong | report it; do not retry in a loop |

Secrets are never printed; recipients appear as sha8 fingerprints in receipts.
