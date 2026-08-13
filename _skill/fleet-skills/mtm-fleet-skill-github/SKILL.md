---
name: mtm-fleet-skill-github
description: >-
  Verified fleet-skill and FAMES federation through the ai_fleet_skills GitHub
  carrier for scar3, darkhero, and altos. Use for content-addressed pull,
  conflict-preserving install, contributor publication, or parity receipts.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: hubclock-only
    token_budget: zero
    engine: _skill/engines/mtm-fleet-skill-github.py
    portable_engine: scripts/receiver.py
    registry: _registry/fleet-skill-github.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# Verified GitHub fleet-skill federation

GitHub is the transport and contributor evidence carrier. The local
`_skill/fleet-skills/` directory remains each host's canonical runtime catalog.

## Carrier layout

```text
ai_fleet_skills/
  manifest.json
  _skill/fleet-skills/
  contributors/
    scar3/manifest.json
    darkhero/manifest.json
    altos/manifest.json       # UNKNOWN until the host publishes it
```

Every installed package must match a contributor's declared per-file hashes.
A missing contributor receipt remains UNKNOWN. It is never synthesized.

## Host receiver

The workspace-installed engine is preferred:

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-fleet-skill-github.py sync
```

A host without the workspace engine can bootstrap from this portable package:

```powershell
Copy-Item references\config.example.json C:\ai_workspace\_registry\fleet-skill-github.json
python scripts\receiver.py sync --config C:\ai_workspace\_registry\fleet-skill-github.json
```

Set `host`, `seat`, and `local_contributor` for the receiving machine before
the first run. The file contains no credentials.

## Safety contract

- Validate root-to-contributor manifest references and every declared file hash.
- Normalize text line endings before hashing; hash binary files as raw bytes.
- Add missing packages and update only packages recorded as receiver-managed.
- Preserve local modifications. Add remote-only portability files without
  overwriting locally changed files.
- Archive an invalid package without `SKILL.md` before repairing it.
- Use atomic swaps, singleton/stale-lock recovery, bounded subprocess timeouts,
  and `CREATE_NO_WINDOW` on Windows.
- Background receivers only pull. `publish` is an explicit curator action.
- Schedule recurring execution only through HubClock and `pythonw`.

## Publication

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-fleet-skill-github.py publish
```

Publication writes only the configured contributor namespace and regenerates
the content-addressed union. Commit and push the carrier after verification.

