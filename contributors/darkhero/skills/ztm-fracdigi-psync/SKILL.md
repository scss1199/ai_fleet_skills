---
name: ztm-fracdigi-psync
description: fracdigi psync deploy and ship for new.messages component. Use on psync deploy; never touch hub _secrets vault.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: operator-gated
    scheduler: session
    token_budget: zero
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# ztm-fracdigi-psync — new.messages ship（高爭議 seat 專用）

**cwd=`fracdigi`** · PRIMARY=`GitHub/new.messages.fracdigi.com` · lane **zero-token-mechanism** · secrets **operator-gated**

## 紅線

- 憑證：**fracdigi-private vault**，勿碰 hub `_secrets`
- **禁止** Firebase deploy from psync repo
- popup-gate：對 **psync repo 路徑**跑 gate，勿掃整個 `.secrets` chrome profile

## 本輪機械流程

```powershell
cd C:\ai_workspace\fracdigi\GitHub\new.messages.fracdigi.com
python C:\ai_workspace\_skill\engines\zt-popup-gate.py gate C:\ai_workspace\fracdigi\GitHub\new.messages.fracdigi.com
powershell -File ship.ps1 -DryRun   # 先 dry-run
python C:\ai_workspace\_skill\engines\ship-queue.py request .
```

## PFKT

Wave 0+1 多 lane → `pfkt-fragment.py split --agent fracdigi --title "psync consolidation" --verify "npm run build"`

## SUBMIT

`_inbox/from_projects/fracdigi/consolidation-*.md` + ack inbox

Handoff: `ai_darkhero/_dispatch/handoff-fracdigi-consolidation-plan.md`
