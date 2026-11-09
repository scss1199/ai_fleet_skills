---
name: ztm-cursor-edge-auth
description: Compatibility adapter for an authenticated in-IDE browser surface. Use only when the platform-neutral ztm-web-auth-ops resolver selects this installed adapter by capabilities; it is never a fleet-wide requirement or policy authority.
---

# In-IDE browser authentication adapter

This package is a host adapter retained for compatibility. The canonical policy and selection
rules live in `ztm-web-auth-ops`.

## Declared capabilities

When measured available, this adapter may declare:

- `authenticated_session`
- `interactive_navigation`
- `dom_interaction`
- `provider_state_readback`
- `download_to_dropfile` only after the local download path is proven
- `operator_external_paste` when the operator can directly use the visible page

Availability, authentication state, download support, and provider rendering must be probed at run
time. Installation of this skill proves none of them.

## Invocation boundary

1. Invoke `ztm-web-auth-ops` and resolve a names-only adapter inventory.
2. Continue here only if this adapter was selected.
3. Reuse the already-authenticated session; never enter or extract password, MFA, CAPTCHA, cookie,
   profile, payment, or recovery data.
4. Perform the bounded console action and read back provider state.
5. Return measured capabilities and terminal state to the canonical workflow.

If this adapter is absent, unauthenticated, blocked, or unable to transfer a one-shot value safely,
return the missing capability. Do not declare that the whole workflow requires this host.

The dated findings in [inapp-browser-secret-transfer.md](inapp-browser-secret-transfer.md) are
adapter evidence and implementation notes, not universal policy.
