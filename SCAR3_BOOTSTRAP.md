# scar3 bootstrap

On **scar3** machine after clone:

```powershell
git clone https://github.com/scss1199/ai_fleet_skills.git C:\ai_workspace\ai_fleet_skills
cd C:\ai_workspace\ai_scar3
python %AI_WORKSPACE%\_skill\engines\mtm-fleet-skill-github.py sync --node ai_scar3
```

- **Pull** reads `contributors/darkhero/` (darkhero uploads)
- **Push** writes `contributors/scar3/` (scar3 local innovations)

Commit messages: `chore(skills/scar3): ...`
