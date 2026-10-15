#!/usr/bin/env python3
"""Repo detection that survives linked worktrees.

`git_smart.py` gates on `os.path.isdir(os.path.join(repo, ".git"))`. In a linked
worktree created by `git worktree add`, `.git` is a FILE holding `gitdir: <path>`,
not a directory, so that gate answers "not a git repo" for a perfectly valid
checkout — measured 2026-08-17 against
C:\\ai_workspace\\fracdigi\\_worktrees\\prod-residual-20260817 (`.git` mode -a-h--).

Ask git instead of guessing at the filesystem: `git rev-parse` is the same answer
git itself uses, so a normal repo, a linked worktree, a detached-HEAD worktree and
a subdirectory of any of them all resolve, while a path outside every repo still
fails closed.

Contract role: called by git_smart.py's `main()` in place of the isdir gate, and
by ship flows that must push a named branch from a detached-HEAD worktree.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_NO_WINDOW,
    )


@dataclass(frozen=True)
class RepoInfo:
    """What git says about a path. `ok=False` means no repo, and `reason` says why."""

    ok: bool
    reason: str = ""
    toplevel: str = ""
    git_dir: str = ""
    common_dir: str = ""
    branch: str = ""          # "" when HEAD is detached
    detached: bool = False
    linked_worktree: bool = False

    @property
    def head_ref(self) -> str:
        """A pushable source ref: the branch name, or literal HEAD when detached."""
        return self.branch or "HEAD"


def resolve_repo(path: str | None = None) -> RepoInfo:
    """Resolve `path` (default cwd) to a repository, or explain the refusal.

    Fails closed on: a path that does not exist, a path that is not a directory,
    and a directory that is not inside any work tree. A bare repository is
    rejected too — the callers stage and commit a work tree.
    """
    target = os.path.abspath(path or os.getcwd())
    if not os.path.exists(target):
        return RepoInfo(False, f"path does not exist: {target}")
    if not os.path.isdir(target):
        return RepoInfo(False, f"path is not a directory: {target}")

    probe = _git(["rev-parse", "--is-inside-work-tree"], target)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return RepoInfo(False, f"not a git work tree: {target}")

    def one(*args: str) -> str:
        r = _git(list(args), target)
        return r.stdout.strip() if r.returncode == 0 else ""

    toplevel = one("rev-parse", "--path-format=absolute", "--show-toplevel")
    git_dir = one("rev-parse", "--path-format=absolute", "--absolute-git-dir")
    common_dir = one("rev-parse", "--path-format=absolute", "--git-common-dir")
    if not toplevel:
        return RepoInfo(False, f"could not resolve work tree root: {target}")

    branch = one("rev-parse", "--abbrev-ref", "HEAD")
    detached = branch in ("", "HEAD")

    # A linked worktree keeps its own git dir under the main repo's
    # .git/worktrees/<name>, so git-dir and git-common-dir differ.
    linked = bool(git_dir and common_dir) and os.path.normcase(
        os.path.normpath(git_dir)
    ) != os.path.normcase(os.path.normpath(common_dir))

    return RepoInfo(
        ok=True,
        toplevel=os.path.normpath(toplevel),
        git_dir=os.path.normpath(git_dir),
        common_dir=os.path.normpath(common_dir),
        branch="" if detached else branch,
        detached=detached,
        linked_worktree=linked,
    )


def push_args(info: RepoInfo, branch: str | None = None, remote: str = "origin") -> list[str]:
    """Push arguments that name their destination explicitly.

    A detached HEAD has no upstream to infer, so `git push` and `git push -u origin HEAD`
    both refuse. Naming the refspec is what makes a worktree deploy shippable.
    """
    if not info.ok:
        raise ValueError(info.reason)
    target = (branch or info.branch).strip()
    if not target:
        raise ValueError("detached HEAD needs an explicit branch to push to")
    return ["push", remote, f"{info.head_ref}:refs/heads/{target}"]


if __name__ == "__main__":  # pragma: no cover - manual probe
    import json
    import sys

    got = resolve_repo(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(got.__dict__, ensure_ascii=False, indent=1))
    raise SystemExit(0 if got.ok else 1)
