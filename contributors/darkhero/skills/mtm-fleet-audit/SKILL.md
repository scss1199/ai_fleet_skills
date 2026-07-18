---
name: mtm-fleet-audit
description: >-
  MTM (minimal-token-mechanism) fleet harvest: auto-pull agent scorecards, park,
  PFKT, SUBMIT — 0-token rubric for skill candidates, optimize, parallel, PFKT compliance.
  MTO replaces spoken ZCT. Use before curator standup or when judging fleet token burn.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: false
    engine: _skill/engines/mtm-fleet-audit.py
    registry: _registry/mtm-protocol.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# mtm-fleet-audit — 全艦最少 token 審計

> **對齊 fracdigi MFO**：Firestore 讀寫分級 → LLM/context 分級（TR0/TR1/TWD/TRN）。  
> **CITE:** `_registry/mtm-protocol.json` · `mfoMeta.ts`

## 何時用

- Curator 開局前：一眼看各 seat 該進 skill / 該優化 / 該平行 / PFKT 是否合規
- 月 token 燒太快（session budget warn）
- **禁止**把 `agent-transcripts/*.jsonl` 貼進 chat — 用本引擎離線收割

## 熱套用（不重開 session）

Curator 已跑 `mtm-hot-apply.py` 時，**開著**的 chat 在**下一則訊息**自動 prepend MTM 契約（`cursor-mtm-hot-inject.py` hook）。

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-hot-apply.py
```

無需重開 Cursor；工作可繼續，注入只發生一次 per wave。

## MTO 一鍵（TR0→TR1）

```powershell
# 可選：先 sync Cursor transcripts → scorecards
python %AI_WORKSPACE%\_skill\engines\mtm-fleet-audit.py --sync-first --brief

# 單 seat
python %AI_WORKSPACE%\_skill\engines\mtm-fleet-audit.py --agent ai_hr --brief

# 持久化（給 portal / 下一輪 chat @ 檔）
python %AI_WORKSPACE%\_skill\engines\mtm-fleet-audit.py --write --json
```

輸出：`_registry/mtm-audit/latest.json` + 終端 `brief` markdown（≤6KB）。

## 資料源（全 0-token 本地）

| 層 | 來源 | MTO class |
|----|------|-----------|
| hot | `cursor_log_sync` → `log_session` | TWD |
| cold | `_logs/*.log` scorecard tail | TR1 |
| block | `session-open-reports`, `pfkt-manifests`, `_inbox/from_projects` | TR1 |

## 分析維度（機械 rubric）

| 維度 | 啟發式 |
|------|--------|
| **skill** | SUBMIT 含 verify/skill；重複 tool≥8 次 |
| **optimize** | 無 park · billable 高 · SLOW_PATH · compliance red |
| **parallel** | 多 open PFKT fragment · Task 無 wave |
| **pfkt** | broad explore 無 mint · open fragment 無 verify |

## 命名遷移

| 舊 | 新（口語） | lane id |
|----|-----------|---------|
| ZTM | **MTM** | `zero-token-mechanism` |
| ZCT | **MTO** | 同 lane |
| ZAT | MTO 交付單元 | `zat-verify-gate.py` 引擎名不變 |

## Curator 對話內用法

1. 跑 `--brief`，把輸出當本輪 PLAN 的證據
2. 只對 **MTD** 列（skill 取捨、架構）開模型判斷
3. 機械項 → `zct-task-router.py` / 子 agent / engines
