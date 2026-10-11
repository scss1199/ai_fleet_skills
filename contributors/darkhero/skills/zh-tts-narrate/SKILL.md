---
name: zh-tts-narrate
description: Zero-key Traditional Chinese narration with edge-tts (Microsoft neural voices, zh-TW-HsiaoChenNeural default) plus objective voice ranking (DNSMOS via voice-mos.py). Use for any video or audio that needs a zh-Hant voice-over without an Azure key, to regenerate a project's chapter audio in another voice, or to audition and rank candidate voices.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# zh-tts-narrate

**Runtime:** `C:/ai_workspace/ai_demo/.venv/Scripts/python.exe -m edge_tts` (edge-tts 7.2.8 installed
2026-10-11; needs network to Microsoft's read-aloud endpoint, no subscription, no key).

## One-liners
```bash
# a single clip
C:/ai_workspace/ai_demo/.venv/Scripts/python.exe -m edge_tts --voice zh-TW-HsiaoChenNeural --rate "+6%" --file text.txt --write-media out.mp3
# every chapter of a brief/tour yaml in a chosen voice (overwrites output/audio/<id>.mp3 + .srt)
python C:/ai_workspace/ai_demo/scripts/regen-audio.py <tour-or-brief.yaml> zh-CN-XiaoyiNeural
# audition + objective MOS of candidate voices (DNSMOS, needs `pip install speechmos`)
python C:/ai_workspace/ai_demo/scripts/voice-audition.py && python C:/ai_workspace/ai_demo/scripts/voice-mos.py
```
`render-brief.mjs` and `make-video.mjs` call edge-tts per chapter automatically (`meta.voice`, `meta.rate`);
`--reuse-audio` skips TTS when the mp3 exists (caption-only re-burns are then 0-network).

## Voices that have been used
- `zh-TW-HsiaoChenNeural` (Taiwan Mandarin, female) — default, cleanest for narration.
- `zh-CN-XiaoyiNeural` — operator-chosen for PSYNC tours (regen-audio.py default).
List all: `python -m edge_tts --list-voices | findstr zh-`.

## Caveats
- DNSMOS (voice-mos.py) ranks speech-enhancement quality, not TTS naturalness; treat small gaps as noise.
- `regen-audio.py` pins an ffprobe path under another user profile; `render-brief.mjs` resolves ffmpeg/ffprobe
  from PATH or the current user's WinGet packages instead — use that resolver when porting.
- Narration text is sent to a Microsoft endpoint: never put secrets or unpublished personal data in it.

## Evidence
`ai_darkhero/evidence/ai-demo-pivot-20261011/` (render self-test 2026-10-11: 3 chapters narrated, 10.1 s MP4).
