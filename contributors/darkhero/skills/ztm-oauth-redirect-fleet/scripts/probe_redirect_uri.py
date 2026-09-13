#!/usr/bin/env python3
"""MTM module block #1 — redirect_uri ground truth, 0 console / 0 LLM tokens.

For every migrated site:
  1. GET its login endpoint with redirects suppressed -> the Location header IS
     the evidence of which client_id + redirect_uri the site actually sends.
  2. Replay that exact authorize URL against Google (redirects suppressed).
     Google answers 400 + "redirect_uri_mismatch" when the URI is NOT registered
     on that client, and 200/302 (consent or login wall) when it IS.

So registration state is measurable WITHOUT opening Cloud Console. Nothing is
written on the Google side and nothing is changed: this is a read-only,
independently rerunnable verifier. Re-run it after any console edit.

THREE INDEPENDENT AXES, deliberately not collapsed into one string
------------------------------------------------------------------
`login`         did the site hand us an authorize URL at all?
`registration`  is the emitted redirect_uri registered on that client?
`origin`        does the emitted redirect_uri point at the host that serves
                the app, over https, with no credentials, and well-formed?

They are orthogonal, and the previous version lost information by ranking them
into a single `google` field:

  - a MISMATCH row overwrote its origin finding, so a site that was BOTH
    unregistered AND pointing at a dead host reported only the registration
    gap. Fixing the console then produced a still-broken login and a green
    probe. Now every axis is reported for every row.
  - a site that answered nothing on its login path was called NO_LOGIN and
    EXCLUDED from the failure count. A service that declares Google SSO in
    inventory.json and stops serving it is a regression, and it now blocks.
    A genuinely hooks-only service declares `expects_login: false` and is
    NOT_APPLICABLE — an explicit statement, not an accident of a 404.

Google's answer alone is NOT sufficient. A site can emit a redirect_uri that is
perfectly registered and still be broken, because the URI points at a host that
no longer serves the app (measured 2026-08-09: ai-ziyaoastro emitted
ai-ziyaoastro.vercel.app, which answers 402 DEPLOYMENT_DISABLED). Google is
happy, issues a code, and strands the user.

CITE: _skill/technique_output/50-techniques/add-missing-gcp-redirect-uris.md
CITE: references/known-failures.md "A registered redirect_uri can still be dead"
"""
import base64
import json
import os
import pathlib
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

# Bumped whenever a consumer-visible field changes. gen_redirect_handoff.py
# refuses to read a state file it was not written against, because emitting
# console instructions from a schema you guessed at is exactly the failure this
# whole skill exists to prevent.
SCHEMA_VERSION = 2

HERE = pathlib.Path(__file__).resolve().parent
INVENTORY_PATH = HERE / "inventory.json"
STATE_PATH = HERE / "redirect_uri_state.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Exact hostname, not a substring. "accounts.google.com.evil.example" contains
# the old substring test's needle and would have been replayed as if it were
# Google.
GOOGLE_AUTHORIZE_HOST = "accounts.google.com"

DEFAULT_PORTS = {"http": 80, "https": 443}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def http_get(url, timeout=25):
    """One request, one dict. Tests replace this symbol; nothing else does I/O.

    A transport failure is `status: 0` AND a non-empty `error`, so a caller can
    tell "the host refused us" from "the host answered 0-ish", which the old
    3-tuple could not: it stuffed the exception text into the body.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = OPENER.open(req, timeout=timeout)
        return {"status": r.status, "headers": dict(r.headers),
                "body": r.read(4000).decode("utf-8", "replace"), "error": None}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "headers": dict(e.headers),
                "body": e.read(4000).decode("utf-8", "replace"), "error": None}
    except Exception as e:  # noqa: BLE001 - transport class is the useful part
        return {"status": 0, "headers": {}, "body": "",
                "error": f"{type(e).__name__}: {e}"}


def _location(headers):
    for k, v in (headers or {}).items():
        if k.lower() == "location":
            return v or ""
    return ""


def _decode_auth_error(loc):
    """Google hides the reason in a base64 `authError` fragment on the error page."""
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
        raw = (q.get("authError") or [""])[0]
        if not raw:
            return ""
        pad = raw + "=" * (-len(raw) % 4)
        return base64.urlsafe_b64decode(pad).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


# --------------------------------------------------------------------------
# inventory / coverage
# --------------------------------------------------------------------------

def workspace_root():
    return pathlib.Path(os.environ.get("AI_WORKSPACE") or
                        pathlib.Path(__file__).resolve().parents[4])


def load_inventory(path=None):
    return json.loads(pathlib.Path(path or INVENTORY_PATH).read_text(encoding="utf-8"))


def build_specs(inventory, cfg_dir=None):
    """Merge the declared inventory with what is actually deployed on disk.

    Coverage has two sources and each catches the other's blind spot: the
    inventory carries intent (ai-busker and ai-eatery have no deploy config yet
    still have logins), the cf-deploy-configs scan carries reality (ai-trader
    had a deploy config and no inventory row, so eight runs of this probe never
    once looked at it).

    A worker present only on disk is `declared: false` and BLOCKS. The old code
    quietly gave it DEFAULT_PATHS and let a 404 read as NO_LOGIN, i.e. as fine.
    """
    services = inventory.get("services") or {}
    default_paths = list(inventory.get("default_login_paths") or [])
    unknown_expects = bool(inventory.get("unknown_service_expects_login", True))

    specs = {}
    for name, entry in services.items():
        specs[name] = {
            "worker": name,
            "declared": True,
            "coverage_source": ["inventory"],
            "expects_login": bool(entry.get("expects_login", True)),
            "login_paths": list(entry.get("login_paths") or default_paths),
            "canonical_origin": entry.get("canonical_origin") or "",
            "callback_path": entry.get("callback_path") or None,
            "note": entry.get("note") or "",
        }

    cfg = pathlib.Path(cfg_dir) if cfg_dir else workspace_root() / "_registry" / "cf-deploy-configs"
    if cfg.is_dir():
        for d in sorted(cfg.iterdir()):
            if not d.is_dir():
                continue
            spec = specs.get(d.name)
            if spec:
                spec["coverage_source"].append("cf-deploy-configs")
                continue
            specs[d.name] = {
                "worker": d.name,
                "declared": False,
                "coverage_source": ["cf-deploy-configs"],
                "expects_login": unknown_expects,
                "login_paths": list(default_paths),
                "canonical_origin": f"https://{d.name}.kyloren.workers.dev",
                "callback_path": None,
                "note": "",
            }

    for spec in specs.values():
        spec["coverage_source"] = "+".join(spec["coverage_source"])
    return dict(sorted(specs.items()))


# --------------------------------------------------------------------------
# URI analysis (pure; the whole offline suite lives here)
# --------------------------------------------------------------------------

def normalize_origin(url):
    """(scheme, host, effective_port) with default ports resolved, or None.

    Comparing raw netlocs called https://x:443/cb and https://x/cb different
    origins and reported a STALE_ORIGIN that did not exist.
    """
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    scheme = (u.scheme or "").lower()
    if scheme not in DEFAULT_PORTS:
        return None
    try:
        host = (u.hostname or "").lower()
        port = u.port
    except ValueError:  # malformed / out-of-range port
        return None
    if not host:
        return None
    return (scheme, host, port or DEFAULT_PORTS[scheme])


def origin_str(parts):
    scheme, host, port = parts
    if port == DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def classify_callback(redirect_uri, canonical_origin):
    """Grade the emitted redirect_uri. Returns (verdict, problems, emitted_origin).

    Most severe first, but `problems` keeps ALL of them: an http:// URI on a
    foreign host is two separate console-visible defects and reporting one hides
    the other from whoever fixes it.
    """
    problems = []
    if not redirect_uri or not str(redirect_uri).strip():
        return "MALFORMED", ["empty_redirect_uri"], None

    raw = str(redirect_uri)
    if raw != raw.strip() or any(c.isspace() for c in raw):
        problems.append("whitespace_in_uri")

    parts = normalize_origin(raw)
    if parts is None:
        problems.append("unparseable_or_non_http_scheme")
        return "MALFORMED", problems, None

    split = urllib.parse.urlsplit(raw)
    if "@" in (split.netloc or ""):
        # userinfo in a callback means a credential rides along in every log,
        # Referer and console listing that ever touches this URI.
        problems.append("credentials_in_uri")
        return "CREDENTIALS", problems, origin_str(parts)

    if problems:  # whitespace made it here: structurally broken, stop.
        return "MALFORMED", problems, origin_str(parts)

    want = normalize_origin(canonical_origin) if canonical_origin else None
    if parts[0] != "https":
        problems.append("insecure_scheme")
        # Hostname only. http://x and https://x differ in effective port purely
        # BECAUSE the schemes differ; reporting a stale_origin there is a false
        # second finding, and a reasons list with noise in it stops being read.
        if want and parts[1] != want[1]:
            problems.append("stale_origin")
        return "INSECURE_SCHEME", problems, origin_str(parts)

    if want is None:
        problems.append("no_canonical_origin_declared")
        return "MALFORMED", problems, origin_str(parts)

    if want[0] != "https":
        problems.append("canonical_origin_not_https")

    same_host = parts[1] == want[1]
    # Ports are only comparable when both sides are https; a declared http
    # canonical is already reported above as its own problem.
    same_port = parts[2] == want[2] or want[0] != "https"
    if not (same_host and same_port):
        problems.append("stale_origin")
        return "STALE", problems, origin_str(parts)

    return ("MATCH" if not problems else "MALFORMED"), problems, origin_str(parts)


def desired_redirect_uri(spec, redirect_uri):
    """The value an ADD line may use: canonical origin + callback path.

    NEVER the emitted URI. When origin is STALE the emitted URI is precisely the
    dead one, and registering it is how a verifier turns a broken login into a
    broken login that passes its own check. The path is taken from the emitted
    URI when it parses (that is the app's business, and it is not the part that
    is wrong), otherwise from the inventory's declared callback_path.
    """
    canonical = spec.get("canonical_origin") or ""
    if not normalize_origin(canonical):
        return None
    path = ""
    if redirect_uri:
        try:
            path = urllib.parse.urlsplit(str(redirect_uri)).path or ""
        except ValueError:
            path = ""
    if not path or not path.startswith("/"):
        path = spec.get("callback_path") or ""
    if not path.startswith("/"):
        return None
    return canonical.rstrip("/") + path


def is_google_authorize(loc):
    if not loc:
        return False
    try:
        u = urllib.parse.urlsplit(loc)
    except ValueError:
        return False
    return (u.scheme or "").lower() == "https" and (u.hostname or "").lower() == GOOGLE_AUTHORIZE_HOST


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------

def find_authorize(spec, timeout=25):
    """Walk the declared login paths. First https://accounts.google.com 3xx wins.

    Distinguishes MISSING (the host answered, just not with an authorize
    redirect) from UNREACHABLE (transport failure or 5xx). Both block, but they
    need different humans.
    """
    base = (spec.get("canonical_origin") or "").rstrip("/")
    attempts = []
    reachable = False
    for path in spec.get("login_paths") or []:
        r = http_get(base + path, timeout=timeout)
        loc = _location(r["headers"])
        attempts.append({"path": path, "http": r["status"],
                         "error": r["error"], "location": loc[:200]})
        if r["error"] or r["status"] == 0 or r["status"] >= 500:
            continue
        reachable = True
        if is_google_authorize(loc):
            return {"login": "FOUND", "login_path": path, "login_http": r["status"],
                    "authorize_url": loc, "attempts": attempts}
    return {"login": "MISSING" if reachable else "UNREACHABLE",
            "login_path": None, "login_http": attempts[-1]["http"] if attempts else None,
            "authorize_url": None, "attempts": attempts}


def check_google(authorize_url, timeout=25):
    """Replay the authorize URL. ONE request; the caller gets the location too.

    control_redirect_uri.py used to call this and then re-fetch the same URL
    just to read the Location header — two hits on Google's auth endpoint for
    one verdict, per case, per run.
    """
    r = http_get(authorize_url, timeout=timeout)
    loc = _location(r["headers"])
    if r["error"] or r["status"] == 0:
        return {"registration": "UNREACHABLE", "http": 0, "location": "",
                "error": r["error"]}
    blob = r["body"] + loc + _decode_auth_error(loc)
    if "redirect_uri_mismatch" in blob:
        verdict = "MISMATCH"
    elif "/signin/oauth/error" in loc:
        verdict = "OAUTH_ERROR"
    elif r["status"] == 400:
        verdict = "HTTP_400_OTHER"
    elif r["status"] in (200, 302, 303):
        verdict = "REGISTERED"
    else:
        verdict = f"UNKNOWN_{r['status']}"
    return {"registration": verdict, "http": r["status"], "location": loc, "error": None}


# --------------------------------------------------------------------------
# verdict composition (pure)
# --------------------------------------------------------------------------

OK_REGISTRATION = {"REGISTERED", "NOT_APPLICABLE"}
OK_ORIGIN = {"MATCH", "NOT_APPLICABLE"}


def compose(spec, login=None, registration=None, origin=None):
    """Fold the three axes into blocking/verdict. No axis can mask another."""
    reasons = []
    if not spec.get("declared"):
        reasons.append("undeclared_service: add it to inventory.json with expects_login")

    login = login or {}
    registration = registration or {}
    origin = origin or {}

    lv = login.get("login", "NOT_APPLICABLE")
    rv = registration.get("registration", "NOT_APPLICABLE")
    ov = origin.get("origin", "NOT_APPLICABLE")

    if lv == "MISSING":
        reasons.append("login_missing: inventory declares Google SSO, no authorize redirect served")
    elif lv == "UNREACHABLE":
        reasons.append("login_unreachable: transport failure or 5xx on every declared login path")

    if rv not in OK_REGISTRATION:
        reasons.append(f"registration_{rv.lower()}")
    for p in origin.get("origin_problems") or []:
        reasons.append(f"origin_{p}")
    if ov not in OK_ORIGIN and not (origin.get("origin_problems") or []):
        reasons.append(f"origin_{ov.lower()}")

    blocking = bool(reasons)
    if not blocking and lv == "NOT_APPLICABLE":
        verdict = "NOT_APPLICABLE"
    elif blocking:
        verdict = "BLOCKED"
    else:
        verdict = "OK"
    return verdict, blocking, reasons


def evaluate(spec, login=None, registration=None, callback=None):
    """Build one row from already-measured parts. Pure — the suite calls this."""
    row = {
        "worker": spec["worker"],
        "declared": spec.get("declared", False),
        "coverage_source": spec.get("coverage_source", ""),
        "expects_login": spec.get("expects_login", True),
        "canonical_origin": spec.get("canonical_origin", ""),
    }
    login = dict(login or {})
    registration = dict(registration or {})

    if not spec.get("expects_login", True):
        login = {"login": "NOT_APPLICABLE", "login_path": None, "login_http": None,
                 "authorize_url": None, "attempts": login.get("attempts", [])}
        registration = {"registration": "NOT_APPLICABLE", "http": None, "location": "", "error": None}
        callback = None

    origin_verdict, problems, emitted = "NOT_APPLICABLE", [], None
    redirect_uri = None
    client_id = None
    if callback:
        redirect_uri = callback.get("redirect_uri")
        client_id = callback.get("client_id")
        origin_verdict, problems, emitted = classify_callback(redirect_uri, spec.get("canonical_origin"))

    origin = {"origin": origin_verdict, "origin_problems": problems, "emitted_origin": emitted}

    row.update({
        "login": login.get("login", "NOT_APPLICABLE"),
        "login_path": login.get("login_path"),
        "login_http": login.get("login_http"),
        "login_attempts": login.get("attempts", []),
        "authorize_url": login.get("authorize_url"),
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "registration": registration.get("registration", "NOT_APPLICABLE"),
        "registration_http": registration.get("http"),
        "registration_error": registration.get("error"),
        "origin": origin_verdict,
        "origin_problems": problems,
        "emitted_origin": emitted,
        "callback_path": spec.get("callback_path"),
        "desired_redirect_uri": desired_redirect_uri(spec, redirect_uri) if spec.get("expects_login", True) else None,
    })
    verdict, blocking, reasons = compose(spec, login, registration, origin)
    row.update({"verdict": verdict, "blocking": blocking, "reasons": reasons})
    return row


def probe(spec, timeout=25):
    """evaluate() plus the two network calls. The only impure step per worker."""
    if not spec.get("expects_login", True):
        return evaluate(spec)
    login = find_authorize(spec, timeout=timeout)
    if login["login"] != "FOUND":
        return evaluate(spec, login=login,
                        registration={"registration": "NOT_APPLICABLE", "http": None,
                                      "location": "", "error": None})
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(login["authorize_url"]).query)
    callback = {"client_id": (q.get("client_id") or [""])[0],
                "redirect_uri": (q.get("redirect_uri") or [""])[0]}
    registration = check_google(login["authorize_url"], timeout=timeout)
    return evaluate(spec, login=login, registration=registration, callback=callback)


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

def state_envelope(rows):
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generator": "probe_redirect_uri.py",
        "summary": summarize(rows),
        "rows": rows,
    }


def write_state(rows, path=None):
    """Atomic replace. A half-written state file used to be indistinguishable
    from a real one, and gen_redirect_handoff would happily emit console
    instructions from the surviving prefix."""
    p = pathlib.Path(path or STATE_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state_envelope(rows), indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def summarize(rows):
    return {
        "total": len(rows),
        "ok": sum(1 for r in rows if r["verdict"] == "OK"),
        "blocked": sum(1 for r in rows if r["verdict"] == "BLOCKED"),
        "not_applicable": sum(1 for r in rows if r["verdict"] == "NOT_APPLICABLE"),
        "undeclared": sum(1 for r in rows if not r.get("declared")),
    }


# --------------------------------------------------------------------------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    exit_zero = "--exit-zero" in argv
    only = None
    if "--only" in argv:
        only = argv[argv.index("--only") + 1]

    inventory = load_inventory()
    specs = build_specs(inventory)
    if only:
        specs = {k: v for k, v in specs.items() if k == only}
        if not specs:
            print(f"no such service: {only}", file=sys.stderr)
            return 2

    rows = []
    for name, spec in specs.items():
        row = probe(spec)
        rows.append(row)
        mark = {"OK": "ok ", "BLOCKED": "XX ", "NOT_APPLICABLE": "-- "}[row["verdict"]]
        print(f"{mark}{name:22s} login={row['login']:14s} "
              f"reg={row['registration']:16s} origin={row['origin']}")
        if row["reasons"]:
            for reason in row["reasons"]:
                print(f"      {reason}")

    write_state(rows)
    s = summarize(rows)
    print(f"\nOK={s['ok']} BLOCKED={s['blocked']} N/A={s['not_applicable']} "
          f"undeclared={s['undeclared']}", file=sys.stderr)
    if s["blocked"] and not exit_zero:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
