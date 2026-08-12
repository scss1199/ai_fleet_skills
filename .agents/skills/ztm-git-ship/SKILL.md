---
name: ztm-git-ship
description: Zero-token git commit and push via git_smart.py --ztm. Use at milestones when repo has changes. Never ask operator to push.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# ztm-git-ship — 0-token git commit（+ push）

**CITE:** `git_smart.py --ztm` · lane **zero-token-mechanism**

## 本地 seat（無 Vercel）

```powershell
.\ship.ps1
# 或
python $env:AI_WORKSPACE\_skill\engines\git_smart.py commit-push . --zct
```

`--zct` = 檔名清單產生 commit message，**零 LLM token**。

## 有 deploy 的 web seat

用各 repo 的 `ship.ps1` / `ship.py`（Vercel probe 內建）。Curator 不問 operator push。

## 禁止

- 裸 `git diff` 進 agent context
- 問 operator「要不要 commit/push」
