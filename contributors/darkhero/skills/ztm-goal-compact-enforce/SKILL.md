---
name: ztm-goal-compact-enforce
description: >-
  Mandatory goal-compact (目標壓縮) + ZTM session discipline. Goal vector g defines
  direction; orthogonal context is compressed at milestones. Use every session start,
  before broad surveys, when token burn is high, or when auto-compact fires.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: true
    engine: _skill/engines/ztm-session-brief.py
    registry: _registry/ztm-enforce.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# ztm-goal-compact-enforce — 目標壓縮（必讀）

> **強制**：SessionStart 已注入 `ztm-session-brief.py`；本 skill 是完整契約。  
> **CITE:** `goal-compact-protocol.md` · `goal-vector-protocol.json`

## 核心模型

**目標 = 特徵向量 g**（`goal-field.py mint` → `_logs/<stamp>.goal.json`）

- 與 **g 對齊** 的 context 保留：五段落 spec、當前段 I/O 契約、stash 指標
- 與 **g 正交或遙遠** 的 chunk → **壓縮掉**（蒸餾 ≤5 行進 stash，原文不留）
- `P_final = P_align × P_compact`；方向錯誤的壓縮會降 `P_compact`

## 五規則（hook 強制提醒）

| # | 規則 | 引擎 |
|---|------|------|
| 1 | 里程碑 **PARK** | `goal_compact.py park <agent>` + `brain/stash.md` |
| 2 | 取用 **窄讀** | grep stash → offset/limit |
| 3 | **禁止** 手打 `/compact` | autoCompactWindow=W*；PreCompact hook 記錄 |
| 4 | **懶載入** | grep INDEX；CLI/engine 先於 browser |
| 5 | **下放** | 探索/機械 → subagent / Groq / engines |

## 開 session（0-token）

```powershell
python %AI_WORKSPACE%\_skill\engines\goal-field.py mint <agent>
python %AI_WORKSPACE%\_skill\engines\ztm-session-brief.py --agent <agent>
```

## 里程碑收工

```powershell
# 1) 蒸餾 bulky 輸入 → brain/stash.md（≤5 行/主題 + 指標）
# 2) PARK
python %AI_WORKSPACE%\_skill\engines\goal_compact.py park <agent> "<milestone>"
# 3) 若主題切換 → 新 chat + @HANDOFF / park 檔
```

## 硬閘（已接 Cursor hooks）

| 閘 | 擋什麼 |
|----|--------|
| `cursor-ztm-broad-gate` | 全艦/ai_workspace 盤點（**含 curator**）無 PFKT/probe |
| `cursor-pfkt-gate` | 複雜/平行無 fragment/wave |
| `compaction-guard` | PreCompact 記錄 + rules 刷新 |
| `git-token-guard` | raw git diff / gh --log |

## Token 預算紀律

- 7/7 已 ~30% 月額 → **禁止 mega-session**；一主題一 chat
- Curator 調度可 MTD；**盤點/掃描/寫 skill** 必 PFKT split 或 probe scope
- 機械活：`auth_check` · `zct-task-router` · `git_smart` · `ship-queue`

## AGC（自動層 — 2026-07-08）

長 session 時 hook 自動維護 `_registry/agc-compact/<agent>.md`。**讀 compact 檔，勿重讀 chat。**

- Skill: `agc-auto-goal-compact`（REQUIRED）
- SSOT: `_registry/agc-protocol.json`
- 手動 PARK 仍必要；AGC 是 turn/read 代理信號上的自動萃取

## 相關

- `agc-auto-goal-compact` — 自動 compact 工件 + hook
- `ztm-web-auth-ops` — 瀏覽器登入階梯
- `50-techniques/goal-compact-distillation.md` — 理論
- `50-techniques/distill-not-compact-segmented-execution.md` — spec 錨定壓縮
