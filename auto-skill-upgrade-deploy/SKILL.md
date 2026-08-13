---
name: adus-auto-deploy-upgrading-skill
description: >-
  ADUS (auto-deploy-upgrading-skill): 自動部署型自我進化技能 — detect, variable-ize,
  verify, promote fleet skill, deploy. Legacy alias ASU / auto-skill-upgrade-deploy.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: true
    concept_id: ADUS
    engine: _skill/engines/adus-deploy.py
    registry: _registry/adus-protocol.json
    lexicon: _registry/fleet-lexicon.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# ADUS — 自動部署型自我進化技能

> **Concept id:** `ADUS` · SSOT: `_registry/fleet-lexicon.json` + `_registry/adus-protocol.json`  
> **Legacy aliases:** ASU · `auto-skill-upgrade-deploy`（deploy 仍同步，詞彙不斷裂）

## When to use

- 解決可重用、可驗證 workflow（非一次性 prompt）
- 同引擎/命令序列 session 內重複 3+ 次
- Seat 本地 skill 尚未進 fleet canonical
- MTM waste scan 標 skill gap

**禁止**複製 REQUIRED fleet skill 到 seat — 用 **ADUS promote** 升級 canonical。

## 概念查詢（ZT）

```powershell
python %AI_WORKSPACE%\_skill\engines\lexicon-resolve.py ADUS --json
python %AI_WORKSPACE%\_skill\engines\lexicon-resolve.py --alias ASU
```

## Agent workflow (TR0)

### 1 Detect

```powershell
python %AI_WORKSPACE%\_skill\engines\adus-detect.py --agent {{agent}} --write
```

### 2 Draft

```powershell
python %AI_WORKSPACE%\_skill\engines\adus-generalize.py --agent {{agent}} --item-id <id>
```

### 3 Verify

```powershell
python %AI_WORKSPACE%\_skill\engines\adus-verify.py --agent {{agent}} --skill <skill-name>
```

### 4 Promote（curator cwd = ai_darkhero）

```powershell
python %AI_WORKSPACE%\_skill\engines\adus-promote.py --agent {{agent}} --skill <skill-name>
```

### 5 Orchestrator

```powershell
python %AI_WORKSPACE%\_skill\engines\adus-deploy.py --agent {{agent}} --max-items 3 --auto-promote
```

## Variable template（lexicon stable）

| Pattern | Placeholder |
|---------|-------------|
| Seat id | `{{agent}}` |
| Seat cwd | `{{seat_root}}` |
| Concept | `{{concept_id}}` → ADUS |
| Hub root | `%AI_WORKSPACE%` |

## Cross-links

| Skill | Role |
|-------|------|
| `ztm-skill-submit` | 手動 SUBMIT（ADUS 補充） |
| `mtm-mto-first` | prework |
| `pfkt-auto-unblock` | gate remediation |

## CITE

`_registry/fleet-lexicon.json` · `_registry/adus-protocol.json` · `adus-deploy.py`
