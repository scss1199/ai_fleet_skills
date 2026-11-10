#!/usr/bin/env python3
"""MTM module block #3 — prove the probe can still tell registered from not.

A verifier that answers "everything is fine" is worthless unless it is also shown
to answer "this one is broken" on a case that IS broken. This runs both controls
against Google and ASSERTS the outcome:

  positive  a redirect_uri the last probe run found REGISTERED  -> REGISTERED
  negative  the same URI on a host that cannot possibly be registered -> MISMATCH

Non-zero exit on any deviation. The previous version printed the two results and
exited 0 unconditionally, so a probe that had degraded to answering REGISTERED
for everything passed its own control silently — and any CI step gating on it
went green.

It also issued TWO requests per case: check_google() for the verdict, then a
second identical GET just to read the Location header for display. check_google()
now returns the location, so this is one request per verdict.

Requires a network. Exit codes:

  0  both controls held — the probe can still tell the two apart
  1  a control produced the OPPOSITE verdict — the probe's answers are suspect
  2  a control produced NO verdict, so nothing was proven either way (no
     REGISTERED+MATCH row in state, Google unreachable, or the request rejected
     before the redirect_uri was ever compared — see BOGUS_HOST)

1 and 2 are deliberately different. 1 accuses the probe; 2 accuses this file.
"""
import json
import pathlib
import sys
import urllib.parse

from probe_redirect_uri import SCHEMA_VERSION, STATE_PATH, check_google

# RFC 2606 §3 reserves example.com for documentation; IANA holds it permanently,
# so no third party can ever acquire it and no client of ours can ever register a
# URI under it. It is also a syntactically valid, publicly-resolvable domain,
# which is the part that matters here.
#
# MEASURED 2026-08-10 — do NOT "harden" this back to a .invalid host. A host under
# the reserved .invalid TLD is rejected by Google BEFORE the redirect_uri is
# compared against the client:
#
#   definitely-not-registered-xyz.invalid      -> invalid_request       (OAUTH_ERROR)
#   definitely-not-registered-xyz.example.com  -> redirect_uri_mismatch (MISMATCH)
#
# i.e. the .invalid variant never reached the check the negative control exists to
# exercise. The control was passing through a policy rejection and calling it proof.
BOGUS_HOST = "definitely-not-registered-xyz.example.com"


def load_rows(path=None):
    p = pathlib.Path(path or STATE_PATH)
    if not p.is_file():
        print(f"FAIL(2): no {p.name}; run probe_redirect_uri.py first", file=sys.stderr)
        raise SystemExit(2)
    data = json.loads(p.read_text(encoding="utf-8"))
    schema = data.get("schema") if isinstance(data, dict) else None
    if schema != SCHEMA_VERSION:
        print(f"FAIL(2): state schema {schema!r} != {SCHEMA_VERSION}; "
              "re-run probe_redirect_uri.py", file=sys.stderr)
        raise SystemExit(2)
    return data["rows"]


# The only two verdicts that mean "Google compared the URI against the client".
# Everything else (UNREACHABLE, OAUTH_ERROR, HTTP_400_OTHER, UNKNOWN_*) means the
# request died earlier, so the control says nothing about the probe either way.
# Collapsing that into "FAIL" sends the operator hunting a probe bug that is
# really a broken control.
CONCLUSIVE = {"REGISTERED", "MISMATCH"}


def pick_positive(rows):
    """A row that is registered AND whose origin matches — both, or the control
    is built on a URI we have already proven is wrong."""
    for r in rows:
        if r.get("registration") == "REGISTERED" and r.get("origin") == "MATCH" \
                and r.get("client_id") and r.get("redirect_uri"):
            return r
    return None


def authorize_url(client_id, redirect_uri):
    q = urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri,
        "response_type": "code", "scope": "openid email", "access_type": "offline",
    })
    return "https://accounts.google.com/o/oauth2/v2/auth?" + q


def mutate(redirect_uri):
    u = urllib.parse.urlsplit(redirect_uri)
    return urllib.parse.urlunsplit(("https", BOGUS_HOST, u.path or "/", "", ""))


def run(rows):
    row = pick_positive(rows)
    if row is None:
        print("FAIL(2): no REGISTERED+MATCH row in state — the positive control "
              "cannot be constructed, so the probe is UNPROVEN. Not a pass.",
              file=sys.stderr)
        return 2

    cases = [
        ("positive", row["redirect_uri"], "REGISTERED"),
        ("negative", mutate(row["redirect_uri"]), "MISMATCH"),
    ]
    failures = 0
    inconclusive = 0
    for label, ruri, expected in cases:
        res = check_google(authorize_url(row["client_id"], ruri))
        got = res["registration"]
        ok = got == expected
        if got not in CONCLUSIVE:
            inconclusive += 1
        elif not ok:
            failures += 1
        print(f"{label:9s} expect={expected:11s} got={got:16s} http={res['http']} "
              f"{'OK' if ok else 'FAIL'}  loc={(res['location'] or '')[:80]}")

    if inconclusive:
        print(f"FAIL(2): {inconclusive} control(s) produced no registration verdict "
              "(unreachable, or rejected by Google before the redirect_uri was "
              "checked). The control did not run; that is not a pass, and it is "
              "not evidence against the probe either — fix the control host.",
              file=sys.stderr)
        return 2
    if failures:
        print(f"FAIL(1): {failures} control(s) deviated. The probe's verdicts "
              "cannot be trusted until this is explained.", file=sys.stderr)
        return 1
    print(f"controls OK (client {row['client_id'][:24]}…, via {row['worker']})",
          file=sys.stderr)
    return 0


def main(argv=None):
    return run(load_rows())


if __name__ == "__main__":
    sys.exit(main())
