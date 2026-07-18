---
name: pfkt-parallel-wave
description: >-
  PFKT parallel execution — pfkt-wave plan, parallel-dag singleton gates, Multitask vs wave.
  Use before Task/fan-out/subagent or when PFKT deny-parallel fires.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: false
    engine: _skill/engines/pfkt-wave.py
    registry: _registry/parallel-gates.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# pfkt-parallel-wave — 平行 PFKT wave（ZT）

## 何時用

- Prompt 含 `parallel` / `Multitask` / `subagent` / `fan out` / `多路`
- PFKT gate `deny-parallel`（缺 wave plan 或 dag_check.ok）
- 準備 Cursor **Task** 多 agent 同 wave

## 機械步驟（0 LLM token）

### 1 確保 fragment manifest

```powershell
python %AI_WORKSPACE%\_skill\engines\pfkt-session-ensure.py --agent <seat>
```

### 2 Wave plan + DAG

```powershell
python %AI_WORKSPACE%\_skill\engines\pfkt-wave.py plan --stamp <STAMP>
```

驗證：`_temp/pf-wave-<STAMP>.json` 存在且 `dag_check.ok=true`。

### 3 Singleton 序列化

SSOT：`_registry/parallel-gates.json`

| singleton | 資源 |
|-----------|------|
| browser_auth | chrome / playwright |
| git_push_same_repo | 同 repo push |
| operator | AskQuestion |
| registry_write | agent-pptt-overrides / rules-blueprint |
| technique_output_write | curator only |

**禁止**：獨立 ZCT 葉無故串行；singleton 碰撞 = 下一 wave。

## Multitask vs pfkt-wave

| 情境 | 用 |
|------|-----|
| Cursor IDE 內多 subagent 同 prompt | **Multitask/Task** + pfkt-wave plan 先 mint |
| 背景 pythonw 批次 | pfkt-wave close-wave + HubClock |
| 單一複雜任務 | pfkt-fragment split → 非 parallel |

## 自動解鎖

Hook 會跑 `auto-gate-unblock` → `pfkt_session_ensure` + `pfkt_wave_plan`。  
手動：`python auto-gate-unblock.py --agent <seat> --gate pfkt`

## 配對 skill

- `mtm-mto-first` — 並行前 MTO
- `pfkt-auto-unblock` — gate deny Remediation
- `ztm-verify-before-done` — close-wave 前 evidence

## CITE

`_registry/pfkt-protocol.json` · `parallel-dag.py` · `pfkt-prompt-gate.py`
