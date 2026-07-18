---
name: ztm-fleet-intelligence
description: >-
  Fleet intelligence amplifier: passive absorb from Vercel when machine off, local
  SSOT when on. Curator ai_darkhero deploys skills+digest to all seats. Zero-token.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: true
    concept_id: FLEET_INTEL
    engine: _skill/engines/fleet-intelligence-gen.py
    registry: _registry/skill-taxonomy.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# Fleet Intelligence — 全艦變聰明（被動吸收）

> **Curator:** `ai_darkhero` · **Live:** `https://ai-darkhero.vercel.app` · 關機仍可讀 JSON（SSO 保護）

## 核心想法

**你變聰明 = 全艦 agent 裝同一套 skill + digest。**  
Curator 用最少 token 維護 SSOT → Vercel 被動散播 → 各 seat SessionStart 吸收。

## SessionStart（TR0，禁全文 Read skill 目錄）

### 機器開著

```powershell
python %AI_WORKSPACE%\_skill\engines\prework.py "<task>" --agent {{agent}}
type %AI_WORKSPACE%\_registry\fleet-passive-absorb.json
```

### 機器關著 / 遠端

Fetch（browser 或 curl，**只取 JSON 不貼 chat**）：

- `https://ai-darkhero.vercel.app/fleet-skills-digest.json`
- `https://ai-darkhero.vercel.app/fleet-intelligence.json`

## Curator 維護（ai_darkhero only）

```powershell
python %AI_WORKSPACE%\_skill\engines\fleet-skill-sync.py tick
python %AI_WORKSPACE%\_skill\engines\fleet-intelligence-gen.py
powershell -File C:\ai_workspace\ai_darkhero\ship.ps1
```

HubClock `hub-ztm-tick` 已鏈 `fleet-skill-sync deploy` + `hub-portal-gen`；ship 上 Vercel。

## 必裝 skill 物種

| 物種 | Skill | 作用 |
|------|-------|------|
| MTE | `mtm-mte-mint` | 重複→腳本 |
| VAR | `ztm-cursor-edge-auth` | 認證變體+OOM |
| POOL | `mtm-api-pool-offload` | context→API |
| Meta | `ADUS` | 自主演化 |

## ADUS reflect 三問（每 milestone）

1. 重複第三次？→ MTE  
2. 新網站組合？→ VAR  
3. 燒 context？→ POOL  

## CITE

`_registry/skill-taxonomy.json` · `fleet-intelligence-gen.py` · `fleet-passive-absorb.json`
