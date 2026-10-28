#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""pinned_drift.py — which FAMES-release-pinned files differ from the shipped runtime, and who edited them.

F1S 當下閉環 item 1 (operator 2026-10-18).  An edit to a file the FAMES runtime release pins turns the release
UNKNOWN_LOCAL_CHANGES and fames-converge + fleet-skill-pulse red until someone ships it: on 2026-10-16 that was
_skill/engines/hubclock.py, on 2026-10-18 _lean/fames/f1s_audit.py sat unshipped for 8 h (converge red 11x,
contract-sync red, 5 handoffs).  The same session that edited the file is the one that can ship it, so the
check runs where that session ends its turn (claude-run-until-done-hook.py) and where HubClock reports the red
rider (hubclock._handoff), instead of counting reds afterwards.

  python pinned_drift.py                 # JSON list of drifted pinned files
  python pinned_drift.py --transcript T  # only the ones transcript T edited

Read-only, no network, fails open (an unreadable manifest = no drift reported).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace")
MANIFEST = HUB / "_skill" / "fleet-skills" / "fames" / "runtime" / "manifest.json"
SHIPPED_REL = Path("_skill") / "fleet-skills" / "fames" / "runtime" / "files"  # the shipped copy of each pinned file
MIN_LINE = 8  # shorter lines (")", "return", "else:") match any edit and decide nothing
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
TAIL_BYTES = 16 * 1024 * 1024
WRITE_MARKERS = ("cp ", "mv ", "copy ", "copy-item", "move-item", "sed -i", "> ", ">>", "tee ", "set-content",
                 "out-file", "add-content", "write_text", "write_bytes", ',"w"', ", 'w'", '"w")', "'w')", "replace(")


def pinned(manifest: Path = MANIFEST) -> dict:
    """{relative posix path: wanted sha256} for every runtime-pinned file."""
    try:
        files = json.loads(manifest.read_text(encoding="utf-8-sig")).get("files") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return {str(k): str((v or {}).get("sha256") or "") for k, v in files.items() if isinstance(v, dict)}


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def drifted(hub: Path = HUB, manifest: Path = MANIFEST) -> list[dict]:
    out = []
    for rel, wanted in sorted(pinned(manifest).items()):
        target = hub / rel
        current = _sha(target)
        if current is not None and wanted and current != wanted:
            try:
                mtime = target.stat().st_mtime
            except OSError:
                mtime = None
            out.append({"path": rel, "current_sha256": current, "wanted_sha256": wanted, "mtime": mtime})
    return out


def _norm(text: str) -> str:
    return str(text).replace("\\", "/").lower()


def _tool_uses(transcript: Path):
    for name, args, _at in _tool_uses_at(transcript):
        yield name, args


def _epoch(stamp) -> float | None:
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _shipped_at(rel: str, hub: Path | None = None) -> float | None:
    """When the shipped runtime copy of `rel` was last written (its release), or None without one."""
    try:
        return ((hub or HUB) / SHIPPED_REL / rel).stat().st_mtime
    except OSError:
        return None


def _tool_uses_at(transcript: Path):
    """(tool name, input, epoch of the row or None) for every tool call in the transcript's tail."""
    try:
        with transcript.open("rb") as fh:
            end = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, end - TAIL_BYTES))
            data = fh.read()
    except OSError:
        return
    for raw in data.split(b"\n"):
        try:
            row = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError):
            continue
        msg = row.get("message") if isinstance(row, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        at = _epoch(row.get("timestamp")) if isinstance(row, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield str(block.get("name") or ""), block.get("input") or {}, at


def _drift_lines(rel: str, hub: Path | None = None) -> tuple[set[str], set[str]] | None:
    """(lines the working copy added, lines it removed) against the shipped runtime copy; None without one."""
    hub = hub or HUB
    try:
        shipped = (hub / SHIPPED_REL / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        current = (hub / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    old = {line.strip() for line in shipped if len(line.strip()) >= MIN_LINE}
    new = {line.strip() for line in current if len(line.strip()) >= MIN_LINE}
    return new - old, old - new


def _wrote_the_drift(rel: str, texts: dict) -> bool:
    """Is the unshipped difference text this transcript's edits carried? 2026-10-24: a session that had edited
    f1s_audit.py and shipped it was blocked twice for another session's later, still-open edit of the same file.
    Unknown stays blamed: no shipped copy, no recorded edit text, or a difference with no line to match."""
    drift = _drift_lines(rel)
    if drift is None or not (texts["new"] or texts["old"]):
        return True
    added, removed = drift
    if not added and not removed:
        return True
    new_blob, old_blob = "\n".join(texts["new"]), "\n".join(texts["old"])
    return any(line in new_blob for line in added) or any(line in old_blob for line in removed)


def edited_by(transcript: Path, paths) -> list[str]:
    """The subset of `paths` (hub-relative) that this transcript wrote: an edit tool on the file whose text is in
    the unshipped difference, or a shell command naming it (cp/sed/redirect — the 2026-10-16 hubclock drift was a
    `cp` into the package; a shell write carries no text to compare, so it is always blamed)."""
    wanted = {p: _norm(p) for p in paths}
    hit = set()
    edited: dict[str, dict] = {}
    shipped_at = {p: _shipped_at(p) for p in wanted}
    shell_writes: dict[tuple[str, str], list] = {}
    for name, args, at in _tool_uses_at(transcript):
        if name in EDIT_TOOLS:
            target = _norm(args.get("file_path") or args.get("notebook_path") or "")
            for p, n in wanted.items():
                if target.endswith("/" + n) or target == n:
                    texts = edited.setdefault(p, {"new": [], "old": []})
                    edits = [args] + [e for e in args.get("edits") or [] if isinstance(e, dict)]
                    texts["new"] += [str(e.get(k) or "") for e in edits for k in ("new_string", "content", "new_source")
                                     if e.get(k)]
                    texts["old"] += [str(e.get("old_string")) for e in edits if e.get("old_string")]
        elif name in SHELL_TOOLS:
            command = _norm(args.get("command") or "")
            # Per command segment: a read (cat/grep/sha256sum) is not an edit, and neither is running the file with
            # its output redirected elsewhere (`python f1s_audit.py > out.txt` blamed a session twice, 2026-10-23).
            for seg in re.split(r"&&|\|\||[;|\n]", command):
                marks = [m for m in WRITE_MARKERS if m in seg]
                if not marks:
                    continue
                redirect_only = all(m in ("> ", ">>") for m in marks)
                for p, n in wanted.items():
                    if n in seg and not (redirect_only and seg.find(n) < seg.rfind(">")):
                        shell_writes.setdefault((p, seg.strip()), []).append(at)
    # A shell write carries no text to compare, but one made before the file's last release was shipped with it
    # (2026-10-24: a long-shipped `sed -i` blamed this session for f1s-evolve's open edit). The same command can recur
    # without a timestamp (a summary row repeats it); it counts at the latest time any copy of it is known.
    for (p, _seg), stamps in shell_writes.items():
        known = [s for s in stamps if s is not None]
        latest = max(known) if known else None
        if latest is None or shipped_at.get(p) is None or latest >= shipped_at[p]:
            hit.add(p)
    hit.update(p for p, texts in edited.items() if _wrote_the_drift(p, texts))
    return sorted(hit)


def ship_command(paths) -> str:
    return ('python C:\\ai_workspace\\_skill\\engines\\ship-f1s.py --why "<why>" --verified-by "<tests run>" --files '
            + " ".join(paths))


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    rows = drifted()
    if "--transcript" in args:
        mine = set(edited_by(Path(args[args.index("--transcript") + 1]), [r["path"] for r in rows]))
        rows = [r for r in rows if r["path"] in mine]
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
