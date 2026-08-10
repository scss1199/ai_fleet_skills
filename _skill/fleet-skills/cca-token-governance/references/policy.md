# CCA token policy

## Provider boundary

Claude usage and Codex usage are separate ledgers. A local Python gate can be zero-model-token, but a Codex review consumes Codex tokens. Never label cross-provider spend as free merely because Claude did not pay it.

## Admission order

1. Require explicit paid-review authorization.
2. Require readable target bytes and a stable content fingerprint.
3. Reuse a passing receipt for the identical fingerprint.
4. Reject a second review of the same target inside the cooldown window.
5. Enforce the per-target/day count.
6. Enforce the raw-token/day budget using structured usage; treat legacy CLI-only `tokens used` as uncached input plus output, not raw total.
7. In observe mode, open the circuit when historical would-block evidence is already high enough to make another automatic review low-value.
8. Only then run the explicitly pinned review profile.

The default policy is a 1,440-minute cooldown, one review per target per 24 hours, and a 100,000 raw-token daily budget. Automatic remediation stays disabled unless an operator explicitly enables it.

## Token buckets

- `input_tokens` includes cached input when the provider reports it that way.
- `cached_input_tokens` is a subset of input, not an extra bucket to add again.
- `uncached_input_tokens = input_tokens - cached_input_tokens`.
- `cache_write_input_tokens`, `output_tokens`, and `reasoning_output_tokens` remain separate.
- Raw traffic and provider-weighted price equivalents are different measures. If price metadata is absent, the weighted equivalent is `UNKNOWN`.

## Review profile

The configured review process uses `gpt-5.4-mini`, `low` reasoning effort, `default` service tier, and ignores user configuration. Re-verify model availability and the exact service-tier behavior before changing this profile.

## Replay semantics

A historical replay is an estimate, not measured post-change usage. Replay events in timestamp order, use the actual structured token buckets where available, and state the conservative estimate used when a legacy record lacks raw buckets. Report measured baseline and replayed post-policy totals separately.

## Safety and observability

Never expose secrets, prompt bodies, raw transcripts, or hidden reasoning. Dashboards may expose timestamps, phase names, tool names, model metadata, verdicts, and aggregate token buckets. Any field that cannot be observed from a supported source is `UNKNOWN`.
