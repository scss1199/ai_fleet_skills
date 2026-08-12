#!/usr/bin/env python3
"""Build, install, and verify the portable content-addressed FAMES bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SURFACES = (".agents", ".claude", ".cursor")
EXECUTION_ORDER = ["FP", "MTM", "SCF", "AEX", "SEAL"]
PROTOCOL_SOURCES = {
    "FAMES": "_registry/fames-protocol.json",
    "FP": "_registry/goal-vector-protocol.json",
    "MTM": "_registry/mtm-protocol.json",
    "SCF": "_registry/scf-protocol.json",
    "AEX": "_registry/fleet-token-ladder.json",
    "SEAL": "_registry/seal-protocol.json",
}
PROTOCOL_TARGETS = {
    key: f"references/protocols/{Path(source).name}"
    for key, source in PROTOCOL_SOURCES.items()
}
MANIFEST_NAME = "bundle-manifest.json"
GENERATION_PREFIX = "FAMES-GEN: "
TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".ps1",
    ".txt",
    ".yaml",
    ".yml",
}


def _sha256(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _stable_sha(payload: object) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)


def _package_identity(version: str, files: dict[str, str]) -> str:
    return _stable_sha(
        {
            "id": "FAMES",
            "version": version,
            "execution_order": EXECUTION_ORDER,
            "files": files,
        }
    )


def _git_protocol_blob(workspace: Path, git_ref: str, source_rel: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{git_ref}:{source_rel}"],
        cwd=workspace,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cannot read {source_rel} from git ref {git_ref}")
    return result.stdout


def build_bundle(
    workspace: Path,
    package_root: Path = PACKAGE_ROOT,
    protocol_git_ref: str | None = None,
) -> dict:
    workspace = workspace.resolve()
    package_root = package_root.resolve()
    copied: dict[str, str] = {}
    for phase, source_rel in PROTOCOL_SOURCES.items():
        source = workspace / source_rel
        target_rel = PROTOCOL_TARGETS[phase]
        target = package_root / target_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if protocol_git_ref:
            target.write_bytes(_git_protocol_blob(workspace, protocol_git_ref, source_rel))
        else:
            if not source.is_file():
                raise FileNotFoundError(f"missing source protocol: {source}")
            shutil.copy2(source, target)
        copied[target_rel] = source_rel

    fames = _read_json(package_root / PROTOCOL_TARGETS["FAMES"])
    expected_files = [
        "SKILL.md",
        "agents/openai.yaml",
        "scripts/fames_fleet.py",
        *PROTOCOL_TARGETS.values(),
    ]
    files = {rel: _sha256(package_root / rel) for rel in sorted(set(expected_files))}
    version = str(fames.get("version") or "")
    manifest = {
        "schema": 1,
        "id": "FAMES",
        "version": version,
        "execution_order": EXECUTION_ORDER,
        "source_files": copied,
        "source_git_commit": (
            subprocess.run(
                ["git", "rev-parse", protocol_git_ref],
                cwd=workspace,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if protocol_git_ref
            else None
        ),
        "files": files,
        "package_sha": _package_identity(version, files),
    }
    _write_json_atomic(package_root / MANIFEST_NAME, manifest)
    return {"ok": True, "package_root": str(package_root), **manifest}


def verify_package(package_root: Path = PACKAGE_ROOT) -> dict:
    package_root = package_root.resolve()
    errors: list[str] = []
    manifest_path = package_root / MANIFEST_NAME
    try:
        manifest = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "package_root": str(package_root), "errors": [f"manifest unreadable: {exc}"]}

    files = manifest.get("files") or {}
    if not isinstance(files, dict) or not files:
        errors.append("manifest files are empty")
        files = {}
    for rel, expected in files.items():
        target = package_root / rel
        if not target.is_file():
            errors.append(f"missing package file: {rel}")
        elif _sha256(target) != expected:
            errors.append(f"package hash mismatch: {rel}")

    version = str(manifest.get("version") or "")
    if manifest.get("id") != "FAMES":
        errors.append("manifest id is not FAMES")
    if manifest.get("execution_order") != EXECUTION_ORDER:
        errors.append("manifest execution order mismatch")
    if manifest.get("package_sha") != _package_identity(version, files):
        errors.append("package_sha mismatch")

    try:
        skill_body = (package_root / "SKILL.md").read_text(encoding="utf-8-sig")
        if "name: fames" not in skill_body:
            errors.append("SKILL.md frontmatter does not declare fames")
        if "references/protocols/fames-protocol.json" not in skill_body:
            errors.append("SKILL.md does not load the bundled protocol")
        fames = _read_json(package_root / PROTOCOL_TARGETS["FAMES"])
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cold-load failed: {exc}")
        fames = {}

    if fames.get("version") != version:
        errors.append("bundled protocol version mismatch")
    if fames.get("execution_order") != EXECUTION_ORDER:
        errors.append("bundled protocol execution order mismatch")
    for phase, source_rel in (fames.get("canonical_protocols") or {}).items():
        if phase not in EXECUTION_ORDER:
            errors.append(f"unexpected phase protocol: {phase}")
            continue
        target = package_root / "references" / "protocols" / Path(source_rel).name
        try:
            phase_protocol = _read_json(target)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{phase} protocol unreadable: {exc}")
            continue
        declared_phase = phase_protocol.get("fames_phase")
        if declared_phase is not None and declared_phase != phase:
            errors.append(f"{phase} protocol declares a different FAMES phase")
        if phase == "AEX" and phase_protocol.get("parent_umbrella") != "FAMES":
            errors.append("AEX protocol is not bound to the FAMES umbrella")

    return {
        "ok": not errors,
        "package_root": str(package_root),
        "version": version,
        "package_sha": manifest.get("package_sha"),
        "file_count": len(files),
        "cold_load": not errors,
        "errors": errors,
    }


def _skill_generation(package_root: Path = PACKAGE_ROOT) -> str:
    """Read the contract generation stamp from SKILL.md on disk, right now."""
    try:
        for line in (package_root / "SKILL.md").read_text(encoding="utf-8-sig").splitlines():
            if line.startswith(GENERATION_PREFIX):
                return line[len(GENERATION_PREFIX):].strip().strip("`")
    except OSError:
        return ""
    return ""


def parity(workspace: Path, package_root: Path = PACKAGE_ROOT) -> dict:
    """Compare every bundled protocol against the workspace registry SSOT.

    A machine without the registry is a legitimate cold load, so the whole check is
    NOT_APPLICABLE there. A registry that exists and disagrees is drift, and drift is
    UNKNOWN: the bundle would otherwise ship a protocol generation the hub has replaced.
    Hashes come from _sha256, which normalizes line endings, so a CRLF registry and an
    LF bundle do not fake a mismatch.
    """
    workspace = workspace.resolve()
    package_root = package_root.resolve()
    rows: list[dict] = []
    errors: list[str] = []
    for phase in EXECUTION_ORDER + ["FAMES"]:
        source_rel = PROTOCOL_SOURCES[phase]
        source = workspace / source_rel
        target = package_root / PROTOCOL_TARGETS[phase]
        row = {"phase": phase, "source": source_rel}
        if not source.is_file():
            row["state"] = "NOT_APPLICABLE"
            row["why"] = "registry absent; bundle is the portable authority"
            rows.append(row)
            continue
        if not target.is_file():
            row["state"] = "UNKNOWN"
            errors.append(f"{phase}: bundled protocol missing")
            rows.append(row)
            continue
        try:
            bundled = _read_json(target)
            registry = _read_json(source)
        except (OSError, json.JSONDecodeError) as exc:
            row["state"] = "UNKNOWN"
            errors.append(f"{phase}: unreadable protocol: {exc}")
            rows.append(row)
            continue
        row["bundle_version"] = bundled.get("version")
        row["registry_version"] = registry.get("version")
        row["content_match"] = _sha256(target) == _sha256(source)
        if row["bundle_version"] != row["registry_version"]:
            row["state"] = "UNKNOWN"
            errors.append(
                f"{phase}: version drift bundle={row['bundle_version']} registry={row['registry_version']}"
            )
        elif not row["content_match"]:
            row["state"] = "UNKNOWN"
            errors.append(f"{phase}: content drift at same version {row['bundle_version']}")
        else:
            row["state"] = "PASS"
        if phase == "FAMES" and registry.get("execution_order") != EXECUTION_ORDER:
            row["state"] = "UNKNOWN"
            errors.append("FAMES: registry execution order mismatch")
        rows.append(row)
    return {
        "ok": not errors,
        "workspace": str(workspace),
        "phases": rows,
        "errors": errors,
    }


def status(workspace: Path, package_root: Path = PACKAGE_ROOT) -> dict:
    """The one command a thread runs to prove it is executing the current FAMES.

    Everything here is read from disk at call time, so a conversation that started
    before an edit gets the new answer the moment it runs this instead of trusting the
    FAMES text already sitting in its context.
    """
    package = verify_package(package_root)
    drift = parity(workspace, package_root)
    generation = _skill_generation(package_root)
    errors = [f"package: {e}" for e in package.get("errors", [])]
    errors += [f"parity: {e}" for e in drift.get("errors", [])]
    if not generation:
        errors.append(f"SKILL.md carries no {GENERATION_PREFIX.strip()} stamp")
    return {
        "ok": not errors,
        "skill_gen": generation,
        "package_sha": package.get("package_sha"),
        "version": package.get("version"),
        "package_ok": package.get("ok"),
        "parity_ok": drift.get("ok"),
        "parity": drift.get("phases"),
        "read_at": datetime.now(timezone.utc).isoformat(),
        "stale_context_rule": (
            "If the FAMES text in your context declares a different %s than skill_gen above, "
            "that copy is stale: re-read SKILL.md and the bundled protocols from disk before "
            "judging any phase." % GENERATION_PREFIX.strip()
        ),
        "errors": errors,
    }


def _copy_package(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        return
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if not item.is_file() or "__pycache__" in item.parts or item.suffix in {".pyc", ".pyo"}:
            continue
        target = destination / item.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def _seat_root(workspace: Path, host: str) -> Path | None:
    candidates = [host]
    if not host.startswith("ai_"):
        candidates.insert(0, f"ai_{host}")
    for name in candidates:
        target = workspace / name
        if target.is_dir():
            return target
    return None


def _install_targets(workspace: Path, host: str) -> list[Path]:
    roots = [workspace]
    seat = _seat_root(workspace, host)
    if seat is not None and seat not in roots:
        roots.append(seat)
    return [root / surface / "skills" / "fames" for root in roots for surface in SURFACES]


def install(workspace: Path, host: str, source: Path = PACKAGE_ROOT) -> dict:
    workspace = workspace.resolve()
    source = source.resolve()
    source_check = verify_package(source)
    if not source_check["ok"]:
        return {"ok": False, "host": host, "errors": source_check["errors"]}
    canonical = workspace / "_skill" / "fleet-skills" / "fames"
    _copy_package(source, canonical)
    targets = _install_targets(workspace, host)
    for target in targets:
        _copy_package(canonical, target)
    checks = [verify_package(target) for target in targets]
    errors = [error for check in checks for error in check.get("errors", [])]
    receipt = {
        "schema": 1,
        "host": host,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "package_sha": source_check["package_sha"],
        "version": source_check["version"],
        "targets": [str(target) for target in targets],
        "verified": not errors,
    }
    _write_json_atomic(workspace / "_registry" / "fames-fleet-receipts" / f"{host}.json", receipt)
    return {"ok": not errors, "receipt": receipt, "errors": errors}


def verify_host(workspace: Path, host: str) -> dict:
    workspace = workspace.resolve()
    canonical = verify_package(workspace / "_skill" / "fleet-skills" / "fames")
    checks = []
    errors = list(canonical.get("errors", []))
    for target in _install_targets(workspace, host):
        check = verify_package(target)
        checks.append(check)
        if not check["ok"]:
            errors.extend(f"{target}: {error}" for error in check["errors"])
        elif check.get("package_sha") != canonical.get("package_sha"):
            errors.append(f"installed generation mismatch: {target}")
    return {
        "ok": canonical.get("ok", False) and not errors and bool(checks),
        "host": host,
        "package_sha": canonical.get("package_sha"),
        "surface_count": len(checks),
        "checks": checks,
        "errors": errors,
    }


def verify_fleet(workspace: Path, hosts: list[str]) -> dict:
    workspace = workspace.resolve()
    repo = workspace / "_skill" / "ai_fleet_skills"
    canonical = verify_package(workspace / "_skill" / "fleet-skills" / "fames")
    expected = canonical.get("package_sha")
    errors = list(canonical.get("errors", []))
    rows = []
    if not (repo / ".git").is_dir():
        errors.append(f"carrier repo missing: {repo}")
    else:
        fetch = subprocess.run(
            ["git", "fetch", "origin", "main"], cwd=repo, capture_output=True, text=True
        )
        if fetch.returncode != 0:
            errors.append("carrier fetch failed")
    for host in hosts:
        manifest_path = repo / "contributors" / host / "manifest.json"
        try:
            manifest = _read_json(manifest_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{host} manifest unreadable: {exc}")
            rows.append({"host": host, "ok": False})
            continue
        skill = next((row for row in manifest.get("skills", []) if row.get("name") == "fames"), None)
        if not skill:
            errors.append(f"{host} FAMES receipt missing")
            rows.append({"host": host, "ok": False, "manifest_sha": manifest.get("manifest_sha")})
            continue
        package_sha = skill.get("package_sha")
        package = verify_package(repo / "contributors" / host / "skills" / "fames")
        row_ok = package.get("ok") and package_sha == expected == package.get("package_sha")
        if not row_ok:
            errors.append(f"{host} FAMES generation mismatch")
        rows.append(
            {
                "host": host,
                "ok": bool(row_ok),
                "manifest_sha": manifest.get("manifest_sha"),
                "package_sha": package_sha,
            }
        )
    return {
        "ok": canonical.get("ok", False) and not errors and len(rows) == len(hosts),
        "expected_package_sha": expected,
        "hosts": rows,
        "errors": errors,
    }


def _emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("PASS" if payload.get("ok") else "FAIL", payload)
    return 0 if payload.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build-bundle", "verify-package", "parity", "status", "install", "verify-host", "verify-fleet"):
        command = sub.add_parser(name)
        command.add_argument("--workspace", type=Path, default=Path.cwd())
        command.add_argument("--json", action="store_true")
        if name in {"verify-package", "parity", "status"}:
            command.add_argument("--skill-dir", type=Path, default=PACKAGE_ROOT)
        if name == "build-bundle":
            command.add_argument("--protocol-git-ref")
        if name in {"install", "verify-host"}:
            command.add_argument("--host", required=True)
        if name == "install":
            command.add_argument("--source", type=Path, default=PACKAGE_ROOT)
        if name == "verify-fleet":
            command.add_argument("--hosts", nargs="+", required=True)
    args = parser.parse_args()
    if args.command == "build-bundle":
        return _emit(
            build_bundle(args.workspace, protocol_git_ref=args.protocol_git_ref),
            args.json,
        )
    if args.command == "verify-package":
        return _emit(verify_package(args.skill_dir), args.json)
    if args.command == "parity":
        return _emit(parity(args.workspace, args.skill_dir), args.json)
    if args.command == "status":
        return _emit(status(args.workspace, args.skill_dir), args.json)
    if args.command == "install":
        return _emit(install(args.workspace, args.host, args.source), args.json)
    if args.command == "verify-host":
        return _emit(verify_host(args.workspace, args.host), args.json)
    return _emit(verify_fleet(args.workspace, args.hosts), args.json)


if __name__ == "__main__":
    sys.exit(main())
