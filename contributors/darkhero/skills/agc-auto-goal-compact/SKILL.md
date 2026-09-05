---
name: agc-auto-goal-compact
description: >-
  AGC (auto-goal-compact): the goal vector survives every compaction. Per-seat
  uncompact_upper_limit with silent refresh of _registry/agc-compact/<agent>.md (never
  blocks a prompt), milestone PARK and the five goal-compact rules (absorbed from
  ztm-goal-compact-enforce on 2026-09-05), and the FAMES auto_goal_compact lane armed on
  every Claude hook (SessionStart, UserPromptSubmit, PreCompact, post-compaction pointer).
  Use at every session start, before broad surveys, when token burn is high, when resuming
  long work, or when auto-compact fires. Read the compact; never re-read the chat.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: true
    engine: _skill/engines/agc-compact.py
    registry: _registry/agc-protocol.json
    absorbed: ztm-goal-compact-enforce (2026-09-05)
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# agc-auto-goal-compact — 自動目標壓縮（必讀；已併入 ztm-goal-compact-enforce）

> **AGC** = 自動層 + 手動 `goal_compact.py park` + 平台 PreCompact，三層合一。
> **CITE:** `_registry/agc-protocol.json` · `_registry/fames-protocol.json#auto_goal_compact`（FAMES 1.32.0）· `_registry/goal-compact-protocol.md` · `_registry/goal-vector-protocol.json`
> 2026-09-05 起 `ztm-goal-compact-enforce` 的五規則、開 session / 收工命令與硬閘全部併入本 skill；舊名只留在 lexicon 的 legacy alias，canon 目錄已隔離到 `_delete/2026-09-05-skill-consolidation/`。

## 核心

長 session 時 **不要重讀 chat/transcript**。改讀本地工件（agent 自行 Read；hook 只注入 ≤420 字指標，不塞全文）：

```
_registry/agc-compact/<agent>.md                 # cold page：goal vector + PARK + stash/PFKT/SUBMIT 指標
_registry/agc-state/<agent>.json                 # 上次 refresh 的 reason/trigger + fames_goal_compact 結果
_registry/agc-compact/<agent>.orthogonal.md      # 被投影走的正交區塊；憑 receipt 的 sha256 可開
```

## 核心模型（目標向量 g）

**目標 = 特徵向量 g**（`goal-field.py mint <agent>` → `_logs/<stamp>.goal.json`）

- 與 **g 對齊** 的 context 保留：五段落 spec、當前段 I/O 契約、stash 指標、PFKT pending、紅線、UNKNOWN/FORBIDDEN 終態
- 與 **g 正交** 的 chunk → 壓縮：手動蒸餾 ≤5 行進 `brain/stash.md`；AGC 投影則移到 orthogonal ledger，原位留一行 `- receipt:`
- `P_final = P_align × P_compact`，`P_compact = 1 - compact_orth_penalty`（goal-vector-protocol 既有定義）；方向錯誤的壓縮會降 `P_compact`

## 五規則（hook 強制提醒）

| # | 規則 | 引擎 |
|---|------|------|
| 1 | 里程碑 **PARK** | `goal_compact.py park <agent> "<milestone>"` + `brain/stash.md` |
| 2 | 取用 **窄讀** | grep stash / compact → offset/limit |
| 3 | **禁止** 手打 `/compact` | 平台自動 compaction；Cursor `hooks/compaction-guard.ps1` 記錄，Claude `claude-agc-precompact-hook.py` 強制 refresh + 記帳 |
| 4 | **懶載入** | grep INDEX；CLI/engine 先於 browser |
| 5 | **下放** | 探索/機械 → subagent / Groq / engines |

## 三層

| 層 | 工具 | 時機 / trigger |
|----|------|----------------|
| AGC（自動、靜默） | `agc-compact.py` + hooks | 超過 uncompact 上限、compact stale、ctx_meter EOQ（`agc_should_compact`） |
| PARK（手動里程碑） | `goal_compact.py park` | 段末 / 收工（`milestone_park`） |
| Platform compact | Cursor preCompact / Claude PreCompact | 視窗滿（`platform_pre_compaction`）；事後 `context_window_compaction` |

## 自適應上限（uncompact_upper_limit）

每 seat 有獨立上限 → `_registry/agc-agent-limits.json`（`agc-adapt-limits.py --write` 可調）：

| 代理 | 典型 ai_career (judgment) | 典型 ai_zonghe (mechanical) |
|------|---------------------------|----------------------------|
| turn | ≤16 | ≤8 |
| read+grep | ≤22 | ≤12 |

達上限 → **靜默 refresh compact 檔**；**絕不** prepend / block 使用者訊息。

## 何時觸發（hook 自動、非阻擋）

| 信號 | 說明 |
|------|------|
| turn / read+grep / shell | 超過該 seat 的 uncompact_upper_limit（proxy 計數） |
| ctx_meter EOQ | `n* = sqrt(2C/g)`；有 transcript 量測時優先於 proxy |
| compact stale | 超過 stale_seconds 且 session 成長 |
| sessionStart | 僅 mint/refresh + **短指標**（≤420 chars），非全文 |
| 冷卻 | 同一 session 300 s 內不重複 refresh（proxy 與 meter 路徑皆適用） |

**no_park 不觸發 beforeSubmitPrompt** — 里程碑用規則 1 手動 PARK。

## Claude hooks（FAMES auto_goal_compact lane，2026-09-05 武裝）

| Hook | 動作 | check_token | 收據 |
|------|------|-------------|------|
| SessionStart | mint/refresh；指標附在 session receipt 的 plan_text | `AGC-LANE-SESSION-START` | `_registry/fames-session/<seat>.json`（schema 5） |
| UserPromptSubmit | `agc-should-compact` 評估 → 需要時靜默 refresh | `AGC-LANE-TURN` | `_registry/fames-turn/<surface>/<session-sha>.json` |
| PreCompact | 強制 refresh（`platform_pre_compaction`）+ 記帳 compaction ledger | `AGC-LANE-PRECOMPACT` | `_registry/fames-precompact/<seat>.json` |
| SessionStart(source=compact) | 注入「CONTEXT WAS COMPACTED — 從 compact 檔與 brain/stash 續作」 | `AGC-LANE-POST-COMPACTION-POINTER` | 同 session receipt |

- 引擎：`_harness/runtime/fames_session_harness.py`（`auto_goal_compact` / `precompact_context` / `resolve_agc_seat`）；adapter：`_skill/fleet-skills/token-preflight/scripts/claude_session_hook.py`（SessionStart + UserPromptSubmit）、`_skill/engines/claude-agc-precompact-hook.py`（PreCompact；印 `{}`、永遠 exit 0、絕不阻擋 compaction）。
- Seat 解析：transcript slug → hook agent → seat 目錄名；解析不到 = UNKNOWN，不寫任何檔案。`fames_probe_mode` 探針只寫收據、不記帳。
- 狀態：`_registry/token-preflight/claude-hook-status.json`（key `agc`）、`_registry/token-preflight/claude-precompact-status.json`。
- Cursor 端：`cursor-agc-session-inject.py`（sessionStart）、`cursor-agc-auto-compact.py`（beforeSubmitPrompt）、`hooks/compaction-guard.ps1`（preCompact，只記錄）；`.cursor/hooks.json` 由 `sync-cursor-hooks.py` 產生，禁止手改。

## 開 session（0-token）

```powershell
python %AI_WORKSPACE%\_skill\engines\goal-field.py mint <agent>
python %AI_WORKSPACE%\_skill\engines\ztm-session-brief.py --agent <agent>
```

## 里程碑收工

```powershell
# 1) 蒸餾 bulky 輸入 → brain/stash.md（≤5 行/主題 + 指標）
# 2) PARK（經 agc_lib.write_compact 觸發 FAMES goal-compact，trigger=milestone_park）
python %AI_WORKSPACE%\_skill\engines\goal_compact.py park <agent> "<milestone>"
# 3) 若主題切換 → 新 chat + @HANDOFF / park 檔
```

## 命令（TR0）

```powershell
python %AI_WORKSPACE%\_skill\engines\agc-should-compact.py --agent <seat> --json
python %AI_WORKSPACE%\_skill\engines\agc-compact.py --agent <seat> --force
python %AI_WORKSPACE%\_skill\engines\agc-adapt-limits.py --write --brief
python %AI_WORKSPACE%\_skill\engines\agc-fleet-audit.py --write --brief
python %AI_WORKSPACE%\_skill\fleet-skills\fames\scripts\fames_fleet.py goal-compact --workspace %AI_WORKSPACE% --agent <seat> --trigger manual --json
python %AI_WORKSPACE%\_skill\fleet-skills\fames\scripts\fames_fleet.py validate-goal-compact --input %AI_WORKSPACE%\_registry\fames-evidence\agc-<seat>-latest.json --json
```

## 硬閘（Cursor hooks，由 `sync-cursor-hooks.py` 產生）

| 閘 | 擋什麼 |
|----|--------|
| `cursor-ztm-broad-gate.py` | 全艦/ai_workspace 盤點（**含 curator**）無 PFKT/probe |
| `cursor-pfkt-gate.py` | 複雜/平行無 fragment/wave |
| `hooks/compaction-guard.ps1` | PreCompact 記錄 + rules 刷新（Cursor；Claude 端改由 `claude-agc-precompact-hook.py`） |

## Token 預算紀律

- **禁止 mega-session**；一主題一 chat（2026-07-07 量測：7/7 已用 ~30% 月額）
- Curator 調度可 MTD；**盤點/掃描/寫 skill** 必 PFKT split 或 probe scope
- 機械活：`auth_check` · `ztm-task-router` · `git_smart` · `ship-queue`

## FAMES 治理（auto_goal_compact lane）

- SSOT：`_registry/fames-protocol.json` 的 `auto_goal_compact` 區段（FAMES 1.32.0）；不是第六個 phase，是餵 MTM 與 SEAL 的 lane。
- 引擎：`python _skill/fleet-skills/fames/scripts/fames_fleet.py goal-compact --workspace C:/ai_workspace --agent <seat> --trigger <trigger> --json`；`agc_lib.write_compact` 寫完 compact 後自動呼叫（best effort、隱藏視窗、30 秒逾時），結果存於 AGC state 的 `fames_goal_compact`。
- 投影規則：以 `## ` 標題分類；目標向量、PARK、stash、PFKT、SUBMIT、紅線、invariant、terminal state、artifact 路徑逐位元組保留；compaction 紀錄、session 訊號、raw tool output、探索性讀取、被取代草稿、閒聊、已完成段落逐字稿移到 `_registry/agc-compact/<seat>.orthogonal.md`，原位留一行 `- receipt:`。含 `RL-*` 或 `UNKNOWN`/`FORBIDDEN` 的區塊一律保留（RED_LINE_PRECEDENCE）。
- 驗證：`validate-goal-compact --input _registry/fames-evidence/agc-<seat>-latest.json --json`；goal hash 前後必須相等、authority 只能縮、紅線逐位元組相同、fabricated 行數為 0、quota 為 0；任一不符即 UNKNOWN 且不寫任何檔案。
- 已武裝：Claude 四個 hook（上表）。`~/.claude/settings.json` 於 2026-09-05 依 operator「升級 AGC 並與 FAMES 整套 skill/harness 結合」指示修改（PreCompact adapter 15 s；SessionStart timeout 10→20 s；備份 `settings.json.bak-20260905T174226`）。
- 未武裝：不新增 HubClock rider。
- Cases（`fames_fleet.py self-check --workspace %AI_WORKSPACE% --json`）：`C-GOALCOMPACT-*` 釘 validator；`C-AGC-LANE-BACKED` 要求 `_registry/agc-protocol.json` 每個 `hooks.claude.*.armed=true` 的 check_token 都存在於 harness 原始碼；`C-AGC-PRECOMPACT-ADAPTER`、`C-AGC-SESSION-ARMED`、`C-AGC-COMPACT-GOAL-HASH` 釘 adapter 存在、收據武裝旗標、每 seat 最新 evidence 的 `goal_hash_matches`。

## 驗證

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-token-waste-scan.py --agent <seat> --brief
python %AI_WORKSPACE%\_harness\tests\test_fames_session_harness.py
```

`no_park` / `tool_read_loop` 事件應下降；compact ≤2400 chars；每 seat 最新 `agc-<seat>-latest.json` 的 `goal_hash_matches` 必為 true。

## 外部對齊

- Claude Code / Anthropic compaction API — platform 端 lossy summarize；AGC 先在本地做 0-token 目標對齊投影
- MemGPT — main vs external context paging（AGC compact = cold page）
- Cursor Composer self-summarization — model 端；AGC = fleet 端 0-token 前置

詳見 `_registry/agc-protocol.json` → `external_alignment`。

## 相關

- `mtm-mto-first` — 禁 TRN Read 迴圈；MTO prework / router
- `fames`（auto_goal_compact lane）— goal-compact 引擎與 validate-goal-compact 驗證器
- `aex-agent-evolution` — parent；`fleet-token-ladder.py show`
- `ztm-web-auth-ops` — 瀏覽器登入階梯
- `_skill/technique_output/50-techniques/goal-compact-distillation.md` — 理論
- `_skill/technique_output/50-techniques/distill-not-compact-segmented-execution.md` — spec 錨定壓縮
