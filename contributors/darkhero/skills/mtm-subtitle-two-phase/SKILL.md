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

## Operator corrections 2026-10-31 (apply in every subtitle / video-cleanup session)

- **One colour, no gender labels** — every zh cue in the existing pink; speaker gender detection is too weak, a wrong label is worse than none (`ai_theater/scripts/subtitle_pink_all.py`). Subtitles sit at the **top** of the window (operator screenshot); Top placement, checked 11-04: the .ass writers already use Alignment=8 (`subtitle_polish.py` write_ass, `subtitle_speakers.py`), but the delivered pink .srt carries no `{n8}` so it sits wherever the player puts it, and `scripts/femdom_gender_subtitle.py` still writes Alignment=2 (bottom) Female/Other styles — never use that lane; top stays open until a delivered title renders at the top.
- **Address by register, not one word** — a woman is not always 女王; pick the zh form from how the Japanese line names/self-names her (姐姐 for the 姉-disciplines-弟 register, 本小姐, …) via `ai_theater/src/ai_theater/zh_enhance.py`. A literal mistranslation (pst-07 「鯛魚」) means the MT lane regressed: compare against the golden titles SALO-008 / 016 / 024 before shipping a batch.
- **Reuse before translating** — compilations (BEST / 総集編 / re-cut films) get their lines from the source films by audio cross-correlation (`ai_theater/scripts/subtitle_compilation_reuse.py map|merge|scan`); only uncovered spans are translated.
- **Re-encode never inflates or blurs** — cap video bitrate at the source's (CRF alone grew SALO-014 4.0 -> 4.65 Mbps), inpaint only text pixels in corner boxes (delogo smears), edge marquees become black strips; the studio's own logo (IPPA …) is not an ad and stays (`ai_theater/src/ai_theater/video_cleanup.py`).
- **No intermediate files** — only the final video + its subtitle exist in the library folder; no MIGRATED-bak, no work copies beside it.

## Docs

- `docs/SUBTITLE-TWO-PHASE.md`
- `docs/SUBTITLE-XPU-BATCH.md`
