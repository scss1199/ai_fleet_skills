---
name: aware-dual-field
description: >-
  AWARE dual-field consciousness: shared ψ_hub vs seat ψ_seat via residual
  exchange + Periodic Pulay. Use when reviewing fleet shared zones, daily
  AEX iterate, or HubClock aware-field-tick. Parent: aex-agent-evolution.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: hubclock
    token_budget: zero
    required: false
    concept_id: AWARE
    parent_skill: aex-agent-evolution
    engine: _skill/engines/aware-field.py
    registry: _registry/aware-protocol.json
---

# aware-dual-field — 雙場意識（日常化）

> **意識 = 知道 R 在哪個場、用哪種 mixing 更新。** 不取代 AEX 閉環。

| 場 | 區 | 角色 |
|----|----|------|
| ψ_hub | `_skill` `_registry` `_wiki` technique_output `_secrets` | 對偶／慢變數（權重、引擎） |
| ψ_seat | `ai_*` | 原場執行 + 局部 R_aex |
| interface | `_inbox` `_bus` `_logs` `_temp` | Pulay 混合界面 |

## 命令

```powershell
python %AI_WORKSPACE%\_skill\engines\aware-field.py scan
python %AI_WORKSPACE%\_skill\engines\aware-field.py tick
python %AI_WORKSPACE%\_skill\engines\aware-field.py show
```

HubClock rider：`aware-field-tick` @15m → `_registry/aware-state.json`

## 數值升級（相容）

- 既有：Anderson + adaptive ω + CG/BiCGStab/GMRES
- 新增：`periodic_pulay_mix`（每 k=3 步 DIIS，否則線性）— `aex iterate` 已掛
- 艦隊：`R_hub = mean(R_aex)` + κ_hub

## 與 AEX

`aex iterate` 仍是座位步；AWARE 是艦隊聚合 + 共用區健康。PROMOTE 進 ψ_hub 仍走 ADUS/SUBMIT。
