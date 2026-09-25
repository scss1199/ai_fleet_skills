#!/usr/bin/env python3
"""Apply a verified canonical FAMES update; never claim live-session activation."""
from __future__ import annotations
import argparse
import contextlib
import datetime
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(workspace):
    workspace = Path(workspace)
    engines = workspace / "_skill/engines"
    package = workspace / "_skill/fleet-skills/fames"
    verifier = load("fames_apply_verifier", package / "scripts/fames_fleet.py")
    checked = verifier.verify_package(package)
    if checked.get("ok") is not True:
        return {"ok": False, "state": "UNKNOWN", "reason": "package_verification_failed"}
    phase_proof = ensure_conformance(workspace)
    if phase_proof.get("ok") is not True:
        return {"ok": False, "state": "UNKNOWN", "reason": "local_phase_conformance_unavailable", "phase_proof": phase_proof}
    # Capture mechanical output locally; never inject the fleet inventory into context.
    with contextlib.redirect_stdout(io.StringIO()):
        skills = load("fames_apply_skills", engines / "fleet-skill-sync.py")
        if Path(skills.HUB).resolve() != workspace.resolve():
            return {"ok": False, "state": "UNKNOWN", "reason": "configured_workspace_mismatch"}
        # Use the shared discovery inventory, but the preservation-aware package
        # installer. Generic skill sync can remove physical duplicate directories.
        roots = [Path(root) for root in skills._named_deploy_roots()]
        targets = list(dict.fromkeys(root.joinpath(*surface["path"], "fames")
                       for root in roots for surface in skills.AGENT_SURFACES))
        if not targets:
            return {"ok": False, "state": "UNKNOWN", "reason": "no_destination_evidence"}
        failures = []
        for target in targets:
            try:
                target.resolve().relative_to(workspace.resolve())
                verifier._copy_package(package, target)
            except (OSError, ValueError):
                failures.append(str(target))
                continue
            readback = verifier.verify_package(target)
            if readback.get("ok") is not True or readback.get("package_sha") != checked.get("package_sha"):
                failures.append(str(target))
        if failures:
            return {"ok": False, "state": "UNKNOWN", "reason": "destination_package_mismatch", "failed_targets": failures}
        # Skill selection checks canonical body hashes; installation must refresh
        # the local index before the next task can resolve the new generation.
        skills.cmd_registry()
        hooks = load("fames_apply_hooks", engines / "sync-cursor-hooks.py")
        if Path(hooks.COMMON).resolve() != workspace.resolve():
            return {"ok": False, "state": "UNKNOWN", "reason": "configured_hook_workspace_mismatch"}
        if hooks.main(["--fames-only"]) != 0:
            return {"ok": False, "state": "UNKNOWN", "reason": "hook_readback_failed"}
        managed = refresh_existing_managed(workspace)
        if managed.get("ok") is not True:
            return {"ok": False, "state": "UNKNOWN", "reason": "existing_managed_hook_refresh_failed", "managed": managed}
    hook_receipt = json.loads((workspace / "_registry/cursor-hooks-sync.json").read_text(encoding="utf-8"))
    # Package may have changed during deployment. Never seal mixed revisions.
    final = verifier.verify_package(package)
    stable = final.get("ok") is True and final.get("package_sha") == checked.get("package_sha")
    ok = stable and hook_receipt.get("configuration_read_back") is True
    receipt = {
        "schema": 1, "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ok": ok, "state": "PASS" if ok else "UNKNOWN", "scope": "local_package_and_hook_configuration",
        "package_sha": checked.get("package_sha"), "version": checked.get("version"),
        "deployed_roots": len(roots), "hook_receipt": str(workspace / "_registry/cursor-hooks-sync.json"),
        "verified_destinations": len(targets),
        "runtime_activation": "UNKNOWN_UNTIL_ACTUAL_LIFECYCLE_RECEIPT",
        "unsupported_surfaces_and_cwds": "UNKNOWN", "model_api_calls": 0,
        "new_resident_processes": 0, "restarts": 0,
        "phase_conformance": phase_proof,
        "managed_hook_refresh": managed,
    }
    return receipt


def refresh_existing_managed(workspace):
    """Update pins only for an already installed user FAMES hook; no new scope."""
    settings = Path.home() / '.claude/settings.json'
    if not settings.is_file():
        return {"ok": True, "state": "NOT_INSTALLED", "native_adoption": "UNKNOWN"}
    try:
        config = json.loads(settings.read_text(encoding='utf-8-sig'))
        installed = any(str(arg).replace('\\', '/').lower().endswith('/hooks/fames_managed_gate.py')
                        for entries in (config.get('hooks') or {}).values() for entry in entries
                        for handler in entry.get('hooks', []) for arg in handler.get('args', []))
        if not installed:
            return {"ok": True, "state": "NOT_INSTALLED", "native_adoption": "UNKNOWN"}
        output = workspace / '_registry/fames-managed-refresh' / uuid.uuid4().hex
        command = [sys.executable, '-B', str(workspace/'_harness/runtime/install_fames_enforcement.py'),
                   '--apply', '--scope', 'user', '--output', str(output)]
        run = subprocess.run(command, capture_output=True, timeout=60,
                             creationflags=0x08000000 if os.name == 'nt' else 0)
        receipt = json.loads((output/'installation-user.json').read_text(encoding='utf-8'))
        ok = run.returncode == 0 and receipt.get('files_readback_equal') is True and receipt.get('policy_readback_equal') is True
        return {"ok": ok, "state": "PASS" if ok else "UNKNOWN", "receipt": str(output/'installation-user.json'),
                "native_adoption": "UNKNOWN"}
    except Exception as exc:
        return {"ok": False, "state": "UNKNOWN", "reason": type(exc).__name__}


def ensure_conformance(workspace):
    """Recheck locally only when a bound dependency changed; no remote proof reuse."""
    root = workspace / "_lean/fames"
    path = workspace / "_registry/fames-phase-conformance.json"
    try:
        phases = load("fames_apply_phase_contract", root / "phase_contract.py")
        gate = load("fames_apply_lean_gate", root / "lean_gate.py")
        if gate.checker_now() is None:
            if os.name != "nt":
                return {"ok": False, "state": "UNKNOWN", "reason": "no_supported_lean_bootstrap_adapter"}
            # Existing managed installer verifies the official release digest,
            # retains downloads, and changes neither PATH nor environment.
            installer = root.parent / "install_lean.py"
            installed = subprocess.run([sys.executable, "-B", str(installer), "--version", "v4.34.0"],
                capture_output=True, timeout=600, creationflags=0x08000000)
            if installed.returncode != 0 or gate.checker_now() is None:
                return {"ok": False, "state": "UNKNOWN", "reason": "lean_bootstrap_incomplete"}
        try:
            phases._conformance(path)
            phase_current = True
        except (OSError, ValueError, KeyError, TypeError):
            phase_current = False
        if not phase_current:
            target = workspace / "_registry/fames-phase-history" / (uuid.uuid4().hex + ".json")
            target.parent.mkdir(parents=True, exist_ok=True)
            command = [sys.executable, "-B", str(root / "phase_conformance.py"), "--producer",
                       str(workspace / "_harness/runtime/fames_phase_runtime.py"), "--out", str(target)]
            for name in ("fames_session_harness.py", "fames_enforcement.py", "local_skill_router.py",
                         "jev_skill_advisor.py", "jev_phase_advisor.py"):
                command.extend(["--bind", str(workspace / "_harness/runtime" / name)])
            result = subprocess.run(command, capture_output=True, timeout=600,
                                    creationflags=0x08000000 if os.name == "nt" else 0)
            if result.returncode != 0:
                return {"ok": False, "state": "UNKNOWN", "reason": "phase_proof_failed", "receipt": str(target)}
            phases._conformance(target)
            data = target.read_bytes()
            staged = path.with_suffix('.tmp')
            staged.write_bytes(data)
            staged.replace(path)
        if not gate.binding_status().get("all_bound"):
            result = subprocess.run([sys.executable, "-B", str(root / "conformance.py")],
                capture_output=True, timeout=600, creationflags=0x08000000 if os.name == "nt" else 0)
            if result.returncode != 0 or not gate.binding_status().get("all_bound"):
                return {"ok": False, "state": "UNKNOWN", "reason": "base_conformance_failed"}
        phases._conformance(path)
        recovery = load('fames_apply_recovery_contract', root / 'turn_recovery_contract.py')
        recovery_path = workspace / '_registry/fames-turn-recovery-conformance.json'
        if not recovery.conformance_status(recovery_path).get('ok'):
            target = workspace / '_registry/fames-phase-history' / ('recovery-' + uuid.uuid4().hex + '.json')
            target.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run([sys.executable, '-B', str(root / 'turn_recovery_contract.py'), '--out', str(target)],
                capture_output=True, timeout=600, creationflags=0x08000000 if os.name == 'nt' else 0)
            if result.returncode != 0 or not recovery.conformance_status(target).get('ok'):
                return {'ok': False, 'state': 'UNKNOWN', 'reason': 'native_recovery_conformance_failed'}
            if recovery_path.is_file():
                shutil.copy2(recovery_path, target.with_name(target.stem + '-previous.json'))
            shutil.copy2(target, recovery_path)
        return {"ok": True, "state": "PASS", "receipt": str(path), "reused_phase_proof": phase_current,
                'native_recovery_conformance': str(recovery_path),
                "native_adoption": "UNKNOWN"}
    except Exception as exc:
        return {"ok": False, "state": "UNKNOWN", "reason": type(exc).__name__}


def apply(workspace=WORKSPACE):
    workspace = Path(workspace).resolve()
    try:
        receipt = _apply(workspace)
    except Exception as exc:
        receipt = {"ok": False, "state": "UNKNOWN", "reason": type(exc).__name__}
    receipt["generated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        manifest = json.loads((workspace / "_skill/fleet-skills/fames/bundle-manifest.json").read_text(encoding="utf-8"))
        receipt["attempted_package_sha"] = manifest.get("package_sha")
    except (OSError, ValueError):
        receipt["attempted_package_sha"] = None
    receipt.setdefault("runtime_activation", "UNKNOWN_UNTIL_ACTUAL_LIFECYCLE_RECEIPT")
    receipt.setdefault("scope", "local_package_and_hook_configuration")
    path = workspace / "_registry/fames-immediate-apply.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    readback = json.loads(path.read_text(encoding="utf-8"))
    if readback != receipt:
        raise RuntimeError("receipt_readback_failed")
    return {**receipt, "receipt_path": str(path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.parse_args(argv)
    try:
        result = apply()
    except Exception as exc:
        result = {"ok": False, "state": "UNKNOWN", "reason": type(exc).__name__}
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
