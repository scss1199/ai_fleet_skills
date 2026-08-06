#!/usr/bin/env python3
"""MTM module block #1 — redirect_uri ground truth, 0 console / 0 LLM tokens.

For every migrated site:
  1. GET its login endpoint with redirects suppressed -> the Location header IS
     the evidence of which client_id + redirect_uri the site actually sends.
  2. Replay that exact authorize URL against Google (redirects suppressed).
     Google answers 400 + "redirect_uri_mismatch" when the URI is NOT registered
     on that client, and 200/302 (consent or login wall) when it IS.

So registration state is measurable WITHOUT opening Cloud Console. Nothing is
written and nothing is changed: this is a read-only, independently rerunnable
verifier. Re-run it after any console edit to confirm the fix.

CITE: _skill/technique_output/50-techniques/add-missing-gcp-redirect-uris.md
"""
import base64
import json
import pathlib
import sys
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)

# Sites that do not live on *.kyloren.workers.dev need their origin spelled out.
# fracdigi is a Cloudflare Worker on a custom domain (wrangler.jsonc routes ->
# new.messages.fracdigi.com); its login client is the Firebase web client
# 786327629029-…, NOT the 174364… Ads/credential client.
# The custom domain in wrangler.jsonc (new.messages.fracdigi.com) does NOT
# resolve yet (getaddrinfo failed, 2026-08-06), so the live origin is the
# workers.dev one — probe what exists, not what the config intends.
BASES = {
    "ai-fracdigi": "https://ai-fracdigi.kyloren.workers.dev",
}

# worker -> candidate login paths (first one that 3xx's to accounts.google.com wins)
SITES = {
    "ai-fracdigi": ["/api/auth/google/start"],
    "ai-jci-taipei": ["/api/auth/login"],
    "ai-darkhero": ["/api/auth/login"],
    "ai-search": ["/api/auth/login"],
    "ai-ut": ["/api/auth/login"],
    "ai-career": ["/api/auth/login"],
    "ai-busker": ["/api/auth/login"],
    "ai-heartlink": ["/api/auth/login"],
    "ai-eatery": ["/api/auth/login"],
    "ai-ziyaoastro": ["/api/auth/google/login", "/api/auth/login", "/api/login/google"],
}


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = OPENER.open(req, timeout=timeout)
        return r.status, dict(r.headers), r.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(4000).decode("utf-8", "replace")
    except Exception as e:
        return 0, {}, f"ERR {type(e).__name__}: {e}"


def find_authorize(worker):
    base = BASES.get(worker, f"https://{worker}.kyloren.workers.dev")
    for path in SITES[worker]:
        st, hd, _ = get(base + path)
        loc = hd.get("Location") or hd.get("location") or ""
        if st in (301, 302, 303, 307, 308) and "accounts.google.com" in loc:
            return path, st, loc
    return None, st, ""


def _decode_auth_error(loc):
    """Google does not spell the error out: it 302s to
    /signin/oauth/error?authError=<base64 protobuf> whose payload carries the
    literal string. A plain substring match on the URL always misses it — that
    false negative is why the first run of this probe reported 9/9 REGISTERED.
    """
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    raw = (q.get("authError") or [""])[0]
    if not raw:
        return ""
    pad = raw.replace("-", "+").replace("_", "/")
    pad += "=" * (-len(pad) % 4)
    try:
        return base64.b64decode(pad).decode("utf-8", "replace")
    except Exception:
        return ""


def check_google(authorize_url):
    st, hd, body = get(authorize_url)
    loc = hd.get("Location") or hd.get("location") or ""
    blob = body + loc + _decode_auth_error(loc)
    if "redirect_uri_mismatch" in blob:
        return "MISMATCH", st
    if "/signin/oauth/error" in loc:
        return "OAUTH_ERROR", st
    if st == 400:
        return "400_OTHER", st
    if st in (200, 302, 303):
        return "REGISTERED", st
    return f"UNKNOWN_{st}", st


def main():
    rows = []
    for worker in SITES:
        path, st, loc = find_authorize(worker)
        if not path:
            rows.append({"worker": worker, "login": "-", "status": f"NO_OAUTH_REDIRECT({st})"})
            continue
        q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
        cid = (q.get("client_id") or ["-"])[0]
        ruri = (q.get("redirect_uri") or ["-"])[0]
        verdict, gst = check_google(loc)
        rows.append({
            "worker": worker, "login": path, "http": st,
            "client_id": cid, "redirect_uri": ruri,
            "google": verdict, "google_http": gst,
        })
    # Write the state file ourselves: PowerShell's `>` redirection writes a
    # UTF-8 BOM, which json.load() rejects, silently breaking every downstream
    # module block that reads redirect_uri_state.json.
    pathlib.Path(__file__).with_name("redirect_uri_state.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    bad = [r for r in rows if r.get("google") != "REGISTERED"]
    print(f"\nOK={len(rows)-len(bad)} BAD={len(bad)}", file=sys.stderr)
    for r in bad:
        print(f"  {r['worker']:16s} {r.get('google','-'):14s} {r.get('redirect_uri','-')}", file=sys.stderr)


if __name__ == "__main__":
    main()
