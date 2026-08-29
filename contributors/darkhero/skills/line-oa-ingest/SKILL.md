---
name: line-oa-ingest
description: Inspect and filter LINE Official Account inbound webhook events that were already persisted to a Google Drive inbox, distinguish saved group or 1:1 events from unavailable LINE chat history, verify the configured bot identity without exposing credentials, and route captured social URLs through the shared zero-model-token acquisition engine. Use for LINE OA inbox audits, group or direct-message retrieval, webhook-storage checks, saved-event exports, and LINE-to-social-content ingestion.
---

# LINE OA Ingest

Treat LINE Messaging API webhooks as the acquisition surface. Do not claim that
LINE exposes an endpoint for arbitrary chat-history retrieval.

## Inspect saved events

Run a metadata-only probe first. It prints counts and group names but no message
text, sender name, LINE ID, group ID, or credential:

```powershell
python scripts/inspect_line_inbox.py --env C:\path\to\line\.env --probe-bot
```

Scan the manifest for one exact group and include only the content needed by the
request:

```powershell
python scripts/inspect_line_inbox.py --env C:\path\to\line\.env --group-name "Group name" --include-text --include-urls --limit 50
```

Add `--scan-raw` to inspect saved raw event files beyond the manifest's newest
200 rows. This is a Drive archive scan, not a LINE history pull. Bound it with
`--max-files` and an exact group filter.

Use `--source-type user` to count saved 1:1 inbound events. Keep text off unless
the user explicitly requested those private messages. Use `--out` for a local
JSON evidence artifact; the script never writes to Drive or LINE.

## Interpret the result

Read [references/line-api-boundaries.md](references/line-api-boundaries.md)
before making access or completeness claims.

- A passing bot probe proves that the configured access token identifies a LINE
  OA. It does not prove that historical messages are queryable.
- A saved `source_type=group` or `source_type=user` row proves that the webhook
  received and retained an inbound event.
- An empty result proves only that the inspected manifest/archive lacks a match.
  It does not prove that the conversation never existed.
- Do not call the saved inbox a complete two-way transcript unless outbound OA
  messages are independently persisted and verified.

## Acquire linked social content

Extract URLs deterministically with `--include-urls`, then pass each approved URL
to the shared engine:

```powershell
python C:\ai_workspace\_skill\engines\distill-url.py "https://example.com/item" --json
```

For public Instagram posts/reels or Threads share links, use the deterministic
headless public-page extractor before using an authenticated browser:

```powershell
node scripts/fetch_public_social.mjs "https://www.instagram.com/p/SHORTCODE/" --include-text
```

Instagram is normalized to its public `/embed/captioned/` page. Threads redirects
are followed to the canonical post. The script reuses an installed Playwright
package and an installed browser; it does not use a session profile. `unfetchable`
is a terminal evidence state; never reconstruct missing body text from a title or
thumbnail.

The acquisition route uses platform/free providers and the hub free model pool,
so it consumes no paid model API tokens. External free-provider quotas and
the current agent's reasoning tokens are separate and must not be described as
zero total compute.

## Safety contract

- Never print access tokens, refresh tokens, client secrets, channel secrets,
  reply tokens, user IDs, or group IDs.
- Verify webhook signatures before accepting new events.
- Prefer exact group filters and bounded raw scans.
- Respect unsend events; if the ingestion service does not delete unsent content,
  report that privacy residual rather than presenting the archive as canonical.
- Treat OAuth and LINE requests as read-only. Do not change webhook settings,
  send messages, or write to Drive in this workflow.

## Validate

```powershell
python -m unittest discover -s scripts -p "test_*.py"
python C:\ai_workspace\_skill\engines\fleet-skill-sync.py verify
```

<!-- 2026-08-13: the second line used to be the skill-creator front-matter validator at
     C:\Users\sc\.codex\skills\.system\skill-creator\scripts\quick_validate.py. It lived inside the
     Codex user profile, which operator instruction removed from this machine; the only copy is now
     _delete/2026-08-13-codex-purge/userprofile/.codex/skills/.system/skill-creator/scripts/quick_validate.py.
     fleet-skill-sync.py verify checks that this skill still resolves on every surface, which is the
     part that can actually break. -->

