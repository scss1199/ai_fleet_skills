---
name: ztm-verify-before-done
description: Mechanical verify-before-done gate before claiming SHIPPED. Use when about to report done, park, or result-field write. Runs claim-linter + zat-verify-gate path.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: low
---

# ztm-verify-before-done — 宣稱完成前的機械審查

**lane: zero-token-mechanism** — 允許少量 session token（snapshot/read），但**禁止**無 evidence 的 done 宣稱。

## 何時用

- 準備寫 `result-field.py write` 或報「已完成」
- `last_p_verified=0` 或 accountability **fake-delivery** 風險
- PFKT fragment 要標 `verify-done`

## 必跑（0-token engines 優先）

```powershell
python %AI_WORKSPACE%\_skill\engines\claim-linter.py --strict --file <your-draft.md>
python %AI_WORKSPACE%\_skill\engines\zat-verify-gate.py verify-done --stamp <STAMP> --id fN --evidence <path>
python %AI_WORKSPACE%\_skill\engines\accountability_enforce.py query --agent <seat>
```

## UI 驗證（token_budget: low）

若 claim 含 UI/portal → 先 **ztm-webapp-verify**（MCP browser snapshot）再 verify-done。

## _escalate → MTD

架構取捨、operator 閘、ambiguous goal → **mtd-judgment-escalation** skill，勿硬套 ZCT。
