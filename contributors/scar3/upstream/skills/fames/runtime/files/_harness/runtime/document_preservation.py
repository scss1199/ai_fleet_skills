"""Shared pre-mutation checks for registered document writers.

Callers bind canonical roots, staging paths and template hashes from their
registered domain configuration. These helpers are not a filesystem sandbox;
they cannot intercept arbitrary writes that bypass supported writer entrypoints.
Document layout/content validation stays in the domain-specific verifier.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import threading

_HELD_LOCKS = threading.local()


class GuardError(RuntimeError):
    pass


def require_workspace(actual_root, canonical_root):
    actual, canonical = Path(actual_root).resolve(), Path(canonical_root).resolve()
    if not canonical.is_dir() or actual != canonical:
        raise GuardError("Run the registered canonical workspace; worktree writers are not authorized")
    return canonical


def canonical_date_directory(parent, date, requested=None):
    if not isinstance(date, str) or not re.fullmatch(r"20\d{6}", date):
        raise GuardError("Meeting date must be a real YYYYMMDD, without suffixes")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError as error:
        raise GuardError("Invalid calendar date") from error
    parent = Path(parent).resolve()
    expected = parent / date
    if not expected.resolve().is_relative_to(parent):
        raise GuardError("Canonical path escaped registered parent")
    if requested is not None and Path(requested).resolve() != expected.resolve():
        raise GuardError("Noncanonical or duplicate work directory")
    return expected


def require_staging_target(target, approved_target):
    target, approved = Path(target).resolve(), Path(approved_target).resolve()
    if target != approved:
        raise GuardError("Direct final write forbidden; use the registered staging target and publisher")
    return approved


def require_hash(path, expected_sha256, label="artifact"):
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise GuardError("Invalid pinned hash")
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise GuardError("Pinned artifact unavailable") from error
    if digest.hexdigest() != expected_sha256:
        raise GuardError(str(label) + " changed from pinned identity")
    return digest.hexdigest()


@contextmanager
def writer_lock(state: Path, *, join_existing=False):
    # Registration/bootstrap owns this one directory. A writer must not create
    # an alternate state directory when the registered one is missing or busy.
    state = Path(state).resolve()
    if not state.is_dir():
        raise GuardError("Unregistered state directory")
    held = getattr(_HELD_LOCKS, "states", None)
    if held is None:
        held = _HELD_LOCKS.states = set()
    owner_key = (os.getpid(), state)
    if join_existing and owner_key in held:
        # Only nested work in the owning thread can join an existing OS lock.
        # Another process/thread still has to acquire that same lock normally.
        yield
        return
    handle = (state / "writer.lock").open("a+b")
    locked = False
    try:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise GuardError("Another document writer is active") from error
        locked = True
        held.add(owner_key)
        yield
    finally:
        try:
            if locked:
                held.discard(owner_key)
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    workspace = sub.add_parser("workspace")
    workspace.add_argument("--actual", required=True)
    workspace.add_argument("--canonical", required=True)
    work = sub.add_parser("work-directory")
    work.add_argument("--parent", required=True)
    work.add_argument("--date", required=True)
    work.add_argument("--requested", required=True)
    staging = sub.add_parser("staging")
    staging.add_argument("--target", required=True)
    staging.add_argument("--approved", required=True)
    artifact = sub.add_parser("hash")
    artifact.add_argument("--path", required=True)
    artifact.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "workspace":
            require_workspace(args.actual, args.canonical)
        elif args.operation == "work-directory":
            canonical_date_directory(args.parent, args.date, args.requested)
        elif args.operation == "staging":
            require_staging_target(args.target, args.approved)
        elif args.operation == "hash":
            require_hash(args.path, args.sha256)
    except (GuardError, OSError, ValueError) as error:
        print(json.dumps({"state": "BLOCKED", "reason": str(error) if isinstance(error, GuardError) else type(error).__name__}))
        return 2
    print(json.dumps({"state": "CHECK_PASSED_NOT_PUBLICATION"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
