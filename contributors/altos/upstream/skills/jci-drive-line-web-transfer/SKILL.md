---
name: jci-drive-line-web-transfer
description: >-
  jci_taipei route map for moving files and content between LINE, Google Drive, the local repo,
  heavy-compute hosts and the website (jci-taipei-website / GAS jci_taipei_70), plus the Google
  credential split and access probes behind it. Pick the engine per direction, run it dry first,
  read the destination back. Use in jci_taipei whenever a task moves meeting files, LINE uploads,
  roster/registry data, IG assets or website content across LINE / Drive / web, or when a Drive or
  GAS call says "Requested entity was not found", invalid_secret or 403.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: names-only
    scheduler: session
    token_budget: low
parent_skill: browser-login-handoff
---

# jci-drive-line-web-transfer — LINE ⇄ Drive ⇄ 網站 傳輸路由

所有指令在 `C:\ai_workspace\jci_taipei` 跑。三個節點各做什麼看 `DATAFLOW.md`（Drive 負責流動、Git 負責版本、
重運算只在 darkhero／altos）；本技能只回答「這個方向用哪支引擎、用哪把憑證、怎麼讀回」。

## 0 範圍與紅線

- 只動 jci_taipei 自己的 LINE OA、Drive 資料夾、網站。別的座位或已交接的專案不碰（`browser-login-handoff` §0）。
- 不印 secret／token 值；vault 只說檔名與 key 名。
- Drive 只做 trash，永久刪除是 operator 親手的事。`drive_trash_files` 能 trash 任何 id：只餵剛從清單讀到的 id，
  不用推算出來的批次，送出後逐一讀回。
- LINE 不能列歷史群組檔：要 webhook 存下的 `message_id` 或本機副本；不准爬 `manager.line.biz`。
- 會寫入的引擎先跑 dry-run（不加 `--apply`／`--push`），看清單再寫。

## 1 路由表（每列都已對過引擎參數）

| 方向 | 引擎 | 憑證 |
|---|---|---|
| LINE 檔案 → Drive 會議夾 | `python _line/line_file_to_drive.py --code <c> --message-id <id> --filename <f> --nth <n>`（或 `--local <path>`） | LINE token + clasp 權杖 |
| LINE 漏掉的檔案 → 撈回 | `python _line/line_oa_recover.py --code <c> --list`，再 `--message-id <id> --download-dir <d>` | LINE token |
| LINE webhook 收件匣（已存到 Drive） | 技能 `line-oa-ingest`；GAS `line_inbox_append` 寫入 | GAS secret |
| LINE OA 收到的錄音／簽到 → IN 夾 + 工單 | `python _line/line_oa_intake.py --code <c> --date <d> --meeting-no <n> --audio … --signin …`，確認後加 `--apply --enqueue` | clasp 權杖 |
| 本機原料 → Drive IN 夾 + `_jobs` 工單 | `python _line/meeting_intake.py --code <c> --date <d> --meeting-no <n> --from <dir>`，確認後加 `--apply --enqueue` | clasp 權杖 |
| Drive `_jobs` → 重運算 → OUT 夾 | `python _line/meetings_web_job.py --poll`（單場：`--code --date --meeting-no --process-file`） | clasp 權杖 |
| repo 鏡像 ⇄ Drive | `python _line/sync_drive.py push [--only <rel>]` / `pull` / `sync` | clasp 權杖 |
| IG 素材 → Drive | `python _line/ig_push_drive.py --term <t>`，確認後加 `--push`（授權說明 `--help-auth`） | 見 `--help-auth` |
| Drive → 網站顯示 | GAS GET `website-drive-list&folderId=<id>`、`website-workspace`、`website-committees`、`website-events`；網站重建 `python ztm.py website` | 公開 GET |
| 網站 → Drive（名冊／registry） | Vercel 呼叫 GAS `website_registry_save`（`GAS_WEBAPP_URL` + `GAS_WRITE_SECRET`，技能 `jci-ztm-deploy`） | GAS secret |
| Drive 整理（搬／改名／共用／trash） | `_line/gas_client.py` 的 `post({"op": "drive_move_files", "secret": vault_secret(), "files": [{"id":…, "destFolderId":…}]})`；`drive_rename_files` 用 `files:[{id,name}]`；`drive_share_files`／`drive_unshare_files` 用 `shares:[{id,email,role}]`；`drive_trash_files` 用 `ids:[…]` | GAS secret |

資料夾 id 的 SSOT 是 `jci_taipei_70/meetings_folders.json`，不要手抄 id。

## 2 憑證分工（2026-10-16 實測）

| 憑證 | 在哪 | 能做 | 不能做 |
|---|---|---|---|
| clasp 權杖（scss1199） | `~/.clasprc.json` | `drive.file` + `drive.metadata.readonly` + `script.*`：讀任何檔案的資料、寫自己建立的檔、推 GAS、部署 | 改／移／還原別人建立的檔（403） |
| GAS 網頁版 jci_taipei_70 | `jci_taipei_70/gas_project.json` 的 `webapp_url` | 以擁有者身分完整讀寫 Drive（上表 `drive_*`） | 沒帶 secret 的寫入一律 `invalid_secret` |
| GAS 寫入 secret | vault `_secrets/jci_taipei/gas.env` 的 `HELPER_APPEND_SECRET`（`gas_client.vault_secret()` 讀，不印） | 呼叫端放進 body 的 `secret` | 輪替看 `_line/RUNBOOK-gas-secret-rotation.md` |
| LINE channel token | `line/.env`（只看 key 名） | Messaging API 取檔、推播 | 列歷史訊息；群組成員 ID（403，只拿得到人數與發過言的人） |
| 會員名冊 sheet（GAS，2026-10-22 實測） | `_line/sync_members_to_sheet.py` 的 `push_via_gas(rows)`：op `merge_member_roster` + `overwrite_roles: True`；讀回 op `read_roster_tab` | 非空值覆寫 姓名／綽號／LINE／IG／Google SSO／職務（`RosterSheetMerge.gs` 的 `ROSTER_OVERWRITE_COLS`）；結束職務＝寫一段已結束的生效時段（例 `20260101-20260722`） | 空值不會清欄（只有 備註 可清）；Sheets API 不可用（Drive OAuth client 在 scss1199 看不到的專案），不要去開，也不准用瀏覽器直接改正式 sheet |
| 網站的 Drive OAuth refresh token | `jci_taipei_website/.env.local` 的 `GOOGLE_DRIVE_*`（只看 key 名） | Drive API PATCH registry 夾（`access_bindings.json`、`sso_allowlist.json`）並讀回 | 其他資料夾 |

clasp 權杖做不到的寫入 → 改走 GAS `drive_*`；兩者都不行才是登入問題（第 4 步）。
宣稱某條寫入路徑「做不到」之前，先 grep 那個 handler 有沒有這個欄位／op（2026-10-22 沒讀
`RosterSheetMerge.gs` 就以為 GAS 不能改 姓名，改走瀏覽器編輯正式 sheet，差點整張選取覆寫）。

## 3 讀回才算完成

- Drive：`website-drive-list&folderId=<目的夾>` 或 Drive API `files?q='<夾>' in parents` 看到檔名與大小。
- 會議夾：`manifest.json` 與會議 JSON 的 `agenda_url` 已更新。
- 網站：GET 正式頁（`https://jci-taipei-website.vercel.app/...`）看到新內容；沒讀回就寫 UNKNOWN。

## 4 找不到檔案／登入／授權

- 唯讀探測階梯與「Requested entity was not found」的讀法照 `browser-login-handoff` §1：只代表目前帳號看不到，
  先查垃圾桶（clasp 權杖可查 `files?q=trashed=true`），不准推定已刪除，也不准自行重建 GAS 專案頂替。
- 垃圾桶裡的檔案 `/exec` 照樣回 200，清除後才 404，所以「網頁還活著」不代表檔案沒被 trash。2026-10-16 曾發現
  jci_taipei_70 被 trash（誰做的 UNKNOWN），已還原；同日複查不在垃圾桶、擁有者 scss1199。
- 還原只能在 drive.google.com/drive/trash 做（clasp 權杖 403）：那是上站動作，照 `browser-login-handoff` 交接。
- `~/.clasprc.json` 失效 → 互動式 `npx @google/clasp login` 是使用者的事（終端機分頁，一次）；GAS 新部署的 OAuth
  同意畫面照 `browser-login-handoff` §4b；指令碼屬性裡的金鑰由使用者貼，代理不代填。
