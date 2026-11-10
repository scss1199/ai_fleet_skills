r"""fleet-bridge.py — the two things a follower host could not get to the curator (operator 2026-11-10
「解決那邊同步的問題以及收集那邊 cwd 的資料來反向修正 f1s」):

  1. BUS    _bus/inbox/<seat>/ on a follower is a local store. A message for a seat that does not live on
            this host (ai_darkhero from scar3, ai_trader from altos ...) sat there forever: 27 ai_scar3 ->
            ai_darkhero messages were only read by hand on 2026-11-10. `export` moves them onto the carrier
            (contributors/<slug>/bus/<seat>/<id>.json, the same fleet-skill-github clone every host already
            pushes); the curator's `import` drops them into its own _bus/inbox/<seat>/ and deletes them from
            the carrier. The relayed local file goes to _delete/<date>-bus-relayed/ (residue rule), never
            unlinked.
  2. LEARN  f1s-harvest.py reads memory dirs, skills and f1s_daily conversation lessons from ~/.claude on the
            host it runs on, so a follower's cwds never reached reverse learning. `export` writes one
            contributors/<slug>/f1s-learn.json (memory files of the seats hosted here, their non-canonical
            SKILL.md inventory, f1s_daily `conversation` lessons); f1s-harvest.harvest_hosts() turns it into
            candidates with seat "<seat>@<host>" on the curator. Published only when its content sha changed.

Runs from the fames-converge rider on every host (fames_fleet._launch_bridge, detached, like hygiene):
`run` = export then import on every host (the authority relays mail for seats it does not host too, but sends
no f1s-learn.json: its own knowledge is the corpus). Self-throttled: one pass per hour
(_registry/fleet-bridge/state.json). Zero model calls. Never touches fracdigi / quant. Python 3.10+.

  python fleet-bridge.py run [--force]            # what the rider runs
  python fleet-bridge.py export [--force] [--no-publish]
  python fleet-bridge.py import [--force]
  python fleet-bridge.py status
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import sys
import time
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace").resolve()
ENGINES = Path(__file__).resolve().parent
PROJECTS = Path.home() / ".claude" / "projects"
STATE_DIR = HUB / "_registry" / "fleet-bridge"
CURATOR = "ai_darkhero"
NEVER = {"fracdigi", "quant"}
THROTTLE_S = 3600
RELAY_TTL_S = 7 * 86400    # a relayed message no host absorbed in a week is dropped by the authority
LEARN_FILE = "f1s-learn.json"
MEMORY_CAP = 6000          # chars of one memory file carried
SKILL_CAP = 2500


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def _save(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def _module(file: str):
    path = ENGINES / file
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(file.replace("-", "_").replace(".py", "_for_bridge"), path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 - a broken sibling engine is reported, never fatal
        return None
    return mod


def this_host() -> str:
    return socket.gethostname().strip().lower()


def slug(hub: Path = HUB) -> str:
    hyg = _module("fleet-hygiene.py")
    if hyg and hasattr(hyg, "contributor_slug"):
        try:
            return str(hyg.contributor_slug(hub, this_host()))
        except Exception:  # noqa: BLE001
            pass
    return this_host()


def local_seats(hub: Path = HUB) -> list[str]:
    """Seats that live on this host: a hub folder with a charter. A synced copy (scar3's ai_darkhero tray
    mirror) has no AGENTS.md and is not a seat here, so its mail is relayed."""
    out = []
    for p in sorted(hub.iterdir()):
        if not p.is_dir() or p.name in NEVER:
            continue
        if (p.name.startswith("ai_") or p.name.startswith("jci_") or p.name == "sdnext_a770") \
                and ((p / "AGENTS.md").is_file() or (p / "CLAUDE.md").is_file()):
            out.append(p.name)
    return out


def is_authority(hub: Path = HUB) -> bool:
    return CURATOR in local_seats(hub)


def _carrier(hub: Path):
    fjd = _module("fleet-job-dispatch.py")
    if fjd is None:
        return None, None
    return fjd, fjd.repo_root(hub)


def _throttled(state: dict, key: str, now: float, force: bool) -> bool:
    return not force and now - float(state.get(key) or 0) < THROTTLE_S


# ── export (every follower) ────────────────────────────────────────────────────────────────────────
def _front(t: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    fm = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
    return fm


def _memory_dir(seat: str) -> Path:
    return PROJECTS / ("C--ai-workspace-" + seat.replace("_", "-")) / "memory"


def learn_doc(hub: Path = HUB, projects: Path | None = None) -> dict:
    """What this host knows that the curator's harvest cannot see: seat memories, local skills, lessons."""
    projects = projects or PROJECTS
    seats = [s for s in local_seats(hub) if s != CURATOR]
    memories, skills = [], []
    canon = {d.name for d in (hub / "_skill" / "fleet-skills").iterdir()} if (hub / "_skill" / "fleet-skills").is_dir() else set()
    roots = [(s, projects / ("C--ai-workspace-" + s.replace("_", "-")) / "memory") for s in seats]
    roots.append(("hub-root", projects / "C--ai-workspace" / "memory"))
    for seat, d in roots:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            t = f.read_text(encoding="utf-8", errors="ignore")
            fm = _front(t)
            memories.append({"seat": seat, "name": fm.get("name") or f.stem, "type": fm.get("type") or "",
                             "summary": (fm.get("description") or "")[:300], "text": t[:MEMORY_CAP], "path": str(f)})
    for seat in seats:
        for f in sorted((hub / seat).glob(".claude/skills/*/SKILL.md")):
            name = f.parent.name
            if name in canon or f.parent.is_symlink():
                continue                               # fleet canon copies are the curator's own text
            t = f.read_text(encoding="utf-8", errors="ignore")
            skills.append({"seat": seat, "name": name, "summary": (_front(t).get("description") or "")[:300],
                           "text": t[:SKILL_CAP], "path": str(f)})
    lessons = [it for it in (_load(hub / "_registry" / "f1s-daily" / "lessons.json", {}).get("items") or [])
               if isinstance(it, dict) and it.get("kind") == "conversation"]
    body = {"memories": memories, "skills": skills, "conversations": lessons[:200]}
    sha = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return {"schema": 1, "host": this_host(), "seats": seats, "sha": sha, **body}


LESSONS_MAX_AGE_S = 24 * 3600


def refresh_lessons(hub: Path = HUB, now: float | None = None, runner=None) -> str:
    """Follower transcripts never met f1s_daily (no rider runs it there): tick it before exporting when
    _registry/f1s-daily/lessons.json is missing or a day old, so conversation lessons ride along."""
    now = now or time.time()
    lessons = hub / "_registry" / "f1s-daily" / "lessons.json"
    engine = ENGINES / "f1s_daily.py"
    if not engine.is_file():
        return "no-engine"
    try:
        if lessons.is_file() and now - lessons.stat().st_mtime < LESSONS_MAX_AGE_S:
            return "fresh"
    except OSError:
        pass
    runner = runner or (lambda cmd: __import__("subprocess").run(cmd, capture_output=True, text=True, timeout=1500,
                                                                   creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)))
    try:
        r = runner([sys.executable, str(engine), "tick"])
        return "ticked" if getattr(r, "returncode", 1) == 0 else f"tick-rc{getattr(r, 'returncode', '?')}"
    except Exception as exc:  # noqa: BLE001 - a slow or broken daily never blocks the relay
        return f"tick-failed:{type(exc).__name__}"


def relay_candidates(hub: Path = HUB) -> list[tuple[str, Path]]:
    """(seat, file) for every inbox message addressed to a seat not hosted here."""
    inbox = hub / "_bus" / "inbox"
    mine = set(local_seats(hub))
    out = []
    if not inbox.is_dir():
        return out
    for d in sorted(inbox.iterdir()):
        if not d.is_dir() or d.name in mine or d.name in NEVER:
            continue
        if not (d.name.startswith("ai_") or d.name.startswith("jci_")):
            continue                                   # hub pseudo-recipients (ai_workspace, hubclock) stay local
        for f in sorted(d.glob("*.json")):
            out.append((d.name, f))
    return out


def export(hub: Path = HUB, force: bool = False, publish: bool = True, now: float | None = None) -> dict:
    now = now or time.time()
    state = _load(STATE_DIR / "state.json", {})
    if _throttled(state, "export_at", now, force):
        return {"skipped": "throttled", "next_in_s": int(THROTTLE_S - (now - state["export_at"]))}
    me = slug(hub)
    authority = is_authority(hub)
    lessons = refresh_lessons(hub, now) if not authority else "authority"
    doc = learn_doc(hub) if not authority else {"memories": [], "skills": [], "conversations": [], "sha": "authority"}
    files: dict = {}
    if not authority and doc["sha"] != state.get("learn_sha"):   # the curator's own knowledge IS the corpus
        files[f"contributors/{me}/{LEARN_FILE}"] = doc
    relayed = relay_candidates(hub)
    for seat, f in relayed:
        msg = _load(f, None)
        if isinstance(msg, dict):
            msg.setdefault("relayed_from", this_host())
            files[f"contributors/{me}/bus/{seat}/{f.name}"] = msg
    out = {"at": now, "host": this_host(), "slug": me, "learn_changed": LEARN_FILE in "".join(files),
           "memories": len(doc["memories"]), "skills": len(doc["skills"]), "conversations": len(doc["conversations"]),
           "bus": len(relayed), "lessons": lessons, "published": None}
    if not authority:
        _save(STATE_DIR / "learn.json", doc)
    if files and publish:
        fjd, repo = _carrier(hub)
        if fjd is None or not repo or not repo.is_dir():
            out["published"] = {"ok": False, "error": "no carrier clone"}
        else:
            out["published"] = fjd._publish(repo, hub, files, f"chore(bridge/{me}): learn + {len(relayed)} relayed messages")
        if out["published"].get("ok"):
            state["learn_sha"] = doc["sha"]
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            for seat, f in relayed:                    # residue rule: moved, never unlinked
                dest = hub / "_delete" / f"{day}-bus-relayed" / seat
                dest.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest / f.name))
            out["moved"] = len(relayed)
    elif files:
        out["published"] = {"ok": None, "skipped": "no-publish"}
    state["export_at"] = now
    state["last_export"] = {k: v for k, v in out.items() if k != "at"}
    _save(STATE_DIR / "state.json", state)
    return out


# ── import (authority) ─────────────────────────────────────────────────────────────────────────────
def import_(hub: Path = HUB, force: bool = False, now: float | None = None) -> dict:
    now = now or time.time()
    state = _load(STATE_DIR / "state.json", {})
    if _throttled(state, "import_at", now, force):
        return {"skipped": "throttled"}
    fjd, repo = _carrier(hub)
    if fjd is None or not repo or not repo.is_dir():
        return {"error": "no carrier clone"}
    errs = fjd._fetch(repo, "main")
    if errs:
        return {"error": errs[0]}
    me = slug(hub)
    mine = set(local_seats(hub))
    imported, deletions, hosts = [], {}, []
    listing = fjd.git(repo, "ls-tree", "-r", "--name-only", "origin/main", "contributors/")
    for rel in listing.stdout.splitlines():
        parts = rel.split("/")
        if len(parts) == 5 and parts[2] == "bus" and parts[4].endswith(".json") and parts[3] not in mine and is_authority(hub):
            stamp = parts[4].split("-", 1)[0]          # inbox ids start with the send epoch
            if stamp.isdigit() and now - int(stamp) > RELAY_TTL_S:
                deletions[rel] = None                  # addressed to a seat no host claimed within the TTL
                continue
        if len(parts) == 5 and parts[2] == "bus" and parts[1] != me and parts[3] in mine and parts[4].endswith(".json"):
            seat, name = parts[3], parts[4]
            show = fjd.git(repo, "show", f"origin/main:{rel}")
            if show.returncode:
                continue
            try:
                msg = json.loads(show.stdout)
            except ValueError:
                deletions[rel] = None                  # unreadable relay: drop it, never block the lane
                continue
            dest = hub / "_bus" / "inbox" / seat / name
            if not dest.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                _save(dest, msg)
                imported.append(rel)
            deletions[rel] = None
        elif len(parts) == 3 and parts[2] == LEARN_FILE and parts[1] != me:
            hosts.append(parts[1])
    out = {"at": now, "imported": len(imported), "deleted": 0, "learn_hosts": sorted(hosts)}
    if deletions:
        pub = fjd._publish(repo, hub, deletions, f"chore(bridge/{me}): absorbed {len(deletions)} relayed messages")
        out["deleted"] = len(deletions) if pub.get("ok") else 0
        out["published"] = pub
    state["import_at"] = now
    state["last_import"] = {k: v for k, v in out.items() if k != "at"}
    _save(STATE_DIR / "state.json", state)
    return out


def learn_from_hosts(hub: Path = HUB) -> list[dict]:
    """Every other host's f1s-learn.json from the carrier clone (git objects on origin/main, worktree untouched)."""
    fjd, repo = _carrier(hub)
    if fjd is None or not repo or not repo.is_dir():
        return []
    me = slug(hub)
    docs = []
    listing = fjd.git(repo, "ls-tree", "-r", "--name-only", "origin/main", "contributors/")
    for rel in listing.stdout.splitlines():
        parts = rel.split("/")
        if len(parts) == 3 and parts[2] == LEARN_FILE and parts[1] != me:
            show = fjd.git(repo, "show", f"origin/main:{rel}")
            if show.returncode:
                continue
            try:
                d = json.loads(show.stdout)
            except ValueError:
                continue
            if isinstance(d, dict):
                d["_carrier_path"] = rel
                docs.append(d)
    return docs


def run(hub: Path = HUB, force: bool = False) -> dict:
    """What the fames-converge rider launches on every host: relay out, then absorb what is addressed here."""
    return {"export": export(hub, force), "import": import_(hub, force)}


def status(hub: Path = HUB) -> dict:
    st = _load(STATE_DIR / "state.json", {})
    return {"host": this_host(), "slug": slug(hub), "authority": is_authority(hub), "local_seats": local_seats(hub),
            "relay_pending": len(relay_candidates(hub)), "state": st}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--force", action="store_true")
    e.add_argument("--no-publish", action="store_true")
    i = sub.add_parser("import")
    i.add_argument("--force", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--force", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "run":
            doc = run(HUB, a.force)
        elif a.cmd == "export":
            doc = export(HUB, a.force, not a.no_publish)
        elif a.cmd == "import":
            doc = import_(HUB, a.force)
        else:
            doc = status(HUB)
    except Exception as exc:  # noqa: BLE001 - the rider lane must not stay red on one host's surprise
        doc = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(doc, ensure_ascii=False, default=str))
    return 1 if "error" in doc else 0


if __name__ == "__main__":
    sys.exit(main())
