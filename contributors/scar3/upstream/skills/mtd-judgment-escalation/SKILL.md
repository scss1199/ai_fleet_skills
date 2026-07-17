---
name: mtd-judgment-escalation
description: When to spend Claude tokens for irreducible judgment. Use when zero-token-mechanism paths and PFKT rubrics cannot decide — architecture, migration strategy, operator gates.
metadata:
  fleet:
    lane: MTD
    secrets: schema-only
    scheduler: session
    token_budget: judgment
---

# mtd-judgment-escalation — 何時該用 token（MTD lane）

**lane: MTD** — token 可花，但每筆 MTD 應 mint 可重用 zero-token-mechanism asset（Proof 2）。

## 升級 ladder（先低後高）

1. **zero-token-mechanism** — engine / HubClock / `git_smart --ztm` / claim-linter / local verify
2. **PFKT** — 複雜/平行前先 `pfkt-fragment.py mint` · `pfkt-wave.py plan`
3. **MTD** — 本 skill：你現在在這層（含 PFKT 拆法 judgment）

## MTD 合法場景（cite mtd-ztm-contract.json schema 3 / mtd-ztm-v3）

- 架構 / rename / migration **策略**（非機械 apply）
- Curator promote `_inbox` → `technique_output`
- Operator 閘：永久刪除、HubClock arming、env 變更
- PFKT 複雜 wave 的 **goal functional J** 選擇
- Accountability suspended 的 **remediation 判斷**（accountability-unblock）

## MTD _session 紀律

- CONSUME canon 先（grep INDEX）
- PFKT mint/split 再動
- 結束時：SUBMIT + 提案 zero-token-mechanism 化（ztm-skill-submit）

## 禁止

- 用 MTD 做 git commit message（應 ztm-git-ship）
- 用 MTD 繞過 evidence gate 假報完成
