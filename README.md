# ai_fleet_skills

Fleet skill federation — **one GitHub repo**, per-machine contributor directories.

| Path | Who uploads |
|------|-------------|
| `contributors/darkhero/` | darkhero PC · `ai_darkhero` curator |
| `contributors/scar3/` | scar3 PC · `ai_scar3` curator |

Each node writes only its own `contributors/<node>/` directory. Fleet receipts
read the contributor manifests directly, avoiding a multi-writer root manifest.

## Commands

```powershell
# darkhero
python %AI_WORKSPACE%\_skill\engines\mtm-fleet-skill-github.py push --node ai_darkhero

# scar3
python %AI_WORKSPACE%\_skill\engines\mtm-fleet-skill-github.py sync --node ai_scar3
```

Local canonical SSOT remains `%AI_WORKSPACE%\_skill\fleet-skills\`.
