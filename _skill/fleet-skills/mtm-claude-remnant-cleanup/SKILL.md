---
name: mtm-claude-remnant-cleanup
description: >-
  Claude remnant MTM pipeline — absorb classify, quarantine to _delete, registry sweep.
  Curator seat ai_darkhero executes; promotes canonical skills after verify.
  Use when cleaning Claude leftovers, C:\working\claude_*, stub seats, CLAUDE_SHARED, or de-claude registry links.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: on-demand
    token_budget: zero
    required: false
    engine: _skill/engines/mtm-claude-tick.py
    registry: _registry/mtm-claude-cleanup-protocol.json
    seat: ai_darkhero
---

# mtm-claude-remnant-cleanup

> **One-liner:** `python %AI_WORKSPACE%\_skill\engines\mtm-claude-tick.py --brief`  
> **Seat:** `ai_darkhero`（curator cwd）執行 `--apply` quarantine。

## 何時用（強制）

- 清理 Claude 殘留路徑 / stub skills / `CLAUDE_SHARED` / `claude_master` 硬編碼
- soak 後要把無用檔 **move** 進 `_delete/claude-remnant-<date>/`
- 驗證 live registry 殘留 `remaining_hits → 0`

## TR0 開局

```powershell
cd C:\ai_workspace\ai_darkhero
python %AI_WORKSPACE%\_skill\engines\prework.py "claude remnant cleanup" --agent ai_darkhero
python %AI_WORKSPACE%\_skill\engines\ztm-task-router.py "claude cleanup"
python %AI_WORKSPACE%\_skill\engines\lexicon-resolve.py MTM_Claude_Cleanup
```

## 一鍵管線（優選）

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-claude-tick.py --brief
# dry-run quarantine:
python %AI_WORKSPACE%\_skill\engines\mtm-claude-tick.py --brief --dry-run
# absorb only:
python %AI_WORKSPACE%\_skill\engines\mtm-claude-tick.py --absorb-only --brief
```

`tick` = absorb×2 → quarantine(if ready) → sweep → write `_registry/mtm-audit/claude-tick-*.json`

## 分步引擎

| Step | Engine | 成功準則 |
|------|--------|----------|
| Absorb | `mtm-claude-absorb.py --write --brief` | `stable:true` 連續 2 輪 |
| Quarantine | `mtm-claude-quarantine.py --apply` | manifest in `_delete/claude-remnant-<date>/` |
| Sweep | `mtm-claude-sweep.py --write --brief` | `remaining_hits: 0` |
| Verify | `lexicon-sync.py --brief` · `fleet-skill-sync.py verify`（允許預存 nested 失敗） |

## 分類語意

| category | 動作 |
|----------|------|
| `keep_absorb` | 已進 SSOT / stub 說明檔 — 留著 |
| `quarantine` | move → `_delete` + SHA manifest |
| `unknown` | 只記报告；**不**自動刪；需人工或下一輪規則收斂 |

## 紅線

- **禁止永久刪除** — 只 move + manifest；`.MIGRATED-bak` 永久刪只寫 operator 指令
- 不碰 `_secrets`、fracdigi vault、operator-gated 路徑
- ADUS draft OK；**promote** → cwd=`ai_darkhero` + `adus-promote.py`

## 全艦套用（curator）

```powershell
python %AI_WORKSPACE%\_skill\engines\fleet-skill-sync.py deploy --seats-only
python %AI_WORKSPACE%\_skill\engines\sync-cursor-hooks.py
```

## CITE

`_registry/mtm-claude-cleanup-protocol.json` · lexicon `MTM_Claude_Cleanup` · `_skill/engines/mtm-claude-*.py`
