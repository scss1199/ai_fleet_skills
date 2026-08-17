---
name: mtm-fleet-skill-github
description: >-
  MTM fleet skill federation via shared GitHub repo ai_fleet_skills.
  contributors/darkhero, contributors/scar3, and contributors/altos publish isolated receipts.
  HubClock tick for dynamic cross-machine skill sync.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: hubclock-only
    token_budget: zero
    engine: _skill/engines/mtm-fleet-skill-github.py
    registry: _registry/fleet-skill-github.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# mtm-fleet-skill-github — 共享 skill repo（三機分目錄）

> **Repo:** `github.com/scss1199/ai_fleet_skills`  
> **SSOT:** `_registry/fleet-skill-github.json`

## 目錄（區分上傳來源）

```
_skill/ai_fleet_skills/
  manifest.json              # union（darkhero + scar3）
  contributors/
    darkhero/skills/...      # darkhero 機 · ai_darkhero 策展
    scar3/skills/...         # scar3 機 · ai_scar3 策展
    altos/skills/...         # altos 機 · ai_altos follower
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

pull 讀 `contributors/darkhero/`；每台主機只寫自己的 contributor 目錄。

FAMES `converge` 會先跑本機正／負控制並寫
`_registry/fames-capabilities/<seat>.json`，再由 FAMES 自帶 publisher 只更新
`contributors/<host>/fames-capability.json`。這條能力 receipt 路徑不依賴本 engine
是否已升級，也不會被「skills 沒變」的快路徑跳過。
中央 `verify-fleet` 必須同時驗 package、capability set、validator set、runner、
caller 與 receipt freshness；三份 contributor manifest 缺一即不是 full convergence。

## 本機 SSOT

策展仍在本機 `_skill/fleet-skills/`；GitHub 只做同步與跨機學習。
