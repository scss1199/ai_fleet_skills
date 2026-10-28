---
name: mtm-mto-first
description: >-
  MTO before any Read/Grep/Shell loop — prework + task-router + narrow-read + PFKT gate.
  Stops TRN waste (top fleet burn: Read×500, Bash×500, browser MCP). Use every non-trivial task start.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: true
    engine: _skill/engines/mtm-token-waste-scan.py
    registry: _registry/mtm-protocol.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# mtm-mto-first — 機械先行（止 TRN 燒 token）

> **證據**：全艦 top sessions — `Read×614` `Bash×593` `Edit×651`（`20260608 fracdigi` 70M billable）；  
> **根因**：skill 有但未裝（deploy bug）或未跑 prework/router。

## 何時用（強制）

- 任務開始前（SessionStart 後第一動作）
- 準備第 2 次 `Read` / `Grep` / `Shell` 同一主題
- 準備 `Task` / 多 agent 並行
- 準備 browser / CDP

## F1S ③ 做法（馬斯克五步，順序不可顛倒）

1. 質疑需求：回到使用者原話（`f1s-intake`）。
2. 刪除不必要的步驟。
3. 簡化。
4. 加速。
5. 最後才自動化。

- 動手前先問要不要寫新東西，依序：重用現有程式 → 標準函式庫 → 原生功能 → 已安裝套件 → 最後才自己寫。
  精簡但不省驗證、安全與錯誤處理。
  重用的界線：新資料源若只是替別的已登記假設會讀的 store 加欄位（例 leadlag 把每個已存市場都當 leader），要另開
  自己的 store，否則設計釘住的輸入會默默改變（ai_trader 2026-10-28：24 個世界指數進 `runtime/research/world_macro`）。
- 改碼前先全域搜尋既有實作與用法（brownfield）；未搜尋即改碼 PROOF 擋（class `code_change`，
  Lean `ClaimContract.code_change_needs_prior_search`）。scratchpad 腳本不算。
- 精準修改：只動要改的行，旁邊的程式一行都不碰。
- 輸出看起來太窄（owner：「上千個投資標的你只選兩個」）時，先找出產生窄度的參數再加資料：ai_trader v14 只持 2–3 檔
  是 K=3 與每單 5,000 上限造成，不是宇宙小；v21 把上櫃併進面板（2,062 檔）後 walk-forward 變好，但預先登記的門檻一項
  都沒過，K=10/20 反而虧。加名單、加資料源是第 1 步沒做完的替代品（反向學習自 ai_trader matrix-lane-v21 2026-10-18）。
- 第 2 步「刪除」落到週期工作與通知：新增排程步驟前先講出誰讀它的輸出，講不出就不加；一條研究線得出 verdict 後，
  同一個變更就把它的腳本移出樹（收據留 commit hash）；推給使用者的通知（LINE 等）只在有新事實時發（有成交或有新
  verdict），「0 筆／UNKNOWN」這種日報是噪音、要壓掉並記原因。座位的低效要從它自己的日誌與 rider 結果量出來，hub
  的通用效率工具給不出座位層級的缺陷；結構性閒置（沒人用的盤中機器）列出來交使用者決定，不自行退場
  （反向學習自 ai_trader workflow-audit-20261020）。
- 「移除沒在用的功能」憑證據退役，不憑沉默：①從 handler 的 AST 找出每個動作實際寫的 log 行，不寫 log 的動作沒有
  證據，改數該功能自己的 log 簽名；②數完整歷史（含輪替封存檔），並讀命中的行——啟動橫幅、tick 名稱會灌水；③查持久
  狀態（armed/enabled）與使用者決定：停放不等於退役，還被腳本或 hub 引擎 import 的模組留著，只拿掉入口；④切之前查
  安全耦合（例：A770 功率上限由開機腳本套用，不在 GPU 選單模組）；⑤檔案移到 `_delete/<日期>-<主題>/` 附 sha256
  MANIFEST（不刪），同一個 commit 拿掉它們的測試、保持「每個動作都有呼叫端」稽核綠燈，殘留檔先加 .gitignore 免得被
  idle sweeper commit。（ai_darkhero tray 2026-10-23：動作 42→25、-3924 行、PowerShell 子程序 13→0／120 s；
  `_delete/2026-10-23-tray-retired/MANIFEST.jsonl`）
- 「最後才自動化」的門檻：同一件手工操作做到第三次才寫成腳本或技能；寫之前先查別的座位做過沒：
  `python %AI_WORKSPACE%\_skill\engines\f1s-harvest.py tools "<關鍵字>"`（全艦工具與技能）、`api <service>`（外部 API）
  （反向學習自 ai_metadata aex-mtm-loop-metadata）。
- 爆紅工具的接法（使用者從 IG／LINE 轉來的 GitHub 技能包、agent 工具、瀏覽器）：①先認正牌：同名 repo 常不只一個，
  `gh repo view <owner>/<repo> --json licenseInfo,createdAt,stargazerCount,pushedAt`（或 search API）看授權、建立日、星數，
  沒授權或認不出正牌就停在這一步；②只讀不裝：`gh api -H "Accept: application/vnd.github.raw" repos/<owner>/<repo>/contents/<path>`
  讀腳本本體，不裝 plugin、不跑它的安裝腳本（`irm … | iex`、`curl … | sh` 一律不執行）；③查本座位有沒有同等功能
  （`f1s-harvest.py tools`、grep）；④沒有就用自己的資料把方法重做成本地模組＋測試，接進既有報告當 report block
  （fail-open，不是 gate），模擬結果一律標「模擬不是勝率」；⑤真的要裝二進位或套件才能比（無頭瀏覽器、索引器）：
  先過 SkillSpector／供應鏈檢查，只裝到專案範圍（不改 ~/.claude 全域設定，那要使用者授權），語意／LLM pass 不得
  動用付費模型；換掉現役工具只憑同一批輸入的 A/B 量測（成功數不低於現役、記憶體或 token 差距寫進收據），量不到或
  輸的就記下數字與不採用原因，不換。（反向學習自 ai_trader first-touch-sim-20261028，commit 5f4d0a02c）

## 工具與 context 紀律（kyloren_bot b7b4e052、bac266b7、053de955）

- 瀏覽器：能預先排好的 2 步以上動作合成一次 `browser_batch` 或一段 `javascript_exec`；平行的 agent 各用自己的分頁，不動使用者正在看的分頁。
- 換模型或 effort 只在新對話的邊界做，不在對話中途換（思考區塊與快取綁定原本的模型與 context）；不把會變的資料（日期、狀態）塞進 system prompt。
- 無人看管的 xhigh／max 長跑，先寫明 token 或回合上限再開始。
- 大型工具輸出（log、清單、截圖）留在檔案，只把路徑和摘要帶進 context。

## MTO 四步（TR0，0 LLM token）

### 1 CONSUME — prework

```powershell
python %AI_WORKSPACE%\_skill\engines\prework.py "<task keywords>" --agent <seat>
```

有 `[ZTM]` hit → **用引擎，禁止重造**。

### 2 ROUTE — task-router

```powershell
python %AI_WORKSPACE%\_skill\engines\ztm-task-router.py "<keywords>"
```

有 route → **只跑 cmd**，不在 chat 裡試探。

### 3 NARROW READ — TR1

| 禁止 (TRN) | 改用 (TR1) |
|------------|------------|
| 整檔 Read | `Grep` INDEX → `Read offset/limit` |
| @codebase | `prework` + `local-find.py` |
| 重複 Read 同檔 | park 指標 + 5 行 stash |

### 4 PFKT — 多步/並行前

```powershell
python %AI_WORKSPACE%\_skill\engines\pfkt-fragment.py mint <seat> "<title>" --verify "<cmd>"
# 平行 → pfkt-wave.py plan
```

## 配對 skill（必讀）

| 情境 | skill |
|------|-------|
| inbox>0 | `ztm-fleet-inbox-absorb` |
| 宣稱 done | `ztm-verify-before-done` |
| 網頁登入 | `ztm-web-auth-ops` |
| milestone | `agc-auto-goal-compact` park |
| 全艦審計 | `mtm-fleet-audit --brief` |
| 平行 Task | `pfkt-parallel-wave` |
| gate HARD DENY | `pfkt-auto-unblock` |
| 重複動作 | `mtm-mte-mint` |
| 網頁認證 OOM | `ztm-cursor-edge-auth` |
| context 外包 | `mtm-api-pool-offload` |
| 全艦智慧 | `ztm-fleet-intelligence` |

## PFKT 平行（第 4b 步）

```powershell
python %AI_WORKSPACE%\_skill\engines\pfkt-wave.py plan --stamp <STAMP>
# 或自動：auto-gate-unblock.py --gate pfkt
```

見 skill `pfkt-parallel-wave` · `pfkt-auto-unblock`。

## 自測

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-token-waste-scan.py --agent <seat> --brief
```

## CITE

`_registry/mtm-protocol.json` · `prework.py` · `ztm-task-router.py`
