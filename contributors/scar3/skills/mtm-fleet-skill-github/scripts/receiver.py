#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""Verified GitHub carrier receiver for fleet skills.

GitHub is transport, ``_skill/fleet-skills`` is the local canonical catalog.
Remote additions and previously-managed updates are installed atomically.  A
locally divergent package is never overwritten; it is recorded for review.

CITE: _skill/fleet-skills/mtm-fleet-skill-github/SKILL.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


WORKSPACE = Path(os.environ.get("AI_WORKSPACE", r"C:\ai_workspace")).resolve()
ENGINE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = WORKSPACE / "_registry" / "fleet-skill-github.json"
DEFAULT_STATE = WORKSPACE / "_registry" / "fleet-skill-github-state.json"
DEFAULT_LOCK = WORKSPACE / "_registry" / "fleet-skill-github.lock"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
TEXT_SUFFIXES = {
    ".json", ".md", ".py", ".ps1", ".txt", ".yaml", ".yml", ".js", ".mjs"
}


class SyncError(RuntimeError):
    pass


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)


def _sha(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _files(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): _sha(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def _fingerprint(files: dict[str, str]) -> str:
    body = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _stable_sha(payload: object) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )


def _git(args: list[str], cwd: Path | None = None, timeout: int = 180) -> str:
    result = _run(["git", *args], cwd=cwd, timeout=timeout)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise SyncError(f"git {' '.join(args[:2])} failed: {detail[-1] if detail else result.returncode}")
    return result.stdout.strip()


def _load_config(path: Path) -> dict:
    config = _read_json(path)
    required = ("repo", "branch", "checkout", "host", "seat", "peers")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise SyncError(f"config missing: {', '.join(missing)}")
    return config


def _checkout(config: dict, *, fetch: bool) -> tuple[Path, str]:
    checkout = Path(config["checkout"]).resolve()
    repo = str(config["repo"])
    branch = str(config["branch"])
    if not checkout.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--depth", "1", "--branch", branch, repo, str(checkout)], timeout=300)
    if not (checkout / ".git").exists():
        raise SyncError(f"checkout is not a git repository: {checkout}")
    origin = _git(["remote", "get-url", "origin"], checkout)
    if origin.rstrip("/").lower() != repo.rstrip("/").lower():
        raise SyncError(f"checkout origin mismatch: {origin}")
    if fetch:
        dirty = _git(["status", "--porcelain"], checkout)
        if dirty:
            raise SyncError("carrier checkout is dirty; refusing pull")
        _git(["fetch", "--depth", "1", "origin", branch], checkout, timeout=300)
        _git(["merge", "--ff-only", "FETCH_HEAD"], checkout)
    return checkout, _git(["rev-parse", "HEAD"], checkout)


def _verify_declared_tree(root: Path, declared: dict[str, str]) -> list[str]:
    errors: list[str] = []
    actual = _files(root)
    for rel, expected in declared.items():
        if rel not in actual:
            errors.append(f"missing:{rel}")
        elif actual[rel] != expected:
            errors.append(f"hash:{rel}")
    extras = sorted(set(actual) - set(declared))
    errors.extend(f"extra:{rel}" for rel in extras)
    return errors


def verify_carrier(repo: Path, peers: list[str]) -> dict:
    root_path = repo / "manifest.json"
    if not root_path.is_file():
        raise SyncError("carrier manifest.json missing")
    root = _read_json(root_path)
    declared_hosts = set(root.get("contributors") or [])
    peer_rows: list[dict] = []
    valid_manifests: dict[str, dict] = {}
    errors: list[str] = []

    for peer in peers:
        manifest_path = repo / "contributors" / peer / "manifest.json"
        if not manifest_path.is_file():
            peer_rows.append({"peer": peer, "status": "missing", "reason": "manifest_missing"})
            continue
        try:
            manifest = _read_json(manifest_path)
        except (OSError, json.JSONDecodeError) as exc:
            peer_rows.append({"peer": peer, "status": "invalid", "reason": str(exc)})
            errors.append(f"{peer}:manifest_invalid")
            continue
        peer_errors: list[str] = []
        if manifest.get("contributor") != peer:
            peer_errors.append("contributor_mismatch")
        if peer not in declared_hosts:
            peer_errors.append("not_in_root_manifest")
        expected_manifest_sha = (root.get("manifests") or {}).get(peer)
        if not expected_manifest_sha or expected_manifest_sha != manifest.get("manifest_sha"):
            peer_errors.append("manifest_sha_reference_mismatch")
        skills = manifest.get("skills") or []
        if manifest.get("skill_count") != len(skills):
            peer_errors.append("skill_count_mismatch")
        for skill in skills:
            name = str(skill.get("name") or "")
            if not name or not isinstance(skill.get("files"), dict):
                peer_errors.append("invalid_skill_entry")
                continue
            tree_errors = _verify_declared_tree(
                repo / "contributors" / peer / "skills" / name, skill["files"]
            )
            peer_errors.extend(f"{name}:{item}" for item in tree_errors)
        status = "valid" if not peer_errors else "invalid"
        peer_rows.append(
            {
                "peer": peer,
                "status": status,
                "authority": manifest.get("authority"),
                "generated_at": manifest.get("generated_at"),
                "skill_count": len(skills),
                "manifest_sha": manifest.get("manifest_sha"),
                "errors": peer_errors,
            }
        )
        if peer_errors:
            errors.extend(f"{peer}:{item}" for item in peer_errors)
        else:
            valid_manifests[peer] = manifest

    candidates: dict[str, list[dict]] = {}
    for manifest in valid_manifests.values():
        for skill in manifest.get("skills") or []:
            candidates.setdefault(skill["name"], []).append(skill)
    canonical = repo / "_skill" / "fleet-skills"
    canonical_rows: list[dict] = []
    for skill_dir in sorted((p for p in canonical.iterdir() if p.is_dir()), key=lambda p: p.name):
        actual = _files(skill_dir)
        matches = [
            row for row in candidates.get(skill_dir.name, [])
            if row.get("files") == actual
        ]
        ok = bool(matches)
        canonical_rows.append(
            {
                "name": skill_dir.name,
                "ok": ok,
                "fingerprint": _fingerprint(actual),
                "package_sha": matches[0].get("package_sha") if matches else None,
            }
        )
        if not ok:
            errors.append(f"canonical:{skill_dir.name}:no_verified_contributor_match")
    if not canonical_rows:
        errors.append("canonical:empty")

    missing_peers = [row["peer"] for row in peer_rows if row["status"] == "missing"]
    return {
        "ok": not errors,
        "fleet_status": "verified" if not missing_peers and not errors else ("unknown" if missing_peers else "invalid"),
        "errors": errors,
        "missing_peers": missing_peers,
        "peers": peer_rows,
        "canonical": canonical_rows,
        "root_manifest": root,
    }


def _atomic_replace_tree(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".{target.name}.sync-{uuid.uuid4().hex}"
    backup = target.parent / f".{target.name}.previous-{uuid.uuid4().hex}"
    shutil.copytree(source, temp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    try:
        if target.exists():
            target.replace(backup)
        temp.replace(target)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if target.exists() and backup.exists():
            shutil.rmtree(target)
        if backup.exists():
            backup.replace(target)
        if temp.exists():
            shutil.rmtree(temp)
        raise


def _copy_file_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False, suffix=".tmp") as handle:
        handle.write(source.read_bytes())
        temp = Path(handle.name)
    temp.replace(target)


def _merge_catalog(source: Path, target: Path, prior: dict, *, dry_run: bool) -> dict:
    installed: dict[str, str] = {}
    added: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    conflicts: list[dict] = []
    repaired: list[dict] = []
    prior_installed = prior.get("managed_catalog") or {}
    for source_dir in sorted((p for p in source.iterdir() if p.is_dir()), key=lambda p: p.name):
        name = source_dir.name
        remote_files = _files(source_dir)
        remote_fp = _fingerprint(remote_files)
        target_dir = target / name
        local_files = _files(target_dir)
        local_fp = _fingerprint(local_files) if local_files else None
        if local_fp == remote_fp:
            unchanged.append(name)
            installed[name] = remote_fp
            continue
        if not target_dir.exists():
            if not dry_run:
                _atomic_replace_tree(source_dir, target_dir)
            added.append(name)
            installed[name] = remote_fp
            continue
        if "SKILL.md" not in local_files:
            archive = (
                WORKSPACE / "_registry" / "fleet-skill-conflicts" / name /
                f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{(local_fp or 'empty')[:12]}"
            )
            if not dry_run:
                archive.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(target_dir, archive)
                _atomic_replace_tree(source_dir, target_dir)
            repaired.append({"name": name, "reason": "missing_SKILL.md", "archive": str(archive)})
            installed[name] = remote_fp
            continue
        if prior_installed.get(name) == local_fp:
            if not dry_run:
                _atomic_replace_tree(source_dir, target_dir)
            updated.append(name)
            installed[name] = remote_fp
            continue
        augmented = sorted(set(remote_files) - set(local_files))
        if augmented and not dry_run:
            for rel in augmented:
                _copy_file_atomic(source_dir / Path(rel), target_dir / Path(rel))
            local_fp = _fingerprint(_files(target_dir))
        conflicts.append(
            {
                "name": name,
                "reason": "local_divergence",
                "local_fingerprint": local_fp,
                "remote_fingerprint": remote_fp,
                "augmented_missing_files": augmented,
            }
        )
    return {
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "conflicts": conflicts,
        "repaired": repaired,
        "managed_catalog": installed,
    }


def _deploy_required(workspace: Path, seat: str, required: list[str], prior: dict, *, dry_run: bool) -> dict:
    seat_root = workspace / seat
    canonical = workspace / "_skill" / "fleet-skills"
    managed = dict(prior.get("managed_surfaces") or {})
    rows: list[dict] = []
    surfaces = [
        (seat_root / ".cursor" / "skills", required),
        (seat_root / ".agents" / "skills", ["fames", "token-preflight"]),
        (seat_root / ".claude" / "skills", ["fames", "token-preflight"]),
    ]
    for base, names in surfaces:
        for name in names:
            source = canonical / name
            target = base / name
            if not source.is_dir():
                rows.append({"target": str(target), "status": "missing_source"})
                continue
            remote_fp = _fingerprint(_files(source))
            local_files = _files(target)
            local_fp = _fingerprint(local_files) if local_files else None
            key = str(target)
            if local_fp == remote_fp:
                status = "unchanged"
            elif not target.exists() or managed.get(key) == local_fp:
                if not dry_run:
                    _atomic_replace_tree(source, target)
                status = "installed"
            else:
                status = "local_divergence"
            if status != "local_divergence":
                managed[key] = remote_fp
            rows.append({"target": key, "status": status, "fingerprint": remote_fp})
    return {"rows": rows, "managed_surfaces": managed}


def _package_sha(skill_dir: Path, files: dict[str, str], previous: dict | None) -> str:
    if previous and previous.get("files") == files and previous.get("package_sha"):
        return str(previous["package_sha"])
    bundle = skill_dir / "bundle-manifest.json"
    if bundle.is_file():
        try:
            package_sha = _read_json(bundle).get("package_sha")
            if package_sha:
                return str(package_sha)
        except (OSError, json.JSONDecodeError):
            pass
    return _stable_sha({"name": skill_dir.name, "files": files})


def publish(config_path: Path, *, fetch: bool, dry_run: bool) -> dict:
    """Publish scar3's verified local catalog into its contributor namespace."""
    config = _load_config(config_path)
    checkout, before_commit = _checkout(config, fetch=fetch)
    verification = verify_carrier(checkout, [str(peer) for peer in config["peers"]])
    if not verification["ok"]:
        raise SyncError("carrier verification failed before publish")
    contributor = str(config["local_contributor"])
    manifest_path = checkout / "contributors" / contributor / "manifest.json"
    previous_manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    previous_skills = {row["name"]: row for row in previous_manifest.get("skills") or []}
    required = list(previous_manifest.get("required") or [])
    local_catalog = WORKSPACE / "_skill" / "fleet-skills"
    if not local_catalog.is_dir():
        raise SyncError("local canonical catalog missing")

    skills: list[dict] = []
    for skill_dir in sorted((p for p in local_catalog.iterdir() if p.is_dir()), key=lambda p: p.name):
        files = _files(skill_dir)
        if "SKILL.md" not in files:
            continue
        previous = previous_skills.get(skill_dir.name)
        entry = {
            "name": skill_dir.name,
            "sha": (str(previous.get("sha")) if previous and previous.get("files") == files else _fingerprint(files)[:16]),
            "required": skill_dir.name in required,
            "lane": previous.get("lane") if previous else None,
            "package_sha": _package_sha(skill_dir, files, previous),
            "files": files,
        }
        skills.append(entry)
    if not skills:
        raise SyncError("local canonical catalog has no publishable skills")

    manifest = {
        key: value for key, value in previous_manifest.items()
        if key not in {"generated_at", "manifest_sha", "skill_count", "skills"}
    }
    manifest.update(
        {
            "schema": 2,
            "authority": manifest.get("authority") or f"ai_{contributor}",
            "contributor": contributor,
            "machine": config["host"],
            "repo": config["repo"],
            "generated_at": _iso(),
            "skill_count": len(skills),
            "skills": skills,
        }
    )
    manifest["manifest_sha"] = _stable_sha(manifest)[:16]

    root = verification["root_manifest"]
    root["generated_at"] = manifest["generated_at"]
    contributors = list(root.get("contributors") or [])
    if contributor not in contributors:
        contributors.append(contributor)
    root["contributors"] = sorted(contributors)
    root.setdefault("manifests", {})[contributor] = manifest["manifest_sha"]
    root.setdefault("detail", {})[contributor] = manifest
    root["union_sha"] = _stable_sha(
        {"manifests": root["manifests"], "detail": root["detail"]}
    )[:16]

    changed = [
        name for name, entry in {row["name"]: row for row in skills}.items()
        if not previous_skills.get(name) or previous_skills[name].get("files") != entry["files"]
    ]
    if not dry_run:
        with tempfile.TemporaryDirectory(prefix="fleet-skill-publish-", dir=checkout.parent) as temp_dir:
            staging = Path(temp_dir) / "skills"
            staging.mkdir()
            for entry in skills:
                shutil.copytree(
                    local_catalog / entry["name"], staging / entry["name"],
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            _atomic_replace_tree(staging, checkout / "contributors" / contributor / "skills")
            _atomic_replace_tree(staging, checkout / "_skill" / "fleet-skills")
        _write_json_atomic(manifest_path, manifest)
        _write_json_atomic(checkout / "manifest.json", root)
        after = verify_carrier(checkout, [str(peer) for peer in config["peers"]])
        if not after["ok"]:
            raise SyncError("carrier verification failed after publish: " + "; ".join(after["errors"][:5]))
    return {
        "ok": True,
        "dry_run": dry_run,
        "before_commit": before_commit,
        "contributor": contributor,
        "skill_count": len(skills),
        "changed_skills": changed,
        "manifest_sha": manifest["manifest_sha"],
        "fleet_status": verification["fleet_status"],
        "missing_peers": verification["missing_peers"],
    }


class _Lock:
    def __init__(self, path: Path, stale_seconds: int = 7200):
        self.path = path
        self.stale_seconds = stale_seconds
        self.owned = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = time.time() - self.path.stat().st_mtime
            if age <= self.stale_seconds:
                raise SyncError("sync already running")
            self.path.unlink()
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": _iso()}, handle)
        self.owned = True
        return self

    def __exit__(self, *_args):
        if self.owned:
            self.path.unlink(missing_ok=True)


def sync(config_path: Path, state_path: Path, *, fetch: bool, dry_run: bool) -> dict:
    config = _load_config(config_path)
    prior = _read_json(state_path) if state_path.is_file() else {}
    checkout, commit = _checkout(config, fetch=fetch)
    verified = verify_carrier(checkout, [str(peer) for peer in config["peers"]])
    if not verified["ok"]:
        raise SyncError("carrier verification failed: " + "; ".join(verified["errors"][:5]))
    catalog = _merge_catalog(
        checkout / "_skill" / "fleet-skills",
        WORKSPACE / "_skill" / "fleet-skills",
        prior,
        dry_run=dry_run,
    )
    root_manifest = verified["root_manifest"]
    required: list[str] = []
    for detail in (root_manifest.get("detail") or {}).values():
        for name in detail.get("required") or []:
            if name not in required:
                required.append(name)
    deployment = _deploy_required(WORKSPACE, str(config["seat"]), required, prior, dry_run=dry_run)
    result = {
        "schema": 1,
        "checked_at": _iso(),
        "ok": True,
        "fleet_status": verified["fleet_status"],
        "remote_commit": commit,
        "dry_run": dry_run,
        "peers": verified["peers"],
        "missing_peers": verified["missing_peers"],
        "catalog": {key: value for key, value in catalog.items() if key != "managed_catalog"},
        "deployment": deployment["rows"],
        "managed_catalog": catalog["managed_catalog"],
        "managed_surfaces": deployment["managed_surfaces"],
    }
    if not dry_run:
        _write_json_atomic(state_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "verify", "status", "publish"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            result = _read_json(args.state) if args.state.is_file() else {"ok": False, "status": "never_run"}
        else:
            config = _load_config(args.config)
            if args.command == "verify":
                checkout, commit = _checkout(config, fetch=not args.no_fetch)
                result = verify_carrier(checkout, [str(peer) for peer in config["peers"]])
                result["remote_commit"] = commit
            elif args.command == "publish":
                with _Lock(args.lock):
                    result = publish(args.config, fetch=not args.no_fetch, dry_run=args.dry_run)
            else:
                with _Lock(args.lock):
                    result = sync(args.config, args.state, fetch=not args.no_fetch, dry_run=args.dry_run)
    except (OSError, ValueError, json.JSONDecodeError, SyncError, subprocess.TimeoutExpired) as exc:
        result = {"ok": False, "checked_at": _iso(), "error": str(exc)}
        if args.command == "sync" and not args.dry_run:
            _write_json_atomic(args.state, result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"fleet-skill-github ok={result.get('ok')} status={result.get('fleet_status', result.get('status', 'error'))}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
