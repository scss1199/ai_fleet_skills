#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""api_budget.py -- persistent usage ledger + quota scheduler for the key pool.

WHY THIS EXISTS (the gap it closes)

Three layers of quota awareness already existed on this box, and none of them
remembers anything useful across a call:

  _llm.py       in-process `capped` set: a 429 on one key skips that key's other
                models for the REST OF THIS PROCESS, then is thrown away on exit.
  key-health.py hours-later live probe flips a key's status to quota0 /
                ratelimited in the matrix. Correct, but it learns by burning a
                real request, and only when the tick happens to run.
  asr_providers try the next key when this one raises. Discover-by-failure.

So every rotation on this machine is REACTIVE: the pool finds out a key is spent
by spending it. Nothing can answer "how many calls did this key make in the last
minute", "which capability is eating the gemini pool", or "is this key close
enough to its ceiling that I should start on a different one". That answer needs
memory that outlives the process, which is what this file is.

    scheduling  = choose a key that is under budget BEFORE calling it
    rotation    = choose a different key AFTER one failed
    this engine = the first; the existing code already does the second

DESIGN RULES

  * No secret values. Ever. A key is identified here by `fp()` -- sha256 of the
    value, first 12 hex. fp() is the only function that touches a value and it
    neither returns nor logs it. The ledger is safe to read out loud.
  * Ledger is LOCAL and gitignored (_logs/), never fleet-synced: it is per-device
    telemetry, and syncing it would both churn git on every API call and leak one
    seat's activity pattern to the others. Budgets (the numbers) ARE fleet data
    and live in _registry/api-budgets.json.
  * Budgets are per (provider, seat). A free tier's ceiling belongs to the
    ACCOUNT, not the device -- three seats sharing one account share one ceiling.
    That is exactly why `scope: account` budgets warn instead of promising: this
    engine can only see the calls THIS box made.
  * Append-only JSONL, compacted on write past a size threshold. A crash mid-run
    loses at most the current line, and a lost line means one call is
    unaccounted-for (over-optimistic by 1), never a wrong ceiling.

USAGE
  python api_budget.py show [--provider gemini] [--json]
  python api_budget.py pick --provider gemini --keys fp1,fp2,fp3 [--json]
  python api_budget.py record --provider gemini --key fp1 --capability vision.handwriting_cjk --outcome ok
  python api_budget.py cooldown --provider gemini --key fp1 --seconds 3600 --reason "429 rpd"
  python api_budget.py gc

CITE: _registry/api-budgets.json (limits) . api_registry.py (catalog/seat split)
      jci_taipei/_line/model_router.py (static priority vs live probe split)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE", r"C:\ai_workspace"))
LEDGER_DIR = HUB / "_logs" / "api-usage"
BUDGETS = HUB / "_registry" / "api-budgets.json"

# Past this the ledger is rewritten keeping only rows inside the longest window
# we ever ask about (a day) plus slack. Bounded file, no cron needed.
COMPACT_BYTES = 512_000
KEEP_SECONDS = 36 * 3600

# Used when a provider has no entry in api-budgets.json. Deliberately generous:
# an unknown ceiling must not become a fake ceiling that throttles a key nobody
# measured. UNKNOWN here means "no scheduling signal", not "blocked".
DEFAULT_BUDGET = {"rpm": None, "rpd": None, "scope": "unknown"}

# Auto-park applied when a call records `ratelimited` and the caller did not say how
# long. 15 minutes is a compromise, and an admitted guess about DURATION only -- not
# about a ceiling: a per-minute limit clears long before it, a per-day limit does not,
# so it costs a little headroom on the first and saves a lot of 429s on the second.
DEFAULT_PARK_SECONDS = 900


def seat() -> str:
    """Fleet seat id, borrowed from api_registry so one mapping serves both.

    The ledger filename has to agree with _registry/api-availability/<seat>.json or
    the two halves of the same seat's story sit under different names. Re-typing the
    hostname table here is how that drifts, so import it and only fall back to a bare
    host id if the import is unavailable.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import api_registry  # noqa: PLC0415 -- deliberate: single source for the mapping
        return api_registry.seat()
    except Exception:
        return os.environ.get("AI_SEAT") or f"host:{socket.gethostname().lower()}"


def fp(value: str) -> str:
    """Key value -> stable 12-hex fingerprint. The only function that sees a value.

    Never returns, prints or stores any part of the value itself: a sha256 prefix
    cannot be walked back to the key, so the ledger stays quotable in a report.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _ledger_path(s: str | None = None) -> Path:
    s = s or seat()
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    return LEDGER_DIR / f"{s.replace(':', '_')}.jsonl"


def _load_budgets() -> dict:
    try:
        return json.loads(BUDGETS.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"providers": {}}


def budget_for(provider: str) -> dict:
    """Declared limit wins; observed ceiling fills in; otherwise UNKNOWN (no throttle).

    Free-tier numbers churn, and a guessed ceiling is worse than none: it throttles
    a key nobody measured and hides real headroom. So api-budgets.json ships with
    every `declared` null, and `learn` fills `observed` from what the ledger
    actually saw a key do before it 429'd. Measured, never assumed.
    """
    b = (_load_budgets().get("providers") or {}).get(provider)
    if not isinstance(b, dict):
        return dict(DEFAULT_BUDGET)
    out = dict(DEFAULT_BUDGET)
    out["scope"] = b.get("scope") or "unknown"
    obs = b.get("observed") or {}
    for field in ("rpm", "rpd"):
        v = b.get(field)
        if v is None:
            v = obs.get(field)
        out[field] = v
    out["source"] = "declared" if b.get("rpd") or b.get("rpm") else ("observed" if obs else "unknown")
    return out


def learn(write: bool = False) -> dict:
    """Derive each provider's real ceiling from what the ledger watched happen.

    Method: for every 429 in the ledger, count that key's metered calls in the
    60s / 24h before it. The smallest such count across incidents is the tightest
    evidence of where the wall is -- one 429 at 47 calls/day means the ceiling is
    at most 47, whatever the docs claim. No incidents yet means no ceiling is
    reported, which is correct: nothing was observed, so nothing is known.
    """
    rows = _rows(since=time.time() - KEEP_SECONDS)
    hits: dict[str, dict[str, list[int]]] = {}
    for r in rows:
        if r.get("outcome") != "ratelimited":
            continue
        p, k, ts = r.get("provider"), r.get("key"), float(r.get("ts") or 0)
        if not p or not k:
            continue
        prior = [x for x in rows if x.get("provider") == p and x.get("key") == k
                 and float(x.get("ts") or 0) < ts
                 and x.get("outcome") in ("ok", "empty", "ratelimited", "error")]
        n_min = sum(1 for x in prior if float(x["ts"]) >= ts - 60)
        n_day = sum(1 for x in prior if float(x["ts"]) >= ts - 86400)
        d = hits.setdefault(p, {"rpm": [], "rpd": [], "n": 0})
        d["n"] += 1
        # A 429 with zero prior calls on THIS box says the ceiling was reached by
        # something this ledger cannot see -- another seat on the same account, or a
        # window that predates the ledger. It is a real incident but carries no
        # evidence about where the wall is, so it must not enter the min(): one such
        # row would pin every learned ceiling at zero forever.
        if n_min:
            d["rpm"].append(n_min)
        if n_day:
            d["rpd"].append(n_day)
    out = {p: {"rpm": min(v["rpm"]) if v["rpm"] else None,
               "rpd": min(v["rpd"]) if v["rpd"] else None,
               "incidents": v["n"]} for p, v in hits.items()}
    if write and out:
        doc = _load_budgets()
        provs = doc.setdefault("providers", {})
        for p, v in out.items():
            entry = provs.setdefault(p, {"rpm": None, "rpd": None, "scope": "unknown"})
            entry["observed"] = {"rpm": v["rpm"], "rpd": v["rpd"],
                                 "incidents": v["incidents"],
                                 "learned_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        doc["learned"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        BUDGETS.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"providers": out, "written": bool(write and out)}


def _rows(since: float | None = None, s: str | None = None) -> list[dict]:
    p = _ledger_path(s)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue  # a torn line costs one row, never the whole ledger
        if since is None or float(r.get("ts") or 0) >= since:
            out.append(r)
    return out


def _append(row: dict) -> None:
    p = _ledger_path()
    if p.exists() and p.stat().st_size > COMPACT_BYTES:
        keep = [r for r in _rows(since=time.time() - KEEP_SECONDS)]
        p.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep),
            encoding="utf-8",
        )
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def record(
    provider: str,
    key: str,
    capability: str = "",
    outcome: str = "ok",
    model: str | None = None,
    units: int = 1,
    detail: str = "",
) -> dict:
    """Log one call. `key` is a fingerprint, never a value.

    outcome vocabulary (kept small on purpose):
      ok            call returned usable content
      empty         HTTP 200 with blank/degenerate output -- the empty-shell
                    failure asr_providers.py documents. Counts against quota
                    (the provider charged for it) but is NOT a success.
      ratelimited   429 / quota refusal
      error         anything else
    """
    row = {
        "ts": round(time.time(), 3),
        "seat": seat(),
        "provider": provider,
        "key": key,
        "capability": capability,
        "model": model,
        "outcome": outcome,
        "units": int(units),
    }
    if detail:
        row["detail"] = detail[:200]
    _append(row)
    if outcome == "ratelimited":
        # Park on the caller's behalf. Leaving this to a second explicit call means
        # the one guarantee this engine exists to provide -- that a 429 discovered by
        # one process is not re-bought by the next -- depends on every caller
        # remembering. A caller that knows the real window calls cooldown() with it;
        # headroom() takes the LONGEST park, so an extra call can lengthen the park
        # but never shorten one -- erring toward not spending a spent key.
        cooldown(provider, key, DEFAULT_PARK_SECONDS, reason=detail or "auto: 429")
    return row


def cooldown(provider: str, key: str, seconds: int, reason: str = "") -> dict:
    """Park a key until ts+seconds. This is the cross-process memory _llm.py lacks.

    A 429 means the ceiling is already hit; every later process that re-picks that
    key inside the window buys another 429. Writing the park into the ledger makes
    one process's discovery available to the next one.
    """
    row = {
        "ts": round(time.time(), 3),
        "seat": seat(),
        "provider": provider,
        "key": key,
        "outcome": "cooldown",
        "until": round(time.time() + max(0, int(seconds)), 3),
        "units": 0,
    }
    if reason:
        row["detail"] = reason[:200]
    _append(row)
    return row


def headroom(provider: str, key: str, rows: list[dict] | None = None) -> dict:
    """How much of this key's budget is left right now."""
    now = time.time()
    rows = rows if rows is not None else _rows(since=now - KEEP_SECONDS)
    mine = [r for r in rows if r.get("provider") == provider and r.get("key") == key]

    parked_until = 0.0
    for r in mine:
        if r.get("outcome") == "cooldown":
            parked_until = max(parked_until, float(r.get("until") or 0))

    # Spent counts every call the provider would have metered, including the
    # empty-shell 200s: they were billed even though the pipeline rejected them.
    def spent(window: float) -> int:
        return sum(
            int(r.get("units") or 1)
            for r in mine
            if r.get("outcome") in ("ok", "empty", "ratelimited", "error")
            and float(r.get("ts") or 0) >= now - window
        )

    b = budget_for(provider)
    used_m, used_d = spent(60), spent(86400)
    last = max([float(r.get("ts") or 0) for r in mine], default=0.0)
    left_m = None if b["rpm"] is None else max(0, int(b["rpm"]) - used_m)
    left_d = None if b["rpd"] is None else max(0, int(b["rpd"]) - used_d)
    return {
        "provider": provider,
        "key": key,
        "rpm_used": used_m,
        "rpd_used": used_d,
        "rpm_left": left_m,
        "rpd_left": left_d,
        "scope": b["scope"],
        "parked": parked_until > now,
        "parked_for": max(0, int(parked_until - now)),
        "last_used": last,
        "usable": parked_until <= now and (left_m is None or left_m > 0) and (left_d is None or left_d > 0),
    }


def pick(provider: str, keys: list[str]) -> dict:
    """Choose which key to call NEXT. This is the scheduling half.

    Order: usable first, then most daily headroom, then least-recently-used.
    LRU matters because an unmeasured provider (rpd=None) gives no headroom
    signal at all -- without it the first key in the list would take every call
    and be the only one that ever hits a ceiling.
    """
    now = time.time()
    rows = _rows(since=now - KEEP_SECONDS)
    plan = [headroom(provider, k, rows) for k in keys]
    ranked = sorted(
        plan,
        key=lambda h: (
            not h["usable"],
            -(h["rpd_left"] if h["rpd_left"] is not None else 10**6),
            h["last_used"],
        ),
    )
    chosen = next((h for h in ranked if h["usable"]), None)
    return {
        "provider": provider,
        "chosen": chosen["key"] if chosen else None,
        "reason": (
            "no-keys" if not keys
            else "all-parked-or-spent" if not chosen
            else f"headroom rpd_left={chosen['rpd_left']} rpm_left={chosen['rpm_left']}"
        ),
        # degraded when the pool is thinner than it looks: the pick is fine but
        # the caller should know it is running on the last usable key.
        "degraded": bool(chosen and sum(1 for h in plan if h["usable"]) < max(1, len(keys)) // 2 + 1),
        "usable_keys": sum(1 for h in plan if h["usable"]),
        "total_keys": len(keys),
        "plan": ranked,
    }


def summary(provider: str | None = None) -> dict:
    now = time.time()
    rows = _rows(since=now - KEEP_SECONDS)
    agg: dict[tuple[str, str], dict] = {}
    for r in rows:
        p, k = r.get("provider") or "?", r.get("key") or "?"
        if provider and p != provider:
            continue
        a = agg.setdefault((p, k), {"provider": p, "key": k, "day": 0, "min": 0,
                                    "ok": 0, "empty": 0, "ratelimited": 0, "error": 0})
        oc = r.get("outcome") or "ok"
        if oc in a:
            a[oc] += 1
        if oc != "cooldown":
            a["day"] += int(r.get("units") or 1)
            if float(r.get("ts") or 0) >= now - 60:
                a["min"] += int(r.get("units") or 1)
    out = []
    for (p, k), a in sorted(agg.items()):
        a.update(headroom(p, k, rows))
        out.append(a)
    by_cap: dict[str, int] = {}
    for r in rows:
        if r.get("capability"):
            by_cap[r["capability"]] = by_cap.get(r["capability"], 0) + int(r.get("units") or 1)
    return {"seat": seat(), "ledger": str(_ledger_path()), "rows": len(rows),
            "keys": out, "by_capability": by_cap}


def main() -> int:
    ap = argparse.ArgumentParser(description="usage ledger + quota scheduler")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("show"); s.add_argument("--provider"); s.add_argument("--json", action="store_true")
    pk = sub.add_parser("pick"); pk.add_argument("--provider", required=True)
    pk.add_argument("--keys", required=True, help="comma-separated FINGERPRINTS (never values)")
    pk.add_argument("--json", action="store_true")
    rc = sub.add_parser("record"); rc.add_argument("--provider", required=True)
    rc.add_argument("--key", required=True); rc.add_argument("--capability", default="")
    rc.add_argument("--outcome", default="ok", choices=["ok", "empty", "ratelimited", "error"])
    rc.add_argument("--model"); rc.add_argument("--units", type=int, default=1); rc.add_argument("--detail", default="")
    cd = sub.add_parser("cooldown"); cd.add_argument("--provider", required=True)
    cd.add_argument("--key", required=True); cd.add_argument("--seconds", type=int, required=True)
    cd.add_argument("--reason", default="")
    ln = sub.add_parser("learn"); ln.add_argument("--write", action="store_true")
    ln.add_argument("--json", action="store_true")
    sub.add_parser("gc")
    a = ap.parse_args()

    if a.cmd == "show":
        out = summary(a.provider)
        if a.json:
            print(json.dumps(out, ensure_ascii=False, indent=2)); return 0
        print(f"seat={out['seat']}  rows={out['rows']}  {out['ledger']}")
        if not out["keys"]:
            print("  (empty ledger -- no call has been scheduled through api_budget yet)")
        for k in out["keys"]:
            state = "PARKED" if k["parked"] else ("usable" if k["usable"] else "spent")
            print(f"  {state:7} {k['provider']:12} {k['key']}  day={k['day']:<5} min={k['min']:<3} "
                  f"left(d/m)={k['rpd_left']}/{k['rpm_left']} scope={k['scope']} "
                  f"ok={k['ok']} empty={k['empty']} 429={k['ratelimited']} err={k['error']}")
        for c, n in sorted(out["by_capability"].items(), key=lambda kv: -kv[1]):
            print(f"    {n:5}  {c}")
        return 0

    if a.cmd == "pick":
        out = pick(a.provider, [k for k in a.keys.split(",") if k])
        if a.json:
            print(json.dumps(out, ensure_ascii=False, indent=2)); return 0
        print(f"{a.provider}: chosen={out['chosen']} ({out['reason']}) "
              f"usable={out['usable_keys']}/{out['total_keys']}"
              f"{'  DEGRADED' if out['degraded'] else ''}")
        return 0 if out["chosen"] else 1

    if a.cmd == "record":
        r = record(a.provider, a.key, a.capability, a.outcome, a.model, a.units, a.detail)
        print(json.dumps(r, ensure_ascii=False)); return 0

    if a.cmd == "cooldown":
        r = cooldown(a.provider, a.key, a.seconds, a.reason)
        print(json.dumps(r, ensure_ascii=False)); return 0

    if a.cmd == "learn":
        out = learn(a.write)
        if a.json:
            print(json.dumps(out, ensure_ascii=False, indent=2)); return 0
        if not out["providers"]:
            print("learn: no 429 in the ledger -- no ceiling has been OBSERVED yet "
                  "(that is not the same as 'no limit'; it means nothing was measured)")
            return 0
        for p, v in out["providers"].items():
            print(f"  {p:12} observed rpm<={v['rpm']} rpd<={v['rpd']} from {v['incidents']} incident(s)")
        print(f"written={out['written']}")
        return 0

    if a.cmd == "gc":
        p = _ledger_path()
        before = p.stat().st_size if p.exists() else 0
        keep = _rows(since=time.time() - KEEP_SECONDS)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep), encoding="utf-8")
        print(f"gc: {before} -> {p.stat().st_size} bytes, {len(keep)} rows kept")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
