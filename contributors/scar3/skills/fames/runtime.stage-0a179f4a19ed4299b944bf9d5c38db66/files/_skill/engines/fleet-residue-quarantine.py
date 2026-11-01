"""Move a session's own leftovers into _delete/<date>-<topic>/ -- never delete them.

Written 2026-09-22 after the operator's correction: the standing rule says the
*permanent* deletion is the operator's to perform by hand, and a session that
reads it as "therefore I may leave my garbage where it fell and ask the operator
to move it" has inverted it. Quarantining is a reversible move and is the
session's own job; only the final removal of _delete/ is the operator's.

So this engine does exactly one thing and refuses to do more: it relocates named
paths under _delete/<YYYY-MM-DD>-<topic>/, preserving their path inside the
workspace, and records where each thing came from so the move can be undone
without guessing. It has no delete path at all -- not a flag, not a branch.

Refusals are deliberate rather than advisory: a path outside the workspace, a
path already quarantined, and the protected trees (.git, _secrets, and the
fracdigi/quant credential areas the red lines say not to touch) all abort the
whole call before anything moves, so a bad argument cannot half-run.

    python fleet-residue-quarantine.py move --topic fames-turn-work \
        --path _registry/fames-evidence/turn/_work [--dry-run] [--note "why"]
    python fleet-residue-quarantine.py selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(os.environ.get("AI_WORKSPACE", r"C:\ai_workspace")).resolve()
QUARANTINE_ROOT = WORKSPACE / "_delete"

# Trees this engine will not move under any argument. The credential areas are
# here because the red line is "do not even touch them" -- a move is a touch.
PROTECTED = (
    ".git",
    "_secrets",
    "_delete",
    "fracdigi/env",
    "ai_quant/.env",
)


def _delete_calls(source: str) -> list[str]:
    """Names of removal primitives *called* in a Python source string.

    Reads the AST rather than the text: a text scan matches the list of
    forbidden names it is itself written with, so it can never certify its own
    file. Only Call nodes count, which is what lets the selftest hold a fixture
    containing a deletion as a string without incriminating this module.
    """
    import ast

    removers = {"rmtree", "remove", "unlink", "rmdir", "removedirs", "send2trash"}
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in removers:
            found.add(name)
    return sorted(found)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_stats(path: Path) -> tuple[int, int]:
    """(file count, total bytes) for a file or a directory."""
    if path.is_file():
        return 1, path.stat().st_size
    files = 0
    total = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
            files += 1
    return files, total


def _check(raw: str, workspace: Path) -> tuple[Path, Path]:
    """Resolve one argument to (absolute source, path relative to workspace).

    Raises ValueError with the reason, because the caller aborts the whole call
    on the first refusal rather than moving some of the paths.
    """
    candidate = Path(raw)
    source = (candidate if candidate.is_absolute() else workspace / candidate).resolve()
    try:
        relative = source.relative_to(workspace)
    except ValueError:
        raise ValueError(f"outside the workspace: {source}") from None
    if not source.exists():
        raise ValueError(f"does not exist: {source}")
    posix = relative.as_posix()
    for guard in PROTECTED:
        if posix == guard or posix.startswith(guard + "/"):
            raise ValueError(f"protected path, refusing to move: {posix}")
    return source, relative


def _free_destination(base: Path) -> Path:
    """A destination that does not already exist, so no quarantined copy is overwritten."""
    if not base.exists():
        return base
    for suffix in range(1, 1000):
        candidate = base.with_name(f"{base.name}-{suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"cannot find a free destination for {base}")


def quarantine(paths: list[str], topic: str, note: str = "", dry_run: bool = False,
               workspace: Path | None = None, stamp: str | None = None) -> dict:
    root = (workspace or WORKSPACE).resolve()
    day = stamp or datetime.now().strftime("%Y-%m-%d")
    bucket = root / "_delete" / f"{day}-{topic}"

    planned: list[tuple[Path, Path, Path]] = []
    for raw in paths:
        source, relative = _check(raw, root)
        planned.append((source, relative, _free_destination(bucket / relative)))

    entries: list[dict] = []
    for source, relative, destination in planned:
        files, total = _tree_stats(source)
        entry = {
            "origin": relative.as_posix(),
            "quarantined_to": destination.relative_to(root).as_posix(),
            "kind": "file" if source.is_file() else "dir",
            "files": files,
            "bytes": total,
            "sha256": _sha256(source) if source.is_file() else None,
            "moved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "note": note,
        }
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            # Verify at the destination rather than trusting the move: a file
            # whose bytes did not survive is a silent data loss, and this engine
            # exists precisely so the operator does not have to check by hand.
            if entry["kind"] == "file":
                entry["verified_sha256"] = _sha256(destination)
                entry["verified"] = entry["verified_sha256"] == entry["sha256"]
            else:
                moved_files, moved_bytes = _tree_stats(destination)
                entry["verified"] = (moved_files, moved_bytes) == (files, total)
            entry["origin_gone"] = not source.exists()
        entries.append(entry)

    manifest_path = bucket / "MANIFEST.json"
    if not dry_run:
        existing = []
        if manifest_path.is_file():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8")).get("entries", [])
            except (OSError, json.JSONDecodeError):
                existing = []
        manifest_path.write_text(json.dumps({
            "topic": topic,
            "workspace": str(root),
            "rule": "quarantine only; permanent deletion is the operator's own action",
            "entries": existing + entries,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    ok = dry_run or all(e.get("verified") and e.get("origin_gone") for e in entries)
    return {"ok": ok, "dry_run": dry_run, "bucket": bucket.relative_to(root).as_posix(),
            "manifest": None if dry_run else manifest_path.relative_to(root).as_posix(),
            "moved": len(entries), "entries": entries}


def verify(bucket_name: str, workspace: Path | None = None) -> dict:
    """Re-check a quarantine bucket from its MANIFEST, long after the move.

    The move already verified itself, but a receipt that cites the move is only
    worth what it can be re-run against: this reads the manifest back, confirms
    each quarantined path still holds the recorded bytes and that the origin is
    still empty, so "it was moved, not lost" stays checkable by anyone.
    """
    root = (workspace or WORKSPACE).resolve()
    manifest_path = root / "_delete" / bucket_name / "MANIFEST.json"
    if not manifest_path.is_file():
        return {"ok": False, "reason": f"no manifest at {manifest_path}"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for entry in manifest.get("entries", []):
        target = root / entry["quarantined_to"]
        origin = root / entry["origin"]
        row = {"origin": entry["origin"], "present": target.exists(),
               "origin_gone": not origin.exists()}
        if entry.get("sha256") and target.is_file():
            row["sha256_matches"] = _sha256(target) == entry["sha256"]
        elif target.is_dir():
            files, total = _tree_stats(target)
            row["sha256_matches"] = (files, total) == (entry["files"], entry["bytes"])
        else:
            row["sha256_matches"] = False
        rows.append(row)
    ok = bool(rows) and all(r["present"] and r["origin_gone"] and r["sha256_matches"]
                            for r in rows)
    return {"ok": ok, "bucket": bucket_name, "entries": len(rows), "rows": rows}


def selftest() -> int:
    """Discriminating controls: a real move, and two refusals that must abort."""
    import ast
    import tempfile

    results: list[dict] = []

    # The load-bearing claim about this engine is that it cannot delete, so the
    # claim is checked against the source rather than asserted in prose: no
    # removal primitive may be *called* anywhere in it, including in this
    # selftest. That is why the "outside the workspace" fixture lives in its own
    # temp dir instead of being cleaned up with an unlink.
    #
    # The check reads the AST, not the text: a text scan matches the list of
    # forbidden names it is itself written with, which is how the first version
    # of this control failed against a source that was already clean.
    own = _delete_calls(Path(__file__).read_text(encoding="utf-8"))
    results.append({"control": "no_delete_primitive_in_source",
                    "pass": not own, "calls_found": own})

    # And a control on the control: a scanner that never fires proves nothing,
    # so feed it a fixture that does call one. The fixture is a string, and this
    # module's own AST therefore stays clean -- which is the point.
    fixture = "import shutil\ndef wipe(p):\n    shutil.rmtree(p)\n"
    results.append({"control": "scanner_detects_injected_delete",
                    "pass": _delete_calls(fixture) == ["rmtree"]})

    with tempfile.TemporaryDirectory() as raw_tmp, tempfile.TemporaryDirectory() as far_tmp:
        fake = Path(raw_tmp).resolve()
        (fake / "junk").mkdir(parents=True)
        payload = b"residue\n" * 32
        (fake / "junk" / "leftover.md").write_bytes(payload)
        (fake / "_secrets").mkdir()
        (fake / "_secrets" / "keys.json").write_text("{}", encoding="utf-8")
        outside = Path(far_tmp).resolve() / "not-in-workspace.txt"
        outside.write_text("x", encoding="utf-8")

        report = quarantine(["junk"], topic="selftest", workspace=fake, stamp="2026-01-01")
        moved = fake / "_delete" / "2026-01-01-selftest" / "junk" / "leftover.md"
        results.append({"control": "dir_moves_and_verifies",
                        "pass": bool(report["ok"]) and moved.is_file()
                        and moved.read_bytes() == payload
                        and not (fake / "junk").exists()})

        for control, arg in (("protected_path_refused", "_secrets"),
                             ("outside_workspace_refused", str(outside))):
            try:
                quarantine([arg], topic="selftest", workspace=fake, stamp="2026-01-01")
                results.append({"control": control, "pass": False})
            except ValueError:
                results.append({"control": control, "pass": True})

        # Nothing this engine does may remove bytes: the protected file that was
        # refused must still be exactly where it was.
        results.append({"control": "refused_path_untouched",
                        "pass": (fake / "_secrets" / "keys.json").is_file()
                        and outside.is_file()})

    ok = all(r["pass"] for r in results)
    print(json.dumps({"ok": ok, "controls": len(results), "results": results}, indent=1))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    move = sub.add_parser("move", help="relocate paths into _delete/<date>-<topic>/")
    move.add_argument("--topic", required=True, help="slug for the quarantine folder")
    move.add_argument("--path", action="append", required=True, dest="paths",
                      help="repeatable; relative to the workspace or absolute")
    move.add_argument("--note", default="", help="why this is residue")
    move.add_argument("--dry-run", action="store_true")

    check = sub.add_parser("verify", help="re-check a bucket against its MANIFEST")
    check.add_argument("--topic", required=True,
                       help="the bucket folder name, e.g. 2026-09-22-fames-turn-work")

    sub.add_parser("selftest", help="run the move/refusal controls")

    args = parser.parse_args()
    if args.command == "selftest":
        return selftest()
    if args.command == "verify":
        report = verify(args.topic)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if report["ok"] else 1

    try:
        report = quarantine(args.paths, topic=args.topic, note=args.note,
                            dry_run=args.dry_run)
    except ValueError as exc:
        print(json.dumps({"ok": False, "refused": str(exc)}, ensure_ascii=False, indent=1))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
