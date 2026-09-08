# LINE Messaging API boundaries

## Authoritative behavior

- LINE sends a webhook event when a user messages an OA in a 1:1, group, or
  multi-person chat. Text is present in that event, and LINE states that there is
  no API to retrieve the text again after receipt:
  <https://developers.line.biz/en/docs/messaging-api/receiving-messages/>
- A group ID comes from a webhook event. The API can retrieve group summary,
  member count/IDs/profiles, and can send or leave; it does not list past group
  messages:
  <https://developers.line.biz/en/docs/messaging-api/group-chats/>
- Binary user content can be fetched for a limited period with the message ID
  delivered by the webhook. This does not apply to historical text:
  <https://developers.line.biz/en/reference/messaging-api/#get-content>
- LINE recommends removing locally stored content when an unsend event arrives:
  <https://developers.line.biz/en/docs/messaging-api/receiving-messages/#processing-on-receipt-of-unsend-event>

## Capability matrix

| Surface | Supported source | Completeness claim |
| --- | --- | --- |
| New inbound 1:1 text | Message webhook | Only events received while the webhook worked |
| New inbound group text | Message webhook while OA is a group member | Same |
| Group name | Group-summary endpoint using a saved group ID | Current summary only |
| Image/audio/video/file | Content endpoint using webhook message ID | Time-limited availability |
| Arbitrary past chat text | None in Messaging API | Unsupported |
| OA outbound replies | Only an application-owned send log | Not present merely because inbound storage exists |

## ai_darkhero implementation map

- `%AI_WORKSPACE%\_skill\fleet-fly-hooks\src\handlers\darkhero\kyloren_bot.js`
  receives and normalizes LINE webhook events.
- `%AI_WORKSPACE%\_skill\fleet-fly-hooks\src\core\drive-inbox-darkhero.js`
  persists raw JSON plus a newest-200 `inbox_manifest.json`.
- `%AI_WORKSPACE%\_skill\engines\distill-url.py` routes captured social URLs
  through deterministic acquisition and the hub free provider pool.
