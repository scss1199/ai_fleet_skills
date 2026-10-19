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
import sys
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace")
MANIFEST = HUB / "_skill" / "fleet-skills" / "fames" / "runtime" / "manifest.json"
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
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield str(block.get("name") or ""), block.get("input") or {}


def edited_by(transcript: Path, paths) -> list[str]:
    """The subset of `paths` (hub-relative) that this transcript wrote: an edit tool on the file, or a shell
    command naming it (cp/sed/redirect — the 2026-10-16 hubclock drift was a `cp` into the package)."""
    wanted = {p: _norm(p) for p in paths}
    hit = set()
    for name, args in _tool_uses(transcript):
        if name in EDIT_TOOLS:
            target = _norm(args.get("file_path") or args.get("notebook_path") or "")
            hit.update(p for p, n in wanted.items() if target.endswith("/" + n) or target == n)
        elif name in SHELL_TOOLS:
            command = _norm(args.get("command") or "")
            if any(marker in command for marker in WRITE_MARKERS):   # a read (cat/grep/sha256sum) is not an edit
                hit.update(p for p, n in wanted.items() if n in command)
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
