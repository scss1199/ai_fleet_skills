---
name: pfkt-auto-unblock
description: >-
  Auto-gate-unblock remediation for PFKT/A2A/accountability HARD DENY.
  Use when beforeSubmitPrompt blocked or agent stuck on gate criteria.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: false
    engine: _skill/engines/auto-gate-unblock.py
    registry: _registry/auto-gate-protocol.json
---

# pfkt-auto-unblock — gate 強制 remediation（ZT）

## 何時用

- `beforeSubmitPrompt` HARD DENY（PFKT / A2A / Accountability）
- inbox stuck、multi-fid、probation ship/done
- Curator 代跑 blocked seat 恢復 `emit_allow`

## 指令

```powershell
# 偵測 + 最多 3 輪 remediation
python %AI_WORKSPACE%\_skill\engines\auto-gate-unblock.py --agent <seat> --gate all

# 單 gate
python %AI_WORKSPACE%\_skill\engines\auto-gate-unblock.py --agent <seat> --gate pfkt
python %AI_WORKSPACE%\_skill\engines\auto-gate-unblock.py --agent <seat> --gate a2a
python %AI_WORKSPACE%\_skill\engines\auto-gate-unblock.py --agent <seat> --gate accountability

# 乾跑
python %AI_WORKSPACE%\_skill\engines\auto-gate-unblock.py --agent <seat> --dry-run --json
```

報告：`_registry/auto-gate-unblock/<seat>-latest.json`

## Remediation chain（SSOT）

| Gate | Rule | Steps |
|------|------|-------|
| pfkt | deny-load-bearing | goal_field_mint → pfkt_session_ensure |
| pfkt | deny-parallel | pfkt_session_ensure → pfkt_wave_plan |
| pfkt | deny-multi-fragment | pfkt_set_active_fid |
| a2a | * | inbox_absorb → inbox_pickup_ack |
| accountability | inbox_lock | inbox_absorb → sweep |
| accountability | probation_lock | result_field template（機械，不造假 evidence） |

## Hook 整合

`cursor-auto-gate-unblock.py` — session 1x silent try → sibling gates re-check。

`cursor-pfkt-gate.py` — deny 前再跑 `--gate pfkt` 一輪。

## 無法自動修

- `deny-unverified-done` — 需真實 `pfkt-fragment.py done --evidence`
- `suspended` + fake-delivery — 需 curator `accountability-unblock` skill
- probation ship/done — 仍 deny（僅 template 提示）

## CITE

`_registry/auto-gate-protocol.json` · `hub_auto_gate.py`
