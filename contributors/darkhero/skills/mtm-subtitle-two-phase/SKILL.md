---
name: mtm-subtitle-two-phase
description: >-
  Two-phase Femdom/MGMQ subtitles: Phase1 seal JA SSOT (A770 STT + speaker + AV01/hohoj bible);
  Phase2 ZH .srt/.ass only. HubClock tick via mtm_subtitle_tick.py. SEAL/AEX/MTM.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: hubclock
    token_budget: zero
    engine: ai_metadata/scripts/mtm_subtitle_tick.py
---

# mtm-subtitle-two-phase

## Contract

1. **JA = sole truth** — `Q:\_subtitle\by_code\CODE.ja.srt` + `.ja.json` sealed (`phase1_sealed` + sha256)
2. **ZH = presentation** — `.srt` / `.ass` iterative; never overwrite JA
3. **Hardware** — A770 STT; A310 off (displays); CPU BelowNormal MT

## TR0 commands

```powershell
python scripts/mtm_subtitle_tick.py status
python scripts/mtm_subtitle_tick.py --gate
python scripts/mtm_subtitle_tick.py --tick --limit 2
python scripts/mtm_mgmq_xpu_queue.py --stt-only --from 170 --to 1
python scripts/mtm_mgmq_xpu_queue.py --mt-drain --from 170 --to 1
```

## HubClock (same fabric as P: library acq-tick)

- Rider id: `metadata-subtitle-tick` @15m
- **Must sit in GUARD band** (near `metadata-tray-watchdog`, early in `hosts.json`) — end-of-list riders starve under `MAX_CONCURRENT=8`
- Gate exit 0 = has work; tick self-spawns `mtm_mgmq_xpu_queue.py`
- **JA-first:** tick uses `--stt-only` when `need_p1>0`; ZH via `--mt-drain` later / re-export anytime
- Order: `configs/subtitle_queue_order.json` — MegamiParadise (mo/sm) → QueenMistress (queen-road) → rest; bible from AV01/hohoj

```powershell
python %AI_WORKSPACE%\_skill\engines\register-rider.py add HubClock metadata-subtitle-tick ^
  "C:\Python312\pythonw.exe C:\ai_workspace\ai_metadata\scripts\mtm_subtitle_tick.py --tick --limit 2" ^
  --cadence 15m ^
  --gate "C:\Python312\pythonw.exe C:\ai_workspace\ai_metadata\scripts\mtm_subtitle_tick.py --gate" ^
  --desc "Femdom JA seal STT first; ZH later; GUARD slot"
```

## Docs

- `docs/SUBTITLE-TWO-PHASE.md`
- `docs/SUBTITLE-XPU-BATCH.md`
