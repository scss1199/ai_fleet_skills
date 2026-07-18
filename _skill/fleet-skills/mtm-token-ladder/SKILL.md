---
name: mtm-token-ladder
description: >-
  LEGACY alias → aex-agent-evolution (AEX Agent Evolution Index).
  Do not teach token-ladder as OS; resolve AEX instead.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: false
    concept_id: LADDER
    renamed_to: AEX
    engine: _skill/engines/fleet-token-ladder.py
    registry: _registry/fleet-token-ladder.json
---

# mtm-token-ladder — SUPERSEDED

> **改用 [`aex-agent-evolution`](../aex-agent-evolution/SKILL.md)。**  
> Token Ladder v1 → **AEX** 飛輪；MTM/PFKT 僅儀器。

```powershell
python %AI_WORKSPACE%\_skill\engines\fleet-token-ladder.py show --brief
python %AI_WORKSPACE%\_skill\engines\fleet-token-ladder.py resolve LADDER
```
