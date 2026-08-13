---
name: accountability-unblock
description: Curator-only. Parse Accountability Enforcer BLOCKED messages and remediate suspended seats. Use when operator pastes BLOCKED by Accountability Enforcer for any fleet agent.
disable-model-invocation: true
metadata:
  fleet:
    lane: MTD
    secrets: none
    scheduler: manual
    token_budget: judgment
---

# Accountability Unblock — curator 強制解鎖

當任一 fleet seat 被 **Accountability Enforcer** 硬阻擋時，operator 把完整 BLOCKED 訊息貼到 **ai_darkhero** session，curator 代為完成 remediation 並恢復該 seat 行動能力。

## 觸發（貼上即執行）

```markdown
@AGENTS.md skip pfkt

## ACCOUNTABILITY UNBLOCK
Agent: <從 BLOCKED 訊息辨識，如 fracdigi>
BLOCKED 原文：
<paste 完整 BLOCKED by Accountability Enforcer ...>

## 必做（curator 代跑，禁止問 operator）
1. `python %AI_WORKSPACE%\_skill\engines\accountability-unblock.py parse --text "<原文>"`
2. `python %AI_WORKSPACE%\_skill\engines\accountability-unblock.py plan --agent <Agent>`
3. **完成 plan 內所有未完成工作**（inbox pickup→執行→ack、result-field evidence、schtasks 清理等）
4. `python %AI_WORKSPACE%\_skill\engines\accountability-unblock.py remediate --agent <Agent> --execute --clear --by curator-unblock`
5. `python %AI_WORKSPACE%\_skill\engines\accountability_enforce.py --agent <Agent>` 確認 level≠suspended
6. SUBMIT `_inbox/from_projects/ai_darkhero/accountability-unblock-<agent>-<date>.md`
```

## 紅線

- 禁止假寫 result-field（evidence 必須可複驗）
- suspended clear 僅在 inbox/stuck 已處理或 curator 已補完工作後
- 回覆繁體中文；BLOCKED 原因用 fixes_en（英文）避免亂碼

## CITE

- `_skill/engines/accountability-unblock.py`
- `_registry/fleet-skill-routing.json`
