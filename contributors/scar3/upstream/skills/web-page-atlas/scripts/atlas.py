#!/usr/bin/env python3
"""web-page-atlas — a zero-token site map for fast page-reach + bidirectional learning.

A per-site JSON atlas of "the page that solves problem X": URL + how-to + quirks.
It GROWS from real navigation (backward learning: `add`) and is CONSULTED before
navigating (forward use: `lookup`). Lookups are a local grep => 0 Claude tokens,
so a session jumps straight to the known URL instead of re-exploring a site.

Grounded in the hub ZT/ZTM model (10-foundations/zt-ztm-mtd-multiagent.md) and the
radar->digest->stamp flywheel (50-techniques/self-reinforcing-knowledge-base.md, KB 2026.06.09-18).
Prior art (web-verified 2026-06-11): Agent Workflow Memory (arXiv 2409.07429),
WebCoach (2511.12997), WebATLAS (2510.22732).

CLI:
  atlas.py lookup <site> [query words...]   # forward (ZT): matching pages, ranked
  atlas.py add    <site>                     # backward: upsert one entry from stdin JSON
  atlas.py radar  <site> [--days N]          # ZTM: list stale (>N d) / non-ok entries
  atlas.py list   <site>                     # dump all pages for a site
Site is matched by substring, so "sinopac" or "sinotrade" both hit sinotrade.com.tw.
"""
import sys, os, json, datetime, glob

# Fleet copy (f1s-reverse-learning 2026-10-16, promoted from ai_trader): one shared map for every seat under
# _registry/web-atlas; WEB_ATLAS_DIR overrides (a seat that must keep private account facts points it at its own dir).
ATLAS_DIR = os.environ.get("WEB_ATLAS_DIR") or os.path.join(
    os.environ.get("AI_WORKSPACE", r"C:\ai_workspace"), "_registry", "web-atlas")


def _site_path(site):
    for p in glob.glob(os.path.join(ATLAS_DIR, "*.json")):
        if site.lower() in os.path.splitext(os.path.basename(p))[0].lower():
            return p
        try:
            if site.lower() in (json.load(open(p, encoding="utf-8")).get("site", "")).lower():
                return p
        except Exception:
            pass
    return os.path.join(ATLAS_DIR, site.lower().split(".")[0] + ".json")


def _load(path):
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return {"site": "", "auth": "", "pages": []}


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def _print_pages(data, pages):
    print(f"# atlas {data.get('site', '?')} — auth: {data.get('auth', '?')}")
    for pg in pages:
        print(f"\n## {pg.get('id')} — {pg.get('purpose', '')}")
        print(f"URL: {pg.get('url')}")
        if pg.get("howto"):
            print(f"HOW: {pg['howto']}")
        for qk in pg.get("quirks", []):
            print(f"!!  {qk}")
        print(f"verified: {pg.get('last_verified', '?')} status={pg.get('status', '?')}")


def cmd_lookup(site, query):
    data = _load(_site_path(site))
    terms = [t for t in " ".join(query).lower().split() if t]
    pages = data.get("pages", [])
    if not terms:
        _print_pages(data, pages)
        return
    scored = []
    for pg in pages:
        blob = json.dumps(pg, ensure_ascii=False).lower()
        score = sum(1 for t in terms if t in blob)
        if score:
            scored.append((score, pg))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        print(f"(atlas) no match for '{' '.join(terms)}' in {data.get('site', '?')}; "
              f"navigate + `atlas.py add` to teach it")
        return
    _print_pages(data, [pg for _, pg in scored[:8]])


def cmd_add(site):
    entry = json.load(sys.stdin)
    path = _site_path(site)
    data = _load(path)
    if not data.get("site"):
        data["site"] = entry.get("site", site)
    if entry.get("auth") and not data.get("auth"):
        data["auth"] = entry["auth"]
    entry.setdefault("last_verified", datetime.date.today().isoformat())
    entry.setdefault("status", "ok")
    pages = data.setdefault("pages", [])
    for i, pg in enumerate(pages):
        if pg.get("id") == entry.get("id"):
            pages[i] = {**pg, **entry}
            break
    else:
        pages.append(entry)
    _save(path, data)
    print(f"(atlas) upserted '{entry.get('id')}' -> {os.path.basename(path)} ({len(pages)} pages)")


def cmd_radar(site, days):
    data = _load(_site_path(site))
    today = datetime.date.today()
    stale = []
    for pg in data.get("pages", []):
        bad = pg.get("status", "ok") != "ok"
        try:
            old = (today - datetime.date.fromisoformat(pg.get("last_verified", "1970-01-01"))).days > days
        except Exception:
            old = True
        if bad or old:
            stale.append(pg)
    total = len(data.get("pages", []))
    if not stale:
        print(f"(atlas radar) {data.get('site', '?')}: all {total} pages fresh (<{days}d, status ok)")
        return
    print(f"(atlas radar) {data.get('site', '?')}: {len(stale)}/{total} need re-verify:")
    for pg in stale:
        print(f"  - {pg.get('id')} ({pg.get('last_verified', '?')}, status={pg.get('status', '?')}) {pg.get('url')}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, site = sys.argv[1], sys.argv[2]
    if cmd == "lookup":
        cmd_lookup(site, sys.argv[3:])
    elif cmd == "list":
        cmd_lookup(site, [])
    elif cmd == "add":
        cmd_add(site)
    elif cmd == "radar":
        days = 30
        if "--days" in sys.argv:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        cmd_radar(site, days)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
