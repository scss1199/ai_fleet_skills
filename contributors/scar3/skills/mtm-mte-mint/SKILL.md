---
name: mtm-mte-mint
description: >-
  MTE-Skill: when an agent repeats the same action 3+ times, mint a minimal-token
  engine script instead of TRN loops. Pairs with ADUS detect→promote. Species MTE.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: false
    concept_id: MTE
    species: MTE
    engine: _skill/engines/adus-detect.py
    registry: _registry/skill-taxonomy.json
---

# MTE — 重複動作腳本化（Minimal Token Engine Skill）

> **Species:** `MTE` · SSOT: `_registry/skill-taxonomy.json` · 演化: `ADUS`

## When to use（強制自省）

- 同 engine / 同 Shell 序列 **session 內第 3 次**
- `mtm-token-waste-scan --brief` 標 `skill_gap` 或 `tool_shell_loop`
- 任務結束前問：**下次還會重做嗎？**

## TR0 workflow

### 1 Detect repeat

```powershell
python %AI_WORKSPACE%\_skill\engines\adus-detect.py --agent {{agent}} --write
```

### 2 Mint engine（不寫進 chat）

- 單一入口 `*.py` + `--agent` + exit code verify
- 變數用 lexicon：`{{agent}}` `%AI_WORKSPACE%`
- 禁止把 raw 輸出貼進對話

### 3 Verify

```powershell
python %AI_WORKSPACE%\_skill\engines\adus-verify.py --agent {{agent}} --skill <draft-name>
```

### 4 Promote（curator cwd = ai_darkhero）

```powershell
python %AI_WORKSPACE%\_skill\engines\adus-promote.py --agent {{agent}} --skill <draft-name>
python %AI_WORKSPACE%\_skill\engines\fleet-skill-sync.py deploy --seats-only
python %AI_WORKSPACE%\_skill\engines\fleet-intelligence-gen.py
```

## Reflect（ADUS 三問之一）

> 這步有沒有重複第三次？→ **MTE** 腳本化，禁第 4 次 TRN。

## CITE

`_registry/skill-taxonomy.json` · `adus-auto-deploy-upgrading-skill` · `mtm-mto-first`
