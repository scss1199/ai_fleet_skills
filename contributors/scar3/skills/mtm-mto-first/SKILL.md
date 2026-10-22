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
- 「最後才自動化」的門檻：同一件手工操作做到第三次才寫成腳本或技能；寫之前先查別的座位做過沒：
  `python %AI_WORKSPACE%\_skill\engines\f1s-harvest.py tools "<關鍵字>"`（全艦工具與技能）、`api <service>`（外部 API）
  （反向學習自 ai_metadata aex-mtm-loop-metadata）。

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
