---
name: auto-skill-upgrade-deploy
description: >-
  Auto-skill-upgrade-deploy (ASU): detect reusable patterns, draft seat skills,
  verify, promote to fleet canonical, deploy. Use after fixing something reusable.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: true
    engine: _skill/engines/asu-deploy.py
    registry: _registry/asu-protocol.json
---

# auto-skill-upgrade-deploy (ASU) — seat skill → fleet canonical

> SSOT: `_registry/asu-protocol.json` · Curator: `ai_darkhero`

## When to use

- You solved a problem with a **reusable, verify-able** workflow (not one-off prompt)
- Same engine/command sequence repeated 3+ times in session
- Seat-local `.cursor/skills/` not yet in fleet canonical
- MTM waste scan flags a skill gap

**Do NOT** duplicate fleet REQUIRED skills locally — **upgrade via ASU promote**.

## Agent workflow (TR0)

### 1 Detect

```powershell
python %AI_WORKSPACE%\_skill\engines\asu-detect.py --agent {{agent}} --write
```

### 2 Draft (generalize + variable-ize)

```powershell
python %AI_WORKSPACE%\_skill\engines\asu-generalize.py --agent {{agent}} --item-id <id>
# or from SUBMIT:
python %AI_WORKSPACE%\_skill\engines\asu-generalize.py --from-submit _inbox/from_projects/{{agent}}/topic.md --agent {{agent}}
```

Draft lands in `_registry/asu-drafts/{{agent}}/<skill>/SKILL.md`.

### 3 Verify

```powershell
python %AI_WORKSPACE%\_skill\engines\asu-verify.py --agent {{agent}} --skill <skill-name>
```

### 4 Promote

- **Non-curator seats:** draft only → `_registry/asu-pending/` (curator promotes)
- **Curator (`ai_darkhero` cwd):**

```powershell
python %AI_WORKSPACE%\_skill\engines\asu-promote.py --agent {{agent}} --skill <skill-name>
```

### 5 One-shot orchestrator

```powershell
python %AI_WORKSPACE%\_skill\engines\asu-deploy.py --agent {{agent}} --max-items 3 --auto-promote
```

## Variable template rules

| Pattern | Placeholder |
|---------|-------------|
| Seat id | `{{agent}}` |
| Seat cwd | `{{seat_root}}` |
| Hub root | `%AI_WORKSPACE%` (never hardcode `C:\ai_workspace`) |
| Secrets | **forbidden** in body — schema-only refs |

## Cross-links

| Skill | Role |
|-------|------|
| `ztm-skill-submit` | Manual SUBMIT format when ASU not enough |
| `mtm-mto-first` | prework before broad reads |
| `pfkt-auto-unblock` | gate remediation |
| `ztm-verify-before-done` | evidence before done |

## Curator converge

```powershell
python %AI_WORKSPACE%\_skill\engines\asu-converge.py --max-rounds 4
python %AI_WORKSPACE%\_skill\engines\fleet-skill-sync.py deploy --seats-only
python %AI_WORKSPACE%\_skill\engines\sync-cursor-hooks.py
python %AI_WORKSPACE%\_skill\engines\cursor_bootstrap_pack.py
python %AI_WORKSPACE%\_skill\engines\agc-hot-apply.py
```

## CITE

`_registry/asu-protocol.json` · `fleet-skill-sync.py` · `asu-detect.py`
