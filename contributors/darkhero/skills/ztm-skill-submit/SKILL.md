---
name: ztm-skill-submit
description: Submit reusable workflow skills to hub curator via skill-update inbox. Use after proving a workflow in .cursor/skills/ that other seats should adopt.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
---

# ztm-skill-submit — 回寫 skill 給 hub curator（0-token）

Curator 吸收路徑：`_inbox/from_projects/<seat>/skill-update-*.md`

## 何時 SUBMIT

沉澱了**可複用、可驗證**的工作流（非一次性 prompt）。

## 必帶 lane 標籤（2026-07-05 起）

每支 skill 的 frontmatter 必含 `metadata.fleet`：

```yaml
metadata:
  fleet:
    lane: zero-token-mechanism | MTD
    secrets: none | schema-only | operator-gated | forbidden
    scheduler: hubclock-only | session | manual | hybrid
    token_budget: zero | low | judgment
```

SSOT 定義：`_registry/fleet-skill-lanes.json`

| lane | 何時用 |
|------|--------|
| **zero-token-mechanism** | 引擎/HubClock/機械 verify/0-token 可完成（含 token_budget: low 的 snapshot） |
| **MTD** | 架構判斷、curator、operator 閘、PFKT 拆法需 judgment |

**不是每支 skill 都要 zero-token-mechanism** — 合理用 token 提效時標 **MTD**。

## SUBMIT 格式

```markdown
# skill-update · <topic> · <seat>

- **name:** my-skill-id
- **lane:** MTD
- **secrets:** none
- **scheduler:** session
- **source:** `.cursor/skills/my-skill-id/SKILL.md`
```

## 之後

1. Curator `fleet-skill-sync.py absorb` → `_skill/fleet-skills/`
2. `fleet-skill-vet.py scan` → `tick` deploy
3. ack inbox directive

禁止：secret 值寫進 skill body。
