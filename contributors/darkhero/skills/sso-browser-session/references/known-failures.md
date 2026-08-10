# sso-browser-session — known failures

Migration Rule 13 log. One entry per failure class actually observed, with symptom,
root cause, safe fix, and the retry rule. Never delete an entry — a fixed bug that
loses its entry comes back.

---

## 1. `seed` prints "OK — session detected" on the login page (false positive)

**Observed:** 2026-08-08, realm `google.cloud.console`, hub engine
`_skill/engines/sso_browser.py`.

**Symptom.** The operator ran

```powershell
python C:\ai_workspace\_skill\engines\sso_browser.py seed google.cloud.console
```

The headful Edge window opened, redirected to the Google sign-in page, and the engine
immediately printed

```
OK — session detected: https://accounts.google.com/v3/signin/identifier?continue=https://console.cloud.google.com/apis/cred…
```

then closed the window and wrote `seeded: true` into
`_secrets/browser-profiles/google.cloud.console/session_meta.json`. **No human ever
typed anything.** Every downstream step then believed a session existed, and the
subsequent `check` / handoff writeup was built on a measurement instrument that could
not fail.

**Root cause — three independent defects, all required for the blast radius:**

1. **The matcher compared fragments against the WHOLE URL, query string included.**
   `logged_in_url_contains` was `console.cloud.google.com/apis/credentials`, and the
   Google sign-in URL carries
   `?continue=https://console.cloud.google.com/apis/credentials`. **The logged-in
   fragment was sitting inside the login page's own query string.** The first loop tick
   after `page.goto(login_url)` therefore matched.

   This is a *general class*, not a Google quirk: every OAuth/SSO login page embeds its
   destination in `continue=` / `redirect_uri=` / `next=` / `ReturnUrl=`. Any naive
   "am I on the destination yet?" substring test over a raw URL **self-satisfies on the
   login page**. tpbusker's `signin.aspx?ReturnUrl=/tpbusker/venue-detail` is the same
   shape.

2. **Stale logged-out patterns.** The realm listed `accounts.google.com/signin`; the
   live URL is `accounts.google.com/v3/signin/identifier`. The `/v3` segment defeats the
   substring, so the negative guard that should have caught defect 1 did not fire.

3. **The seed loop sabotaged the login it was waiting for.** The body ran
   `if time.time() % 15 < 2: page.goto(validate_url, …)`, force-navigating roughly every
   15 s. That yanks the operator out of a multi-step Google sign-in (identifier →
   password → 2FA) mid-flow, so even without defects 1–2 the seed could not have
   completed.

**Safe fix (all four landed together):**

- `_url_key(url)` — every URL comparison in the module now goes through
  `urlsplit()` and keys on **`netloc + path`, lowercased, query and fragment
  discarded**. A destination can never be matched out of a query string again.
- `_IDP_HOSTS` hard veto — `accounts.google.com`, `login.microsoftonline.com`,
  `login.live.com`, `signin.aws.amazon.com`, `github.com/login` return `False`
  unconditionally. **An identity provider is never a destination**, whatever the
  fragments say.
- **Confirm, do not trust one sample.** On a positive the seed re-navigates to
  `validate.url` and requires the match to hold before writing `seeded: true`; a
  mid-redirect frame can satisfy the fragments for one tick.
- **Suppress the nudge while on an IdP host**, so the periodic re-navigation can no
  longer destroy a sign-in in progress.

**Retry rule.**

- Regression cases are pinned in the engine itself as a subcommand — there is no
  `_skill/engines/test_*.py` convention to hook into:

  ```powershell
  python C:\ai_workspace\_skill\engines\sso_browser.py selftest
  ```

  Exit `0` = pass, `1` = fail. It pins the exact false-positive URL plus two
  `gov.isso.tpbusker` cases to prove no regression. **Run it after touching any
  realm's `validate` block or any matcher code.** Measured 2026-08-08: `7/7 passed`.
- When adding a realm, `logged_out_url_contains` must name the **host and path** of the
  IdP (`accounts.google.com/`, `/signin/identifier`, `/ServiceLogin`), never a bare
  product word.
- **Never trust `seeded: true` alone.** It records that a seed run *ended*, not that a
  session exists. `check <realm>` is the authority; a stale `seeded: true` from a bad
  run must be cleared, or the next agent inherits the same false conclusion.
- Treat "the mechanism reported success without a human doing the human step" as
  proof of a broken matcher, not as good news.

**Stated limitation of the fix** (raised by Codex shadow review `20260808_174141`,
verdict PASS / 0 blockers — this is a documented cost, not an open defect):

> `_url_key()` discards query and fragment, so **a realm whose logged-in and logged-out
> states differ only by query string is indistinguishable by URL.**

No realm in `_registry/sso-realms.json` is that shape today (`google.cloud.console`,
`gov.isso.tpbusker` and the `social.*` realms all differ by host or path). A realm that
*is* must not try to solve it with URL patterns — it has to declare a DOM signal:

```json
"validate": { "logged_in_selector": "…", "logged_out_selector": "…" }
```

`_dom_logged_in()` applies these in both `check` and the seed confirmation, and only ever
**narrows** the URL verdict (`ok = url_ok and dom_ok`), so a selector can never resurrect
the false positive above. `check` reports which signals ran as `"signal": "url"` or
`"url+dom"`. `selftest` also lints the registry: any `logged_in_url_contains` /
`logged_out_url_contains` pattern containing `?`, `&` or `=` is **dead config** — it can
never match host+path — and fails the run.

---

## 2. `seed` reports "timeout" after a *successful* sign-in (false negative)

**Observed:** 2026-08-08, same engine, found while re-reading the fix for entry 1.

**Symptom.** The seed banner tells the operator: *"complete SSO in the browser window,
then close it (or wait for auto-detect)."* Closing the window makes `ctx.pages` empty,
the wait loop `break`s, and the post-loop path unconditionally wrote
`seeded: false` and printed `timeout — last url: …` — **reporting the documented happy
path as a failure**, even though the cookies were by then sitting in the persistent
profile.

**Root cause.** The loop's exit was treated as the failure case. There is no way for the
in-window loop to observe a session after the window it was watching is gone, so
"loop ended without confirming" was silently equated with "no session".

**Safe fix.** The loop no longer decides. It records `confirmed_url` and breaks; the
headful context is closed; then `_validate_persistent()` — the same headless check that
backs `check` — re-opens the profile and is the arbiter. Meta and exit code come from
that result. Success prints `OK — session verified headless after the window closed: …`.

**Retry rule.** Any code path that writes `seeded:` must be able to name the observation
it is reporting. If it cannot see the profile, it must ask `_validate_persistent()`
rather than assume. Both directions of the lie belong to the same class: **the seed must
never report a state it did not measure.**

---

## 3. Seed window expires before the human reaches the machine

**Observed:** 2026-08-08, realm `google.cloud.console`. An agent-launched background seed
ran **607 s** (17:50:18 → 18:00:25 — the whole hard-coded 600 s deadline), nobody signed
in, and it correctly reported `no session — headless re-check: accounts.google.com/…`,
exit 1. The report was honest; the run was still wasted.

**Root cause.** `deadline = time.time() + 600` assumed the operator is at the keyboard
when the command starts. That holds when *they* type it, not when the agent opens the
window for them to pick up later — the one case where the human step is the whole point.

**Safe fix.** The wait is now a parameter: `seed <realm> [--wait SECONDS]`, default
`SEED_WAIT_DEFAULT` (600, overridable by `SSO_SEED_WAIT_SECONDS`). The banner prints the
window length so a "no session" result can be read against how long it actually waited.

**Retry rule.** When the agent opens a seed window for the operator to complete later,
pass `--wait` generously (`3600`). A short deadline turns a *timing* miss into what looks
like an auth failure, and the agent may not type the password to shorten it —
`ztm-oauth-redirect-fleet/SKILL.md:128`.
