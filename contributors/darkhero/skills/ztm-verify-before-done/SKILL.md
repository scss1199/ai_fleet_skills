---
name: ztm-verify-before-done
description: Mechanical verify-before-done gate before claiming SHIPPED, plus F1S rules ④⑤⑥ (evidence or UNKNOWN, green test after the last edit before saying fixed, no lying or hand-back, no unrequested .md/.json). Use when about to report done, fixed, read, automated or blocked, before park or a result-field write. Runs claim-linter + zat-verify-gate path.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: low
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# ztm-verify-before-done — 宣稱完成前的機械審查

**lane: zero-token-mechanism** — 允許少量 session token（snapshot/read），但**禁止**無 evidence 的 done 宣稱。

## 何時用

- 準備寫 `result-field.py write` 或報「已完成」
- `last_p_verified=0` 或 accountability **fake-delivery** 風險
- PFKT fragment 要標 `verify-done`

## F1S ④⑤⑥（PROOF Stop hook 機械擋；本文教怎麼過）

- ④ 每個主張要有本回合跑過的驗證或能開的檔案，否則寫 UNKNOWN；寧可說不知道也不准自信亂答再翻供。
  改碼後說「修好」必須在最後一次改碼之後跑過綠的測試（tdd，避免改 A 壞 B；
  Lean `ClaimContract.fix_claim_needs_test_after_write`）。
- ⑤ 不准說謊、不准推託：已讀、推進、已自動化、做不到、重問同一決定、要已給過的值、把自己能做的步驟
  推給使用者，每一句都要有本回合工具結果，否則寫 UNKNOWN 或自己去做。只有登入/OAuth、永久刪除、
  rider 授權、全域設定、金鑰、資金、硬體是使用者的步驟。Anthropic 額度用完不是停下的理由：
  `claude-remote-exec` auto lane 改走本機 OmniRoute 免費池（`omniroute-gateway.py`）。
- ⑥ 嚴禁隨意產出 .md/.json：只寫使用者點名的檔案、charter、`_registry` 狀態與 SEAL 收據；
  報告、筆記、摘要寫在回覆裡（Lean `F1SCore.reports_are_junk`）。
- 宣稱完成時跑 SEAL：`fames_phase_runtime.py --turn --result --closure`。

## 必跑（0-token engines 優先）

```powershell
python %AI_WORKSPACE%\_skill\engines\claim-linter.py --strict --file <your-draft.md>
python %AI_WORKSPACE%\_skill\engines\zat-verify-gate.py verify-done --stamp <STAMP> --id fN --evidence <path>
python %AI_WORKSPACE%\_skill\engines\accountability_enforce.py query --agent <seat>
```

## 程式審查（kyloren 15 Skills：Superpowers / Addy Osmani）

非 trivial 的改碼在宣稱完成前，交給沒寫這段程式的 subagent 走技能 `independent-review`
（生成者不得是自己產出的唯一裁判）；審查結果與 diff 一起引用。

## UI 驗證（token_budget: low）

若 claim 含 UI/portal → 先 **ztm-webapp-verify**（MCP browser snapshot）再 verify-done。

## _escalate → MTD

架構取捨、operator 閘、ambiguous goal → **mtd-judgment-escalation** skill，勿硬套 ZCT。
