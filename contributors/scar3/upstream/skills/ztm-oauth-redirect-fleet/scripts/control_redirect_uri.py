#!/usr/bin/env python3
"""Negative control for probe_redirect_uri.py — verify the verifier.

A detector that can only ever say REGISTERED proves nothing. Feed the same real
client_id one URI we believe is registered and one that certainly is not; the
detector must separate them.
"""
import json
import pathlib
import urllib.parse

from probe_redirect_uri import check_google, get

# The positive case must be a pair the last probe run actually observed as
# REGISTERED. Hard-coding one (this file used to pin ai-career) turns the
# control into a false alarm the moment that site is the thing being fixed.
_rows = json.loads(
    (pathlib.Path(__file__).with_name("redirect_uri_state.json")).read_text(encoding="utf-8"))
_ok = next(r for r in _rows if r.get("google") == "REGISTERED")
CID = _ok["client_id"]
_good = _ok["redirect_uri"]
_bad = _good.replace("://", "://definitely-not-registered-xyz.", 1)
CASES = [
    (f"expect REGISTERED ({_ok['worker']})", _good),
    ("expect MISMATCH             ", _bad),
]

for label, ruri in CASES:
    q = urllib.parse.urlencode({
        "client_id": CID, "redirect_uri": ruri,
        "response_type": "code", "scope": "openid email", "access_type": "offline",
    })
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + q
    verdict, st = check_google(url)
    _, hd, _ = get(url)
    loc = (hd.get("Location") or "")[:80]
    print(f"{label} -> {verdict:12s} http={st} loc={loc}")
