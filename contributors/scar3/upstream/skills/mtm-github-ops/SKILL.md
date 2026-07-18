---
name: mtm-github-ops
description: >-
  MTM-first GitHub/repo operations: architecture snapshot, structural cross-seat diff,
  static runtime prediction — all TR0 engines, no full-repo reads. Use before exploring
  repos, comparing fleet seats, or pre-ship verification. Pairs with ztm-git-ship + git-token-guard.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: false
    engine: _skill/engines/mtm-github-fleet-scan.py
    registry: _registry/mtm-protocol.json
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# mtm-github-ops — MTM GitHub 機械先行

> **對齊 fracdigi**：`git-token-guard.ps1` 阻擋 raw `git diff`/`gh --log`；本 skill 用 **結構指紋** 取代全文 diff。  
> **ship 慣例**：`git_smart.py commit-push` + `ship-queue.py`（見 `ztm-git-ship`）。  
> **CITE:** `_registry/mtm-protocol.json` · `mtm_github_lib.py` · `fracdigi mfoMeta.ts`

## 何時用（強制於 TRN 前）

- 探索陌生 repo / 跨 seat 比較架構
- 進 ship 前快速靜態檢查（syntax / scripts / lockfile drift）
- Curator 全艦 GitHub 健康掃描
- **禁止**：未跑本 skill 就 `Read` 整個 repo / `@codebase` / raw `git diff`

## MTO 工作流（arch → static → diff）

### 0 CONSUME

```powershell
python %AI_WORKSPACE%\_skill\engines\prework.py "github repo diff architecture" --agent <seat>
```

### 1 架構快照 — TR0

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-github-arch.py --seat <seat> --max-chars 4000
python %AI_WORKSPACE%\_skill\engines\mtm-github-arch.py --repo fracdigi/new.messages.fracdigi.com --json
python %AI_WORKSPACE%\_skill\engines\mtm-github-arch.py --path C:\ai_workspace\ai_trader
```

輸出：top dirs、manifests、languages（`gh api` 或本地推斷）、entry points、git branch/dirty。

### 2 靜態預測 — TR0

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-github-static.py --seat <seat>
```

- Python：`ast` 語法 + import 圖（不 install）
- JS/TS：`package.json` scripts；有 `tsconfig.json` 時嘗試 `tsc --noEmit`（timeout，缺 deps 不阻擋）

### 3 結構 diff — 僅需要時

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-github-diff.py --seat-a ai_trader --seat-b ai_darkhero
python %AI_WORKSPACE%\_skill\engines\mtm-github-diff.py --seat-a fracdigi --seat-b ai_demo --files package.json,AGENTS.md
```

- 預設：**目錄 + manifest + lockfile hash**，非全文
- `--files`：bounded `git diff --stat --no-index`（符合 git-token-guard）

### 4 全艦掃描 — TR1

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-github-fleet-scan.py --write --brief
```

持久化：`_registry/mtm-audit/github-fleet-latest.json`（portal / 下一輪 chat 單檔讀取）。

## Token 規則

| 禁止 (TRN) | 改用 (TR0/TR1) |
|------------|----------------|
| 整 repo Read | `mtm-github-arch.py --max-chars N` |
| raw `git diff` | `mtm-github-diff.py` 或 `git diff --stat` |
| `gh run view --log` | `gh_ci.py` 或 `--log-failed \| head` |
| 逐檔探索 entry | `mtm-github-static.py` + project-matrix `entry` |

## fracdigi 對齊

| 項目 | 慣例 |
|------|------|
| PRIMARY deploy | `fracdigi/GitHub/new.messages.fracdigi.com`（psync） |
| READ-ONLY refs | `insights.fracdigi.com`, `messages.fracdigi.com` |
| meetings | `fracdigi/meetings` — Python pipeline，無 gh push |
| ship | `ship.bat` = `git_smart` + `vercel --prod` |
| token guard | hooks `git-token-guard.ps1` — 與本 skill 互補 |

project-matrix `components` 用 `--seat fracdigi` 或 `--repo owner/repo` 解析。

## 配對 skill

| 情境 | skill |
|------|-------|
| commit/push | `ztm-git-ship` |
| 任務開始 | `mtm-mto-first` |
| 宣稱 done | `ztm-verify-before-done` |
| fracdigi deploy | `ztm-fracdigi-psync` |
| 全艦 token 審計 | `mtm-fleet-audit --brief` |

## gh CLI

```powershell
gh auth status   # schema only — 引擎不印 token
```

無 gh 時引擎降級為本地 git + manifest 推斷。

## 自測

```powershell
python %AI_WORKSPACE%\_skill\engines\mtm-github-arch.py --seat ai_darkhero
python %AI_WORKSPACE%\_skill\engines\mtm-github-diff.py --seat-a ai_darkhero --seat-b ai_trader
python %AI_WORKSPACE%\_skill\engines\mtm-github-fleet-scan.py --agent ai_darkhero --brief
```
