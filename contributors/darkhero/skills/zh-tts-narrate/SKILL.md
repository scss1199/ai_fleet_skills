---
name: zh-tts-narrate
description: Zero-key Traditional Chinese narration with edge-tts plus voice ranking. Use for a zh-Hant voice-over without an Azure key or to audition voices.
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

**Runtime:** `C:/ai_workspace/ai_demo/.venv/Scripts/python.exe -m edge_tts` (edge-tts 7.3.1 since
2026-10-28: 7.2.8 got a 403 handshake from the endpoint; needs network to Microsoft's read-aloud endpoint, no
subscription, no key).

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
- Narration text is sent to a Microsoft endpoint: never put secrets or unpublished personal data in it. (PROOF `secret_ask`)
- A 403 handshake means the installed edge-tts is too old for the endpoint: upgrade the package first.
- The endpoint sometimes returns `NoAudioReceived` for one request, and a resend of the same text can succeed.
  For multi-line scripts send one request per sentence, retry each up to about 8 times with backoff, and check
  that every mp3 is larger than 0 bytes before concatenating (seen on the 2026-10-28 Recco test clips).

## Offline fallback (endpoint down or no network)
Windows' built-in SAPI voice `Microsoft Hanhan Desktop` (zh-TW) runs on the CPU with nothing to install and no
key: `System.Speech.Synthesis.SpeechSynthesizer`, `SelectVoice('Microsoft Hanhan Desktop')`, `SetOutputToWaveFile`.
2026-11-03 probe: one zh-TW sentence gave 5.48 s of 16 kHz audio (RMS 2339) in 45 ms. It sounds more robotic
than edge-tts, so use it only when edge-tts fails after its retries. Windows PowerShell 5.1 reads a script without
a BOM as ANSI, so pass the Chinese text as UTF-8 base64 or from a file, not inline.
VoiceStudio (debpalash/VoiceStudio, AGPL-3.0, from the 10-31 GitHub trending article) was not adopted: it is an
Electron app with an `irm | iex` installer and model downloads, which is far heavier than the built-in voice.
Voice cloning of any kind needs the speaker's consent first.

OmniVoice candidate (not trialled; checked against the repos 2026-11-12). Its engine is k2-fsa/OmniVoice
(Apache-2.0). The only route allowed without the Electron app is `pip install omnivoice` into the ai_demo venv,
then `omnivoice-infer --model k2-fsa/OmniVoice --text ... --output x.wav`. That route is PyTorch, so pin CPU
explicitly and never use `xpu`. Run it under load_grant like any heavy CPU job. Its language list has Mandarin
`zh` but no zh-TW variant. The GGUF build (VoiceStudio docs/engines/omnivoice-gguf.md) ships only in the desktop
installer or a source build. Its `auto` backend opens the first discrete Vulkan GPU, which is the A770 here, so
`OMNIVOICE_DEVICE=cpu` plus `OMNIVOICE_GGUF_BACKEND=cpu` would be mandatory. Its weights are stated noncommercial,
so it is not for jci marketing renders. Adopt it only after one zh-TW sentence beats SAPI by ear, with the receipt
cited here.

## Evidence
`ai_darkhero/evidence/ai-demo-pivot-20261011/` (render self-test 2026-10-11: 3 chapters narrated, 10.1 s MP4).
