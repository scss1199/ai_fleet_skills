---
name: library-bookmark-coverage
description: >-
  Prove every ai_library person × platform bookmark (IG / X / pixiv / fanbox / missav / …)
  has a real update path, end-to-end. Derives coverage from Chrome bookmarks, fails closed on
  UNKNOWN, and catches the "type-level fake" — a platform advertised in config/tuning with no
  registered adapter, or an engine module that exists but nothing routes to.
metadata:
  fleet:
    lane: zero-token-mechanism
    secrets: platform-cookies-read-only
    scheduler: hubclock
    token_budget: low
    engine: ai_metadata/scripts/library_coverage.py
    rider: metadata-acq-tick (sweep step, 360m interval)
---

# library-bookmark-coverage — 人物 × 平台 我的最愛全覆蓋

## Outcome

For every person reachable from `ai_library.html`, every bookmarked site of theirs has a
**verified** update path: bookmark → classify → engine → lane → download. `covered` is a claim
about the pipeline, not about a module existing on disk.

## The two lies this skill exists to kill

1. **Type-level fake** — a platform name valid in `config.Platform` / `PLATFORM_TUNING` /
   `classify_url`'s `social_fetch` list while `platforms.available()` has no `@register` for it.
   The config then *advertises* support that cannot run.
   Guard: `tests/test_platform_registry.py` (the unimplemented set is DERIVED, never listed —
   a hand-written list goes stale the moment an adapter lands).
2. **Route-level fake** — an engine module imports fine and *nothing calls it*.
   `web_video_zct` worked for months while `probe_url` returned `non_fetch` for `web_video` and
   the Chrome→lane sync only read bookmarks already filed under `_mission_/<lane>`.
   Guard: `library_coverage._pipeline_ok`, which checks the ROUTE, not the import.

CITE: `C:\claude_technique\technique_output\50-techniques\zt-producer-consumer-audit.md`.

## Run it

```bash
python scripts/library_coverage.py --gate
```

- `--gate` → non-zero exit on any **unwaived** gap. This is the PFKT verify command.
- `--probe` → live yt-dlp probe for `web_video` rows that only a *generic* extractor could reach,
  cached in `runtime/library-coverage-probe.json`. Read-only against the operator's own pages:
  it lists formats and downloads nothing. Never reads or prints cookie values.

Coverage rules, in order of strength:

| row kind | covered when |
|---|---|
| `social_fetch` | a registered adapter exists for `guess_platform(url)` **and** it has a `PLATFORM_TUNING` row |
| `web_video` | a **dedicated** yt-dlp extractor matches (offline: `gen_extractor_classes()` + `cls.suitable()` + `IE_NAME != "generic"`), **or** a recorded live probe succeeded |
| `manual` | declared non-fetchable (shop page / link aggregator / talent profile) — see `routing.REFERENCE_WEB_HOSTS` |
| anything else | **not covered.** UNKNOWN fails closed. |

A dedicated extractor that exists but whose page probe failed is reported under
`broken_bookmarks` — a dead/blocked bookmark for the operator to re-point, **not** a capability
gap. It must never silently flip the verdict either way.

## Adding a platform (the whole checklist)

Doing fewer than all five re-creates one of the two lies above.

1. `routing.guess_platform` — the single source of URL→platform. Never hand-copy a host table.
2. `platform_tuning.PLATFORM_TUNING` — filename template + gallery-dl args.
   `GDL_PLATFORMS` is `frozenset(PLATFORM_TUNING)`; do not restate it.
3. `platforms/<name>.py` — `@register("<name>")`, plus `_remote_id` / `_post_url` so the item
   maps back to a canonical page URL.
4. `bookmarks_sync.classify_url` — pick `social_fetch` / `web_video` / `manual`. `manual` is an
   honest answer; `web_video` for a page with no media is a fake.
5. `config.Platform` — **only if the platform is subscribable.** It is NOT the set of keys
   `guess_platform` can return; adding probe-only names there manufactures fakes.

Then: `pytest tests/test_library_coverage.py tests/test_platform_registry.py tests/test_platform_tuning.py`.

## Security invariants (seat red lines)

- `CATCH_ALL_PLATFORM = "web"`, never a credentialed platform. The platform key selects
  `secrets/<platform>/cookies.txt` (`web_video_zct._cookiefile_for`,
  `downloader.download_via_extractor`), so a catch-all of `"youtube"` hands an arbitrary
  unknown host the owner's YouTube cookies. `web` has no secrets dir — that is the point.
- Cookie/secret **values** are never printed. Schema and counts only.
- Login-walled fetch only through the owner's own session. Never bypass.

## Scheduling

The full pass is `cm bookmarks sweep --execute` (not `bookmarks sync` — different subcommand,
different coverage). It rides the already-armed HubClock rider `metadata-acq-tick`, cadence-gated
by `runtime/acq-sweep-stamp.json` (`SWEEP_INTERVAL_MIN`, default 360). It is stamped even on
failure so a broken sweep cannot become a 15m request storm, and it is non-fatal to the tick.

Do **not** register a second rider for it: arming a new rider is operator-gated, and a second
rider would duplicate the cookie refresh this one already performs. Never `schtasks`.

## Idempotency

`mission_zct.enqueue_task` is idempotent through a per-lane `.enqueued.json` ledger (leading dot
so `list_tasks` never mistakes it for a task). This is **required**, not an optimisation: a
finished task file is unlinked by `_finish_ok` but the Chrome bookmark stays, so without the
ledger every sweep would re-enqueue an already-downloaded URL. Statuses: `added` / `ledger`
(seen before) / `live` (a pre-ledger task file exists) / `invalid` (not http).

## Declared gaps — `WAIVED_HOSTS`

A permanently red gate stops carrying signal, and the first genuinely new uncovered host
disappears into the noise. So a host that provably cannot be covered goes into
`WAIVED_HOSTS` **with its reason**: it is still counted in `gaps`, still printed under
"declared gaps", still attributed to its person — it simply stops vetoing the gate.
Removing a host from the dict must turn the gate red again; nothing is ever waived by silence.

`WAIVED_HOSTS` is **not** a parking lot for unfinished work. It is only for hosts where the
seat's red lines forbid the one remaining technique.

- `topfaps.com` — **waived.** The player URL is emitted by a purpose-built obfuscated JS
  payload (jwplayer + packed loader). Neither yt-dlp (generic → `Unsupported URL`, verified
  2026-08-13 on both `/model/` and `/video/` pages) nor gallery-dl has an extractor. The only
  route left is deobfuscating an anti-scraping layer the site deployed on purpose — declined,
  not deferred. Re-point the bookmark to close it.
- `jp.pornhub.com/model/…` — **not** a gap. The route exists (`PornHubPagedVideoList`), the
  page returns HTTP 410. It lands in `broken_bookmarks`: surface it for the operator to
  re-point, and never fabricate a download success.

Guards: `test_waiver_matches_only_the_declared_host_and_its_subdomains` (a waiver must not
widen via substring match) and `test_every_waiver_carries_a_reason`.
