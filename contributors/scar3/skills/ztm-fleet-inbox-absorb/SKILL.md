---
name: ztm-fleet-inbox-absorb
description: Fleet A2A inbox via HubClock background absorb. Use when inbox>0, a2a-read-gate blocks, or reading fleet-pickup digest. Execute and ack — never wait for operator pickup.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: hybrid
    token_budget: zero
---

# ZCT fleet-inbox-absorb — 全艦 A2A（HubClock 背景，零 operator 步驟）

**SSOT:** `_skill/fleet-skills/ztm-fleet-inbox-absorb/SKILL.md` · tags: `_registry/fleet-skill-lanes.json`

## SSOT：HubClock 背景跑，不是 Cursor reload

| Rider | Cadence | 做什麼 |
|-------|---------|--------|
| **fleet-inbox-absorb-tick** | **@5m** | 全 hub seat 自動 pickup + stamp + 寫 state |
| **fleet-mandatory-tick** | @15m | 合規 sweep + directive + portal |
| **hub-ztm-tick** | @2h | 鏈式含 absorb + skill-sync + portal |

狀態檔：`_registry/fleet-inbox-absorb-state.json`  
gate 讀 `last_absorb_at`（25m 內）→ **allow**，不需 operator 手打 `inbox.py pickup`。

## Agent 必做

1. HubClock 已代讀 — 看 SessionStart 或 `_registry/fleet-pickup/<seat>.md`
2. **執行 + ack** — `python $env:AI_WORKSPACE\_skill\engines\fleet-inbox-absorb.py ack <id>`
3. 有 skill 可推廣 → 見 **ztm-skill-submit**

## 手動 debug

```powershell
pythonw $env:AI_WORKSPACE\_skill\engines\fleet-inbox-absorb-tick.py
```
