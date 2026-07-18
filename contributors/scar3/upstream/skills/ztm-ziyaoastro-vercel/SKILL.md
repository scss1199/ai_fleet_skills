---
name: ztm-ziyaoastro-vercel
description: Vercel deploy and health probe for ai_ziyaoastro. Use on vercel ship or first prod deploy.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# ztm-ziyaoastro-vercel — Vercel 首 deploy（Fly 退役）

**token-class: ZT** · cwd=`ai_ziyaoastro` · SSOT live=`https://ziyaoastro.vercel.app`

## 現況（2026-07-04 verify）

- `ziyaoastro.vercel.app` → **404**（尚未 prod deploy）
- `ziyaoastro.fly.dev` → 302 `/login`（legacy；GHA `if: false`）
- `.vercel/project.json` 已 link

## 目標

1. **Vercel-only** public web（`vercel.json` Astro+FastAPI services）
2. `scripts/ship.py` 待 migrate：CI 段改 Vercel probe，勿再 wait Fly

## 機械步驟

```powershell
cd C:\ai_workspace\ai_ziyaoastro
python C:\ai_workspace\_skill\engines\zt-popup-gate.py gate ai_ziyaoastro
# preflight
cd frontend; npm run build; cd ..
python -m compileall -q backend
# deploy
vercel deploy --prod --yes
curl.exe -sI https://ziyaoastro.vercel.app/
```

## PFKT

架構爭議（monorepo services）→ split：preflight / deploy / probe 各一段 verify-done

## SUBMIT

`_inbox/from_projects/ai_ziyaoastro/vercel-bootstrap-*.md`

Refs: `ai_darkhero/_dispatch/handoff-vercel-unify-migration.md`
