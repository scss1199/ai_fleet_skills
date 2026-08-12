---
name: aex-agent-evolution
description: >-
  AEX closed evolution cycle + Krylov acceleration (CG/BiCGStab/GMRES).
  EXEC→INSTR→DISTILL→PROMOTE→OPEN→GUARD→EXEC. PFKT overlays SCF.
  Use for iterate/converge, not one-shot token teaching.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
    required: true
    concept_id: AEX
    engine: _skill/engines/fleet-token-ladder.py
    registry: _registry/fleet-token-ladder.json
    lexicon: _registry/fleet-lexicon.json
---

# aex-agent-evolution — 閉環疊代 + Krylov 加速

> **禁止重教。** 本體 = SCF 式閉環；PFKT = 上層 Fragment/Parallel；MTM/EFF = 儀器。

**北極星：** 選 CG→BiCGStab→GMRES 加快 ‖R_aex‖↓，每圈 GUARD 後回到 EXEC。

## 命令

```powershell
python %AI_WORKSPACE%\_skill\engines\fleet-token-ladder.py show --brief
python %AI_WORKSPACE%\_skill\engines\fleet-token-ladder.py aex cycle
python %AI_WORKSPACE%\_skill\engines\fleet-token-ladder.py aex iterate --agent <seat>
```

`aex iterate` → `solver` + `phases_this_cycle` + `R_aex`/`kappa`/`sigma` + **Periodic Pulay**（`scf_numerics`）。

艦隊雙場：**AWARE** → Skill `aware-dual-field` / `aware-field.py`（ψ_hub ↔ ψ_seat）。

## 循環

`EXEC → INSTR → DISTILL → PROMOTE → OPEN → GUARD → EXEC`

| Solver | 何時 | 行為 |
|--------|------|------|
| CG | κ小、σ穩、R↓ | 跳過 OPEN（最省） |
| BiCGStab | σ低 / κ抖 | INSTR+OPEN 雙向搜 |
| GMRES | κ≥1 / 偽進化 | 全相位 + Anderson |

## PFKT ↔ SCF

- SCF：`g,r,R,κ`（`scf-protocol.json`）
- PFKT：F / P_par overlay（`pfkt-protocol.json`）→ AEX **OPEN** / GMRES 子空間

## 艦橋日常化

**HUBPULSE**（Skill `hubpulse-ops`）：HubClock=節拍 · Tray=操作面 · fleet-skills=能力織 · AWARE=場。  
`hubpulse.py status` / Tray Hub → Deploy fleet skills。
