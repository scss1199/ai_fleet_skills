---
name: chapter-compose
description: Compose a narrated, captioned, branded MP4 from a chapter YAML with ffmpeg — ai_demo's render layer for the "prompts + assets -> video" pipeline (video-brief/3). Chapter types card / still / clip / t2i / i2v / screen; brand packs (jci_taipei, psync); content-addressed assets with consent gating; every render leaves an evidence JSON. Use when any seat needs a video from a brief (jci_taipei 2027 marketing, product tours, explainers).
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
ladder_ref: _registry/fleet-token-ladder.json
parent_skill: aex-agent-evolution
---

# chapter-compose

**Contract:** `C:/ai_workspace/ai_demo/docs/BRIEF-SCHEMA.md` (video-brief/3). Read it before writing a brief.
**Engine:** `node C:/ai_workspace/ai_demo/scripts/render-brief.mjs <video.yaml> [--reuse-audio] [--allow-pending]`
**Self-test:** `node C:/ai_workspace/ai_demo/scripts/render-brief.mjs --selftest` (PASS 2026-10-11).

## The three layers (who owns what)
| layer | seat | entry point |
|---|---|---|
| assets + prompts | `jci_taipei/marketing/2027/` | `assets/build_index.py` (index.json: sha256, source, consent) + `briefs/<id>/video.yaml` |
| generation (A770) | `sdnext_a770` | `scripts/gen_from_brief.py <video.yaml> --dry-run / --submit / --backfill` |
| render | `ai_demo` | `scripts/render-brief.mjs` (this skill) |

Claude writes the brief and the prompts; the pipeline does the work (0 model tokens per render).

## Flow
1. `python .../assets/build_index.py` — refresh the asset index (consent/notes preserved).
2. Copy `briefs/_template/video.yaml` to `briefs/<id>/video.yaml`; fill narration, pick `asset:` ids or `src:` paths,
   write `prompts/<chapter>.md` for t2i/i2v chapters.
3. `gen_from_brief.py --dry-run` → `prompts/jobs.json`; `--submit` when SD.Next :7860 is up (operator starts
   `sdnext_a770_t2i.bat`; the A770 is a hard-reset risk under load, see memory power-loss-combined-cpu-gpu-load).
4. `render-brief.mjs video.yaml` — refuses while t2i/i2v chapters are pending; `--allow-pending` renders a draft
   with placeholder cards for review.
5. Look at frames (`ffmpeg -ss t -i out.mp4 -frames:v 1 f.png`) — ffprobe proves streams, not layout.
6. Deliverable = `ai_demo/output/finals/<output>.mp4` + `.evidence.json` (brief sha, input shas, ffprobe, commands).

## Rules
- Faces: `roster`/`line` assets render only with `consent: granted` in index.json (the engine refuses otherwise).
- Brand is a parameter (`meta.brand` -> `ai_demo/brand/<name>/brand.json`); never hard-code a logo or colour.
- Logos/posters: `visual.fit: contain`; photos: default `cover`. Ken Burns is on unless `motion: none`.
- Chapter length follows narration (+0.5 s); pictures are frozen/padded, never cut short.
- Do not merge this into a consumer seat (ai_demo SEAT-SPEC constraint); consumers submit briefs.

## Evidence
`ai_darkhero/evidence/ai-demo-pivot-20261011/` — self-test frames, draft `2027-teaser-01.mp4` (27 s, 5 chapters, 2 pending).
