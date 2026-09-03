---
name: agc-auto-goal-compact
description: >-
  AGC (auto-goal-compact): per-seat uncompact_upper_limit; silent refresh of
  _registry/agc-compact/<agent>.md — never blocks user prompts. Read compact when
  resuming long work. Adapt limits via agc-adapt-limits.py.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: true
    engine: _skill/engines/agc-compact.py
    registry: _registry/agc-protocol.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# agc-auto-goal-compact — 自動目標壓縮（必讀）

> **AGC** = automatic layer on top of manual `goal_compact.py park`.  
> **CITE:** `_registry/agc-protocol.json` · `ztm-goal-compact-enforce` (manual PARK rules)

## 核心

長 session 時 **不要重讀 chat/transcript**。改讀本地工件（agent 自行 Read，hook 不會塞進你的 prompt）：

```
_registry/agc-compact/<agent>.md
_registry/agc-state/<agent>.json
```

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
| turn / read+grep / shell | 超過該 seat 的 uncompact_upper_limit |
| compact stale | 超過 stale_seconds 且 session 成長 |
| sessionStart | 僅 mint/refresh + **短指標**（~400 chars），非全文 |

**no_park 不再觸發 beforeSubmitPrompt** — 里程碑用 `ztm-goal-compact-enforce` + 手動 park。

## 命令（TR0）

```powershell
python %AI_WORKSPACE%\_skill\engines\agc-should-compact.py --agent <seat> --json
python %AI_WORKSPACE%\_skill\engines\agc-compact.py --agent <seat> --force
python %AI_WORKSPACE%\_skill\engines\agc-adapt-limits.py --write --brief
python %AI_WORKSPACE%\_skill\engines\agc-fleet-audit.py --write --brief
```

## 與 manual PARK 的關係

| 層 | 工具 | 時機 |
|----|------|------|
| AGC（自動、靜默） | agc-compact.py | 超過 uncompact 上限 |
| PARK（手動里程碑） | goal_compact.py park | 段末/收工 |
| Platform compact | PreCompact hook | Cursor/Claude 視窗滿 |

**禁止**手打 `/compact`。里程碑仍要 `brain/stash.md` + `goal_compact.py park`。

## FAMES 治理（auto_goal_compact lane）

- SSOT：`_registry/fames-protocol.json` 的 `auto_goal_compact` 區段（FAMES 1.31.0 起）；不是第六個 phase，是餵 MTM 與 SEAL 的 lane。
- 引擎：`python _skill/fleet-skills/fames/scripts/fames_fleet.py goal-compact --workspace C:/ai_workspace --agent <seat> --trigger <trigger> --json`；`agc_lib.write_compact` 寫完 compact 後自動呼叫（best effort、隱藏視窗、30 秒逾時），結果存於 AGC state 的 `fames_goal_compact`。
- 投影規則：以 `## ` 標題分類；目標向量、PARK、stash、PFKT、SUBMIT、紅線、invariant、terminal state、artifact 路徑逐位元組保留；compaction 紀錄、session 訊號、raw tool output、探索性讀取、被取代草稿、閒聊、已完成段落逐字稿移到 `_registry/agc-compact/<seat>.orthogonal.md`，原位留一行 `- receipt:`。含 `RL-*` 或 `UNKNOWN`/`FORBIDDEN` 的區塊一律保留。
- 驗證：`validate-goal-compact --input _registry/fames-evidence/agc-<seat>-latest.json --json`；goal hash 前後必須相等、authority 只能縮、紅線逐位元組相同、fabricated 行數為 0、quota 為 0；任一不符即 UNKNOWN 且不寫任何檔案。
- 分數：`compact_orth_penalty = 未分類殘餘 bytes / bytes_after`，`P_compact = 1 - compact_orth_penalty`（goal-vector-protocol 既有定義）。
- 未武裝：Claude 端 PreCompact hook 只是提案（需 operator 核准修改 user-level settings）；`.cursor/hooks.json` 為 `sync-cursor-hooks.py` 產生，禁止手改；不新增 HubClock rider。

## 驗證

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-token-waste-scan.py --agent <seat> --brief
```

`no_park` / `tool_read_loop` 事件應下降；compact ≤2400 chars。

## 外部對齊

- Claude Code / Anthropic compaction API — platform 端 lossy summarize
- MemGPT — main vs external context paging（AGC compact = cold page）
- Cursor Composer self-summarization — model 端；AGC = fleet 端 0-token 前置

詳見 `_registry/agc-protocol.json` → `external_alignment`。

## 相關

- `ztm-goal-compact-enforce` — 五規則 + manual PARK
- `mtm-mto-first` — 禁 TRN Read 迴圈
- `fames`（auto_goal_compact lane）— goal-compact 引擎與 validate-goal-compact 驗證器
