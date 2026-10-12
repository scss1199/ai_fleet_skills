---
name: ztm-skill-submit
description: Submit reusable workflow skills to the hub curator through a skill-update inbox receipt. Use after a workflow is proven in a project-local skill and should be vetted for fleet adoption.
---

# Submit a fleet skill

Submit a proven reusable workflow to `_inbox/from_projects/<seat>/skill-update-*.md`.

Use this receipt:

```text
# skill-update - <topic> - <seat>

- **name:** my-skill-id
- **lane:** MTD
- **secrets:** none
- **scheduler:** session
- **source:** `.cursor/skills/my-skill-id/SKILL.md`
```

The curator absorbs the receipt into `_skill/fleet-skills/`, vets it, deploys it, and sends an inbox acknowledgement. Do not place secrets in the skill body.

Keep runtime frontmatter limited to `name` and `description`. Read [references/fleet-metadata.md](references/fleet-metadata.md) only when assigning fleet lane metadata.
