---
name: pfkt-auto-unblock
description: >-
  Auto-gate-unblock remediation for A2A and accountability prompt denies.
  The PFKT prompt gate no longer denies (pfkt-v4); its v2 HARD DENY chains are retired.
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
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# pfkt-auto-unblock — gate remediation（ZT）

> pfkt-v4（2026-09-30）：PFKT 不再是逐 prompt 的 gate。`pfkt-prompt-gate.py` 對每個 prompt 都回 `allow`，
> 只在點名平行工作時建議開 work graph（`pfkt_work_graph.py`）。v2 的 PFKT HARD DENY 與其 remediation chain
> （`pfkt_session_ensure` / `pfkt_wave_plan` / `pfkt_set_active_fid`）已退役，見
> `_registry/auto-gate-protocol.json#retired_remediation_chains` 與 `_registry/pfkt-protocol.json`。
> 技能名稱保留給仍引用它的 seat；實際處理的是 A2A 與 accountability。

## 何時用

- `beforeSubmitPrompt` deny（A2A / Accountability）
- inbox stuck、probation ship/done
- Curator 代跑 blocked seat 恢復 `emit_allow`

## 指令

```powershell
# 偵測 + 最多 3 輪 remediation
python %AI_WORKSPACE%\_skill\engines\auto-gate-unblock.py --agent <seat> --gate all

# 單 gate
python %AI_WORKSPACE%\_skill\engines\auto-gate-unblock.py --agent <seat> --gate a2a
python %AI_WORKSPACE%\_skill\engines\auto-gate-unblock.py --agent <seat> --gate accountability

# 乾跑
python %AI_WORKSPACE%\_skill\engines\auto-gate-unblock.py --agent <seat> --dry-run --json
```

報告：`_registry/auto-gate-unblock/<seat>-latest.json`

## Remediation chain（SSOT `_registry/auto-gate-protocol.json#remediation_chains`）

| Gate | Rule | Steps |
|------|------|-------|
| a2a | * | inbox_absorb → inbox_pickup_ack |
| accountability | inbox_lock | inbox_absorb → inbox_pickup_ack → accountability_sweep |
| accountability | probation_lock | result_field_template（機械，不造假 evidence）→ accountability_sweep |
| accountability | suspended / * | inbox_absorb → accountability_sweep |

PFKT 沒有 chain：若 PFKT deny 重新出現，它會保持為可見的 block，而不是被 mint fragment 清掉。

## PFKT 現在怎麼用（v4）

- 多個可獨立驗證的交付或明確平行工作：`pfkt_work_graph.py open --plan <plan.json>` → `status` 取可派 wave →
  `close-node --node <id> --evidence <path>` → `closure` 交 SEAL。
- graph OPEN / UNKNOWN 時 SEAL 擋完成宣稱；OPEN 逾 24h = `pfkt-graph-stale` 合規 flag。
- `pfkt-fragment.py` / `pfkt-wave.py` 仍是 v2 manifest 的手動工具，非必要。

## Hook 整合

`cursor-auto-gate-unblock.py` — 偵測到 block 時 silent remediation，再 re-check sibling gates。

`cursor-pfkt-gate.py` — 每個 prompt 放行，只附 work-graph 建議。

## 無法自動修

- `suspended` + fake-delivery — 需 curator `accountability-unblock` skill
- probation ship/done — 仍 deny（僅 template 提示）

## CITE

`_registry/auto-gate-protocol.json` · `_registry/pfkt-protocol.json` · `auto-gate-unblock.py` · `pfkt_work_graph.py`
