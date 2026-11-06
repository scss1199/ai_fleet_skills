#!/usr/bin/env python3
"""Deterministic tests for git_repo_detect — no network, no fleet state.

Builds throwaway repositories in a temp dir and asserts the four shapes the old
isdir gate could not tell apart: a normal repo, a linked worktree on a branch, a
detached-HEAD worktree, and a path outside every repo.

Run: python tests/test_git_repo_detect.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engines"))

from git_repo_detect import push_args, resolve_repo  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
failures: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")
        failures.append(name)


def git(cwd: str, *args: str) -> None:
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, creationflags=NO_WINDOW
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {r.stderr.strip()}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="git-detect-") as tmp:
        main_repo = os.path.join(tmp, "main")
        os.makedirs(main_repo)
        git(main_repo, "init", "-b", "trunk")
        git(main_repo, "config", "user.email", "test@example.invalid")
        git(main_repo, "config", "user.name", "test")
        open(os.path.join(main_repo, "a.txt"), "w", encoding="utf-8").write("one\n")
        git(main_repo, "add", "-A")
        git(main_repo, "commit", "-m", "one")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=main_repo, capture_output=True, text=True
        ).stdout.strip()

        nested = os.path.join(main_repo, "sub", "deep")
        os.makedirs(nested)

        branch_wt = os.path.join(tmp, "wt-branch")
        git(main_repo, "worktree", "add", "-b", "side", branch_wt)

        detached_wt = os.path.join(tmp, "wt-detached")
        git(main_repo, "worktree", "add", "--detach", detached_wt, head)

        outside = os.path.join(tmp, "outside")
        os.makedirs(outside)

        # --- normal repo -------------------------------------------------------
        print("normal repository")
        r = resolve_repo(main_repo)
        check("ok", r.ok, True)
        check("branch", r.branch, "trunk")
        check("detached", r.detached, False)
        check("linked_worktree", r.linked_worktree, False)
        check("toplevel", os.path.normcase(r.toplevel), os.path.normcase(os.path.realpath(main_repo)))

        print("subdirectory of a normal repository")
        check("ok", resolve_repo(nested).ok, True)
        check("toplevel", os.path.normcase(resolve_repo(nested).toplevel),
              os.path.normcase(os.path.realpath(main_repo)))

        # --- linked worktree on a branch — the reported defect ------------------
        print("linked worktree on a branch")
        # The old gate: os.path.isdir(<wt>/.git) is False because .git is a file.
        check("dot_git_is_a_file", os.path.isfile(os.path.join(branch_wt, ".git")), True)
        check("old_isdir_gate_would_reject", os.path.isdir(os.path.join(branch_wt, ".git")), False)
        r = resolve_repo(branch_wt)
        check("ok", r.ok, True)
        check("branch", r.branch, "side")
        check("detached", r.detached, False)
        check("linked_worktree", r.linked_worktree, True)
        check("push_args", push_args(r), ["push", "origin", "side:refs/heads/side"])

        # --- detached HEAD worktree --------------------------------------------
        print("detached HEAD worktree")
        r = resolve_repo(detached_wt)
        check("ok", r.ok, True)
        check("detached", r.detached, True)
        check("branch", r.branch, "")
        check("linked_worktree", r.linked_worktree, True)
        check("head_ref", r.head_ref, "HEAD")
        check("push_args_named_branch", push_args(r, "release"),
              ["push", "origin", "HEAD:refs/heads/release"])
        try:
            push_args(r)
            check("push_without_branch_raises", False, True)
        except ValueError:
            check("push_without_branch_raises", True, True)

        # --- outside any repository --------------------------------------------
        print("outside any repository")
        r = resolve_repo(outside)
        check("ok", r.ok, False)
        check("reason_names_worktree", "not a git work tree" in r.reason, True)

        print("missing path")
        r = resolve_repo(os.path.join(tmp, "does-not-exist"))
        check("ok", r.ok, False)
        check("reason", "does not exist" in r.reason, True)

        print("file instead of a directory")
        r = resolve_repo(os.path.join(main_repo, "a.txt"))
        check("ok", r.ok, False)
        check("reason", "not a directory" in r.reason, True)

        # Windows cannot remove a worktree's files while git holds them registered.
        git(main_repo, "worktree", "remove", "--force", branch_wt)
        git(main_repo, "worktree", "remove", "--force", detached_wt)

    print()
    if failures:
        print(f"FAIL {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("PASS git_repo_detect")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
