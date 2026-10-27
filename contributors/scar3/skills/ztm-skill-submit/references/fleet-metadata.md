# Fleet metadata

Fleet governance metadata belongs in `_registry/fleet-skill-metadata.json`, keyed by skill directory name. Do not put it in `SKILL.md` frontmatter.

Required fields:

```json
{
  "lane": "zero-token-mechanism or MTD",
  "secrets": "none, schema-only, operator-gated, or forbidden",
  "scheduler": "hubclock-only, session, manual, or hybrid",
  "token_budget": "zero, low, or judgment"
}
```

Use `zero-token-mechanism` only for deterministic local mechanisms. A workflow that invokes a model, including a cross-provider reviewer, is not zero-token. Use `MTD` when the workflow requires model judgment or operator judgment.
