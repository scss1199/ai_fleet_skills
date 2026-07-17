---
name: mtm-obsidian-wiki
description: >-
  Hub Obsidian LLM Wiki + MTM shared knowledge. Vault C:/ai_workspace/_wiki (data zone, not a project seat).
  TR0: keywords → mtm-wiki-query --brief → resolve 1–3 pages max.
  Never full-Read the vault. onepkg/digest via engines; inbox compile via digest.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: hubclock-only
    token_budget: zero
    engine: _skill/engines/mtm-wiki-query.py
    registry: _registry/fleet-wiki-knowledge.json
    sub_skills:
      - mtm-wiki-query
      - mtm-wiki-absorb
      - mtm-wiki-onepkg
      - mtm-wiki-digest
---

# mtm-obsidian-wiki — Wiki-first MTM（TR0）

> **Vault SSOT:** `C:\ai_workspace\_wiki`（資料區，與 `_skill`／`_registry` 同級；**不是** project seat）  
> **Proto:** `_registry/fleet-wiki-knowledge.json`

## TR0

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-wiki-query.py query "<keywords>" --brief
python %AI_WORKSPACE%\_skill\engines\mtm-wiki-query.py resolve <slug>
```

## Absorb OneNote (P: backup → local scss1199)

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-wiki-onenote-absorb-job.py run --phase all
python %AI_WORKSPACE%\_skill\engines\mtm-wiki-onenote-absorb-job.py status
```

Root: `P:\_Backup\scss_1015\__Work\_Intel\__onenote` then `Documents\OneNote Notebooks\scss1199`
