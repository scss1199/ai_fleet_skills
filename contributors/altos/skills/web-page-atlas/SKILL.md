---
name: web-page-atlas
description: >-
  Use BEFORE and AFTER any web-UI navigation on a complex or authenticated site
  (broker portals like 永豐/sinotrade, admin consoles, dashboards, member areas).
  BEFORE navigating, `lookup` the atlas to jump straight to the known page + exact
  steps + known quirks for a task — a local grep, zero tokens, no re-exploring.
  AFTER navigating, `add` what you learned (URL, how-to, gotchas) so the map
  self-improves across sessions. `radar` flags stale entries to re-verify. Triggers:
  "go to the X page", "where do I do Y on this site", "how do I enable Z in the
  portal", recurring navigation on the same site, "remember this page", or any
  in-app browser / computer-use web operation that you'll likely repeat.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: none
    scheduler: session
    token_budget: zero
---

# web-page-atlas — a self-improving, zero-token site map

A persistent, per-site map of **"the page that solves problem X"**: its URL, the
exact steps, and the quirks that bit you. The map **grows from real navigation**
and is **consulted before navigating**, so each visit makes the next one cheaper.

This is the file-based, zero-token realization of *Agent Workflow Memory* — see
**Prior art** below. It plugs into the hub's ZT/ZTM model
(`10-foundations/zt-ztm-mtd-multiagent.md`) and the radar→digest→stamp flywheel
(`50-techniques/self-reinforcing-knowledge-base.md`, KB 2026.06.09-18).

## The bidirectional loop

```
            ┌──────────────── forward (ZT, 0 tokens) ───────────────┐
            ▼                                                               │
   atlas.py lookup <site> <task>  ──►  jump to known URL + steps + quirks   │
            │                                                               │
   (navigate / act in the browser)                                         │
            │                                                               │
            ▼                                                               │
   learned something new/changed? ──► atlas.py add <site>  (backward learn) ┘
            │
   periodically: atlas.py radar <site>  ──►  re-verify stale/broken pages (ZTM)
```

- **Forward (use)** — *always `lookup` first.* If the atlas knows the page, you
  save the whole explore-the-menus dance. Lookup is a local grep = **0 tokens**.
- **Backward (learn)** — after you reach a page worth remembering, or a page's
  behavior changed, `add` it. The one judgement call ("is this worth recording?")
  is the only brain step; storage/dedup/indexing is tokenless.
- **ZTM upkeep** — `radar` lists entries past their freshness window or marked
  non-`ok`, so a later session re-verifies them instead of trusting rot.

## Commands

Engine: `scripts/atlas.py` (stdlib only): `python %AI_WORKSPACE%\_skill\fleet-skills\web-page-atlas\scripts\atlas.py ...`.

```
python atlas.py lookup <site> [query words...]   # ranked matching pages
python atlas.py list   <site>                     # dump all pages
python atlas.py radar  <site> [--days N]          # stale (>N d, default 30) / non-ok
echo '<json>' | python atlas.py add <site>        # upsert one page entry (by id)
```

`<site>` matches by substring, so `sinopac` and `sinotrade` both resolve the same
file. Fleet data lives in `_registry/web-atlas/<site>.json` (one map shared by every seat; `WEB_ATLAS_DIR` overrides).

**Never write credentials, account numbers or personal data into the shared atlas** — the `facts` block is for
non-secret facts; seat-private facts stay in that seat's own atlas (`WEB_ATLAS_DIR`). Promoted to F1S from ai_trader
2026-10-16 by f1s-reverse-learning.

## Entry shape (one page)

```json
{
  "id": "python-api-key",
  "url": "https://www.sinotrade.com.tw/newweb/PythonAPIKey/",
  "purpose": "create / manage the Shioaji API key",
  "howto": "Add API KEY -> 2FA -> tick 'Production Environment' -> copy Key+Secret",
  "quirks": ["no Production tick => real login fails 'Token doesn't have production permission'"],
  "last_verified": "2026-06-11",
  "status": "ok"
}
```
A top-level `auth` string per site records *how* you're logged in (e.g. "owner logs
in manually in their Chrome; MCP tab shares the same profile/session"). A `facts`
block holds durable account facts (account ids, what's missing) that explain quirks.

## How a session should use it

1. Task names a site you've touched before → `lookup` it FIRST. Act on the URL it
   gives; heed the `!!` quirks (they are scars from last time).
2. Hit something new (a working URL, a gotcha, a dead end) → `add` it immediately,
   while it's fresh. Set `status` to `ok`, `broken-*`, or `blocked-*` honestly.
3. Before trusting an old entry on a flaky site → `radar` to see what's stale.

## Honest boundary

Like the self-reinforcing KB: **automate everything except the judgement.** Lookup,
storage, dedup, staleness scan are tokenless. The only token step is deciding
*what* a page taught you — and that is exactly where a token earns its keep.

## Prior art (web-verified 2026-06-11)

This skill is a lightweight, file-based, zero-token take on a real research line:
- **Agent Workflow Memory** (arXiv 2409.07429) — induce reusable workflows from
  successful trajectories; "snowball": simple maps compose into complex ones.
- **WebCoach** (arXiv 2511.12997) — cross-session episodic memory; self-evolving
  web agents that improve without retraining.
- **WebATLAS** (arXiv 2510.22732) — a persistent *cognitive map* of a site built
  from interaction experience. (Same idea, same name.)

The delta here: those keep memory inside an agent runtime; this keeps it as a
**plain JSON file** any session (or a tokenless script) can read/write — so it
costs zero tokens to consult and survives across projects.
