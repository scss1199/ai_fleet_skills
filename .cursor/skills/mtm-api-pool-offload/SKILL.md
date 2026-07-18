---
name: mtm-api-pool-offload
description: >-
  POOL-Skill: offload bulk context work to free-tier API pool in parallel. Results
  go to cold artifacts; agent reads compact only. Species POOL.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: vault-schema-only
    scheduler: on-demand
    token_budget: zero-local
    required: false
    concept_id: POOL_OFFLOAD
    species: POOL
    registry: _registry/skill-taxonomy.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# POOL — Context 外包（API Pool Offload）

> **Species:** `POOL` · SSOT: `_registry/skill-taxonomy.json`

## When to use

- 大量 **讀檔 / 摘要 / 分類 / 比對** 占 agent context
- AGC 逼近 `uncompact_upper_limit`
- Vault 有免費 tier 或 seat 已有 API pool pattern（如 Groq）

## TR0 workflow

### 1 Schema-only 探測（禁印 key）

```powershell
python %AI_WORKSPACE%\_skill\engines\auth_check.py check <provider>
```

只讀 vault **schema / count**，不讀 value。

### 2 平行編排

```powershell
python %AI_WORKSPACE%\_skill\engines\pfkt-wave.py plan --stamp <STAMP>
```

- 多路 API 呼叫 → 寫 **cold artifact**（`brain/`、`_registry/`、`_temp/`）
- Agent 只 Read **摘要檔**（≤50 行）

### 3 禁止

- 把整份 API response 貼進 chat
- 無 pfkt-wave 就 fan-out 10 路 shell

## 已知 pool patterns（CONSUME 再擴）

| Seat | Pattern |
|------|---------|
| ai_news / ai_fintrend | Groq distill chain |
| fleet | `_secrets` vault keys by service |

## Reflect（ADUS 三問之三）

> 這步在燒我的 context 嗎？→ **POOL** 代勞 + 平行。

## CITE

`_registry/skill-taxonomy.json` · `agc-auto-goal-compact` · `pfkt-parallel-wave`
