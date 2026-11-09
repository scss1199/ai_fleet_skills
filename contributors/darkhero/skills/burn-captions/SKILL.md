---
name: burn-captions
description: Deterministic burnt-in Traditional Chinese captions (.ass) for ffmpeg renders. Use when burning subtitles, or when captions overlap UI or stack.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# burn-captions

**Engine (single source of truth):** `C:/ai_workspace/ai_demo/scripts/caption-lib.mjs`
(exports `buildCaptionAss`, `assFilter`, `writeCaptionPolicy`, `splitCues`, `wrapCue`, `captionTopY`, `CAP`).
Post-gate: `C:/ai_workspace/ai_demo/scripts/check-captions.py` (0-token check of the written .ass).

## Why it exists (the bug it kills)
Proportional one-cue-per-sentence .srt burnt without `PlayResX/Y` let libass assume 384x288 and
scale the font ~3.75x; long comma-laden sentences became one tall cue anchored at the bottom and
growing UP into the app UI (「字幕太高擋到介面」) or colliding with centred card text (「疊字」).
caption-lib emits a deterministic .ass with `PlayResX/Y` locked to the real resolution, cues split
on 。！？ AND commas, hard-wrapped to <= 2 lines inside a bottom safe band.

## Use
```js
import { buildCaptionAss, assFilter, writeCaptionPolicy, CAP } from "C:/ai_workspace/ai_demo/scripts/caption-lib.mjs";
writeCaptionPolicy(outDir, W, H, CAP.FONT_PX);           // once per render: records the layout policy
buildCaptionAss(text, durationSec, assPath, srtPath, { W, H, fontPx: CAP.FONT_PX });
// then in the ffmpeg filter graph:  [v]${assFilter(assPath)}[out]
```
Already wired in `ai_demo/scripts/render-brief.mjs` (video-brief/3) and `make-video.mjs` (PSYNC tours).

## Rules
- Resolution passed to `buildCaptionAss` MUST equal the encoded frame size, or libass rescales again. Checked by `ai_demo/scripts/check-captions.py` (PlayRes vs stream resolution).
- Card chapters put title/subtitle at screen centre; captions stay in the bottom band — never move either. `check-captions.py` fails Alignment != 2 (bottom-centre).
- Verify with a frame grab (`ffmpeg -ss <t> -i out.mp4 -frames:v 1 f.png`) and look at it; ffprobe cannot see layout.

## Evidence
`ai_darkhero/evidence/ai-demo-pivot-20261011/` (render self-test frames 2026-10-11).
