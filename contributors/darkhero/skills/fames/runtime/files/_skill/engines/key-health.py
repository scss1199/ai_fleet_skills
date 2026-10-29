#!/usr/bin/env python3
"""key-health.py — explicitly probe API credentials without accidental side effects.

Closes the harvest loop: free_api_hunter stages candidates -> YOU sign up + put the key in
api-matrix.json as status='untested' -> this validates each with a tiny live call and marks it.
Run after onboarding a key, or periodically (it is idempotent + self-healing: a quota0/
ratelimited key re-flips to ok once the provider recovers). Throttled so it never bursts a
provider (bursting is what got the Groq orgs org-restricted).

Driven by the matrix `endpoints` block (schema = openai | gemini | openai-local), so a NEW
provider added to endpoints is auto-covered — no edit here. openai-local (ollama) is skipped
(local, no remote key to validate).

Baked-in lesson (KB 50-techniques/multi-provider-llm-fallback.md + 70-pitfalls/
cloudflare-ja3-fingerprinting.md, KB 2026.06.09-18): a 403 with a Cloudflare body
("error code: 1010" / "Just a moment" / "Attention Required") is a TLS-fingerprint block on
urllib, NOT a dead key. We re-probe that case via curl (browser-like TLS) to read the TRUE
body before classifying — this is how an org-restricted key hiding behind CF is correctly
distinguished from a transient block.

Safety contract:
  * no arguments, --help, and invalid arguments never probe and never write;
  * `probe` is read-only unless --write is explicit;
  * every attempted probe records evidence type and time only when --write is explicit;
  * missing/blank tombstones are never sent to a provider;
  * credential-only checks never upgrade a key to inference-callable.

Usage:
  python key-health.py summary
  python key-health.py probe [--provider NAME] [--max-probes N]
  python key-health.py probe --write [--stale-hours 168]
  python key-health.py --dry      # legacy alias for read-only `probe`
"""
import argparse, datetime, json, os, sys, time, subprocess, shutil, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # co-located engines (_paths)
from _paths import API_MATRIX
from _atomicio import atomic_write

MP = API_MATRIX
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
_CURL = shutil.which("curl")
_CF_HINTS = ("error code: 1010", "just a moment", "attention required", "cloudflare", "cf-ray")
# ZT: this engine is reachable from a WINDOWLESS background launcher (key-pool-tick rider /
# ClaudeHub_KeyPoolTick task, both pythonw). A bare subprocess.run(curl,...) makes Windows
# allocate+SHOW a conhost -> a foreground flash that steals the user's focus. CREATE_NO_WINDOW
# suppresses it (capture_output does NOT). KB 50-techniques/zero-foreground-execution.md.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _is_cf_block(body: str) -> bool:
    low = body.lower()
    return any(h in low for h in _CF_HINTS)


def _curl_oai(url, key, model):
    """Re-probe via curl (browser TLS) to defeat a CF JA3 block on urllib. Returns (http_code, body) or None."""
    if not _CURL:
        return None
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 5})
    try:
        r = subprocess.run(
            [_CURL, "-s", "-m", "40", "-w", "\n%{http_code}", url,
             "-H", f"Authorization: Bearer {key}", "-H", "Content-Type: application/json",
             "-d", body],
            capture_output=True, text=True, timeout=45,
            creationflags=_NO_WINDOW)  # ZT: no conhost flash (KB zero-foreground-execution.md)
        out = r.stdout.rsplit("\n", 1)
        if len(out) == 2 and out[1].strip().isdigit():
            return int(out[1].strip()), out[0][:200]
    except Exception:
        pass
    return None


# 2026-10-27 audit: a valid key was stored `invalid` because its MODEL was refused, e.g. Mistral 403
# tier_not_allowed ("This model is not available in your subscription tier"), NVIDIA 410 end-of-life,
# OpenRouter 404 "This model is unavailable for free". These say nothing about the key: try the next model.
_MODEL_HINTS = ("tier_not_allowed", "subscription tier", "end of life", "unavailable for free",
                "model_not_found", "does not exist", "not found for account", "no longer available")


def _classify_http(code, body):
    low = body.lower()
    if code in (403, 404, 410) and (code == 410 or any(h in low for h in _MODEL_HINTS)):
        return "model-unavailable"
    if any(term in low for term in ("credits", "quota", "billing", "license", "licenses")):
        return "quota0"
    if code == 400 and "restricted" in low:
        return "restricted"
    if code in (401, 403):
        if "restricted" in low or "permission-denied" in low:
            return "restricted"
        return "invalid"
    if code == 402:
        return "quota0"          # credits/quota depleted; re-flips to ok on reset
    if code == 429:
        return "ratelimited"     # transient; still usable
    return f"http{code}"


def test_oai(url, key, model):
    body = {"model": model, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 5}
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=40)
        return "ok"
    except urllib.error.HTTPError as e:
        b = e.read().decode("utf-8", "replace")[:200]
        # CF JA3 block on urllib hides the true status -> re-probe with curl before judging.
        if e.code == 403 and _is_cf_block(b):
            real = _curl_oai(url, key, model)
            if real is None:
                return "cf-blocked"          # unknown; leave status as-is
            rc, rb = real
            return "ok" if rc == 200 else _classify_http(rc, rb)
        return _classify_http(e.code, b)
    except Exception:
        return "neterr"


def test_typesafe(url, key, model):
    # Jev takes typed questions, not chat messages (docs.typesafe.ai/api.md); one tiny noul question.
    body = {"model": model or "jev-1.13.0", "state": {"probe": "ok"},
            "questions": {"ok": {"type": "noul", "instructions": "Is the word in state.probe equal to ok?"}}}
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return "ok" if "answers" in json.loads(r.read().decode("utf-8", "replace") or "{}") else "http200-noanswer"
    except urllib.error.HTTPError as e:
        return _classify_http(e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception:
        return "neterr"


def test_gemini(url_tmpl, key, model):
    # Header auth avoids leaking the credential into proxy/access-log query strings.
    u = url_tmpl.replace("{model}", model)
    req = urllib.request.Request(u, method="POST",
        data=json.dumps({"contents": [{"parts": [{"text": "ok"}]}]}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 "x-goog-api-key": key})
    try:
        urllib.request.urlopen(req, timeout=30)
        return "ok"
    except urllib.error.HTTPError as e:
        # HTTP 429 alone does not prove exhausted quota; it can be transient rate limiting.
        return "ratelimited" if e.code == 429 else _classify_http(e.code, "")
    except Exception:
        return "neterr"


def test_bearer_identity(url, key):
    req = urllib.request.Request(url, method="GET",
        headers={"Authorization": f"Bearer {key}", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=30)
        return "auth-ok"
    except urllib.error.HTTPError as e:
        return _classify_http(e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception:
        return "neterr"


def test_deepgram_identity(key):
    req = urllib.request.Request("https://api.deepgram.com/v1/auth/token", method="GET",
        headers={"Authorization": f"Token {key}", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=30)
        return "auth-ok"
    except urllib.error.HTTPError as e:
        return _classify_http(e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception:
        return "neterr"


def _parse_time(value):
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None


def _is_fresh(entry, stale_hours, now):
    if stale_hours is None:
        return False
    checked = _parse_time((entry.get("health") or {}).get("checked_at"))
    return bool(checked and (now - checked).total_seconds() < stale_hours * 3600)


def _summary(m):
    states = {}
    for entry in m.get("keys", []):
        provider = entry.get("provider", "UNKNOWN")
        status = entry.get("status", "untested")
        row = states.setdefault(provider, {"total": 0, "present": 0, "status": {}})
        row["total"] += 1
        row["present"] += int(bool(entry.get("key")))
        row["status"][status] = row["status"].get(status, 0) + 1
    print("provider       total present statuses")
    for provider, row in sorted(states.items()):
        status = ",".join(f"{k}:{v}" for k, v in sorted(row["status"].items()))
        print(f"{provider:14} {row['total']:>3} {row['present']:>7} {status}")


def _alt_models(k, ep, tried):
    """Other models to try for this key after a model-level refusal: the endpoint roster, in order, deduped."""
    seen, out = {tried}, []
    for m in (ep or {}).get("models") or []:
        if isinstance(m, str) and m and m not in seen:
            seen.add(m); out.append(m)
    return out[:6]


def run_probe(args):
    with open(MP, encoding="utf-8-sig") as handle:
        m = json.load(handle)
    eps = m.get("endpoints", {})
    now = datetime.datetime.now(datetime.timezone.utc)
    selected = set(args.provider or [])
    print(f"{'provider':14}{'row':6}{'result':14}{'evidence':12} -> status   (write={args.write})")
    tested = skipped = unknown = changed = 0
    for idx, k in enumerate(m.get("keys", []), start=1):
        p = k["provider"]
        if selected and p not in selected:
            continue
        if args.max_probes is not None and tested >= args.max_probes:
            skipped += 1
            continue
        if not k.get("key"):
            print(f"  {p:14}{idx:<6}{'tombstone':14}{'none':12} -> {k.get('status', 'untested')}")
            skipped += 1
            continue
        if _is_fresh(k, args.stale_hours, now):
            print(f"  {p:14}{idx:<6}{'fresh-skip':14}{'cached':12} -> {k.get('status', 'untested')}")
            skipped += 1
            continue
        ep = eps.get(p) if isinstance(eps.get(p), dict) else None
        schema = (ep or {}).get("schema", "")
        model = k.get("model") or ((ep or {}).get("models", [None]) or [None])[0]
        evidence = "none"
        if not ep or schema == "openai-local":
            res = "skip"; skipped += 1
        elif schema == "gemini":
            res = test_gemini(ep["url"], k["key"], model or "gemini-2.5-flash")
            evidence = "inference"; tested += 1
        elif schema == "openai":
            res = test_oai(ep["url"], k["key"], model)
            evidence = "inference"; tested += 1
            if res in ("model-unavailable", "http404"):
                for alt in _alt_models(k, ep, model):
                    time.sleep(args.delay)
                    alt_res = test_oai(ep["url"], k["key"], alt)
                    if alt_res in ("ok", "ratelimited", "restricted", "invalid", "quota0"):
                        print(f"  {p:14}{idx:<6}{'model-swap':14}{model} -> {alt}")
                        res = alt_res
                        if args.write and alt_res in ("ok", "ratelimited"):
                            k["model"] = alt   # non-secret field: the key's working model
                        break
        elif schema == "typesafe-systemone":
            res = test_typesafe(ep["url"], k["key"], model)
            evidence = "inference"; tested += 1
        elif schema == "deepgram":
            res = test_deepgram_identity(k["key"])
            evidence = "credential"; tested += 1
        elif p == "xai" or schema == "openai_vision":
            res = test_bearer_identity("https://api.x.ai/v1/models", k["key"])
            evidence = "credential"; tested += 1
        else:
            res = "skip"; skipped += 1
        # map result -> stored status (only flip on a CONFIDENT signal; leave as-is otherwise)
        old = k.get("status", "untested")
        if evidence == "inference" and res in ("ok", "ratelimited"):
            k["status"] = "ok" if res == "ok" else "ratelimited"
        elif res in ("restricted", "invalid", "quota0"):
            k["status"] = res
        # auth-ok proves the credential, not inference; httpXXX/neterr/skip remain UNKNOWN.
        if res not in ("skip",):
            health = {"checked_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                      "result": res, "evidence": evidence}
            if args.write:
                k["health"] = health
        if k.get("status", "untested") != old:
            changed += 1
        if res in ("cf-blocked", "neterr", "model-unavailable") or res.startswith("http") or res == "skip":
            unknown += int(res != "skip")
        print(f"  {p:14}{idx:<6}{res:14}{evidence:12} -> {k.get('status', 'untested')}")
        if res not in ("skip",):
            time.sleep(args.delay)
    if args.write:
        atomic_write(MP, json.dumps(m, indent=2, ensure_ascii=False))
    print(f"\ntested={tested} skipped={skipped} unknown={unknown} changed={changed}")
    print("matrix written atomically." if args.write else "matrix NOT written (use --write explicitly).")
    return 3 if unknown else 0


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("summary", help="read matrix metadata; no network and no write")
    probe = sub.add_parser("probe", help="run bounded network probes; read-only by default")
    probe.add_argument("--provider", action="append", help="limit to provider (repeatable)")
    probe.add_argument("--max-probes", type=int)
    probe.add_argument("--stale-hours", type=float)
    probe.add_argument("--delay", type=float, default=2.0)
    probe.add_argument("--write", action="store_true", help="atomically persist status/evidence")
    ap.add_argument("--dry", action="store_true", help=argparse.SUPPRESS)
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--dry"]:
        argv = ["probe"]
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return 2
    if args.cmd == "summary":
        with open(MP, encoding="utf-8-sig") as handle:
            m = json.load(handle)
        _summary(m)
        return 0
    return run_probe(args)


if __name__ == "__main__":
    sys.exit(main())
