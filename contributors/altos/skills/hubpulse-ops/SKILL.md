---
name: hubpulse-ops
description: >-
  HUBPULSE fabric: redefined HubClock (metronome) + hub_tray ops + skill
  create→deploy→agent apply. Use for rider bands, Restart HubClock, Deploy
  fleet skills, ADUS/SUBMIT lifecycle. Parent: aex-agent-evolution.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: hubclock
    token_budget: zero
    required: false
    concept_id: HUBPULSE
    parent_skill: aex-agent-evolution
    engine: _skill/engines/hubpulse.py
    registry: _registry/hubpulse-protocol.json
---

# hubpulse-ops — 艦橋脈衝織

> **禁止再教「HubClock = 排程」單層。**  
> HubClock = 節拍 · Tray = 操作面 · fleet-skills = 能力織 · AWARE = 意識場。

## 四層

| 層 | 是什麼 | 引擎／契約 |
|----|--------|------------|
| metronome | `hubclock.py` 牆鐘 rider | `hosts.json` HubClock |
| operator_surface | `hub_tray` | `fleet-tray-contract.json` |
| capability_fabric | create→promote→deploy→apply | `fleet-skill-sync.py` + ADUS |
| field_awareness | ψ_hub / ψ_seat | `aware-field.py` |

## Rider 頻帶

- **FREQ** ≤1m — 輕量（net-poll…）
- **OPS** 2–30m — inbox / mandatory / **fleet-skill-pulse** / aware / tray-ensure
- **FIELD** ≥1h 或 @daily — `hub-ztm-tick`（plan-usage）重鏈

```powershell
python %AI_WORKSPACE%\_skill\engines\hubpulse.py status
python %AI_WORKSPACE%\_skill\engines\hubpulse.py classify
```

## Tray 操作（Hub 區）

| 動作 | 意義 |
|------|------|
| Open Hub Dashboard | portal |
| Restart HubClock | 節拍層修復（禁止 silent auto-restart） |
| Deploy fleet skills | 立刻 `hubpulse skills-apply` |
| Open HubPulse status | `_registry/hubpulse-state.json` |
| Watch | memory-watch（見 tray-memory-watch） |
| Ship | ship_autopilot 背景 queue |

## Skill 建立 → 各 agent 應用

```
CREATE (ADUS / seat draft)
  → SUBMIT skill-update-*.md
  → ABSORB incubator
  → PROMOTE _skill/fleet-skills/
  → DEPLOY → each seat .cursor/skills/   ← fleet-skill-pulse @15m
  → APPLY (agent CONSUME; entry=aex-agent-evolution)
  → FEDERATE (mtm-fleet-skill-github 跨機)
```

```powershell
python %AI_WORKSPACE%\_skill\engines\hubpulse.py skills-apply
python %AI_WORKSPACE%\_skill\engines\fleet-skill-sync.py verify
```

**REQUIRED** 含 `aex-agent-evolution`（教學入口）。Seat 禁止手抄 REQUIRED skill — 只走 deploy。

## 配對

- `tray-memory-watch` · `fleet-proc-hygiene`
- `adus-auto-deploy-upgrading-skill` · `ztm-skill-submit`
- `aware-dual-field` · `aex-agent-evolution`
