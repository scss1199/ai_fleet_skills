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

## 從機自動升級（2026-10-15 scar3 驗證過的做法）

從機（scar3、altos）的 HubClock 上要有這幾個 rider（用 `register-rider.py add HubClock …`；arming 要 operator
在那台的 session 親自授權，peer 轉述的授權不算）：
- `fames-converge`（15m）：把 F1S／FAMES 套件收斂到 GitHub 上的最新版。
- `fleet-job-dispatch`（5m）：`fleet-job-dispatch.py tick`，處理 `jobs/<host>/` 的探測。主機名與 host 不同時要加 `--host`。
- `fleet-skill-github-sync`（30m）：技能同步。
- `omniroute-ensure`（10m）：`omniroute-gateway.py start`。新機器第一次先跑 `omniroute-gateway.py setup`（只用本機金鑰，金鑰只走 stdin）。

HubClock 本身要開機自啟（pythonw 或 wscript，禁止 -WindowStyle Hidden）。rider 命令裡的引號由 hubclock
`_parse_rider_argv` 處理（1.45.30 起每個參數都會去引號）。

**驗收**：darkhero 出貨新版後，用 `fleet-job-dispatch.py submit --target-host <host> --kind probe` 派一份探測；
沒有人工介入就自動回應、且回報的 fames 版本等於新版，才算這台已同步。scar3 在 1.45.30 的實測是 251 秒。
新功能送到從機 = 檔案到位、不啟動：tray／rider／daemon 在那台的啟用是那台 operator 的決定（2026-10-29 「tray 先不用開」），
送過去不等於開起來。「推過去並檢查是否成功」要讀從機自己的結果列（`fleet-job-dispatch.py status --json` 的 result／ok／blocker、
follower receipt 的版本），不是 submit 回傳；從機關機時狀態寫 UNKNOWN 附 staged job id，等它開機再讀回。2026-10-29 兩筆同內容
的 job：altos 42bf560f ok、scar3 e6cfed50 ok=false blocker claude_remote_exec_check_unreadable，只看 push 會把兩台都報成功。

## 本機 SSOT

策展仍在本機 `_skill/fleet-skills/`；GitHub 只做同步與跨機學習。
