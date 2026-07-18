---
name: mtm-fleet-skill-github
description: >-
  MTM fleet skill federation via shared GitHub repo ai_fleet_skills.
  contributors/darkhero = darkhero uploads; contributors/scar3 = scar3 uploads.
  HubClock tick for dynamic cross-machine skill sync.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: hubclock-only
    token_budget: zero
    engine: _skill/engines/mtm-fleet-skill-github.py
    registry: _registry/fleet-skill-github.json
---

# mtm-fleet-skill-github — 共享 skill repo（雙機分目錄）

> **Repo:** `github.com/scss1199/ai_fleet_skills`  
> **SSOT:** `_registry/fleet-skill-github.json`

## 目錄（區分上傳來源）

```
ai_fleet_skills/
  manifest.json              # union（darkhero + scar3）
  contributors/
    darkhero/skills/...      # darkhero 機 · ai_darkhero 策展
    scar3/skills/...         # scar3 機 · ai_scar3 策展
```

Commit 訊息：`chore(skills/darkhero): ...` 或 `chore(skills/scar3): ...`

## darkhero

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-fleet-skill-github.py push --node ai_darkhero
```

## scar3

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-fleet-skill-github.py sync --node ai_scar3
```

pull 讀 `contributors/darkhero/`；push 只寫 `contributors/scar3/`。

## 本機 SSOT

策展仍在本機 `_skill/fleet-skills/`；GitHub 只做同步與跨機學習。
