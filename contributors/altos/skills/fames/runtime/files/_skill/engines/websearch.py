#!/usr/bin/env python3
"""websearch.py — tokenless web search + page-text fetch (ZERO Claude tokens, no API key).

Uses DuckDuckGo's keyless HTML endpoint with a browser User-Agent (same CF-1010 fix as the
Groq pool, see 70-pitfalls/cloudflare-ja3-fingerprinting.md). Returns result (title,url), and
fetches readable page text for feeding into _debate / the free LLM pool. Login-walled hosts
(ig/threads/x/fb) are skipped — they return no content and make models hallucinate.
"""
import sys, re, json, gzip, io, urllib.request, urllib.parse, urllib.error
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from webops_auto import logged_call
except Exception:
    def logged_call(*_a, **_k):
        return (lambda f: f)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
WALLED = ("instagram.com", "threads.net", "threads.com", "x.com", "twitter.com", "facebook.com")

def _get(url, data=None, timeout=20):
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
        headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
                 "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8", "Accept-Encoding": "gzip"})
    r = urllib.request.urlopen(req, timeout=timeout)
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return raw.decode("utf-8", "replace")

def _clean(t):
    return re.sub(r"<[^>]+>", "", t).strip()

def _ddg_url(href):
    mm = re.search(r"uddg=([^&]+)", href)
    url = urllib.parse.unquote(mm.group(1)) if mm else href
    return ("https:" + url) if url.startswith("//") else url

def _b_ddg_html(q):
    h = _get("https://html.duckduckgo.com/html/", data=urllib.parse.urlencode({"q": q}).encode(), timeout=12)
    return [(_clean(m.group(2)), _ddg_url(m.group(1)))
            for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', h, re.S)]

def _b_ddg_lite(q):
    h = _get("https://lite.duckduckgo.com/lite/", data=urllib.parse.urlencode({"q": q}).encode(), timeout=12)
    return [(_clean(m.group(2)), _ddg_url(m.group(1)))
            for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*class="result-link"[^>]*>(.*?)</a>', h, re.S)]

def _b_bing(q):
    h = _get("https://www.bing.com/search?q=" + urllib.parse.quote(q) + "&setlang=zh-hant", timeout=12)
    return [(_clean(m.group(2)), m.group(1))
            for m in re.finditer(r'<h2>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', h, re.S)]

def _bing_url(href):
    """bing.com/ck/a?...&u=a1<base64url>  ->  the real target (ai_trader 2026-10-15: every hit was a ck/a link)."""
    import base64
    href = href.replace("&amp;", "&")
    m = re.search(r"[?&]u=a1([A-Za-z0-9_-]+)", href)
    if not m:
        return href
    try:
        raw = m.group(1)
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")
    except Exception:
        return href


def _gemini_keys():
    try:
        m = json.loads(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_secrets",
                                         "api-matrix.json"), encoding="utf-8-sig").read())
    except Exception:
        return []
    return [k["key"] for k in m.get("keys", []) if k.get("provider") == "gemini" and k.get("status") == "ok" and k.get("key")]


def _resolve(url, timeout=8):
    """Follow the grounding redirect to the page itself; keep the redirect URL if that fails."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.geturl()
    except Exception:
        return url


# ai_trader 2026-10-16 audit: gemini-2.5-flash answers 404 "no longer available to new users" on newer keys
# and 429 on exhausted ones, so each key walks the models instead of dying on the first one.
# 2026-10-16 18:40 probe: 2.5-flash and 2.5-flash-lite answered on keys 1-2 (key 3: 404); the -latest aliases 429'd.
GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest", "gemini-flash-lite-latest")
LAST_ERRORS = {}   # backend name -> last failure ("HTTP 429", "URLError", ...) of the latest search() call


def _b_gemini(q):
    """Google results through Gemini search grounding (free key). ai_ut/ai_trader 2026-10-15: both DDG backends
    returned 0 and Bing returned unrelated pages; grounding returned on-topic sources (taifex.com.tw first)."""
    from concurrent.futures import ThreadPoolExecutor
    errors = []
    for key in _gemini_keys():
        for model in GEMINI_MODELS:
            body = {"contents": [{"parts": [{"text": "Search the web for: " + q + ". List the most relevant sources."}]}],
                    "tools": [{"google_search": {}}]}
            req = urllib.request.Request(
                "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent",
                data=json.dumps(body).encode("utf-8"), method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": key})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                errors.append("%s HTTP %s" % (model, e.code))
                continue
            except Exception as e:
                errors.append("%s %s" % (model, type(e).__name__))
                continue
            chunks = ((d.get("candidates") or [{}])[0].get("groundingMetadata") or {}).get("groundingChunks") or []
            webs = [c.get("web") or {} for c in chunks if (c.get("web") or {}).get("uri")]
            with ThreadPoolExecutor(max_workers=8) as ex:
                urls = list(ex.map(_resolve, [w["uri"] for w in webs]))
            return [(w.get("title") or "", u) for w, u in zip(webs, urls)]
    if errors:
        raise RuntimeError("gemini: " + ", ".join(errors))   # search() records it instead of a silent []
    return []


def _b_gnews(q):
    """Google News RSS, keyless (ai_trader 2026-10-16 audit: answered 96/96 while DDG errored 192/192)."""
    zh = bool(re.search(r"[㐀-鿿]", q))
    hl, gl, ceid = ("zh-TW", "TW", "TW:zh-Hant") if zh else ("en-US", "US", "US:en")
    x = _get("https://news.google.com/rss/search?q=%s&hl=%s&gl=%s&ceid=%s" % (urllib.parse.quote(q), hl, gl, ceid),
             timeout=15)
    pairs = []
    for item in re.findall(r"<item>(.*?)</item>", x, re.S)[:6]:
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        u = re.search(r"<link>(.*?)</link>", item, re.S)
        if t and u:
            pairs.append((_clean(t.group(1).replace("<![CDATA[", "").replace("]]>", "")), u.group(1).strip()))
    # news.google.com/rss/articles/<id> neither redirects nor yields text (fetch_text -> 0 chars, 2026-10-16):
    # decode each id to the publisher URL so distill-url can read the article itself.
    from concurrent.futures import ThreadPoolExecutor

    def dec(pair):
        try:
            return pair[0], _gnews_decode(pair[1]) or pair[1]
        except Exception as e:   # news.google.com 429s bursts: keep the raw link, say why
            LAST_ERRORS["_b_gnews_decode"] = (getattr(e, "code", None) and "HTTP %s" % e.code) or type(e).__name__
            return pair
    with ThreadPoolExecutor(max_workers=3) as ex:   # 6+ parallel decodes drew HTTP 429 (2026-10-16)
        return list(ex.map(dec, pairs))


def _gnews_decode(link, timeout=15):
    """Google News article id (AU_yqL… format) -> publisher URL via the page's signature + batchexecute."""
    gid = urllib.parse.urlparse(link).path.split("/")[-1]
    page = _get("https://news.google.com/articles/" + gid, timeout=timeout)
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return ""
    inner = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                            "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], gid, int(ts.group(1)), sg.group(1)]
    data = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", json.dumps(inner), None, "generic"]]])}).encode()
    req = urllib.request.Request("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=data, method="POST",
                                 headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    m = re.search(r'\[\\"garturlres\\",\\"(.*?)\\"', body)
    return m.group(1).replace("\\\\u003d", "=").replace("\\\\u0026", "&") if m else ""


def _tokens(text):
    # CJK as bigrams: single characters let any page sharing one common hanzi through
    # (ai_zonghe 2026-10-16: Bing's 10 unrelated hits for a Chinese TCM query all passed).
    text = text.lower()
    cjk = set()
    for run in re.findall(r"[㐀-鿿]+", text):
        cjk |= {run[i:i + 2] for i in range(len(run) - 1)} if len(run) > 1 else {run}
    return set(re.findall(r"[a-z0-9]{3,}", text)) | cjk


def _relevant(query, title, url):
    """Keyword-scraped hits must share something with the query; grounding hits are trusted as on-topic."""
    q = _tokens(query)
    hay = title + " " + urllib.parse.unquote(url)
    return not q or bool(q & _tokens(hay)) or any(len(t) == 1 and t in hay for t in q)


BACKENDS = [_b_gemini, _b_gnews, _b_ddg_html, _b_ddg_lite, _b_bing]

@logged_call("search", rung=0, domain_from=lambda a, kw: "duckduckgo.com")
def search(query, n=10):
    """Up to n (title, url) results. Tries multiple keyless backends (DDG html/lite, Bing) so one
    throttled/changed engine doesn't kill the run; first non-empty wins. Returns [] when all throttled
    (a scheduled background run simply retries later — IP-rate-limit on scrapers is time-bounded).
    Each failing backend's reason lands in LAST_ERRORS and, when nothing answers, on stderr."""
    LAST_ERRORS.clear()
    for backend in BACKENDS:
        try:
            raw = backend(query)
        except urllib.error.HTTPError as e:
            LAST_ERRORS[backend.__name__] = "HTTP %s" % e.code
            continue
        except Exception as e:
            LAST_ERRORS[backend.__name__] = str(e)[:200] or type(e).__name__
            continue
        out, seen = [], set()
        for title, url in raw:
            if backend is _b_bing:
                url = _bing_url(url)
            if not url.startswith("http") or url in seen:
                continue
            if backend is not _b_gemini and not _relevant(query, title, url):
                continue
            seen.add(url); out.append((title, url))
            if len(out) >= n:
                break
        if out:
            return out
    if LAST_ERRORS:
        print("websearch: no backend answered: " + json.dumps(LAST_ERRORS, ensure_ascii=False), file=sys.stderr)
    return []

@logged_call("fetch_text", rung=0, domain_from=lambda a, kw: a[0] if a else "unknown")
def fetch_text(url, max_chars=6000):
    """Fetch a page and return readable text (tags/script/style stripped). '' if walled/failed."""
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    # exact domain match: a substring test made "taifex.com" match "x.com" and skipped the whole TAIFEX site
    if any(host == w or host.endswith("." + w) for w in WALLED):
        return ""  # login wall -> no content
    try:
        html = _get(url, timeout=20)
    except Exception:
        return ""
    # \b: without it `<head` also matched `<header ...>` and the lazy span ate the page body (taifex indexMarging
    # lost its margin table: 243 KB html -> 220 chars, ai_trader 2026-10-15).
    html = re.sub(r"(?is)<(script|style|noscript|svg|head)\b[^>]*>.*?</\1>", " ", html)
    # prefer og:description + title as a strong summary, then body text
    og = ""
    mo = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if mo: og = mo.group(1).strip()
    mt = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = re.sub(r"<[^>]+>", "", mt.group(1)).strip() if mt else ""
    body = re.sub(r"(?is)<[^>]+>", " ", html)
    body = re.sub(r"&[a-z#0-9]+;", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    txt = "\n".join(x for x in [title, og, body] if x)
    return txt[:max_chars]

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp950 consoles (ai_ut/ai_trader 2026-10-15)
    except Exception:
        pass
    q = " ".join(sys.argv[1:]) or "內家拳 丹田 內功"
    for i, (t, u) in enumerate(search(q, 8), 1):
        print(f"{i}. {t}\n   {u}")
