#!/usr/bin/env python3
r"""_atomicio.py — write a file without a window in which it is neither old nor new.

Every engine here that rewrites a file in place had the same shape:

    open(path, "w").write(new_text)

That truncates first. If the process dies, the disk fills, or the write raises anywhere
after the truncate, the old content is gone and the new content is incomplete. For the
files this hub rewrites that is not a theoretical loss:

  - _secrets/api-matrix.json holds every free-API key. A partial write leaves invalid JSON,
    and key-pool-tick, key-health, the roster refresh and token verification all stop.
  - _secrets/token-inbox.txt is, by design, the ONLY copy of a token that failed to install.
    A failed rewrite of the file destroys the very thing the rewrite exists to preserve.

    from _atomicio import atomic_write
    atomic_write(path, text)          # raises OSError; the old file survives untouched

Write to a sibling temp file, flush it to the platter, then swap it in.

On Windows the swap is ReplaceFileW when a file is already there, and a create-only
os.rename when nothing is. os.replace is never used, and that is not incidental: it moves
the temp file *over* the target, so the surviving file carries the TEMP file's security
descriptor — inherited from the parent directory. A file deliberately locked down tighter
than its directory would silently widen on its next write, which for a credential store is
the one direction that must never happen quietly.

ReplaceFileW exists for exactly this: it keeps the replaced file's DACL, its attributes,
its object identifier and any named streams, and takes only the data from the replacement.
When it reports no such file, os.rename is the counterpart — on Windows it REFUSES to
overwrite, so it puts the temp file in place if and only if the path is still empty, and
raises FileExistsError if someone got there first. _swap_win alternates the two in a
bounded loop, so whichever situation is real at that instant is handled by the operation
that is safe for it. Nothing lands by unconditional overwrite, and nothing here ever
unlinks the target.

Two designs were tried and discarded, both recorded at their call sites: copying the
security descriptor onto the temp file by hand (which strips this process of the DELETE
right the following rename needs), and staking an O_EXCL placeholder (whose failure path
needs an undo, and any undo is a check-then-unlink that can delete a concurrent writer's
file).
"""
import ctypes
import os
import shutil
from ctypes import wintypes

__all__ = ["atomic_write"]


def _replace_win(target, tmp):
    """ReplaceFileW(target <- tmp), preserving the target's security descriptor.

    Flags are 0 on purpose. REPLACEFILE_IGNORE_MERGE_ERRORS would let the swap succeed
    while quietly failing to carry the DACL across, which is the silent widening this
    function exists to prevent — better to raise and leave the original in place.
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = k32.ReplaceFileW
    fn.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                   wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
    fn.restype = wintypes.BOOL
    if not fn(target, tmp, None, 0, None, None):
        raise ctypes.WinError(ctypes.get_last_error())


_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
# Each round trip needs the target to both vanish and reappear between two calls. A handful
# of attempts covers any real contention; a bound is here so a pathological loop reports
# itself instead of spinning.
_SWAP_ATTEMPTS = 5


def _swap_win(target, tmp):
    """Swap tmp into target, never taking the metadata-losing path for a file that exists.

    Deciding between ReplaceFileW and os.replace from an up-front os.path.exists() check is
    a TOCTOU: a target created in the gap would be clobbered by os.replace, losing whatever
    the other writer put there and resetting a restrictive DACL to the temp file's
    directory-inherited one. So the existence question is never asked in advance — it is
    answered by ReplaceFileW itself, which is the freshest observation available.

    Data lands by exactly one of two means, and both are safe by construction: ReplaceFileW
    when a file is there (its descriptor is kept), or a create-only rename when nothing is
    there (there is no descriptor to keep). Nothing in between overwrites, and this module
    never unlinks the target, so no failure path can destroy another writer's file.
    """
    for _ in range(_SWAP_ATTEMPTS):
        try:
            _replace_win(target, tmp)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (_ERROR_FILE_NOT_FOUND,
                                                      _ERROR_PATH_NOT_FOUND):
                raise
        try:
            # Create-only rename. On Windows os.rename REFUSES to overwrite, which makes
            # this an atomic "put it there if and only if nothing is there" — the tmp file
            # is already complete and fsynced, so what lands is whole.
            #
            # Two earlier designs failed here. os.replace silently widened permissions,
            # since a file created in the intervening microseconds can already carry a
            # restrictive descriptor (CreateFile takes lpSecurityAttributes). An O_EXCL
            # placeholder then needed an undo on failure, and that undo could only ever be
            # a size check followed by an unlink — a TOCTOU that deletes whatever a
            # concurrent writer swapped in between the two calls. This version creates
            # nothing it might have to remove and never unlinks the target at all.
            os.rename(tmp, target)
            return
        except FileExistsError:
            # Someone got there in the window. Go round again: ReplaceFileW now applies and
            # preserves THEIR descriptor, which is exactly the outcome we want.
            continue
    raise OSError("%s: gave up after %d swap attempts — the target keeps appearing and "
                  "disappearing between calls" % (target, _SWAP_ATTEMPTS))


def atomic_write(path, text, encoding="utf-8"):
    """Replace `path` with `text` atomically. On failure the original is left as it was."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    # Same directory, so the swap stays within one filesystem — ReplaceFileW requires it,
    # and os.replace is only atomic under it. The pid keeps two engines writing the same
    # target from clobbering each other's temp file.
    tmp = os.path.join(d, ".%s.%d.tmp" % (os.path.basename(path), os.getpid()))
    try:
        with open(tmp, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())   # without this, the swap can win the race to a crash
        if os.name == "nt":
            _swap_win(path, tmp)
        else:
            try:
                shutil.copymode(path, tmp)   # POSIX: carry the mode bits across
            except OSError:
                pass                          # no existing target; nothing to carry
            os.replace(tmp, path)
    except BaseException:
        # Leaving a stray .tmp next to a secrets file would be its own small leak.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
