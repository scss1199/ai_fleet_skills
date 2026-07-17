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
---

# mtm-mto-first — 機械先行（止 TRN 燒 token）

> **證據**：全艦 top sessions — `Read×614` `Bash×593` `Edit×651`（`20260608 fracdigi` 70M billable）；  
> **根因**：skill 有但未裝（deploy bug）或未跑 prework/router。

## 何時用（強制）

- 任務開始前（SessionStart 後第一動作）
- 準備第 2 次 `Read` / `Grep` / `Shell` 同一主題
- 準備 `Task` / 多 agent 並行
- 準備 browser / CDP

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
| milestone | `ztm-goal-compact-enforce` park |
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
