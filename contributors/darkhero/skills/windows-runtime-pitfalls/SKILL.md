---
name: windows-runtime-pitfalls
description: >-
  Fleet-wide runtime lessons reverse-learned from the seats (f1s-reverse-learning, 2026-10-16): Windows
  socket/process/COM traps, stale locks, retry storms, time and data freshness guards, and code-reachability
  traps that each cost a seat real incidents. Use when writing or debugging a local service, daemon, rider,
  watchdog, HTTP handler, singleton helper, git automation, or anything that trusts a clock or a data feed.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
parent_skill: ztm-verify-before-done
---

# windows-runtime-pitfalls — 各座位踩過的執行期坑（F1S 反向學習）

每條都有一個座位真的出過事；括號是來源 memory，細節去那裡讀。

## 行程、socket、COM

- **單例本機服務一律 `allow_reuse_address = False`，啟動前先 health-probe 舊實例。** Windows 的 SO_REUSEADDR 讓多個
  行程同時 bind 同一埠、輪流分流請求：症狀是同一 URL 間歇 404／舊行為、同秒互斥事件；用 `Get-CimInstance Win32_Process`
  按命令列查同名行程。（hub-root windows-so-reuseaddr-multibind）
- **HTTP handler 拒絕請求前先讀掉宣告的 body**（設上限與短 timeout，讀到的不使用）。沒讀完就關閉，Windows 會送 RST，
  呼叫端拿到 10053/10054 而不是 403，看起來像「偶發環境問題」。（ai_trader http-refusal-before-body-read-rst）
- **判斷行程死活時，AccessDenied ≠ 已死。** 權限不足（例：S4U／session 0 起的行程）要當 UNKNOWN，不能據此再起一份，
  否則兩個 daemon 搶同一個 pid 檔一起跑。（ai_trader hubclock-duplicate-daemons）
- **靜默安裝程式會提權後無聲跑好幾分鐘，一般權限看不到也殺不掉；看守要盯安裝目錄或它的 log，不是視窗。** 這台機器
  UAC `ConsentPromptBehaviorAdmin=0`，安裝程式的 `/auto`／`/S` 直接提權不彈窗（零彈窗紅線下這是預期），於是「沒視窗」不等於
  沒在裝、「殺不掉」不等於當機：完成判定用目標目錄出現主程式＋版本檔、或 `%APPDATA%` 下的 profile 資料夾，逾時再回報
  UNKNOWN 附兩者路徑。（ai_trader 2026-10-29 mt5setup.exe /auto 約 6 分鐘無視窗；memory owner-fx-route-20261029）
- **背景 python 會跳「應用程式錯誤」對話框**：CPython 3.12 的 `platform.*` 走 WMI COM thread，機器忙時崩潰 → csrss
  硬錯誤框（短暫、無 Event 1000）。背景程序避免在 import 期呼叫 `platform.machine()/uname()` 這類查詢；零彈窗紅線。
  （ai_trader zero-popup-python-crash-dialog；hub memory pythonw-platform-ver-flash）
- **共用的來源標籤不能歸因呼叫者；指名之前先讀嫌疑方自己的 log。** ai_theater 的 gate 把每個 POST
  /api/subtitle/background 都標成 `ai_theater_background`，2026-10-19 的提案據此指名 load_guard 重新 arm 字幕，
  但 load_guard.log 全檔 0 筆 shed/resume/gate 事件、ladder level 一直是 0——真正的呼叫端至今 UNKNOWN，因為
  gate 的 access log 只走 `logging.debug` 沒落地。做法：每個呼叫端自帶 source（或 User-Agent），服務端把 access
  log 寫到檔案；而「還原」類動作要綁自己那一代的 intent generation，資料裡出現更新的 stop/start 就不再還原
  （load_guard `off_generation`，test_load_guard_ladder_restore）。
- **`python -I`（隔離模式，含 -E）會忽略 PYTHONIOENCODING，stdout 退回 cp950**：印中日文或符號直接
  UnicodeEncodeError。要輸出非 ASCII 的腳本在程式內 `sys.stdout.reconfigure(encoding="utf-8")`，不要靠環境變數。
  （ai_career 1c9ea56；2026-10-21 實測 `-I` 下 `sys.flags.ignore_environment=1`、encoding=cp950）
- **`ctypes.windll.<dll>` 的函式指標全行程共用一份，`.argtypes` 誰最後設誰算。** 兩個模組各自把
  `user32.BeginPaint.argtypes` 設成 `POINTER(自己的 PAINTSTRUCT)`，另一個模組的呼叫就 ArgumentError（同名 Structure
  仍是不同型別）；在 WNDPROC 裡例外被吞（pythonw 沒 stderr），WM_PAINT 永不 validate、訊息迴圈空轉（tray 睡眠
  overlay 執行緒 139.6→2.2 CPU-s／600 s）。共用 argtypes 的結構指標一律 `ctypes.c_void_p`（`byref()` 照用），或用私有
  `ctypes.WinDLL("user32")`。診斷：`py-spy dump --native` 頂端是 NtUserPeekMessage／DispatchMessage，再從別的行程對其
  視窗呼叫 GetUpdateRect（更新區永遠不空）。（ai_darkhero 21550c71 sleep_mode/hub_tray）
- **拖放是跨行程同步 COM 呼叫：drop target 卡住，來源的 Explorer 視窗就跟著死。** `ole32!DoDragDrop` 在來源執行緒等
  目標的 `IDropTarget::Drop` 回傳，期間用 PeekMessage 空轉（~1000–2700 ctxsw/s、15–33% 一核），之後任何打進該執行緒的
  跨行程呼叫（OneDrive COM surrogate、Copilot、設定）全部跟著掛。2026-10-28：PotPlayer 在 Drop 裡做 D3D9 Present，顯示卡
  Arc A310（4 GB、接兩台 3072×1728）顯存 89–90% 時 `NtGdiDdDDIPresent` 永不返回，`TerminateProcess` 後行程變殭屍
  （exit code 已設、3 條執行緒仍在 NtGdiDdDDI* 等待、960 MB 顯存不放），Explorer 資料夾視窗空轉 13 小時。
  診斷順序：IsHungAppWindow／Ghost 視窗 → WCT（要先 `RegisterWaitChainCOMCallback`，否則 COM 外送只顯示 Blocked）→
  dbghelp 小型 minidump 取 RIP（`minidump`+`pefile` 解到 module!export，不需 WinDbg）→ PDH `GPU Adapter Memory` 對
  DXGI 的 dedicated 容量（PDH 的 luid 是大寫十六進位，DXGI 小寫，比對要 lower）。解法：殭屍只有顯示驅動重置
  （Win+Ctrl+Shift+B，**SendInput 注入不被核心接受，要實體按**）或重開機；Explorer 不用重啟，目標一死 DoDragDrop 就返回。
  預防：顯示卡顯存 ≥85% 先警告並列出佔用者。引擎 `fleet-hang-guard.py probe|run|watch`（probe 揪錯 lane 與 stabilize
  穩定 lane 平行；kill／gfx-reset 各自要 operator 旗標）。（ai_darkhero evidence/hang-dnd-20261028）
- **Windows 判定視窗「對齊」看的是 DWM 可見框（`DWMWA_EXTENDED_FRAME_BOUNDS`），不是 `GetWindowRect`。** Win10/11 一般視窗在可見框外
  還有一圈隱形縮放邊框（125% 下左右下各 8 px），兩個看起來貼齊的視窗 rect 其實重疊；Snap Layouts 把框邊放在工作區邊與鄰窗邊上
  （右邊界 exclusive：鄰窗 left == 本窗 right）；自畫邊框的程式（LINE／Qt）框 == rect。所以量與搬都用框座標，搬動時再用「該視窗自己
  的」邊框偏移換回 rect，resize 後偏移可能變、搬完讀回不符就修正一次；只碰非最小化、非最大化、未 cloaked（`DWMWA_CLOAKED`）、
  有標題、非 tool 的他程視窗。通則：要替 OS 補一個它本來就有判定的行為（對齊、焦點、閒置），先量 OS 自己怎麼判、沿用它的模型，
  不要自創門檻。（ai_darkhero 68c2fa21 tray/window_snap.py + tray/tests/test_window_snap.py）

## 重試、鎖、排程

- **重試一定要有上限與冷卻**，而且要讀回執行證據：一條永遠到不了 DONE 的鏈被 watchdog 每 5 分鐘重跑，一天 50–65 次、
  每次都登入外部服務。改了「判定」也要檢查它對重試迴圈的副作用。（ai_trader preopen-chain-retry-storm）
- **會被逾時殺掉的週期步驟，開工前先寫 STARTED 狀態並對同一輸入指紋設冷卻**：否則子程序每次被 kill、狀態從沒寫入，
  下一輪又從頭重跑（ai_trader strategy_lineage 300 s 逾時、一小時被殺 3 次）；預算快用完時不要再開新的一天／新的一批
  （news_tone 保留 DAY_RESERVE_S）；前置條件已知不成立（owner 停用的 cockpit）就跳過，不要讓它每輪 rc=1。
  （ai_trader workflow-audit-20261020）
- **「報價過期」「來源斷線」這類狀態是一段 episode，記一次進入＋一次恢復（附持續秒數），不是每次輪詢記一列**：
  0.5 秒一輪的迴圈在紐約收盤後 12 分鐘寫了 247 列同一句話，真正的事件（何時斷、斷多久）反而要事後數列才知道。
  做法：狀態機保存「目前是否在 episode 內」，轉入時寫 `*_begin`，轉出時寫 `*_end` 帶 `duration_s`；同一狀態重複輪詢
  不寫。待機中的長迴圈另外每 5 分鐘寫一列 `heartbeat`（帶關鍵計數），看守才分得出「閒置」與「死掉」——這是
  「盯每段都會長的檔」（時間與資料新鮮度）那條的寫入端。（ai_trader 79ecb9ee3；sinopac-trading-system/scripts/fx_scalp_runner.py `last_heartbeat`）
- **多個實例共用同一個帳戶／目錄／佇列時，收尾只動自己建立的東西，乾跑永不執行會改狀態的分支**：共用的標籤
  （MT5 magic、comment、檔名前綴）只證明「同一支程式」，不證明「這個行程」；收尾（視窗結束平倉、清理、退役）用本行程
  自己記下的 ticket／id 集合判定歸屬，另一個實例開的一律不碰。ai_trader 2026-10-29：一個 dryrun runner 在視窗結束時把
  另一個 demo runner 剛開的倉平掉（−0.26 AUD），修法＝`own_tickets` 集合＋`mode == "dryrun"` 不平倉（c8d33f58d）。
  排程 rider、清理腳本、雙向同步的「刪掉對方多出來的」同理。
- **呼叫有額度的遠端（Drive、LINE、Workers、免費池）的週期 rider，先比本機變更指紋，沒變就零遠端呼叫直接結束**：
  沒有變化的一輪也去 list／fetch，額度就這樣燒光。參考實作 ai_photo `src/ai_photo/drive_sync.py` 的
  `local_state()`／`last_full()`，測試 `tests/test_drive_sync.py::test_unchanged_folder_spends_no_rclone_call`。
  （ai_photo 2923431；2026-10-27 Cloudflare 全帳號額度耗盡事件）
- **大多數時間是空的 outbox 不用短週期 rider 輪詢；寫入它的程式在結束時自己觸發消費者，rider 只當稀疏備援**：
  operator 2026-10-29（ai_photo）「東西都確認傳完後就全空不用留任何資料夾 並讓 tray 不用一直像白癡偵測這裡」。
  做法：①來源目錄唯讀（只讀、不增不減、交付時回報它的檔數沒變）；②每個會寫 outbox 的指令結束時 `kick()` 一次隱藏
  背景 `run --until-empty`（CREATE_NO_WINDOW／pythonw，零前景），反覆上傳→逐檔比對（size+md5）→搬到確認區，直到
  outbox 清空，連它留下的空日期資料夾也 rmdir（永遠不動 outbox 本身）；③outbox 沒檔就在任何遠端呼叫之前以 `empty`
  結束，kick 對空 outbox 不起行程；④HubClock rider 只補中斷的上傳，週期從 10 分鐘放到 6 小時（縮短週期才需要授權）。
  參考實作 ai_photo `src/ai_photo/drive_sync.py` `kick()`／`prune_empty()`，測試 `tests/test_drive_sync.py::
  test_uploaded_outbox_ends_empty_with_no_folders`、`::test_kick_starts_nothing_for_an_empty_outbox`、
  `::test_until_empty_repeats_until_the_outbox_is_empty`（ai_photo 6d28ac9，95 passed）。
- **後端所有資料庫存取共用一把鎖時，先把「等鎖」和「用鎖」分開計時，再把持鎖期間的遠端寫入改成寫後（write-behind）**：
  ai_ziyaoastro 2026-10-29 正式站 12 個同時請求，有的自己只用 DB 1 ms 卻排了 4–5.6 s，因為 `/fate` 持鎖 2.7 s、
  每日第一次 `/daily` 持鎖寫遠端 Turso 2.6 s。做法：`_shared_get_conn` 量 `db_wait` 與 `db_use` 各自放進
  Server-Timing（沒有這兩個數字就只能猜是後端慢還是排隊）；純快取表（period／ai_text cache）先寫行程內鏡像
  （有上限）立即回傳、背景執行緒落庫、讀取先查鏡像；寫完要立刻讀回的寫入（profile refresh）保持同步，本機 sqlite
  路徑不變。修後 12 個並發 `db_wait` 全 0 ms；剩下的慢是 CPU 計算（流年 8–16 s）而不是鎖，要分開報。
  （ai_ziyaoastro 95a6f4f，`backend/app/storage/db.py`，`tests/db_cache_write_test.py`，全套 352 passed）
- **git 128 先查殘留 `.git/index.lock`**：確認沒有長命 git 行程後改名成 `index.lock.stale-<時間>.MIGRATED-bak`（不刪）。
  殘鎖會讓排程備份「靜默不 commit」好幾天。（ai_trader git-index-lock-stale）
- **把 runtime 資料移出 git 追蹤後，checkout／reset 到舊 commit 會用舊版覆寫正在用的檔案**（資料庫、kill flag）；
  移出時列出所有還追蹤它的分支並警告。（ai_trader runtime-untracked-checkout-hazard）

## 時間與資料新鮮度

- **「只在有變化才推」的通知閘，撤回也是新聞**：閘的鍵不是「今天要做的集合」，而是「上次已告訴使用者要做的集合」。
  上次說了要做的項目，在使用者還能行動的窗口內掉出集合＝撤回，必須推送並寫明撤回原因；項目只是窗口到期而消失則不推。
  空集合不等於沒事：前一晚說「申購」、早上條件不成立卻因「今天沒東西要做」而靜音，使用者會照舊指令行動。
  做法：持久化上次推送的集合＋每項窗口截止；每輪算 retracted＝上次集合 − 本次集合 且 now＜窗口截止，retracted 非空就推，
  測試要同時覆蓋「撤回有推」與「到期沒推」。適用每個 seat 的 LINE／通知閘。（ai_trader 3a6ab78cd：東森 2614 截止日早上
  spread +10.9%→+9.0% 掉出申購名單卻無訊息；subscription_apply_list.py run() retracted／was，tests/test_subscription_apply_list.py）
- **時間窗口／黑名單時段要管「已持有的狀態」，不只擋新動作**：閘放在「有沒有持倉」判斷之後，只會擋進場，
  窗口前最後一刻進的單會被抱著跨過窗口（ai_trader fx_scalp_runner 排除 21、0 UTC 的 rollover，20:30 UTC 進場抱到 21:00 後：
  付了 swap、連吃 3 次 60 s 報價停滯，excluded_hour 計數仍是 0）。規則：設定了任何時間窗口（排除時段、休市、維護、黑名單）
  就要三件都做——(a) 窗口內不開新動作；(b) 行程自己擁有的狀態（持倉、鎖、租約、未完成批次）在窗口開始前一段 lead time
  內主動解除，並寫一列有原因的紀錄（`excluded_close`）；(c) 一個測試把狀態建立在窗口前、推進時鐘跨過邊界，斷言狀態已解除。
  「窗口內沒新動作」的測試過了不代表窗口有效。（ai_trader 956eb20c8：`seconds_to_excluded_hour()`＋`exclude_lead_s`，
  tests/test_fx_scalp_runner.py test_held_position_is_flattened_before_the_excluded_hour_starts；memory owner-fx-route-20261029）
- **事件時間與收到時間比對前先確認本機時鐘已同步**（W32Time 可能幾週沒同步）；時鐘慢會讓「收到早於事件」這種檢查
  靜默拒絕所有訊號，而且被去重的記錄把痕跡吃掉。（ai_trader orb-missed-signal-clock-skew）
- **行情／事件來源的時間戳是對方伺服器的時鐘，不是 UTC**：GoMarkets-Demo 的 MT5 `tick.time` 比 UTC 快約 3 小時，拿 UTC
  現在時間減它，每一筆都成了「未來」或永遠新鮮。做法：連線後用看到的最新一筆學 offset＝server_time − utc_now，之後只有
  更新的 tick 才把 offset 往上修，新鮮度＝(now＋offset) − tick.time，超過門檻才算過期；換伺服器／重連就重學。
  （ai_trader 25920a3a5，sinopac-trading-system/src/services/mt5_broker.py `_server_offset`）
  寫出的資料也一樣：自帶時鐘的來源（MT5、shioaji tick.datetime、交易所 CSV）先減掉 offset 才能標 UTC，offset 四捨五入到
  900 秒時區格線並寫進每份 receipt（`server_offset_s`）；offset 未知就 fail closed（raise／非零 exit），永不預設 0——
  `or 0.0` 正是 MT5 bar 被標成 +00:00、時段全晚 3 小時的機制。只寫 UTC 卻沒有 offset 欄位的 receipt 一律當 UNKNOWN。
  （ai_trader 398e7be30、cfb8b068d，scripts/pull_mt5_history.py `learned_offset_s`，tests/test_pull_mt5_history.py）
- **檔案內嵌的時間戳記可能是匯出時間，不是事件時間**：LINE 匯出的 m4a 四軌 creation_time 全落在 22:08:03–22:08:15
  （匯出那一刻）。這類時間只拿來和可信來源（簽到表、議程、使用者給的時間）比對、超過門檻就標待審，永遠不直接寫成事實。
  （jci_taipei jci-minutes-web-pipeline-benchmark 2026-10-23）
- **外部資料源過期時，下游要明確進入保守模式並把原因寫出來**，同時記錄「上游修好後多久才會生效」（節流快取）。
  （ai_trader pcr-iv-stale-feed-blocks-longs）
- **接上既有資料源的新消費者，先查寫入者還活著**（index.json last_run、rider 清單、owner 退役紀錄）再寫；輸出帶資料年齡與
  stale 旗標，研究／報告類只標示不擋（交易決策類照上一條進保守模式）。門檻取該市場最長休市日數（台股農曆年約 10 天），
  否則長假被誤報、收集器停掉卻靜默。只寫 pool_through 之類的截止日不算新鮮度標示。（ai_trader first_touch 1ada5c877：
  1 分 K 收集器 10-20 已退役，MAX_POOL_AGE_DAYS=10，報告 pool_age_days 9）
- **非預期斷電（Kernel-Power 41）後，斷電前幾分鐘寫的檔案可能大小正常但內容全是零**：只寫一次的資料檔要記 sha256
  journal，斷電後全檔比對找壞檔，壞檔改名 `.CORRUPT-bak` 重抓，不要信任檔案存在或大小。預防：原子寫入在 rename 前要先 fsync——寫 `.part`、`flush()` + `os.fsync()`，
  再 `replace`；少了 fsync，斷電時 rename 已落盤而資料沒有。附一個重算 sha256 對 journal 的 verify 指令。
  修一個寫入再 rename 的 helper 時，要全 seat 搜 `os.replace`／`Path.replace`／`os.rename`，把每個複本都修掉；
  優先修「檔案已存在就跳過」的只寫一次存檔（斷電留下的全零檔永遠不會被重寫，來源只給當期就永久遺失），
  每個 tick 重寫的狀態檔下一次寫入就自癒，熱路徑可不加 fsync 省延遲。
  （ai_trader v30：3,238 檔壞 2；commit ee5e6e523 matrix_data_pull._save；8b234c3ac 再修同 seat 三個複本）
  只寫一次的存放區出貨規範（ai_trader 44ce255ef，F1S 2026-10-29 吸收）：就地寫目標的 writer（`np.savez_compressed(目標)`、
  `Path.write_bytes`）沒有 rename，靜態掃「寫＋rename 的函數」看不到它，斷電一樣留全零檔——只寫一次的存放區一律走同一個
  tmp→fsync→replace helper；同一支 CLI 附 `verify` 子命令：journal 每列記 sha256，verify 全檔重算、列 mismatch／missing／unjournaled、
  有壞檔 exit 4；掃描再加一條：對 `glob('*.npz'/'*.gz')` 且 `exists()` 就跳過的存放區，同模組必須有 verify
  （範本 sinopac-trading-system/tests/test_fsync_before_rename.py＋test_pull_fx_ticks_verify.py，2026-10-29 hub 重跑 8 passed；
  實測 histdata 164/164、dukascopy 4/4 相符）。工具陷阱：Claude Bash 的 heredoc 會把雙反斜線收成單反斜線，Python 原始碼字串裡
  「反斜線 x00」就變成真 NUL 進檔（SyntaxError: source code string cannot contain null bytes）；要產生該轉義文字用 Write 工具或
  `chr(92)+'x00'` 拼。
- **斷電後 append-only 的 JSONL／log 尾巴會留一段 NUL，下一列直接黏在 NUL 後面**：讀取端每列先 strip `' \t\r\n\x00'`，
  仍 `json.loads` 失敗的那列跳過（計數，不 raise）；寫入端 append 前先讀最後一個位元組，不是 `\n` 就先補一個換行，
  新列才不會黏在殘骸上。例外：設計釘住的 gate 檔讀取端不得默默改寬容，要另案提出。
  （ai_trader 2026-10-27：17,065 個 runtime 檔有 7 個帶 NUL 段，3 個 JSONL 有有效列黏在後面；commit 00d2d65f8）
- **伺服器看不懂的參數會靜默退回預設值，不會報錯**：例如 TPEx `date=yyyy/mm` 不解析就回當月資料。新接的查詢要用
  兩個不同參數值比對回應確實不同；盤中檔的第一列也可能是前一日收盤（TWSE 5 秒檔 09:00:00 列），差異集中在第一個
  檢查點時先查這列。（ai_trader ipo-auction-source、v30）
- **「ok、0 列」不等於完成，欄位按名稱不按位置，API 列得到的才算存在。** 來源對假日回 ok＋0 列，要另一個來源也說
  休市才記完成；官方行事曆說開盤但兩個來源都沒資料＝臨時休市，正確答案是空。數字欄出現文字（除息／除權、`---`）記
  NaN（未知），不是 0。規劃多年回測前先查 API 的合約列舉範圍：shioaji `Contracts` 只列目前掛牌的 TXO，到期合約不在裡面，
  選擇權多年盤中歷史在券商 API 不存在，只能前瞻收集——先 1 次登入＋2 次 kbars 探測再排計畫。（ai_trader v30 2026-10-24）
- **看守長任務要盯「每段都會長的檔」**（逐段 JSONL、心跳檔），不要盯「整塊完成才寫一行」的 run_log：ai_trader
  2026-10-29 長錄音轉文字 run_log 25 分鐘沒新行，其實 8 個程序都在寫，盯 run_log 就是 stale 誤報。
- **兩個來源互相同步，逐項以最新狀態與時間戳判定，兩個方向都要寫，衍生檔跟著來源的刪除走。** 判定順序
  搬移→重複→新增→刪除；哪邊是「最新」看那一項的修改時間，不是整份檔案誰新。一個方向停了幾天的真正原因是
  「以為寫不進去」（Chrome 的加密書籤檔）——「做不到」要先在對方同款機制上實測過才算（Edge 前一天已驗證：移開加密副本就讀明文檔），
  沒測過的不可能是 UNKNOWN 不是限制。來源項目被刪，對應的衍生檔（下載資料夾、快取）要搬進 `_delete/<日期>-…`，永久刪除留給 operator。
  找孤兒衍生檔用帳號名或編號**完全比對**，名稱片段配對（`karina`、`twice`）會把舊資料夾誤判成還有來源。
  （ai_metadata 2026-10-27：Chrome 佇列 144 筆＝移除 23／新增 42／去重 75／空夾 4，commit 5d213312 58 測試；
  `__beauty` 兩個孤兒夾 1,934 檔搬到 `P:\_delete\2026-10-26-deleted-bookmarks\`）
- **衍生儲存（對照頁、快取、索引、分享包）不得比來源大；每次寫出完整輸出前先問「目的地是否已持有同一份」。**
  同一張完整輸出寫兩份（一份進目的地、一份留在對照資料夾）、被換掉的舊版無上限累積、試跑檔與過期的分享壓縮檔沒人回收，
  一個本該不到 1 GB 的索引夾就長到 25 GB。規則：對照頁只留裁切／縮圖和指向目的地的路徑或 sha256，完整輸出只寫目的地一份；
  被取代的版本與過期分享包搬進 `_delete/<日期>-…`（永久刪除留給 operator）；每批收尾量 `du` 衍生夾與來源夾的比值寫進回報，
  衍生夾比來源大就是缺陷不是正常。（ai_photo 2026-10-27：`_photo_index` 25 G 中 review\compare 17 G＝_pick 副本 7.31 G
  ＋_prev 7.40 G＋試跑 1.09 G，share 7.5 G；抽 5 張 sha256 全同；commit bbd9d92／039fc79，57 測試）

## CPU 配額與批次負載

- **新加的 OCR／STT／影像批次工作先限執行緒，再量「每幀／每分鐘成本」，量完才放大。** onnxruntime 類引擎
  （rapidocr_onnxruntime）預設 intra_op 執行緒＝全部核心：一個 OCR 行程吃掉 27 核，同機的 faster-whisper 與 4 條
  STT lane 每 10 s 只拿到 5 CPU-s、25 分鐘音訊跑了 83 分鐘，看起來像「模型卡住」。一律 `RapidOCR(intra_op_num_threads=4)`
  這類明確上限；懷疑模型慢之前先看 CPU 配額。（hub-root burnin-subtitle-ocr-learning；ai_theater
  scripts/subtitle_burnin_learn.py）
- **psutil 在 Windows 的 O(N²) 陷阱**：`Process.ppid()`、`num_threads()` 每次呼叫都重建整機快照；對拒絕存取的行程
  讀 `cmdline()/cwd()/cpu_percent()` 走慢速拒絕路徑（每次 0.1–0.25 s）。每 tick 掃 ~470 個行程＝O(N²)（allocator 建
  索引 23.1 s、cmdline 全掃 19.8 s）。每 tick 只呼叫一次 `psutil._psplatform.ppid_map()`；執行緒數與「拒絕」的 cmdline
  按行程生命週期快取（拒絕不會變可讀）；`cpu_percent` 只 prime 要讀的列；先用快取的名稱過濾。（hub memory
  tray-process-scan-cost；ai_darkhero 27be6919、e6ed3b33）
  `create_time()` 對受保護行程同樣退回整機快照（每次 0.069 s）：放進 `process_iter([... "create_time"])` 讓冷掃
  15.1 s 裡 10.9 s 花在它身上。只對通過 cmdline 過濾的列才讀；行程存活期間 process_iter 回傳同一個 Process 物件，
  可直接當快取鍵（冷掃降到 4.4–5.0 CPU-s；ai_darkhero 739740e7）。
- **就地退役檔案的佇列目錄（改名 `*.MIGRATED-bak`）會無限長大**：`_registry/ship-queue` 累積 26,138 筆，每次 glob
  找有效檔都是 O(目錄)（每次探測 0.17 CPU-s）。只在目錄 mtime 變動時重列，且變動未滿 2 s 時下次仍重列（檔案時間
  的刻度比連續寫入粗）；退役檔要清掉仍是 operator 的事（不刪紅線）。（ai_darkhero 21550c71 hub_tray）
- **互動／UI 行程（tray）繼承父行程的優先權與 affinity**：在 100% 負載下以 BelowNormal、2 CPU 起來，8 分鐘以上才出
  圖示、選單打不開。啟動時重設成 Normal／全部 CPU，並在任何 CPU allocator 中豁免它；豁免清單放永遠 union 的常數——
  設定檔的清單若「取代」預設清單，會靜默丟掉預設豁免。
- **量每個執行緒的 CPU 用 `Process.threads()` 的 user+system 差值，再對應 `py-spy dump` 的執行緒名稱**；py-spy 的
  wall 取樣含 GIL 等待，會指錯執行緒。
- **逐幀跑昂貴辨識前先用便宜的變化偵測，而且偵測要對準目標區域的特徵。** 整幀灰階差分擋不住動態畫面
  （3061 幀仍要 1858 次 OCR）；改比對近白色字幕遮罩（HSV V≥200、S≤60，縮到 360×58，mean abs diff ≥4 才重辨識）
  降到 277 次、274 s。（同上）

- **加負載先拿 load grant（darkhero，operator 2026-10-24 兩次斷電）**：觸發斷電的是「負載突然加上去」，不是負載高
  （01:12:54 A770 1 秒內 49→150 W，疊在約 165 W 的 CPU 上；比這台機器以前扛過的總負載還低）。所以整套測試、build、
  模型載入、批次轉檔、字幕 lane 這類會加負載的工作，開始前先跑
  `python C:/ai_workspace/ai_darkhero/tray/scripts/load_grant.py wait --owner <seat>/<task> --step <W>`（exit 0 才做；
  或 `load_grant.py run --owner … --step … -- <cmd>`）。放行條件：近 60 s CPU+A770 功率 p90−p10 ≤ 30 W、這一步 ≤ 40 W、
  加上去 ≤ 250 W、距上一次放行 ≥ 20 s、感測紀錄是新的。超過 40 W 的工作要自己分段加，每段再申請；被拒就等，不要硬跑。
  托盤狀態列顯示目前功率與最新一次放行。

## 音訊擷取與通話偵測

- **App 自己挑裝置**（LINE.ini 的 voip_mike_id 指向已拔掉的藍牙耳機，整通電話沒開麥克風）：錄全部麥克風加全部喇叭
  loopback 混音，不要錄「預設裝置」。
- **用 WASAPI session（pycaw）偵測通話**，不要信 ConsentStore LastUsedTime（本機 09-22 起凍結）。只認通話專用 App
  （LineCall.exe、Zoom、Teams）的 render session 且音量表在動，10 s 內 3 次有聲才算開始（一次 blip 錄出 49 s 空檔），
  再用 hold 撐過停頓；App 可能永遠掛著一個無聲的 ACTIVE session。手動開的錄音要能被自動模式接手（忘了關的手動錄音
  擋掉所有自動開始 17 分鐘）。
- **WASAPI process loopback：INCLUDE（單一 App 樹）可靠，EXCLUDE（除了某 App 以外）錄到一半退化成 2 ms 嗡聲**（重現 3 次）
  → 「整台電腦的聲音」用裝置 loopback，App 的部分在下游扣掉。時鐘節拍的 mixer 底下，來源 reader 絕不能自己補靜音。
  逐段定位故障：原始封包 → reader 單獨 → mixer 單獨 → 加併行麥克風 → 分開行程。
- **合成端到端（ffmpeg／PowerShell 佔住麥克風）證明的是機制不是整合**：真實通話觀察到之前，回報要寫清楚驗證的是哪一個。
  （hub memory linecall-asr-findings-20261019；ai_darkhero 7a07eca3、7d5f3f2e、f1d4e1b5、0948c6e8、082c860d）

## 程式可達性

- **判斷死碼要把子程序派工（`python -m pkg.mod`、`scripts/x.py` 字串）、排程 rider 命令、launcher、以及把原始碼當文字
  讀的測試都算進根節點**，只看 import 圖會把正在跑的東西列進清理名單。（ai_trader subprocess-dispatch-breaks-import-graph）
- **反過來，判決後退役研究腳本時不能把測試當根節點**：reachability 工具把 tests/ 當 root，所以只剩自己測試在 import
  的腳本會被算成 reached（ai_trader v29/v30 兩條 NOT_QUALIFIED 線各多留了 4 天）。真正的檢查是「除了自己的測試，還有誰
  import 或 dispatch 它」為空：為空就退役，腳本與它的測試同一個 commit 拿掉，收據與 raw 資料留在 runtime；擁有資料
  store 的 puller（含 `verify` 子命令）不隨研究線退役。（ai_trader 7b9b59da0：6 檔 −1,921 行、unreached 15→13；
  sinopac-trading-system/scripts/code_reachability.py；memory v30-cash-intraday-leadlag-20261024）
- **控制第三方軟體先找它的設定語意（登錄檔／設定檔），不要先做 UI 模擬**；例：PotPlayer 切檔變大小是
  `ScreenFitBySize`。（hub-root potplayer-fixed-window-registry）
- **Claude Bash 工具會把命令文字裡的雙反斜線收成單反斜線，heredoc 的 'EOF' 引號不保護它**：用 heredoc 餵 Python 去 patch
  原始碼時，來源裡的 `\\x00` 落地成真正的 0x00（pytest `source code string cannot contain null bytes`、CreateProcess
  `embedded null character`），`\\.` 變成無效跳脫，正規表示式與路徑字串全走樣，而且同一寫法重修還是錯。做法：要透過
  Bash 產生含反斜線的原始碼，先用 Write 工具把腳本寫成檔案再執行（Write 不收反斜線），或用 `chr(92) + "x00"` 拼；落地後用
  Python `bytes([0]) in data` 檢查有沒有 NUL。（ai_trader 2026-10-29 order #14 連踩三次；ai_darkhero 同日 patch f1s-sources.py
  的 `[ \t]+` 與 PAGE_STUB 正規表示式同樣走樣；memory bash-tool-heredoc-backslash-collapse、bash-tool-quirks）
- **閘門訊號要帶年齡，寫入者死了的「最後一筆」不得永久擋工作**：`_registry/network-signal.json` 的寫入者（ai_network）2026-09-01 停了，它最後一筆 `congested=true`（jitter 81.93ms）讓 garytalks-feed 每 6 小時 0.1 秒就跳出，連續 59 天沒 poll，zt-guard CHECK6 天天紅卻沒人看懂；acquisition_hub 也照同一筆把頻寬打七五折。做法：讀閘門訊號時先算 `generated`／`probe_ts` 的年齡，超過訊號應有的刷新週期（這裡 6 h）就當作沒有訊號（UNKNOWN 不阻擋），並在 verdict 裡寫出年齡；寫入者要有 liveness（rider 結果或 CHECK6 列），沒有就把讀取端的過期保護當成唯一防線。（ai_darkhero/brain/insight/network_polite.py `load_signal(max_age_s)`、_skill/engines/acquisition_hub.py `_signal_stale`；F1S 2026-10-31 curator audit）
