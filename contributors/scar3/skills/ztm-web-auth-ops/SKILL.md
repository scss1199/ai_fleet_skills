---
name: ztm-web-auth-ops
description: Platform-neutral web authentication and provider-console operations. Selects an authenticated UI, management API, CLI, or secure handoff adapter by capabilities and safety evidence, never by AI host name. Use before OAuth, SSO, console configuration, consent, webhook, or provider key operations.
---

# Platform-neutral web authentication operations

This is the canonical policy. Host-specific skills are adapters, not authorities.

## Invariants

- Select by declared capabilities, availability, authority, evidence freshness, and risk.
- Never branch on an AI product, model, vendor, IDE, browser brand, or skill name.
- A platform-specific adapter may implement actions but must not redefine selection or safety policy.
- Never ask an agent to enter passwords, recovery codes, payment data, MFA, or CAPTCHA responses.
- Never extract browser profiles, cookies, password-manager data, or secret values into chat, logs, argv, evidence, or policy files.
- Reuse an operator-authenticated session only through an available adapter with an explicit session capability.
- Missing one host integration is not a blocker. The blocker is `NO_CAPABLE_ADAPTER` after runtime discovery.
- A successful click, request, or redirect is not completion. Read back the provider state named by the goal.

## Capability contract

Build a names-only request and inventory as described in
[host-adapter-contract.md](host-adapter-contract.md). Required capabilities commonly include:

- `provider_management_api` or `provider_cli` for non-interactive work;
- `authenticated_session`, `interactive_navigation`, and `dom_interaction` for console UI;
- one safe egress path: `provider_store_direct`, `secure_stdin`,
  `download_to_dropfile`, or `operator_external_paste` when a one-shot value exists;
- `provider_state_readback` for verification.

Always forbid `agent_password_entry`, `captcha_bypass`, `cookie_extraction`,
`profile_extraction`, `secret_to_chat`, `secret_to_argv`, and `secret_to_log`.

Resolve the smallest capable surface:

```powershell
python scripts/auth-surface-resolver.py --input <names-only-inventory.json> --json
```

The resolver ranks eligible adapters by lower risk, lower interaction cost, higher declared
priority, then inventory order. Adapter identifiers are labels only and never affect eligibility or
score.

## Execution flow

1. **FREEZE** — record provider, intended state, authority, irreversible boundary, required
   capabilities, forbidden capabilities, and read-back predicate.
2. **DISCOVER** — enumerate currently available management API, CLI, project script, interactive
   session, and secure handoff adapters. Do not assume an adapter exists because a skill is installed.
3. **RESOLVE** — run the resolver. `PASS` selects one adapter; `HANDOFF` names missing capabilities;
   malformed or unverifiable inventory is `UNKNOWN`.
4. **ACT** — perform only the authorized operation. The operator alone handles signup, terms,
   identity proof, password, MFA, CAPTCHA, billing, and other owner-only input.
5. **TRANSFER** — keep one-shot values out of agent-visible channels. Prefer provider-to-provider
   storage, then secure stdin or a watched drop file. External paste is the last safe handoff.
6. **VERIFY** — use provider read-back plus a behaviour-specific probe. Record only names, scopes,
   timestamps, status, and evidence identities.
7. **CLOSE** — return `PASS`, `HANDOFF`, `UNKNOWN`, or `FAIL`; never replace a missing capability
   with a platform-specific instruction.

## Deepgram and other provider consoles

If a management credential lacks key-creation scope, request an adapter with
`authenticated_session`, `interactive_navigation`, `dom_interaction`, a safe secret egress
capability, and `provider_state_readback`. Any host that satisfies this contract may continue the
same workflow. If none is available, report `HANDOFF / NO_CAPABLE_ADAPTER` and list the missing
capabilities. Do not phrase the handoff as requiring a particular AI platform.

## Evidence boundary

[oauth-verify-ledger.md](oauth-verify-ledger.md) and [reference.md](reference.md) contain dated
observations about specific tools and sessions. They may inform adapter availability or risk, but
they are not normative policy. Re-test stale observations before routing.
