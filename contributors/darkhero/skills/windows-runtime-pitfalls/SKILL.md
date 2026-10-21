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
- **背景 python 會跳「應用程式錯誤」對話框**：CPython 3.12 的 `platform.*` 走 WMI COM thread，機器忙時崩潰 → csrss
  硬錯誤框（短暫、無 Event 1000）。背景程序避免在 import 期呼叫 `platform.machine()/uname()` 這類查詢；零彈窗紅線。
  （ai_trader zero-popup-python-crash-dialog；hub memory pythonw-platform-ver-flash）
- **共用的來源標籤不能歸因呼叫者；指名之前先讀嫌疑方自己的 log。** ai_theater 的 gate 把每個 POST
  /api/subtitle/background 都標成 `ai_theater_background`，2026-10-19 的提案據此指名 load_guard 重新 arm 字幕，
  但 load_guard.log 全檔 0 筆 shed/resume/gate 事件、ladder level 一直是 0——真正的呼叫端至今 UNKNOWN，因為
  gate 的 access log 只走 `logging.debug` 沒落地。做法：每個呼叫端自帶 source（或 User-Agent），服務端把 access
  log 寫到檔案；而「還原」類動作要綁自己那一代的 intent generation，資料裡出現更新的 stop/start 就不再還原
  （load_guard `off_generation`，test_load_guard_ladder_restore）。

## 重試、鎖、排程

- **重試一定要有上限與冷卻**，而且要讀回執行證據：一條永遠到不了 DONE 的鏈被 watchdog 每 5 分鐘重跑，一天 50–65 次、
  每次都登入外部服務。改了「判定」也要檢查它對重試迴圈的副作用。（ai_trader preopen-chain-retry-storm）
- **會被逾時殺掉的週期步驟，開工前先寫 STARTED 狀態並對同一輸入指紋設冷卻**：否則子程序每次被 kill、狀態從沒寫入，
  下一輪又從頭重跑（ai_trader strategy_lineage 300 s 逾時、一小時被殺 3 次）；預算快用完時不要再開新的一天／新的一批
  （news_tone 保留 DAY_RESERVE_S）；前置條件已知不成立（owner 停用的 cockpit）就跳過，不要讓它每輪 rc=1。
  （ai_trader workflow-audit-20261020）
- **git 128 先查殘留 `.git/index.lock`**：確認沒有長命 git 行程後改名成 `index.lock.stale-<時間>.MIGRATED-bak`（不刪）。
  殘鎖會讓排程備份「靜默不 commit」好幾天。（ai_trader git-index-lock-stale）
- **把 runtime 資料移出 git 追蹤後，checkout／reset 到舊 commit 會用舊版覆寫正在用的檔案**（資料庫、kill flag）；
  移出時列出所有還追蹤它的分支並警告。（ai_trader runtime-untracked-checkout-hazard）

## 時間與資料新鮮度

- **事件時間與收到時間比對前先確認本機時鐘已同步**（W32Time 可能幾週沒同步）；時鐘慢會讓「收到早於事件」這種檢查
  靜默拒絕所有訊號，而且被去重的記錄把痕跡吃掉。（ai_trader orb-missed-signal-clock-skew）
- **外部資料源過期時，下游要明確進入保守模式並把原因寫出來**，同時記錄「上游修好後多久才會生效」（節流快取）。
  （ai_trader pcr-iv-stale-feed-blocks-longs）

## CPU 配額與批次負載

- **新加的 OCR／STT／影像批次工作先限執行緒，再量「每幀／每分鐘成本」，量完才放大。** onnxruntime 類引擎
  （rapidocr_onnxruntime）預設 intra_op 執行緒＝全部核心：一個 OCR 行程吃掉 27 核，同機的 faster-whisper 與 4 條
  STT lane 每 10 s 只拿到 5 CPU-s、25 分鐘音訊跑了 83 分鐘，看起來像「模型卡住」。一律 `RapidOCR(intra_op_num_threads=4)`
  這類明確上限；懷疑模型慢之前先看 CPU 配額。（hub-root burnin-subtitle-ocr-learning；ai_theater
  scripts/subtitle_burnin_learn.py）
- **逐幀跑昂貴辨識前先用便宜的變化偵測，而且偵測要對準目標區域的特徵。** 整幀灰階差分擋不住動態畫面
  （3061 幀仍要 1858 次 OCR）；改比對近白色字幕遮罩（HSV V≥200、S≤60，縮到 360×58，mean abs diff ≥4 才重辨識）
  降到 277 次、274 s。（同上）

## 程式可達性

- **判斷死碼要把子程序派工（`python -m pkg.mod`、`scripts/x.py` 字串）、排程 rider 命令、launcher、以及把原始碼當文字
  讀的測試都算進根節點**，只看 import 圖會把正在跑的東西列進清理名單。（ai_trader subprocess-dispatch-breaks-import-graph）
- **控制第三方軟體先找它的設定語意（登錄檔／設定檔），不要先做 UI 模擬**；例：PotPlayer 切檔變大小是
  `ScreenFitBySize`。（hub-root potplayer-fixed-window-registry）
