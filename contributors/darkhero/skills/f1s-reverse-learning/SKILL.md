---
name: f1s-reverse-learning
description: >-
  F1S learns back from every cwd: harvests each seat's skills, memory lessons, tools and external APIs,
  compares them with what F1S already says, triages candidates on the free pool, and keeps a
  self-updating goal list (coverage + next goals) that a long-running session works through until
  nothing generalizable is left. Use when asked to absorb what the seats know into F1S, to keep a
  long task going with self-set goals, or before writing a new skill/engine (check what a seat already
  built). Curator seat runs it; other seats feed it automatically.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: low
parent_skill: mtm-mto-first
---

# f1s-reverse-learning — 從各 cwd 反向學習（F1S）

operator 2026-10-16：「把他們各自用到的所有技能 經驗 系統 api 整合會到f1s 使得f1s直接建立一個從各cwd反向學習的機制
… 讓這個對話的f1s能夠維持長任務自己找目標自己更新目標去把上面那件事情做到極致」。

## 三層

| 層 | 做什麼 | 指令（全部在 `_skill\engines\f1s-harvest.py`） |
|---|---|---|
| 收 | 每個 cwd（ai_* / jci_* / sdnext_a770，永不掃 fracdigi、quant）：技能（canonical／drifted／seat-local）、`~/.claude/projects/<cwd>/memory` 的經驗、`tools/ scripts/ _line/` 有 docstring 的工具、外部 API（只收變數名與主機名） | `scan` |
| 比 | 每筆對 F1S 單一文件（canonical 技能、hot directive、curator memory）算包含率；≥0.5 = 已在 F1S；其餘依種類、跨座位重複數、未覆蓋程度打分 | `scan` |
| 分 | 免費池（`chat_for("extract")`）逐批判定：generalize（附一句繁中規則）／seat-specific／noise；seat-specific 自動結案 | `triage` |
| 目標 | `_registry/f1s-harvest/goals.json`：coverage＝已結案／總數，`next`＝依分數排序的下一批目標（同服務、同名工具跨座位合併成一個目標） | `goals` |
| API | 全艦外部服務目錄（服務→類別、用到的座位、變數名、程式出處、是否已在免費池） | `catalog`、`api <service>` |
| 工具 | 全艦工具與技能查詢：寫新東西前查哪個座位已經做過（名稱＋docstring＋triage 規則排序） | `tools "<關鍵字>"` |

`cycle` 一次跑完收→比→分→API 目錄→重算目標。

## 長任務：自己找目標、自己更新目標

1. `python f1s-harvest.py cycle` → 讀 `goals.json` 的 `next`。
2. 取第一個目標，依種類整合（下表），做完立刻
   `python f1s-harvest.py mark <id> integrated --evidence "<commit 或路徑>"`（整組跨座位一起結案）；
   判定不該進 F1S 的寫 `rejected`／`duplicate`／`seat-specific` 並附理由。
3. 回到 1。每次 `cycle` 會重新收（新的 memory、新工具）、重算分數，目標清單自己往前推。
4. 停的條件：`open_goals` 為 0，或最高分低於 1.0（剩下都是低價值）。停時回報 coverage 前後數字。

| 種類 | 整合方式 |
|---|---|
| memory（generalize） | 規則寫進最相關的 canonical 技能（同主題 ≥3 條才新開技能）；用 triage 的 `rule` 當草稿，對照原 memory 修正，不帶專案名 |
| skill（local／drifted） | 通用的升為 `_skill/fleet-skills/` canonical；drifted 把座位的改進合回 canonical |
| system | 預設整合成「工具目錄」（`tools` 查詢＋mtm-mto-first 規則：寫新工具前先查），`cycle` 自動結案並註明「未搬進 hub」；真正與座位無關、多座位會用的才搬進 `_skill/engines/`（附測試） |
| api | 由 `catalog` 一次整合，`cycle` 自動結案；接新外部服務前先 `api <service>` 看誰接過、參考哪段程式 |

出貨照 F1S：`f1s_audit.py` 加對應列（check_text 綁新文字）→ `ship-f1s.py`。

## 週期與上行

- 其他座位不用做事：它們寫的 memory、技能、工具，下次 `cycle` 就會被收到。
- `propose --n 5` 會把最高分目標用 `inbox.py send ai_darkhero <seat> --kind task "F1S: …"` 送進上行路徑，
  由 f1s-evolve 自動整合（T1 不可改、Lean 稽核與測試全綠才出貨）。
- 週期：HubClock rider `f1s-harvest`（operator 2026-10-16 核准）每天 03:40 跑 `cycle --triage-limit 120 --propose 3`，
  max_runtime 3600；新目標自動送進 f1s-evolve。

## 橫向：座位之間互相套用強化（`f1s-mesh.py`，operator 2026-10-27）

`f1s-harvest` 只往上收；被判 `seat-specific` 的經驗從此卡在原座位，同能力的其他座位用不到。`_skill\engines\f1s-mesh.py run`
一次跑完一個回合，處理完畢自動封存：

| 階段 | 做什麼 |
|---|---|
| CENSUS | 嚴格模型普查：模型只在**程式碼**（去掉註解行）出現才算，`.md` 只列「僅文件提及」；每個模型標 本機／免費額度／付費；同時算每座位的能力標籤（stt、gas、line、trading…，只看程式碼且 ≥2% 檔案） |
| MATCH | harvest 帳本中 `seat-specific`／`candidate` 的 memory／system／skill × 擁有相同能力標籤的其他座位（IDF 加權，分數 ≥ `MIN_SCORE`）；對方已有等價內容（單一文件包含率 ≥0.5）就跳過 |
| REINFORCE | 已派送的邊若對方座位現在已涵蓋 → `adopted`；同一技巧被 ≥2 座位採用、或符合 ≥3 座位 → 一次性提案給 f1s-evolve 升成全艦規則；21 天沒回應 → `stale` |
| GATE | NVIDIA SkillSpector（`_harness/tools/skillspector`，固定 commit a5425e59，`--no-llm` 純靜態，座位經驗不外送）掃每條邊的來源：分數 ≥50 或有 HIGH/CRITICAL → `blocked-risk` 不送；掃描器不在或失敗 → 暫緩（fail closed）。已審核接受的發現只放 `_registry/f1s-mesh/skillspector/hub-baseline.yaml`；`scan-fleet` 掃全部 canonical 技能 |
| DISPATCH | 每個目標座位一則 inbox task（最多 5 條，其餘留下一回合），每條附靜態風險分數 |
| CLOSE → ARCHIVE | 每條邊都到終態、每則訊息檔都在才結案，收據移到 `_registry/f1s-mesh/archive/<round>.json`；缺件就留在 `rounds/` 並寫原因 |

**收到 `F1S mesh:` inbox 的座位**：逐條讀來源，適用就套用，然後
`python C:\ai_workspace\_skill\engines\f1s-mesh.py adopt <edge> --evidence "<路徑或 commit>"`；不適用就
`reject <edge> --reason "<為什麼>"`。`status` 看回合與邊數，`tiers` 依任務意圖判斷付費／免費／無模型能否套用到他座位，
`render` 從狀態重產 `ai_darkhero/f1s-projects-ai-map.html`（數字不手寫）。
SkillSpector 在 Windows 不能用 `--output`（Safe file output unsupported）→ 讀 stdout；`--recursive` 有 aggregate 上限（56 個只回 32 個），
要逐一掃；`--exclude` 壓不掉 SC8/SC9（範圍外的 .pyc 照報），要用 baseline 規則。
週期跑需要 operator 核准的 HubClock rider；未核准前由 curator 在對話中手動 `run`。

## 紅線

- 只收名稱與文字，不讀 `.env`／金鑰值；fracdigi、quant 整個不掃；`ai_ut` 的 UT.xlsx 不是文字來源。
- memory 內容含個資或帳戶資料的，整合時只取通用規則，不搬原文。

## 2026-10-16 第一輪結果

- 收：24 個 cwd，去重後 2103 項（技能 1087、工具 681、API 183、經驗 152）。coverage 0.80（第一次掃描）→ 1.00。
- 免費池分類 189 項：89 項可通用、92 項屬單一座位。
- 進 F1S：新 canonical 技能 `windows-runtime-pitfalls`（13 條各座位事故）、升為 canonical `web-page-atlas`（ai_trader，
  改成全艦共用 `_registry/web-atlas/`）、`gas-google-sso-webapp`（ai_accountancy，補今天的 GAS 教訓）、
  `mtm-subtitle-two-phase`（ai_metadata＋ai_theater 同一份）；規則併入 api-key-apply、mtm-api-pool-offload、
  ztm-verify-before-done、web-ui-taste、mtm-mto-first；API 目錄 130 個服務；工具目錄 681 項。
- 引擎自己的教訓：比對要用「單一文件最佳包含率」（聯集會讓什麼都像已覆蓋）、同一座位技能的多份部署副本要去重、
  hot directive 上限 1400 字（f1s_audit 現在會先擋）。
