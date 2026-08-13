<!-- absorbed from ai_darkhero_integration/skill-update-mtm-claude-remnant-cleanup-2026-07-08.md @ 2026-07-08T20:13:38 -->

# skill-update — mtm-claude-remnant-cleanup

**Date:** 2026-07-08  
**From:** ai_darkhero_integration  
**Skill:** `mtm-claude-remnant-cleanup`  
**Canonical:** `_skill/fleet-skills/mtm-claude-remnant-cleanup/`

## Why fleet skill

Operator: Claude remnant cleanup must be **MTM-first** — one tick, 0 token, deployable. Curator does not run this line; integration seat does.

## What upgraded (Wave 1)

| Piece | Change |
|-------|--------|
| `mtm-claude-tick.py` | **NEW** one-liner: absorb×2 → quarantine → sweep |
| SKILL.md | One-liner first; when/how/red-lines; cite protocol |
| absorb | Narrow stub classify; archive noise skipped (jira/news portal dumps) |
| protocol | `one_liner` + tick engine; allowlist `ztm-task-routes.json` |
| `ztm-task-routes.json` | Route `mtm-claude-remnant-cleanup` |

## Verify (green)

```text
mtm-claude-tick.py --brief
→ ok:true absorb stable quarantine applied sweep remaining_hits:0
ztm-task-router "claude cleanup" → mtm-claude-tick.py --brief
lexicon-sync issues=0
```

## Deploy

```powershell
python %AI_WORKSPACE%\_skill\engines\fleet-skill-sync.py deploy --seats-only
```

Already deployed to `ai_darkhero` + `ai_darkhero_integration`. Promote note: skill is already under `_skill/fleet-skills/` (canonical); no incubator needed.

## Red lines unchanged

Move-only quarantine · operator permanent delete · no secrets print
