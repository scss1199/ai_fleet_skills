#!/usr/bin/env python3
"""Build, install, and verify the portable content-addressed FAMES bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SURFACE_REGISTRY = "_registry/agent-surfaces.json"
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
CASES_SOURCE = "_registry/fames-cases.json"
CASES_TARGET = "references/cases.json"
PRODUCTION_PROFILE_SOURCE = "_registry/fames-production-web-delivery.json"
PRODUCTION_PROFILE_TARGET = "references/production-web-delivery.json"
HARDWARE_PROFILE_SOURCE = "_registry/fames-hardware-compute.json"
HARDWARE_PROFILE_TARGET = "references/hardware-compute.json"
SELF_EVIDENCE_DIR = "_registry/fames-evidence/self"
RESIDUAL_DIMENSIONS = (
    "R_CONTRACT",
    "R_SEMANTICS",
    "R_FLEET",
    "R_CAPABILITY",
    "R_HYGIENE",
    "R_FRESHNESS",
)
CASE_KINDS = {
    "path_exists",
    "file_size_max",
    "json_probe",
    "validator_probe",
    "parity",
    "newest_age_max",
    "claim_backed",
    "forbidden_text",
}
FAIL_MODES = {"closed", "degraded"}
MANIFEST_NAME = "bundle-manifest.json"
GENERATION_PREFIX = "FAMES-GEN: "
DEFAULT_AUTHORITY = "https://raw.githubusercontent.com/scss1199/ai_fleet_skills/main/contributors/darkhero"
RIDER_REGISTRY = "_registry/hosts.json"
RIDER_ENGINE = "_skill/engines/register-rider.py"
CONVERGE_RIDER_ID = "fames-converge"
CONVERGE_RIDER_HOST = "HubClock"
CONVERGE_CADENCE = "15m"
CONVERGE_PRIORITY = 90
CONVERGE_DESC = "FAMES self-convergence: verified GitHub generation pull + heartbeat"
CONVERGE_DIR = "_registry/fames-converge"
CAPABILITY_DIR = "_registry/fames-capabilities"
FLEET_HOSTS = ("darkhero", "scar3", "altos")
PROMOTION_NON_REGRESSION_CASES = (
    "C-BOUNDARY-BASE",
    "C-BOUNDARY-SEMANTIC-DRIFT",
    "C-BOUNDARY-DISTRIBUTION-DRIFT",
    "C-RUN-BOUNDARY-MISSING",
)
LOCAL_CAPABILITY_CASES = {
    "contract-core": ("C-RUN-BASE", "C-RUN-HASH", "C-PARITY"),
    "cognitive-boundary": (
        "C-BOUNDARY-BASE",
        "C-BOUNDARY-POPULATION",
        "C-BOUNDARY-SEMANTIC-DRIFT",
        "C-BOUNDARY-PROFILE-INFERENCE",
        "C-BOUNDARY-NONMEASURED",
        "C-BOUNDARY-NEGATIVE-CONTROL",
        "C-BOUNDARY-HIGH-RISK-COMPREHENSION",
        "C-BOUNDARY-PROMOTION-GATE",
        "C-BOUNDARY-EXPIRED",
        "C-BOUNDARY-METRIC-SPOOF",
        "C-BOUNDARY-OUTSIDE-CONTRADICTION",
        "C-BOUNDARY-MONITOR-REGRESSION",
        "C-BOUNDARY-DISTRIBUTION-DRIFT",
        "C-BOUNDARY-FORBIDDEN-INFERENCE",
        "C-BOUNDARY-PROFILE-OUTLIVES-TASK",
        "C-BOUNDARY-CURRENT-RETRACTED",
        "C-RUN-BOUNDARY-MISSING",
        "C-RUN-BOUNDARY-RESULT-MISMATCH",
        "C-INTERACTION-BOUNDARY-MISSING",
        "C-INTERACTION-BOUNDARY-MISMATCH",
        "C-INGEST-PROMOTION-BASE",
        "C-INGEST-PROMOTION-CANDIDATE",
        "C-INGEST-PROMOTION-CLAIM-SEMANTICS",
        "C-INGEST-PROMOTION-LANDING-BYTES",
        "C-INGEST-PROMOTION-SOURCE-BINDING",
        "C-INGEST-PROMOTION-TRIAL-HASH",
        "C-INGEST-PROMOTION-UNRELATED-FILE",
        "C-INGEST-PROMOTION-REPLAY-CANDIDATE",
        "C-INGEST-PROMOTION-REVIEW",
        "C-INGEST-PROMOTION-SELF-REVIEW",
        "C-INGEST-PROMOTION-REVIEWER-MISMATCH",
        "C-INGEST-PROMOTION-NONREG-VALIDATOR",
        "C-INGEST-PROMOTION-NONREG-OUTPUT",
        "C-INGEST-PROMOTION-REVIEW-STALE",
    ),
    "delivery-integrity": (
        "C-INTERACTION-BASE",
        "C-DELIVERY-SCOPE-INFLATION",
        "C-DELIVERY-HIDDEN-UNKNOWN",
        "C-DELIVERY-NUMERIC-PROXY",
        "C-DELIVERY-FIX-NO-BEFORE",
        "C-DELIVERY-BUILD-AS-DEPLOY",
        "C-DELIVERY-PASS-WITH-DEFECT",
        "C-REPAIR-NO-NEXT-TEST",
        "C-REPAIR-BUDGET",
    ),
    "capability-convergence": (
        "C-CAPABILITY-SYNC-BASE",
        "C-CAPABILITY-SYNC-MISSING-HOST",
        "C-CAPABILITY-SYNC-PACKAGE-DRIFT",
        "C-CAPABILITY-SYNC-VALIDATOR-DRIFT",
        "C-CAPABILITY-SYNC-MISSING-CAPABILITY",
        "C-CAPABILITY-SYNC-NEGATIVE-CONTROL",
        "C-CAPABILITY-SYNC-NO-CALLER",
        "C-CAPABILITY-SYNC-RUNNER",
        "C-CAPABILITY-SYNC-STALE",
    ),
    "platform-neutral-execution": (
        "C-PLATFORM-NEUTRAL-POLICY",
        "C-PLATFORM-NEUTRAL-REJECTS-HOST-NAME",
    ),
    "harness-contract-enforcement": (
        "C-HARNESS-BASE",
        "C-HARNESS-MISSING-SURFACE",
        "C-HARNESS-NAME-POLICY",
        "C-HARNESS-UNREGISTERED-PASS",
    ),
    "background-execution-enforcement": (
        "C-BACKGROUND-BASE",
        "C-BACKGROUND-CHILD-FLAGS",
        "C-BACKGROUND-DETACHED-ONLY",
        "C-BACKGROUND-PROMPT",
        "C-BACKGROUND-READBACK",
    ),
    "hardware-compute-scheduling": (
        "C-COMPUTE-BASE",
        "C-COMPUTE-BACKGROUND-P-CORE",
        "C-COMPUTE-URGENCY-EVIDENCE",
        "C-COMPUTE-AUTHORITY",
        "C-COMPUTE-OVER-CAP",
        "C-COMPUTE-WORKERS",
        "C-COMPUTE-EXCLUSIVE-AUTH",
        "C-COMPUTE-READBACK",
    ),
}
TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".ps1",
    ".txt",
    ".yaml",
    ".yml",
}
PHASE_STATES = {"PASS", "NOT_APPLICABLE", "UNKNOWN", "FAIL"}
TASK_PROFILES = {
    "read-only explanation": "R0",
    "diagnosis": "R0",
    "one-shot deterministic edit": "R1",
    "multi-file implementation": "R1",
    "live-device mutation": "R2",
    "deployment/external write": "R2",
    "recurring autonomous control": "R2",
    "safety-critical operation": "R3",
    "cross-cycle optimization": "R1",
    "distributed/fleet promotion": "R2",
}
RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
RB_RISK_CATEGORIES = {
    "R0": ["none"],
    "R1": ["reversible_local_edit"],
    "R2": ["authority_sensitive"],
    "R3": ["destructive", "authority_sensitive"],
}
RESIDUAL_KEYS = (
    "R_outcome", "R_safety", "R_evidence", "R_complexity",
    "R_portability", "R_authority", "R_operability",
)


def _silent_cli_env(extra: dict | None = None) -> dict:
    """Return a non-interactive environment for background-capable child CLIs."""
    env = os.environ.copy()
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "SSH_ASKPASS": "",
        }
    )
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    return env


def _hidden_subprocess_kwargs() -> dict:
    """Build Windows flags that hide the whole console-capable child launch."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        "startupinfo": startupinfo,
    }


def _run_hidden(args, **kwargs):
    """Run one child with no shell, no prompt, and no visible Windows console."""
    if kwargs.pop("shell", False):
        raise ValueError("background child execution forbids shell=True")
    supplied_env = kwargs.pop("env", None)
    kwargs["env"] = _silent_cli_env(supplied_env)
    for key, value in _hidden_subprocess_kwargs().items():
        if key == "creationflags":
            kwargs[key] = int(kwargs.get(key, 0)) | int(value)
        else:
            kwargs.setdefault(key, value)
    return subprocess.run(args, shell=False, **kwargs)


GOAL_FIELDS = (
    "outcome", "verification", "constraints", "authority_scope", "non_goals",
    "irreversible_boundary", "success_horizon", "task_profile",
    "required_evidence_classes",
)
EVIDENCE_FIELDS = (
    "goal_identity", "result_identity", "timestamp", "freshness_seconds", "source",
    "method", "authority", "state_before", "state_after", "exit_status",
    "error_category", "diagnostic",
)
COMPLEXITY_FIELDS = (
    "new_files", "new_dependencies", "new_resident_processes",
    "new_abstractions", "duplicated_authorities",
)
# external_learning lane: an ingest record is outside material proposing a canon change.
INGEST_FIELDS = (
    "source_uri", "source_kind", "source_channel", "scope", "acquired_at", "acquisition_route", "quota_cost",
    "content_identity", "trust_class_map", "claims", "verdict", "promoted",
)
INGEST_CLAIM_FIELDS = ("id", "claim", "trust_class", "verdict", "why")
TRUST_CLASSES = {"measured", "modelled", "asserted"}
INGEST_VERDICTS = {"adopt", "adapt", "reject", "already_covered", "UNKNOWN"}
INGEST_SOURCE_KINDS = {"skill", "academic", "web", "line", "other"}
INGEST_SOURCE_CHANNELS = {"skill_registry", "line_ingest", "background_web_ingest", "manual"}
INGEST_FORBIDDEN_KEYS = (
    "token", "cookie", "credential", "api_key", "apikey", "password",
    "secret", "authorization", "session_id",
)


def _sha256(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _stable_sha(payload: object) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _version_tuple(value: object) -> tuple[int, ...] | None:
    """Ordered generation number, or None when the version cannot be ordered."""
    parts = str(value or "").strip().split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _package_generation(package_dir: Path) -> dict:
    """Generation a package declares about itself, independent of its health.

    Deliberately reads the manifest instead of calling verify_package: the package a
    follow is about to overwrite must be compared even when it fails verification,
    because a broken canonical is a reason to stop, not a licence to regress.
    """
    try:
        payload = json.loads((package_dir / MANIFEST_NAME).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {"version": payload.get("version"), "package_sha": payload.get("package_sha")}


def _canonical_identity(workspace: Path) -> dict:
    return _package_generation(workspace.resolve() / "_skill" / "fleet-skills" / "fames")


def _regression_guard(canonical: dict, remote_skill: dict, allow_rollback: bool = False) -> list[str]:
    """Canon never moves backwards. A follow may only activate a newer generation.

    On a hub-shared tree every install target resolves through the seat surfaces into
    ONE canonical package, so a follow run for ANY seat rewrites canon. Three times, at
    2026-08-14T19:30:06Z, 2026-08-15T02:00:06Z and 2026-08-15T02:07Z, a
    `follow --host ai_scar3` on the authority machine activated the published 1.5.0
    package over canonical 1.6.0 and silently deleted a shipped lane. The comparison
    below is the fix, and it needs no machine identity: an older or unorderable remote
    generation is refused, and an equal version carrying a different package_sha is
    UNKNOWN, which fails closed. An absent canonical package is a genuine bootstrap and
    is allowed.
    """
    if allow_rollback or not canonical:
        return []
    local_version = _version_tuple(canonical.get("version"))
    if local_version is None:
        return []
    remote_version = _version_tuple(remote_skill.get("version"))
    if remote_version is None:
        return [
            "remote generation is unversioned; refusing to overwrite canonical "
            f"{canonical.get('version')} on an unorderable identity (--allow-rollback forces)"
        ]
    if remote_version < local_version:
        return [
            f"refusing to regress canonical {canonical.get('version')} to "
            f"{remote_skill.get('version')} (--allow-rollback forces)"
        ]
    if remote_version == local_version and remote_skill.get("package_sha") != canonical.get("package_sha"):
        return [
            f"same version {canonical.get('version')} with a different package_sha is UNKNOWN "
            "drift; the authority must bump the generation (--allow-rollback forces)"
        ]
    return []


def semantic_goal_hash(goal: dict) -> str:
    """Provider-neutral identity over only the canonical FP goal fields."""
    return _stable_sha({key: goal.get(key) for key in GOAL_FIELDS})


def _parse_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def validate_run(run: dict) -> dict:
    """Validate one FAMES phase ledger without executing or expanding authority."""
    errors: list[str] = []
    goal = run.get("goal") if isinstance(run.get("goal"), dict) else {}
    missing_goal = [field for field in GOAL_FIELDS if field not in goal]
    if missing_goal:
        errors.append("goal fields missing: " + ", ".join(missing_goal))
    expected_hash = semantic_goal_hash(goal)
    if goal.get("semantic_goal_hash") != expected_hash:
        errors.append("semantic goal hash mismatch")
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    if result.get("goal_hash") != expected_hash:
        errors.append("result goal hash mismatch")

    profile = goal.get("task_profile")
    risk = run.get("risk_class")
    minimum_risk = TASK_PROFILES.get(profile)
    if minimum_risk is None:
        errors.append("unknown task profile")
    if risk not in RISK_ORDER:
        errors.append("unknown risk class")
    elif minimum_risk and RISK_ORDER[risk] < RISK_ORDER[minimum_risk]:
        errors.append(f"risk class {risk} is below task profile minimum {minimum_risk}")

    ledger = run.get("phase_ledger") if isinstance(run.get("phase_ledger"), list) else []
    if [row.get("phase") for row in ledger if isinstance(row, dict)] != EXECUTION_ORDER:
        errors.append("phase ledger execution order mismatch")
    phase_map = {row.get("phase"): row for row in ledger if isinstance(row, dict)}
    for phase in EXECUTION_ORDER:
        row = phase_map.get(phase, {})
        state = row.get("state")
        if state not in PHASE_STATES:
            errors.append(f"{phase}: invalid or missing state")
        elif state in {"UNKNOWN", "FAIL"}:
            errors.append(f"{phase}: {state} fails closed")
        elif state == "NOT_APPLICABLE" and not (
            row.get("activation_predicate") is False and row.get("why")
        ):
            errors.append(f"{phase}: NOT_APPLICABLE requires a false predicate and reason")

    residual = phase_map.get("SCF", {}).get("residual")
    if not isinstance(residual, dict) or any(key not in residual for key in RESIDUAL_KEYS):
        errors.append("SCF residual vector incomplete")
        residual = {}
    for hard_key in ("R_safety", "R_evidence", "R_authority"):
        if residual.get(hard_key) not in (0, 0.0):
            errors.append(f"{hard_key} is not converged")
    cross_cycle = goal.get("success_horizon") == "cross-cycle" or profile == "cross-cycle optimization"
    comparable_residual = any(residual.get(key) not in (None, 0, 0.0) for key in RESIDUAL_KEYS)
    aex = phase_map.get("AEX", {})
    aex_required = cross_cycle and comparable_residual
    if aex_required:
        if aex.get("state") != "PASS" or aex.get("activation_predicate") is not True:
            errors.append("AEX must activate for a verified comparable cross-cycle residual")
        elif aex.get("target_residual") not in RESIDUAL_KEYS:
            errors.append("AEX must name the residual it targets")
    elif aex.get("state") != "NOT_APPLICABLE" or aex.get("activation_predicate") is not False:
        errors.append("AEX must not activate without a cross-cycle residual")

    complexity = run.get("complexity") if isinstance(run.get("complexity"), dict) else {}
    budget = complexity.get("budget") if isinstance(complexity.get("budget"), dict) else {}
    actual = complexity.get("actual") if isinstance(complexity.get("actual"), dict) else {}
    for field in COMPLEXITY_FIELDS:
        if field not in budget or field not in actual:
            errors.append(f"complexity field missing: {field}")
            continue
        if actual[field] > budget[field] and not complexity.get("justification_evidence"):
            errors.append(f"complexity budget exceeded: {field}")

    architecture = run.get("architecture") if isinstance(run.get("architecture"), dict) else {}
    for component in architecture.get("components") or []:
        if not component.get("caller") or not component.get("contract_role"):
            errors.append(f"component lacks caller or contract role: {component.get('name', 'unknown')}")
        if component.get("layer") == "core" and component.get("provider_specific"):
            errors.append(f"provider-specific component leaked into core: {component.get('name', 'unknown')}")
    canonical_writers: dict[str, list[str]] = {}
    for writer in architecture.get("writers") or []:
        if writer.get("enabled") and writer.get("canonical"):
            canonical_writers.setdefault(str(writer.get("target")), []).append(str(writer.get("name")))
    for target, writers in canonical_writers.items():
        if len(writers) != 1:
            errors.append(f"duplicate canonical writers for {target}: {', '.join(writers)}")

    validated_at = _parse_time(run.get("validated_at")) or datetime.now(timezone.utc)
    evidence_rows = run.get("evidence") if isinstance(run.get("evidence"), list) else []
    if not evidence_rows:
        errors.append("evidence is missing")
    for index, evidence in enumerate(evidence_rows):
        missing = [field for field in EVIDENCE_FIELDS if field not in evidence]
        if missing:
            errors.append(f"evidence[{index}] fields missing: {', '.join(missing)}")
            continue
        if evidence.get("goal_identity") != expected_hash:
            errors.append(f"evidence[{index}] goal identity mismatch")
        if evidence.get("result_identity") != result.get("identity"):
            errors.append(f"evidence[{index}] result identity mismatch")
        if evidence.get("authority") != goal.get("authority_scope"):
            errors.append(f"evidence[{index}] authority mismatch")
        timestamp = _parse_time(evidence.get("timestamp"))
        freshness = evidence.get("freshness_seconds")
        if timestamp is None or not isinstance(freshness, (int, float)):
            errors.append(f"evidence[{index}] freshness is unverifiable")
        elif (validated_at - timestamp).total_seconds() > freshness:
            errors.append(f"evidence[{index}] is stale")
        if evidence.get("exit_status") != 0:
            errors.append(f"evidence[{index}] verification exit status failed")
        diagnostic = str(evidence.get("diagnostic") or "").lower()
        if any(marker in diagnostic for marker in (
            "token=", "cookie=", "authorization:", "scram", "password=", "https://user:"
        )):
            errors.append(f"evidence[{index}] diagnostic may contain secret material")

    if risk in {"R2", "R3"}:
        transaction = run.get("transaction") if isinstance(run.get("transaction"), dict) else {}
        required = (
            "before_state", "rollback", "intended_mutation_identity", "read_back",
            "authority_verified", "journal_state", "recovery",
        )
        missing = [field for field in required if field not in transaction]
        if missing:
            errors.append("transaction fields missing: " + ", ".join(missing))
        if transaction.get("authority_verified") is not True:
            errors.append("transaction authority is not verified")
        if transaction.get("journal_state") not in {"COMMITTED", "RECOVERED"}:
            errors.append("interrupted transaction is not recovered")
        if risk == "R3" and transaction.get("recovery_drill") != "PASS":
            errors.append("R3 recovery drill is not passing")

    if profile == "distributed/fleet promotion":
        promotion = run.get("promotion") if isinstance(run.get("promotion"), dict) else {}
        required = (
            "actor", "authority", "generation", "migration_path", "rollback_path",
            "compatibility_proof",
        )
        missing = [field for field in required if not promotion.get(field)]
        if missing:
            errors.append("promotion fields missing: " + ", ".join(missing))
        if promotion.get("actor") != promotion.get("authority"):
            errors.append("follower cannot promote the canonical generation")

    errors.extend(
        _validate_boundary_gate(
            run,
            context="validate_run",
            force_required=True,
            expected_caller="validate_run",
            expected_goal_identity=expected_hash,
            expected_result_identity=result.get("identity"),
            expected_authority_scope=goal.get("authority_scope"),
            expected_risk_categories=RB_RISK_CATEGORIES.get(str(risk)),
        )
    )

    return {
        "ok": not errors,
        "state": "PASS" if not errors else "FAIL",
        "semantic_goal_hash": expected_hash,
        "risk_class": risk,
        "task_profile": profile,
        "aex_required": aex_required,
        "errors": errors,
    }


def _is_counted(value: object) -> bool:
    """A number, flag, or absence cannot carry material; MTM cost fields are counts."""
    return value is None or isinstance(value, bool) or isinstance(value, (int, float))


def _forbidden_key_paths(node: object, trail: str = "") -> list[str]:
    """Report only the JSON path of a forbidden-material key, never its value."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{trail}/{key}" if trail else str(key)
            safe_identity = (
                str(key).lower().endswith(("_identity", "_identity_sha"))
                and isinstance(value, str)
                and SHA256_RE.fullmatch(value.lower()) is not None
            )
            if any(marker in str(key).lower() for marker in INGEST_FORBIDDEN_KEYS) and not _is_counted(value) and not safe_identity:
                found.append(here)
            found.extend(_forbidden_key_paths(value, here))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_forbidden_key_paths(value, f"{trail}[{index}]"))
    return found


def validate_ingest(record: dict) -> dict:
    """Validate one external_learning ingest record. UNKNOWN fails closed."""
    errors: list[str] = []
    for field in INGEST_FIELDS:
        if field not in record:
            errors.append(f"ingest field missing: {field}")

    if _parse_time(record.get("acquired_at")) is None:
        errors.append("acquired_at is not a parseable timestamp")
    if not str(record.get("source_uri") or "").strip():
        errors.append("source_uri is empty")
    source_kind = record.get("source_kind")
    if source_kind not in INGEST_SOURCE_KINDS:
        errors.append("source_kind is not declared")
    source_channel = record.get("source_channel")
    if source_channel not in INGEST_SOURCE_CHANNELS:
        errors.append("source_channel is not declared")
    scope = record.get("scope")
    if not isinstance(scope, dict):
        errors.append("scope ledger is missing")
    else:
        for field in ("user_scope", "authority_scope", "in_scope"):
            if field not in scope:
                errors.append(f"scope.{field} is missing")
        if scope.get("in_scope") is not True:
            errors.append("ingest is outside the declared scope")
    if not str(record.get("acquisition_route") or "").strip():
        errors.append("acquisition_route is empty: route order is cost order and must be stated")
    quota = record.get("quota_cost")
    if not isinstance(quota, dict) or "metered_calls" not in quota:
        errors.append("quota_cost must declare metered_calls")
    elif not isinstance(quota["metered_calls"], int) or quota["metered_calls"] < 0:
        errors.append("quota_cost.metered_calls must be a non-negative integer")

    identity = record.get("content_identity")
    if not isinstance(identity, dict) or not any(str(value or "").strip() for value in identity.values()):
        errors.append("content_identity is empty: acquisition without identity is UNKNOWN")

    trust_map = record.get("trust_class_map")
    if not isinstance(trust_map, dict) or not trust_map:
        errors.append("trust_class_map is missing")
    else:
        for item, klass in trust_map.items():
            if klass not in TRUST_CLASSES:
                errors.append(f"trust_class_map[{item}] is not a declared trust class")

    claims = record.get("claims")
    adopted = 0
    if not isinstance(claims, list) or not claims:
        errors.append("claims is empty: an ingest with no claim proposes nothing")
        claims = []
    for index, claim in enumerate(claims):
        label = claim.get("id") if isinstance(claim, dict) else index
        if not isinstance(claim, dict):
            errors.append(f"claim {index} is not an object")
            continue
        for field in INGEST_CLAIM_FIELDS:
            if not str(claim.get(field) or "").strip():
                errors.append(f"claim {label}: {field} missing")
        if claim.get("trust_class") not in TRUST_CLASSES:
            errors.append(f"claim {label}: undeclared trust class")
        verdict = claim.get("verdict")
        if verdict not in INGEST_VERDICTS:
            errors.append(f"claim {label}: verdict is not a declared value")
        elif verdict == "UNKNOWN":
            errors.append(f"claim {label}: UNKNOWN fails closed")
        elif verdict in {"adopt", "adapt"}:
            adopted += 1
            trial = claim.get("trial") if isinstance(claim.get("trial"), dict) else {}
            if not str(trial.get("verification") or "").strip():
                errors.append(f"claim {label}: adopted without a Verification written before the trial")
            if not str(trial.get("result") or "").strip():
                errors.append(f"claim {label}: adopted without a trial result")
            if trial.get("evidence_class") != "measured":
                errors.append(
                    f"claim {label}: adopted on non-measured evidence; only measured items are admissible"
                )
            if not str(claim.get("lands_in") or "").strip():
                errors.append(f"claim {label}: adopted without naming the canon file it lands in")

    if source_kind == "academic":
        citation = record.get("academic_citation")
        if not isinstance(citation, dict):
            errors.append("academic source lacks academic_citation")
            citation = {}
        if not str(citation.get("style") or "").strip():
            errors.append("academic citation style is missing")
        in_text = citation.get("in_text")
        references = citation.get("references")
        if not isinstance(in_text, list) or not in_text:
            errors.append("academic source lacks in-text citations")
            in_text = []
        if not isinstance(references, list) or not references:
            errors.append("academic source lacks a reference list")
            references = []
        reference_ids: list[str] = []
        for index, reference in enumerate(references):
            here = f"academic_citation.references[{index}]"
            if not isinstance(reference, dict):
                errors.append(f"{here} is not an object")
                continue
            for field in ("citation_id", "authors", "year", "title", "container", "persistent_id"):
                value = reference.get(field)
                if value is None or value == "" or value == []:
                    errors.append(f"{here}: {field} missing")
            if isinstance(reference.get("citation_id"), str):
                reference_ids.append(reference["citation_id"])
        if len(reference_ids) != len(set(reference_ids)):
            errors.append("academic reference-list citation ids are not unique")
        claim_ids = {
            str(claim.get("id"))
            for claim in claims
            if isinstance(claim, dict) and str(claim.get("id") or "").strip()
        }
        cited_claims: set[str] = set()
        for index, item in enumerate(in_text):
            here = f"academic_citation.in_text[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{here} is not an object")
                continue
            citation_id = item.get("citation_id")
            linked = item.get("claim_ids")
            if citation_id not in reference_ids:
                errors.append(f"{here}: citation_id does not resolve exactly once")
            if not isinstance(linked, list) or not linked:
                errors.append(f"{here}: claim_ids missing")
            else:
                unknown_claims = {str(value) for value in linked} - claim_ids
                if unknown_claims:
                    errors.append(f"{here}: unknown claim ids")
                cited_claims.update(str(value) for value in linked)
            if not str(item.get("locator") or "").strip():
                errors.append(f"{here}: locator missing")
        uncited = claim_ids - cited_claims
        if uncited:
            errors.append("academic claims lack in-text citations")

    if record.get("verdict") not in INGEST_VERDICTS:
        errors.append("record verdict is not a declared value")
    elif record.get("verdict") == "UNKNOWN":
        errors.append("record verdict UNKNOWN fails closed")

    if record.get("promoted") is True:
        promotion = record.get("promotion") if isinstance(record.get("promotion"), dict) else {}
        if promotion.get("actor") != promotion.get("authority"):
            errors.append("only the authority node promotes an external claim into canon")
        for phase in ("FP", "SCF", "SEAL"):
            if promotion.get("phases", {}).get(phase) != "PASS":
                errors.append(f"promotion requires {phase} PASS")
        if adopted == 0:
            errors.append("promoted with no adopted claim")
        source_identity = _stable_sha(record.get("content_identity") or {})
        promoted_claims = [claim for claim in claims if isinstance(claim, dict) and claim.get("verdict") in {"adopt", "adapt"}]
        claim_ids = sorted(str(claim.get("id")) for claim in claims if isinstance(claim, dict))
        claim_semantics = sorted(({
            "id": claim.get("id"),
            "claim": claim.get("claim"),
            "trust_class": claim.get("trust_class"),
            "verdict": claim.get("verdict"),
            "why": claim.get("why"),
            "lands_in": claim.get("lands_in"),
        } for claim in promoted_claims), key=lambda row: str(row.get("id")))
        artifact_rows: list[dict] = []
        for claim in promoted_claims:
            landing = claim.get("landing_artifact")
            errors.extend(_content_ref_errors(landing, f"claim {claim.get('id')}.landing_artifact", replay=True))
            expected_path = (_active_workspace() / str(claim.get("lands_in") or "")).resolve()
            if not isinstance(landing, dict) or Path(str(landing.get("path") or "")).resolve() != expected_path:
                errors.append(f"claim {claim.get('id')}: landing artifact path does not match lands_in")
            artifact_rows.append({
                "id": claim.get("id"),
                "lands_in": claim.get("lands_in"),
                "path": landing.get("path") if isinstance(landing, dict) else None,
                "sha256": landing.get("sha256") if isinstance(landing, dict) else None,
            })
        artifact_identity = _stable_sha(sorted(artifact_rows, key=lambda row: str(row.get("id"))))
        candidate_identity = _stable_sha({
            "source_identity": source_identity,
            "claim_semantics": claim_semantics,
            "artifact_identity": artifact_identity,
        })
        if promotion.get("candidate_identity") != candidate_identity:
            errors.append("promotion candidate identity does not match source, claims, and landing artifacts")
        errors.extend(_validate_boundary_gate(
            promotion,
            context="validate_ingest promotion",
            force_required=True,
            expected_caller="validate_ingest",
            expected_authority_scope=(record.get("scope") or {}).get("authority_scope"),
            expected_source_identity=source_identity,
            expected_claim_ids=claim_ids,
            expected_artifact_identity=artifact_identity,
            expected_candidate_identity=candidate_identity,
        ))
        validator_identity = _sha256(Path(__file__).resolve())
        if promotion.get("validator_identity") != validator_identity:
            errors.append("promotion validator identity does not match the executing validator")
        boundary_input = ((promotion.get("cognitive_boundary_gate") or {}).get("record")
                          if isinstance(promotion.get("cognitive_boundary_gate"), dict) else None)
        replayed_outcome = validate_cognitive_boundary(boundary_input) if isinstance(boundary_input, dict) else {}
        replay_input_identity = _stable_sha(boundary_input or {})
        review_subject_identity = _boundary_review_subject_identity(boundary_input or {})
        replay_output_identity = _stable_sha(replayed_outcome)
        review = promotion.get("independent_review")
        if not isinstance(review, dict) or review.get("accepted") is not True:
            errors.append("promotion lacks accepted independent review")
        else:
            reviewer_identity = review.get("reviewer_identity")
            if not isinstance(reviewer_identity, str) or not reviewer_identity.strip():
                errors.append("promotion independent reviewer identity missing")
            elif reviewer_identity in {promotion.get("actor"), promotion.get("authority")}:
                errors.append("promotion independent reviewer is not separated from promoter authority")
            expected_review = {
                "kind": "independent_review",
                "candidate_identity": candidate_identity,
                "artifact_identity": artifact_identity,
                "builder_identity": promotion.get("actor"),
                "reviewer_identity": reviewer_identity,
                "validator_identity": validator_identity,
                "reproduction_input_identity": review_subject_identity,
                "reproduction_output_identity": replay_output_identity,
                "decision": "ACCEPT",
                "executed_at": review.get("executed_at"),
                "valid_until": review.get("valid_until"),
            }
            errors.extend(_receipt_window_errors(review, "promotion.independent_review"))
            errors.extend(_bound_json_receipt_errors(
                review.get("evidence"), "promotion.independent_review.evidence", expected_review
            ))
        non_regression = promotion.get("non_regression")
        if not isinstance(non_regression, dict) or non_regression.get("passed") is not True:
            errors.append("promotion lacks passing non-regression evidence")
        else:
            actual_non_regression = _promotion_non_regression()
            expected_non_regression = {
                "kind": "non_regression",
                "candidate_identity": candidate_identity,
                "artifact_identity": artifact_identity,
                **actual_non_regression,
                "executed_at": non_regression.get("executed_at"),
                "valid_until": non_regression.get("valid_until"),
            }
            for field, expected in actual_non_regression.items():
                if non_regression.get(field) != expected:
                    errors.append(f"promotion non-regression {field} mismatch")
            if actual_non_regression.get("state") != "PASS" or actual_non_regression.get("exit_status") != 0:
                errors.append("promotion active non-regression replay did not pass")
            errors.extend(_receipt_window_errors(non_regression, "promotion.non_regression"))
            errors.extend(_bound_json_receipt_errors(
                non_regression.get("evidence"), "promotion.non_regression.evidence", expected_non_regression
            ))
        for claim in claims:
            if not isinstance(claim, dict) or claim.get("verdict") not in {"adopt", "adapt"}:
                continue
            trial = claim.get("trial") if isinstance(claim.get("trial"), dict) else {}
            if trial.get("validator_identity") != validator_identity:
                errors.append(f"claim {claim.get('id')}: promoted trial validator identity mismatch")
            replay = trial.get("replay")
            if not isinstance(replay, dict):
                errors.append(f"claim {claim.get('id')}: execution replay receipt missing")
            else:
                expected_replay = {
                    "candidate_identity": candidate_identity,
                    "input_identity": replay_input_identity,
                    "validator_identity": validator_identity,
                    "output_identity": replay_output_identity,
                    "state": "PASS",
                    "exit_status": 0,
                }
                for field, expected in expected_replay.items():
                    if replay.get(field) != expected:
                        errors.append(f"claim {claim.get('id')}: replay {field} mismatch")
                executed_at = _parse_time(replay.get("executed_at"))
                valid_until = _parse_time(replay.get("valid_until"))
                now = datetime.now(timezone.utc)
                if executed_at is None or valid_until is None or executed_at > now or valid_until <= now:
                    errors.append(f"claim {claim.get('id')}: replay receipt is future-dated or expired")
            refs = trial.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                errors.append(f"claim {claim.get('id')}: promoted trial lacks content-addressed evidence")
            else:
                for ref_index, ref in enumerate(refs):
                    errors.extend(_content_ref_errors(ref, f"claim {claim.get('id')}.trial.evidence_refs[{ref_index}]", replay=True))
                    if isinstance(ref, dict) and Path(str(ref.get("path") or "")).resolve() != Path(__file__).resolve():
                        errors.append(f"claim {claim.get('id')}: trial evidence is not the executing validator source")

    for path in _forbidden_key_paths(record):
        errors.append(f"forbidden material key at {path}")

    return {
        "ok": not errors,
        "state": "PASS" if not errors else "FAIL",
        "claims": len(claims),
        "adopted": adopted,
        "promoted": record.get("promoted") is True,
        "errors": errors,
    }


def validate_harness(record: dict) -> dict:
    """Validate decentralized harness execution against one provider-neutral contract."""
    try:
        protocol = _read_json(PACKAGE_ROOT / PROTOCOL_TARGETS["FAMES"])
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "state": "UNKNOWN", "errors": [f"harness policy unreadable: {exc}"]}
    policy = ((protocol.get("architecture_standard") or {}).get("harness_contract") or {})
    if not policy:
        return {"ok": False, "state": "UNKNOWN", "errors": ["harness contract missing"]}
    if not isinstance(record, dict):
        return {"ok": False, "state": "UNKNOWN", "errors": ["record is not an object"]}

    errors: list[str] = []
    unknowns: list[str] = []
    for field in ("registry_identity", "canonical_package_sha"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            unknowns.append(f"harness {field} missing")
    allowed = set(policy.get("selection_predicates") or ())
    forbidden = set(policy.get("forbidden_predicates") or ())
    predicates = record.get("selection_predicates")
    if not isinstance(predicates, list) or not predicates:
        unknowns.append("harness selection predicates missing")
    else:
        if any(predicate not in allowed for predicate in predicates):
            errors.append("harness policy uses an undeclared selection predicate")
        if set(predicates) & forbidden:
            errors.append("harness policy selects by a forbidden product identity")

    registered = record.get("registered_surface_ids")
    if not isinstance(registered, list) or not registered:
        unknowns.append("registered harness population missing")
        registered = []
    elif len(registered) != len(set(registered)):
        errors.append("registered harness population contains duplicate identities")
    receipts = record.get("surface_receipts")
    if not isinstance(receipts, list) or not receipts:
        unknowns.append("harness surface receipts missing")
        receipts = []
    receipt_ids: list[str] = []
    canonical_sha = record.get("canonical_package_sha")
    required_fields = tuple(policy.get("required_surface_receipt_fields") or ())
    for index, receipt in enumerate(receipts):
        here = f"surface_receipts[{index}]"
        if not isinstance(receipt, dict):
            unknowns.append(f"{here}: receipt is not an object")
            continue
        missing = [field for field in required_fields if receipt.get(field) in (None, "", [])]
        if missing:
            unknowns.append(f"{here}: missing {', '.join(missing)}")
        surface_id = receipt.get("surface_id")
        if isinstance(surface_id, str) and surface_id:
            receipt_ids.append(surface_id)
        if receipt.get("package_sha") != canonical_sha:
            errors.append(f"{here}: package identity differs from canonical")
        for field in ("load_receipt", "behavior_probe", "local_verification", "read_back"):
            if receipt.get(field) is not True:
                errors.append(f"{here}: {field} did not pass")
        if receipt.get("turn_read_back") is not True:
            errors.append(f"{here}: per-turn rule or context did not read back")
        if not isinstance(receipt.get("turn_refresh_event"), str) or not receipt["turn_refresh_event"].strip():
            unknowns.append(f"{here}: turn refresh event missing")
        for field in (
            "session_identity_sha", "prompt_identity", "prompt_contract_identity",
            "turn_adapter_identity", "turn_rule_or_context_identity",
        ):
            if field in receipt and not SHA256_RE.fullmatch(str(receipt.get(field) or "").lower()):
                errors.append(f"{here}: {field} is not SHA-256")
    if registered and set(receipt_ids) != set(registered):
        errors.append("harness receipts do not cover the exact registered population")
    if len(receipt_ids) != len(set(receipt_ids)):
        errors.append("harness surface receipts contain duplicate identities")

    rename = record.get("rename_probe")
    if not isinstance(rename, dict):
        unknowns.append("harness rename probe missing")
    else:
        if rename.get("name_changed") is not True or rename.get("capability_identity_unchanged") is not True:
            errors.append("harness rename probe does not isolate name from capability")
        if rename.get("before_decision") != rename.get("after_decision"):
            errors.append("harness rename changed the routing decision")
    if record.get("promotion_writer_count") != 1:
        errors.append("harness topology must retain exactly one canonical promotion writer")
    if record.get("local_execution_decentralized") is not True:
        errors.append("harness execution is not locally decentralized")
    if record.get("unregistered_harness_state") != "UNKNOWN":
        errors.append("unregistered harness was implicitly claimed compliant")
    return {
        "ok": not errors and not unknowns,
        "state": "UNKNOWN" if unknowns else ("PASS" if not errors else "FAIL"),
        "registered_surfaces": len(registered),
        "receipts": len(receipt_ids),
        "errors": errors + unknowns,
    }


def _hardware_profile() -> tuple[dict, str | None]:
    try:
        profile = _read_json(PACKAGE_ROOT / HARDWARE_PROFILE_TARGET)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"hardware compute profile unreadable: {exc}"
    return profile, None


def measure_compute_topology(workspace: Path) -> dict:
    """Discover a capability adapter and return measured P/E topology."""
    profile, problem = _hardware_profile()
    if problem:
        return {"ok": False, "state": "UNKNOWN", "errors": [problem]}
    errors: list[str] = []
    for adapter in profile.get("host_adapter_examples") or ():
        if not isinstance(adapter, dict) or adapter.get("policy_authority") is not False:
            continue
        path = workspace.resolve() / str(adapter.get("path") or "")
        if path.name != "fleet_pe_allocator.py" or not path.is_file():
            continue
        try:
            proc = _run_hidden(
                [sys.executable, str(path), "--json", "status"],
                cwd=path.parent,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"adapter probe failed: {exc.__class__.__name__}")
            continue
        if proc.returncode != 0:
            errors.append(f"adapter probe exit {proc.returncode}")
            continue
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            errors.append("adapter probe returned invalid JSON")
            continue
        topology = payload.get("topology") if isinstance(payload.get("topology"), dict) else {}
        p_ids = topology.get("P") if isinstance(topology.get("P"), list) else []
        e_ids = topology.get("E") if isinstance(topology.get("E"), list) else []
        if not p_ids and not e_ids:
            errors.append("adapter topology has no P/E identities")
            continue
        return {
            "ok": True,
            "state": "PASS",
            "adapter_id": str(path.relative_to(workspace.resolve())).replace("\\", "/"),
            "topology": {
                "measured": True,
                "source": topology.get("source") or "fleet_pe_allocator",
                "logical_p": len(p_ids),
                "logical_e": len(e_ids),
                "p_cpu_ids": p_ids,
                "e_cpu_ids": e_ids,
            },
            "errors": [],
        }
    return {
        "ok": False,
        "state": "UNKNOWN",
        "errors": errors or ["NO_CAPABLE_ADAPTER: no measured P/E topology adapter is available"],
    }


def validate_background(record: dict) -> dict:
    """Validate that a scheduled launch and its descendants are genuinely windowless."""
    profile, problem = _hardware_profile()
    if problem:
        return {"ok": False, "state": "UNKNOWN", "errors": [problem]}
    if not isinstance(record, dict):
        return {"ok": False, "state": "UNKNOWN", "errors": ["background record is not an object"]}
    policy = profile.get("background_execution") or {}
    errors: list[str] = []
    unknowns: list[str] = []
    if record.get("background") is not True:
        errors.append("record is not classified as background")
    if record.get("full_descendant_policy_applied") is not True:
        errors.append("windowless controls do not cover the full descendant tree")
    controls = set(record.get("windows_console_flags") or ())
    required = set(policy.get("windows_console_flags") or ())
    if not controls:
        unknowns.append("Windows console controls are unmeasured")
    elif not required.issubset(controls):
        errors.append("required Windows hidden-launch controls are missing")
    if record.get("shell_false") is not True:
        errors.append("background launch must use shell=False")
    if record.get("detached_process_only") is True:
        errors.append("DETACHED_PROCESS alone is not a hidden-window control")
    if record.get("interactive_prompts_disabled") is not True:
        errors.append("interactive child prompts are not disabled")
    for field in ("visible_window_count", "focus_steal_count"):
        value = record.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            unknowns.append(f"{field} is unmeasured")
        elif value != 0:
            errors.append(f"{field} must be zero")
    return {
        "ok": not errors and not unknowns,
        "state": "UNKNOWN" if unknowns else ("PASS" if not errors else "FAIL"),
        "errors": errors + unknowns,
    }


def _service_class(task: dict) -> str:
    task_class = task.get("task_class")
    importance = task.get("importance")
    urgency = task.get("urgency")
    if urgency == "immediate" and importance == "critical" and task_class == "safety_recovery":
        return "critical"
    if urgency == "immediate" or (urgency == "deadline" and importance in {"high", "critical"}):
        return "urgent"
    if importance in {"high", "critical"}:
        return "priority"
    if task_class in {"batch_background", "io_background", "maintenance"}:
        return "background"
    if importance == "low" and urgency == "deferrable":
        return "eco"
    return "normal"


def _bounded_count(available: int, fraction: float) -> int:
    if available <= 0 or fraction <= 0:
        return 0
    return max(1, int(available * fraction))


def plan_compute(request: dict, workspace: Path | None = None) -> dict:
    """Produce one deterministic task-level P/E-core allocation."""
    profile, problem = _hardware_profile()
    if problem:
        return {"ok": False, "state": "UNKNOWN", "errors": [problem]}
    if not isinstance(request, dict):
        return {"ok": False, "state": "UNKNOWN", "errors": ["compute request is not an object"]}
    topology = request.get("topology") if isinstance(request.get("topology"), dict) else {}
    measured_adapter = None
    if not topology and workspace is not None:
        measured_adapter = measure_compute_topology(workspace)
        if measured_adapter.get("ok"):
            topology = measured_adapter["topology"]
    task = request.get("task") if isinstance(request.get("task"), dict) else {}
    pressure = request.get("pressure") if isinstance(request.get("pressure"), dict) else {}
    errors: list[str] = []
    unknowns: list[str] = []
    if topology.get("measured") is not True or not isinstance(topology.get("source"), str):
        unknowns.append("runtime topology is not measured")
    p_total = topology.get("logical_p")
    e_total = topology.get("logical_e")
    if not isinstance(p_total, int) or isinstance(p_total, bool) or p_total < 0:
        unknowns.append("logical_p is unknown")
        p_total = 0
    if not isinstance(e_total, int) or isinstance(e_total, bool) or e_total < 0:
        unknowns.append("logical_e is unknown")
        e_total = 0
    task_classes = set((profile.get("task_classes") or {}).keys())
    if task.get("task_class") not in task_classes:
        unknowns.append("task_class is unknown")
    if task.get("importance") not in set(profile.get("importance") or ()):
        unknowns.append("importance is unknown")
    if task.get("urgency") not in set(profile.get("urgency") or ()):
        unknowns.append("urgency is unknown")
    if task.get("authority_verified") is not True:
        errors.append("compute authority is not verified")
    scopes = task.get("authority_scope")
    if not isinstance(scopes, list) or not scopes:
        unknowns.append("compute authority scope is missing")
        scopes = []
    if task.get("urgency") in {"deadline", "immediate"} and not task.get("deadline_evidence"):
        errors.append("deadline/immediate urgency lacks deadline evidence")
    exclusive = task.get("exclusive_compute_requested") is True
    expected_duration = task.get("expected_duration_seconds")
    if exclusive:
        if "hardware.compute.exclusive" not in scopes:
            errors.append("exclusive compute authority is missing")
        if task.get("operator_impact_ack") is not True:
            errors.append("exclusive compute lacks operator impact acknowledgement")
        if not isinstance(expected_duration, int) or expected_duration <= 0 or expected_duration > 900:
            errors.append("exclusive compute duration must be 1..900 seconds")
        if task.get("restore_on_exit") is not True:
            errors.append("exclusive compute must restore resources on exit")
    reserve = profile.get("topology", {}).get("reserve") or {}
    reserve_p = 0 if exclusive else min(p_total, int(reserve.get("p_logical_min", 2)))
    reserve_e = 0 if exclusive else min(e_total, int(reserve.get("e_logical_min", 2)))
    available_p = max(0, p_total - reserve_p)
    available_e = max(0, e_total - reserve_e)
    service = _service_class(task)
    if pressure.get("sustained") is True and task.get("task_class") in {"batch_background", "io_background", "maintenance"}:
        service = "eco"
    class_policy = (profile.get("service_classes") or {}).get(service) or {}
    cap_p = _bounded_count(available_p, float(class_policy.get("p_fraction", 0)))
    cap_e = _bounded_count(available_e, float(class_policy.get("e_fraction", 0)))
    task_class = task.get("task_class")
    if task_class in {"batch_background", "io_background", "maintenance"}:
        cap_p = 1 if task.get("p_core_required") is True and available_p else 0
        task_caps = (profile.get("allocation") or {}).get("task_default_caps") or {}
        if task_class == "maintenance":
            cap_e = min(cap_e, int(task_caps.get("maintenance_e_max", 2)))
        elif task_class == "io_background":
            cap_e = min(cap_e, int(task_caps.get("io_background_e_max", 4)))
    elif task_class in {"latency_serial", "interactive"}:
        cap_e = 0 if service in {"eco", "normal"} else min(cap_e, 1)
    requested_p = task.get("requested_p", cap_p)
    requested_e = task.get("requested_e", cap_e)
    if not isinstance(requested_p, int) or isinstance(requested_p, bool) or requested_p < 0:
        unknowns.append("requested_p is invalid")
        requested_p = 0
    if not isinstance(requested_e, int) or isinstance(requested_e, bool) or requested_e < 0:
        unknowns.append("requested_e is invalid")
        requested_e = 0
    allocated_p = min(requested_p, cap_p)
    allocated_e = min(requested_e, cap_e)
    logical_allocated = allocated_p + allocated_e
    global_cap = request.get("global_concurrency_cap", logical_allocated)
    if not isinstance(global_cap, int) or isinstance(global_cap, bool) or global_cap < 1:
        unknowns.append("global_concurrency_cap is invalid")
        global_cap = logical_allocated
    requested_workers = task.get("requested_workers", logical_allocated)
    if not isinstance(requested_workers, int) or isinstance(requested_workers, bool) or requested_workers < 1:
        unknowns.append("requested_workers is invalid")
        requested_workers = 0
    workers = min(requested_workers, logical_allocated, global_cap) if logical_allocated else 0
    if logical_allocated == 0:
        errors.append("allocation has no logical CPU")
    if unknowns or errors:
        state = "UNKNOWN" if unknowns else "FAIL"
    else:
        state = "PASS"
    return {
        "ok": state == "PASS",
        "state": state,
        "service_class": service,
        "topology_source": topology.get("source"),
        "topology_adapter": measured_adapter.get("adapter_id") if measured_adapter else request.get("topology_adapter"),
        "reserve": {"p": reserve_p, "e": reserve_e},
        "caps": {"p": cap_p, "e": cap_e},
        "allocation": {"p": allocated_p, "e": allocated_e, "workers": workers},
        "priority": class_policy.get("priority"),
        "power_throttling": class_policy.get("power_throttling"),
        "exclusive": exclusive,
        "clamped": requested_p > cap_p or requested_e > cap_e or requested_workers > workers,
        "errors": errors + unknowns,
    }


def validate_compute(record: dict) -> dict:
    """Recompute the plan and verify an applied allocation plus windowless read-back."""
    if not isinstance(record, dict):
        return {"ok": False, "state": "UNKNOWN", "errors": ["compute record is not an object"]}
    request = record.get("request")
    plan = plan_compute(request)
    if plan.get("state") != "PASS":
        return plan
    errors: list[str] = []
    unknowns: list[str] = []
    declared = record.get("plan") if isinstance(record.get("plan"), dict) else {}
    for field in ("service_class", "allocation", "priority", "power_throttling", "reserve"):
        if declared.get(field) != plan.get(field):
            errors.append(f"declared compute plan differs at {field}")
    if record.get("applied") is not True:
        unknowns.append("compute allocation was not applied")
    read_back = record.get("read_back") if isinstance(record.get("read_back"), dict) else {}
    if not read_back.get("adapter_id") or not read_back.get("topology_source"):
        unknowns.append("compute adapter/topology read-back is missing")
    allocation = plan["allocation"]
    expected = {
        "applied_p": allocation["p"],
        "applied_e": allocation["e"],
        "applied_workers": allocation["workers"],
        "priority": plan["priority"],
        "power_throttling": plan["power_throttling"],
    }
    for field, value in expected.items():
        if field not in read_back:
            unknowns.append(f"compute read-back missing {field}")
        elif read_back.get(field) != value:
            errors.append(f"compute read-back differs at {field}")
    if read_back.get("visible_window_count") != 0 or read_back.get("focus_steal_count") != 0:
        errors.append("compute adapter produced a visible window or focus steal")
    if plan.get("exclusive") and read_back.get("restored") is not True:
        errors.append("exclusive compute did not restore resources")
    if not plan.get("exclusive") and read_back.get("restored") not in {True, False}:
        unknowns.append("restore state is unmeasured")
    return {
        "ok": not errors and not unknowns,
        "state": "UNKNOWN" if unknowns else ("PASS" if not errors else "FAIL"),
        "plan": plan,
        "errors": errors + unknowns,
    }


def _parse_xy_budget(value: object) -> tuple[int, int] | None:
    text = str(value or "").strip().upper()
    if "P+" not in text or not text.endswith("E"):
        return None
    p_text, e_text = text[:-1].split("P+", 1)
    try:
        p_value, e_value = int(p_text), int(e_text)
    except ValueError:
        return None
    if p_value < 0 or e_value < 0:
        return None
    return p_value, e_value


def validate_local_compute(profile: dict, workspace: Path | None = None) -> dict:
    """Validate one host's measured project/lifecycle P/E localization."""
    if not isinstance(profile, dict):
        return {"ok": False, "state": "UNKNOWN", "errors": ["local compute profile is not an object"]}
    errors: list[str] = []
    unknowns: list[str] = []
    for section in (
        "hardware", "evidence", "lifecycle_classes", "global_caps",
        "expected_projects", "project_profiles", "process_rules", "rules",
    ):
        if section not in profile:
            errors.append(f"local compute profile missing {section}")

    hardware = profile.get("hardware") if isinstance(profile.get("hardware"), dict) else {}
    numeric_fields = (
        "logical_p", "logical_e", "ordinary_reserve_p", "ordinary_reserve_e",
        "ordinary_cap_p", "ordinary_cap_e",
    )
    for field in numeric_fields:
        value = hardware.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"hardware {field} is invalid")
    logical_p = hardware.get("logical_p") if isinstance(hardware.get("logical_p"), int) else 0
    logical_e = hardware.get("logical_e") if isinstance(hardware.get("logical_e"), int) else 0
    cap_p = hardware.get("ordinary_cap_p") if isinstance(hardware.get("ordinary_cap_p"), int) else 0
    cap_e = hardware.get("ordinary_cap_e") if isinstance(hardware.get("ordinary_cap_e"), int) else 0
    reserve_p = hardware.get("ordinary_reserve_p") if isinstance(hardware.get("ordinary_reserve_p"), int) else 0
    reserve_e = hardware.get("ordinary_reserve_e") if isinstance(hardware.get("ordinary_reserve_e"), int) else 0
    if cap_p + reserve_p != logical_p or cap_e + reserve_e != logical_e:
        errors.append("ordinary caps plus reserves do not equal measured topology")

    lifecycle = profile.get("lifecycle_classes") if isinstance(profile.get("lifecycle_classes"), dict) else {}
    required_lifecycle = {
        "resident_control", "resident_service", "scheduled_ephemeral",
        "on_demand_batch", "on_demand_interactive", "safety_recovery",
    }
    if set(lifecycle) != required_lifecycle:
        errors.append("lifecycle classes are incomplete or contain an undeclared class")
    valid_priorities = {"idle", "below_normal", "normal", "above_normal", "high"}
    for name, row in lifecycle.items():
        if not isinstance(row, dict):
            errors.append(f"lifecycle {name} is not an object")
            continue
        p_value, e_value = row.get("default_p"), row.get("default_e")
        if not isinstance(p_value, int) or not isinstance(e_value, int) or p_value < 0 or e_value < 0:
            errors.append(f"lifecycle {name} has an invalid default budget")
        elif p_value > cap_p or e_value > cap_e:
            errors.append(f"lifecycle {name} exceeds the ordinary host cap")
        if row.get("priority") not in valid_priorities:
            errors.append(f"lifecycle {name} has an invalid priority")

    global_caps = profile.get("global_caps") if isinstance(profile.get("global_caps"), dict) else {}
    hub_limit = global_caps.get("hubclock_max_concurrent")
    scheduled = global_caps.get("scheduled_ephemeral") if isinstance(global_caps.get("scheduled_ephemeral"), dict) else {}
    if not isinstance(hub_limit, int) or isinstance(hub_limit, bool) or not 1 <= hub_limit <= 8:
        errors.append("HubClock concurrency must be between 1 and 8")
    elif scheduled.get("max_concurrent") != hub_limit:
        errors.append("HubClock and scheduled-ephemeral concurrency caps differ")
    if scheduled.get("aggregate_p", cap_p + 1) > cap_p or scheduled.get("aggregate_e", cap_e + 1) > cap_e:
        errors.append("scheduled-ephemeral aggregate budget exceeds the ordinary host cap")

    expected = profile.get("expected_projects") if isinstance(profile.get("expected_projects"), list) else []
    project_profiles = profile.get("project_profiles") if isinstance(profile.get("project_profiles"), dict) else {}
    if not expected or len(expected) != len(set(expected)):
        errors.append("expected project list is empty or duplicated")
    if set(expected) != set(project_profiles):
        missing = sorted(set(expected) - set(project_profiles))
        extra = sorted(set(project_profiles) - set(expected))
        errors.append(f"project coverage mismatch missing={missing} extra={extra}")
    for project, row in project_profiles.items():
        if not isinstance(row, dict) or not row.get("role"):
            errors.append(f"project {project} lacks a role")
            continue
        if not isinstance(row.get("observed_resident"), bool):
            errors.append(f"project {project} lacks an observed_resident boolean")
        for field in ("resident", "scheduled", "interactive", "urgent"):
            budget = _parse_xy_budget(row.get(field))
            if budget is None:
                errors.append(f"project {project} has invalid {field} budget")
            elif budget[0] > cap_p or budget[1] > cap_e:
                errors.append(f"project {project} {field} budget exceeds the ordinary cap")

    seen_rules: set[str] = set()
    process_rules = profile.get("process_rules") if isinstance(profile.get("process_rules"), list) else []
    for row in process_rules:
        if not isinstance(row, dict):
            errors.append("process rule is not an object")
            continue
        rule_id = str(row.get("id") or "")
        if not rule_id or rule_id in seen_rules:
            errors.append("process rule id is missing or duplicated")
        seen_rules.add(rule_id)
        if row.get("project") not in project_profiles:
            errors.append(f"process rule {rule_id} references an unknown project")
        if row.get("lifecycle") not in lifecycle:
            errors.append(f"process rule {rule_id} references an unknown lifecycle")
        matches = row.get("match_all")
        if not isinstance(matches, list) or not matches or not all(isinstance(item, str) and item for item in matches):
            errors.append(f"process rule {rule_id} has no deterministic match")
        p_value, e_value = row.get("p"), row.get("e")
        if not isinstance(p_value, int) or not isinstance(e_value, int) or p_value < 0 or e_value < 0:
            errors.append(f"process rule {rule_id} has an invalid budget")
        elif p_value > cap_p or e_value > cap_e or p_value + e_value < 1:
            errors.append(f"process rule {rule_id} exceeds the ordinary cap or allocates no CPU")
        if row.get("priority") not in valid_priorities:
            errors.append(f"process rule {rule_id} has an invalid priority")

    rules = profile.get("rules") if isinstance(profile.get("rules"), dict) else {}
    if rules.get("all_hubclock_rider_invocations_are") != "scheduled_ephemeral":
        errors.append("HubClock rider lifecycle is not scheduled_ephemeral")
    if rules.get("registered_does_not_mean_resident") is not True:
        errors.append("registered riders can be misclassified as resident")
    if rules.get("background_visible_window_count") != 0:
        errors.append("background visible-window policy is not zero")

    if workspace is not None and not errors:
        workspace = workspace.resolve()
        registry = workspace / "_registry" / "hosts.json"
        if not registry.is_file():
            unknowns.append("HubClock registry is unavailable for local read-back")
        else:
            try:
                riders = (_read_json(registry).get("hosts") or {}).get("HubClock", {}).get("riders") or []
                observed_count = len(riders)
                declared_count = (profile.get("evidence") or {}).get("rider_count")
                if observed_count != declared_count:
                    unknowns.append(f"rider registry drift: declared={declared_count} observed={observed_count}")
            except (OSError, json.JSONDecodeError, AttributeError) as exc:
                unknowns.append(f"HubClock registry read-back failed: {exc.__class__.__name__}")

    state = "FAIL" if errors else ("UNKNOWN" if unknowns else "PASS")
    return {
        "ok": state == "PASS",
        "state": state,
        "host_id": profile.get("host_id"),
        "hardware": {"p": logical_p, "e": logical_e, "reserve_p": reserve_p, "reserve_e": reserve_e},
        "project_count": len(project_profiles),
        "process_rule_count": len(process_rules),
        "hubclock_max_concurrent": hub_limit,
        "errors": errors + unknowns,
    }


def validate_autonomic(record: dict) -> dict:
    """Validate one bounded FAMES autonomic lifecycle record."""
    try:
        protocol = _read_json(PACKAGE_ROOT / PROTOCOL_TARGETS["FAMES"])
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "state": "UNKNOWN", "errors": [f"autonomic policy unreadable: {exc}"]}
    policy = protocol.get("autonomic_lifecycle")
    if not isinstance(policy, dict):
        return {"ok": False, "state": "UNKNOWN", "errors": ["autonomic_lifecycle policy missing"]}
    if not isinstance(record, dict):
        return {"ok": False, "state": "UNKNOWN", "errors": ["record is not an object"]}

    errors: list[str] = []
    unknowns: list[str] = []
    required = (policy.get("record") or {}).get("required_fields") or ()
    for field in required:
        if field not in record:
            unknowns.append(f"autonomic field missing: {field}")
    if not isinstance(record.get("cycle_id"), str) or not record["cycle_id"].strip():
        unknowns.append("cycle_id is empty")

    authority_before = record.get("authority_before")
    authority_after = record.get("authority_after")
    if not isinstance(authority_before, list) or not isinstance(authority_after, list):
        unknowns.append("autonomic authority ledger missing")
    elif not set(authority_after).issubset(set(authority_before)):
        errors.append("autonomic lifecycle expanded authority")

    ip_classes = set((policy.get("record") or {}).get("ip_classes") or ())
    disclosure_classes = set((policy.get("record") or {}).get("disclosure_classes") or ())
    sources = record.get("sources")
    if not isinstance(sources, list) or not sources:
        unknowns.append("autonomic sources missing")
        sources = []
    for index, source in enumerate(sources):
        here = f"sources[{index}]"
        if not isinstance(source, dict):
            unknowns.append(f"{here}: source is not an object")
            continue
        for field in ("source_id", "content_identity"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                unknowns.append(f"{here}: {field} missing")
        refs = source.get("provenance_refs")
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            unknowns.append(f"{here}: provenance references missing")
        ip_class = source.get("ip_class")
        disclosure = source.get("disclosure")
        if ip_class not in ip_classes:
            unknowns.append(f"{here}: IP class is unknown")
        if disclosure not in disclosure_classes:
            unknowns.append(f"{here}: disclosure class is unknown")
        if ip_class in {"restricted", "proprietary"} and disclosure != "local_only":
            errors.append(f"{here}: restricted material is not local-only")
        if source.get("ip_scan") not in {"CLEAN", "NOT_REQUIRED"}:
            unknowns.append(f"{here}: IP scan is not resolved")
        if ip_class in {"restricted", "proprietary"} and source.get("ip_scan") != "CLEAN":
            errors.append(f"{here}: restricted material lacks a clean IP scan")
        if disclosure in {"paste_safe", "publishable"} and ip_class != "public" and source.get("ip_scan") != "CLEAN":
            errors.append(f"{here}: non-public disclosure lacks a clean IP scan")
        if source.get("raw_restricted_embedded") is not False:
            errors.append(f"{here}: raw restricted material is embedded")
        if source.get("negative_results_preserved") is not True:
            errors.append(f"{here}: honest negative results were not preserved")
        if not isinstance(source.get("negative_results"), list):
            unknowns.append(f"{here}: negative-result ledger missing")
        hypotheses = source.get("hypotheses")
        if not isinstance(hypotheses, list):
            unknowns.append(f"{here}: hypothesis ledger missing")
        else:
            for h_index, hypothesis in enumerate(hypotheses):
                if not isinstance(hypothesis, dict) or hypothesis.get("label") != "HYPOTHESIS":
                    errors.append(f"{here}.hypotheses[{h_index}]: hypothesis is not labelled")
                elif not isinstance(hypothesis.get("verified"), bool):
                    unknowns.append(f"{here}.hypotheses[{h_index}]: verification state is unmeasured")

    allowed_lanes = set(policy.get("triage_lanes") or ())
    isolation_values = set(policy.get("safe_isolation") or ())
    triage = record.get("triage")
    if not isinstance(triage, list) or not triage:
        unknowns.append("triage ledger missing")
        triage = []
    for index, item in enumerate(triage):
        here = f"triage[{index}]"
        if not isinstance(item, dict):
            unknowns.append(f"{here}: item is not an object")
            continue
        if item.get("lane") not in allowed_lanes:
            unknowns.append(f"{here}: lane is unknown")
        for field in ("owner_only", "authorized", "shared_state_dirty", "destructive_command_used"):
            if not isinstance(item.get(field), bool):
                unknowns.append(f"{here}: {field} is unmeasured")
        if item.get("disposition") not in {"execute", "handoff", "block", "continue_safe_branch"}:
            unknowns.append(f"{here}: disposition is unknown")
        refs = item.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            unknowns.append(f"{here}: routing evidence missing")
        if item.get("owner_only") is True and item.get("disposition") == "execute":
            errors.append(f"{here}: owner-only decision was executed by the agent")
        if item.get("disposition") in {"execute", "continue_safe_branch"}:
            if item.get("authorized") is not True:
                errors.append(f"{here}: unauthorized work was executed")
            isolation = item.get("isolation_strategy")
            if isolation not in isolation_values:
                unknowns.append(f"{here}: isolation strategy is unknown")
            if item.get("shared_state_dirty") is True and isolation in {"not_applicable", None}:
                errors.append(f"{here}: dirty shared state was mutated without isolation")
        if item.get("destructive_command_used") is not False:
            errors.append(f"{here}: destructive-command boundary is unresolved or violated")
        if item.get("owner_only") is True and not item.get("handoff_ref"):
            unknowns.append(f"{here}: owner-only decision lacks a handoff")

    drive = record.get("drive")
    if not isinstance(drive, dict):
        unknowns.append("drive record missing")
        drive = {}
    controller_available = drive.get("controller_available")
    if not isinstance(controller_available, bool):
        unknowns.append("controller availability is unmeasured")
    if controller_available is True and not str(drive.get("controller_channel") or "").strip():
        unknowns.append("available controller has no channel identity")
    if not str(drive.get("goal_identity") or "").strip():
        unknowns.append("drive goal identity missing")
    frozen_validator = str(drive.get("validator_identity") or "").strip()
    if not frozen_validator:
        unknowns.append("drive validator identity missing")
    maximum = drive.get("max_attempts")
    attempts = drive.get("attempts")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 10:
        unknowns.append("repair attempt budget is invalid")
    if not isinstance(attempts, list):
        unknowns.append("repair attempts missing")
        attempts = []
    elif isinstance(maximum, int) and len(attempts) > maximum:
        errors.append("repair attempt budget exceeded")
    previous_after = None
    stagnant = 0
    for index, attempt in enumerate(attempts):
        here = f"drive.attempts[{index}]"
        if not isinstance(attempt, dict):
            unknowns.append(f"{here}: attempt is not an object")
            continue
        for field in ("artifact_before", "artifact_after", "goal_identity", "validator_identity"):
            if not isinstance(attempt.get(field), str) or not attempt[field].strip():
                unknowns.append(f"{here}: {field} missing")
        if drive.get("goal_identity") and attempt.get("goal_identity") != drive.get("goal_identity"):
            errors.append(f"{here}: goal identity changed during repair")
        if frozen_validator and attempt.get("validator_identity") != frozen_validator:
            errors.append(f"{here}: validator identity changed during repair")
        if attempt.get("validator_state") not in {"PASS", "FAIL", "UNKNOWN"}:
            unknowns.append(f"{here}: validator state is unknown")
        delta = attempt.get("discriminating_delta")
        if not _number(delta):
            unknowns.append(f"{here}: discriminating delta is unmeasured")
            delta = 0
        changed = attempt.get("artifact_after") != attempt.get("artifact_before")
        if previous_after is not None and attempt.get("artifact_after") == previous_after and delta <= 0:
            stagnant += 1
        else:
            stagnant = 0
        if not changed and delta <= 0 and attempt.get("validator_state") != "PASS":
            stagnant += 1
        previous_after = attempt.get("artifact_after")
    if stagnant >= 3:
        errors.append("three stagnant repair attempts did not stop or change strategy")
    terminal = drive.get("terminal_state")
    if terminal not in set(policy.get("terminal_states") or ()):
        unknowns.append("drive terminal state is unknown")
    if controller_available is False and terminal == "PASS":
        errors.append("drive claimed PASS without a controller")
    if controller_available is False and not drive.get("handoff_ref"):
        unknowns.append("missing controller did not produce a handoff")
    if terminal == "PASS":
        if not attempts or attempts[-1].get("validator_state") != "PASS":
            errors.append("drive PASS lacks a final validator PASS")
        if drive.get("external_read_back") is not True:
            errors.append("drive PASS lacks external read-back")
    if drive.get("repair_requests_structured") is not True:
        errors.append("repair requests are not structured")

    review = record.get("review")
    if not isinstance(review, dict):
        unknowns.append("review record missing")
        review = {}
    if review.get("lane") not in set(policy.get("review_lanes") or ()):
        unknowns.append("review lane is unknown")
    if not str(review.get("target_identity") or "").strip():
        unknowns.append("review target identity missing")
    if attempts and review.get("target_identity") != attempts[-1].get("artifact_after"):
        errors.append("review target is not the final repaired artifact")
    commands = review.get("commands_rerun")
    if (
        not isinstance(commands, list)
        or not commands
        or any(not isinstance(command, str) or not command.strip() for command in commands)
    ):
        unknowns.append("review reproduced no command")
    if review.get("builder_narrative_only") is not False:
        errors.append("review relied on builder narrative")
    if review.get("negative_results_preserved") is not True:
        errors.append("review erased negative results")
    blocking_unknowns = review.get("blocking_unknowns")
    if not isinstance(blocking_unknowns, list):
        unknowns.append("review blocking-unknown ledger missing")
        blocking_unknowns = []
    verdict = review.get("verdict")
    if verdict not in {"ACCEPTED", "REJECTED", "UNKNOWN"}:
        unknowns.append("review verdict is unknown")
    if verdict == "ACCEPTED" and (review.get("evidence_reproduced") is not True or blocking_unknowns):
        errors.append("review accepted without reproduced evidence or with blocking UNKNOWN")

    evolution = record.get("evolution")
    if not isinstance(evolution, dict):
        unknowns.append("evolution record missing")
        evolution = {}
    for field in ("activated", "promoted", "negative_results_preserved"):
        if not isinstance(evolution.get(field), bool):
            unknowns.append(f"evolution {field} is unmeasured")
    if evolution.get("negative_results_preserved") is False:
        errors.append("evolution erased negative results")
    before = evolution.get("residual_before")
    after = evolution.get("residual_after")
    if not _number(before) or not _number(after):
        unknowns.append("evolution residual is unmeasured")
    if _number(before) and before > 0 and evolution.get("activated") is not True and not evolution.get("blocker_refs"):
        unknowns.append("measured residual neither activated AEX nor named a blocker")
    if evolution.get("promoted") is True:
        if evolution.get("activated") is not True:
            errors.append("promotion occurred without AEX activation")
        if verdict != "ACCEPTED" or evolution.get("measured_trial") is not True:
            errors.append("promotion lacks accepted review or measured trial")
        if evolution.get("actor") != evolution.get("authority"):
            errors.append("non-authority actor promoted the generation")
        if not str(evolution.get("package_sha") or "").strip():
            unknowns.append("promoted package identity missing")
        for field in ("version_bumped", "generation_bumped", "package_identity_changed", "negative_results_preserved"):
            if evolution.get(field) is not True:
                errors.append(f"promotion gate failed: {field}")
        if _number(before) and _number(after) and after > before:
            errors.append("promotion increased the measured residual")

    sync = record.get("sync")
    if not isinstance(sync, dict):
        unknowns.append("sync record missing")
        sync = {}
    expected_sha = str(sync.get("expected_package_sha") or "").strip()
    expected_capability_sha = str(sync.get("expected_capability_set_sha") or "").strip()
    expected_validator_sha = str(sync.get("expected_validator_set_sha") or "").strip()
    if not expected_sha:
        unknowns.append("sync package identity missing")
    if not expected_capability_sha:
        unknowns.append("sync capability-set identity missing")
    if not expected_validator_sha:
        unknowns.append("sync validator-set identity missing")
    if evolution.get("promoted") is True and evolution.get("package_sha") != expected_sha:
        errors.append("evolution and sync package identities differ")
    if evolution.get("promoted") is True and (sync.get("atomic") is not True or sync.get("idempotent") is not True):
        errors.append("promoted package lacks atomic idempotent sync")
    readbacks = sync.get("readbacks")
    if not isinstance(readbacks, list) or not readbacks:
        unknowns.append("sync read-backs missing")
        readbacks = []
    unknown_hosts = sync.get("unknown_hosts")
    if not isinstance(unknown_hosts, list) or any(not isinstance(host, str) or not host.strip() for host in unknown_hosts):
        unknowns.append("sync unknown-host ledger missing")
        unknown_hosts = []
    matching = 0
    for index, row in enumerate(readbacks):
        here = f"sync.readbacks[{index}]"
        if not isinstance(row, dict) or not row.get("host"):
            unknowns.append(f"{here}: host identity missing")
            continue
        host = row.get("host")
        if row.get("state") not in {"PASS", "UNKNOWN", "FAIL"}:
            unknowns.append(f"{here}: read-back state is unknown")
        identities_match = (
            row.get("package_sha") == expected_sha
            and row.get("capability_set_sha") == expected_capability_sha
            and row.get("validator_set_sha") == expected_validator_sha
        )
        matched = (
            identities_match
            and row.get("state") == "PASS"
            and row.get("capability_state") == "PASS"
            and row.get("runner_state") == "armed"
        )
        if row.get("state") == "PASS" and not identities_match:
            errors.append(f"{here}: PASS read-back has a mismatched package, capability, or validator identity")
        if row.get("state") == "PASS" and row.get("capability_state") != "PASS":
            errors.append(f"{here}: PASS read-back lacks capability validation")
        if row.get("state") == "PASS" and row.get("runner_state") != "armed":
            errors.append(f"{here}: PASS read-back lacks an armed convergence runner")
        if matched:
            matching += 1
        elif host not in unknown_hosts:
            errors.append(f"{here}: stale or failed host was not named UNKNOWN")
    if evolution.get("promoted") is True and matching == 0:
        errors.append("promoted package has no matching read-back")
    if sync.get("full_convergence_claim") is True and (unknown_hosts or matching != len(readbacks)):
        errors.append("full convergence claimed with stale or unknown hosts")

    observation = record.get("observation")
    if not isinstance(observation, dict):
        unknowns.append("observation record missing")
        observation = {}
    if observation.get("self_check_state") not in {"PASS", "FAIL", "UNKNOWN"}:
        unknowns.append("observation self-check state is unknown")
    if evolution.get("promoted") is True and observation.get("self_check_state") != "PASS":
        errors.append("promoted generation lacks a passing self-check")
    if not isinstance(observation.get("residuals"), list):
        unknowns.append("observation residual ledger missing")
    if observation.get("feedback_enqueued") is not True:
        errors.append("observation did not close the feedback loop")
    if not str(observation.get("next_action") or "").strip():
        unknowns.append("observation next action missing")

    return {
        "ok": not errors and not unknowns,
        "state": "UNKNOWN" if unknowns else ("PASS" if not errors else "FAIL"),
        "sources": len(sources),
        "triage_items": len(triage),
        "attempts": len(attempts),
        "readbacks": len(readbacks),
        "errors": errors + unknowns,
    }


def _cognitive_contract() -> tuple[dict, str]:
    """Load the provider-neutral cognitive-operator policy from the bundled protocol."""
    try:
        protocol = _read_json(PACKAGE_ROOT / PROTOCOL_TARGETS["FAMES"])
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"cognitive contract unreadable ({exc.__class__.__name__})"
    layer = protocol.get("cognitive_operator_layer")
    if not isinstance(layer, dict):
        return {}, "cognitive_operator_layer missing from bundled protocol"
    if not isinstance(layer.get("operators"), dict) or not isinstance(layer.get("pipelines"), dict):
        return {}, "cognitive operator or pipeline policy missing"
    return layer, ""


def _validate_cognitive_trace(trace: object, layer: dict, index: int) -> list[str]:
    """Validate one bounded operator trace; the policy stays in JSON, not code."""
    prefix = f"trace[{index}]"
    if not isinstance(trace, dict):
        return [f"{prefix} is not an object"]
    errors: list[str] = []
    task_class = trace.get("task_class")
    route = layer["pipelines"].get(task_class)
    if not isinstance(route, list) or not route:
        return [f"{prefix}: unknown task_class {task_class!r}"]
    stages = trace.get("stages")
    if not isinstance(stages, list):
        return [f"{prefix}: stages missing"]
    expected = [(row.get("operator"), row.get("role")) for row in route if isinstance(row, dict)]
    actual = [
        (row.get("operator"), row.get("role"))
        for row in stages
        if isinstance(row, dict)
    ]
    if len(actual) != len(stages) or actual != expected:
        errors.append(f"{prefix}: pipeline order or role mismatch")
    if trace.get("evidence_class") != "measured":
        errors.append(f"{prefix}: only measured traces are seal-admissible")

    operators = layer["operators"]
    for stage_index, stage in enumerate(stages):
        here = f"{prefix}.stages[{stage_index}]"
        if not isinstance(stage, dict):
            errors.append(f"{here}: stage is not an object")
            continue
        missing = [field for field in ("operator", "role", "input_ref", "output_ref", "stop") if field not in stage]
        if missing:
            errors.append(f"{here}: missing {', '.join(missing)}")
            continue
        operator = stage.get("operator")
        policy = operators.get(operator)
        if not isinstance(policy, dict):
            errors.append(f"{here}: unknown operator {operator!r}")
            continue
        stop = stage.get("stop")
        if not isinstance(stop, dict):
            errors.append(f"{here}: stop contract missing")
            continue
        if stop.get("rule") != policy.get("required_stop_rule"):
            errors.append(f"{here}: stop rule mismatch")
        if stop.get("met") is not True or not stop.get("evidence"):
            errors.append(f"{here}: stop condition is not measured as met")

        if operator == "Ni":
            if not stage.get("model") or not stage.get("discriminating_test"):
                errors.append(f"{here}: Ni needs a model and discriminating test")
            if stage.get("residual_bounded") is not True:
                errors.append(f"{here}: Ni residual is not bounded")
        elif operator == "Ne":
            candidates = stage.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                errors.append(f"{here}: Ne produced no alternatives")
            sources = stage.get("discovery_sources")
            allowed_sources = set(policy.get("allowed_source_kinds") or ())
            if not isinstance(sources, list) or not sources:
                errors.append(f"{here}: Ne discovery sources missing")
            else:
                for source_index, source in enumerate(sources):
                    source_here = f"{here}.discovery_sources[{source_index}]"
                    if not isinstance(source, dict):
                        errors.append(f"{source_here}: source is not an object")
                        continue
                    if source.get("kind") not in allowed_sources:
                        errors.append(f"{source_here}: source kind is outside the registered Ne scope")
                    for field in ("source_ref", "content_identity"):
                        if not isinstance(source.get(field), str) or not source[field].strip():
                            errors.append(f"{source_here}: {field} missing")
                    for field in ("scope_match", "freshness_checked", "authority_checked"):
                        if source.get(field) is not True:
                            errors.append(f"{source_here}: {field} is not measured true")
            window = policy.get("saturation_window", 3)
            if not isinstance(window, int) or isinstance(window, bool) or window < 1:
                errors.append(f"{here}: Ne saturation policy is invalid")
                window = 3
            observed = stop.get("stable_rank_additions")
            saturated = (
                isinstance(observed, (int, float))
                and not isinstance(observed, bool)
                and observed >= window
            )
            if not saturated or stop.get("ranking_changed") is not False:
                errors.append(f"{here}: Ne saturation rule not met")
        elif operator == "Ti":
            invariants = stage.get("invariants")
            if not isinstance(invariants, list) or not invariants:
                errors.append(f"{here}: Ti invariants missing")
            if stage.get("counterexample_status") not in {"none_within_budget", "found_and_resolved"}:
                errors.append(f"{here}: Ti counterexample search unresolved")
        elif operator == "Te":
            if stage.get("external_state_changed") is not True:
                errors.append(f"{here}: Te has no measured external state change")
            if stage.get("verification_met") is not True:
                errors.append(f"{here}: Te verification is not met")
        elif operator == "Si":
            for field in ("structure_identity", "version", "application_receipt"):
                if not isinstance(stage.get(field), str) or not stage[field].strip():
                    errors.append(f"{here}: Si {field} missing")
            for field in ("caller_backed", "measured", "fresh"):
                if stage.get(field) is not True:
                    errors.append(f"{here}: Si {field} is not measured true")
        elif operator == "Fe":
            for field in ("actors", "commitments", "context_refs"):
                value = stage.get(field)
                if not isinstance(value, list) or not value:
                    errors.append(f"{here}: Fe {field} missing")
            if not isinstance(stage.get("authority_context"), dict) or not stage["authority_context"]:
                errors.append(f"{here}: Fe authority context missing")
            if stage.get("intent_inferred") is not False:
                errors.append(f"{here}: Fe inferred intent from interaction context")
        elif operator == "Fi":
            assessments = stage.get("claim_assessments")
            invariants = stage.get("commitment_invariants")
            if not isinstance(assessments, list) or not assessments:
                errors.append(f"{here}: Fi claim assessments missing")
            if not isinstance(invariants, list) or not invariants:
                errors.append(f"{here}: Fi commitment invariants missing")
            if stage.get("intent_boundary_preserved") is not True:
                errors.append(f"{here}: Fi intent boundary is not preserved")
            deception = stage.get("deception_state")
            if deception not in {"SUPPORTED", "UNKNOWN"}:
                errors.append(f"{here}: Fi deception state is undeclared")
            if deception == "SUPPORTED":
                refs = stage.get("direct_intent_evidence_refs")
                if stage.get("intent_evidence_class") != "measured" or not isinstance(refs, list) or not refs:
                    errors.append(f"{here}: Fi deception verdict lacks direct measured intent evidence")
    return errors


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_meticulousness_item(item: object, policy: dict, index: int) -> tuple[list[str], list[str]]:
    """Validate one UT-derived engineering hypothesis with measured, typed inputs."""
    prefix = f"meticulousness[{index}]"
    if not isinstance(item, dict):
        return [f"{prefix} is not an object"], []
    kind = item.get("kind")
    if kind not in (policy.get("mechanisms") or {}):
        return [], [f"{prefix}: unknown mechanism {kind!r}"]
    errors: list[str] = []
    unknowns: list[str] = []

    if kind == "stability_margin":
        unit = item.get("unit")
        required = ("margin", "trend", "warning_threshold", "trend_limit")
        if not isinstance(unit, str) or not unit.strip():
            unknowns.append(f"{prefix}: margin unit is undefined")
        if any(not _number(item.get(field)) for field in required):
            unknowns.append(f"{prefix}: margin or trend is not measurable")
        if not item.get("measured_at") or not item.get("leading_indicator"):
            unknowns.append(f"{prefix}: measurement time or leading indicator missing")
        if not unknowns:
            warning = (
                item["margin"] <= item["warning_threshold"]
                or item["trend"] < -abs(item["trend_limit"])
            )
            expected = "warning" if warning else "safe"
            if item.get("status") != expected:
                errors.append(f"{prefix}: stability status must be {expected}")

    elif kind == "conservation_ledger":
        transitions = item.get("transitions")
        if not isinstance(transitions, list) or not transitions:
            unknowns.append(f"{prefix}: transitions missing")
        else:
            cost_fields = tuple(policy["mechanisms"][kind].get("cost_fields") or ())
            for j, row in enumerate(transitions):
                here = f"{prefix}.transitions[{j}]"
                if not isinstance(row, dict):
                    unknowns.append(f"{here}: transition is not an object")
                    continue
                costs = row.get("costs")
                if not isinstance(costs, dict) or any(not _number(costs.get(k)) for k in cost_fields):
                    unknowns.append(f"{here}: costs are not fully measured")
                before = row.get("authority_before")
                after = row.get("authority_after")
                if not isinstance(before, list) or not isinstance(after, list):
                    unknowns.append(f"{here}: authority ledger missing")
                elif not set(after).issubset(set(before)):
                    errors.append(f"{here}: authority expanded during transition")
                evidence = row.get("evidence")
                if not isinstance(evidence, dict) or any(
                    not isinstance(evidence.get(key), int) or isinstance(evidence.get(key), bool)
                    for key in ("input", "new", "claimed")
                ):
                    unknowns.append(f"{here}: evidence ledger is unmeasured")
                elif evidence["claimed"] > evidence["input"] + evidence["new"]:
                    errors.append(f"{here}: output claims exceed input evidence")
                if not isinstance(row.get("residual"), str) or not row["residual"].strip():
                    errors.append(f"{here}: residual was silently discarded")

    elif kind == "loop_escape":
        attempts = item.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            unknowns.append(f"{prefix}: attempts missing")
        elif any(
            not isinstance(row, dict)
            or not _number(row.get("external_delta"))
            or not _number(row.get("discrimination_delta"))
            for row in attempts
        ):
            unknowns.append(f"{prefix}: attempt deltas are unmeasured")
        else:
            stagnant = len(attempts) >= 3 and all(
                row["external_delta"] == 0 and row["discrimination_delta"] == 0
                for row in attempts[-3:]
            )
            allowed = set(policy["mechanisms"][kind].get("escape_actions") or ())
            if stagnant and item.get("next_action") not in allowed:
                errors.append(f"{prefix}: stagnant loop did not switch to a discriminating action")

    elif kind == "grip_guard":
        impact = item.get("impact")
        if impact not in RISK_ORDER:
            unknowns.append(f"{prefix}: mutation impact is unknown")
        else:
            high = RISK_ORDER[impact] >= RISK_ORDER["R2"]
            bounded = all(item.get(key) is True for key in ("bounded_transaction", "rollback", "read_back"))
            emergency = item.get("emergency_recovery") is True and item.get("recovery_drill_pass") is True
            if high and not (bounded or emergency):
                errors.append(f"{prefix}: unbounded high-impact mutation is blocked")

    elif kind == "destructive_interference":
        if item.get("new_capability_probe") is not True:
            unknowns.append(f"{prefix}: new capability was not measured")
        if item.get("core_before_pass") is not True or item.get("core_after_pass") is not True:
            errors.append(f"{prefix}: existing core capability regressed or lost its caller")
        allowed = {"R_CAPABILITY", "R_OPERABILITY", "R_COMPLEXITY"}
        residuals = item.get("residuals")
        if not isinstance(residuals, list) or any(row not in allowed for row in residuals):
            unknowns.append(f"{prefix}: interference residual vocabulary is invalid")

    elif kind == "bifurcation_foresight":
        series = item.get("series")
        if not isinstance(series, list) or len(series) < 3 or any(not _number(v) for v in series):
            unknowns.append(f"{prefix}: measured series is missing or malformed")
        elif any(not _number(item.get(key)) for key in ("threshold", "age_seconds", "max_age_seconds")):
            unknowns.append(f"{prefix}: threshold or freshness is unmeasured")
        elif item["age_seconds"] > item["max_age_seconds"]:
            unknowns.append(f"{prefix}: series is stale")
        else:
            slope = series[-1] - series[-2]
            if series[-1] >= item["threshold"]:
                classification = "measured_conclusion"
            elif slope > 0 and series[-1] + slope >= item["threshold"]:
                classification = "forecast"
            else:
                classification = "stable"
            if item.get("classification") != classification:
                errors.append(f"{prefix}: classification must be {classification}")

    elif kind == "basis_alignment":
        routes = item.get("routes")
        chosen = item.get("chosen")
        metrics = tuple(policy["mechanisms"][kind].get("metrics") or ())
        if item.get("operator_route") != ["Ne", "Ti", "Ni", "Te"]:
            errors.append(f"{prefix}: operator route is not Ne->Ti->Ni->Te")
        if "score" in item:
            errors.append(f"{prefix}: unitless aggregate score is forbidden")
        if not isinstance(routes, list) or not routes:
            unknowns.append(f"{prefix}: routes missing")
        else:
            indexed = {row.get("id"): row for row in routes if isinstance(row, dict)}
            selected = indexed.get(chosen)
            if not selected or any(not _number(selected.get(metric)) for metric in metrics):
                unknowns.append(f"{prefix}: selected route metrics are unmeasured")
            else:
                for route_id, row in indexed.items():
                    if route_id == chosen or any(not _number(row.get(metric)) for metric in metrics):
                        continue
                    dominated = all(row[m] <= selected[m] for m in metrics) and any(
                        row[m] < selected[m] for m in metrics
                    )
                    if dominated:
                        errors.append(f"{prefix}: route {route_id} dominates selected route")
                        break

    elif kind == "inverse_diagnosis":
        symptom = item.get("symptom")
        mapping = policy["mechanisms"][kind].get("mapping") or {}
        expected = mapping.get(symptom)
        if not isinstance(expected, dict):
            unknowns.append(f"{prefix}: symptom has no falsifiable mapping")
        elif item.get("minimal_stage") != expected.get("stage") or item.get("next_test") != expected.get("test"):
            errors.append(f"{prefix}: result-to-stage inversion is not minimal or decisive")

    elif kind == "epistemic_layers":
        claims = item.get("claims")
        allowed = {"source/measured", "model/hypothesis", "draft/unverified"}
        if not isinstance(claims, list) or not claims:
            unknowns.append(f"{prefix}: claims missing")
        else:
            for j, row in enumerate(claims):
                here = f"{prefix}.claims[{j}]"
                if not isinstance(row, dict) or row.get("layer") not in allowed:
                    unknowns.append(f"{here}: epistemic layer is unknown")
                    continue
                admissible = row["layer"] == "source/measured"
                if row.get("seal_admissible") is not admissible:
                    errors.append(f"{here}: seal admissibility contradicts epistemic layer")
    return errors, unknowns


def _validate_meticulousness(record: dict, layer: dict) -> tuple[list[str], list[str], int]:
    policy = layer.get("meticulousness_and_efficiency")
    if not isinstance(policy, dict) or not isinstance(policy.get("mechanisms"), dict):
        return [], ["meticulousness_and_efficiency policy missing"], 0
    items = record.get("meticulousness")
    if not isinstance(items, list) or not items:
        return [], ["meticulousness checks missing"], 0
    errors: list[str] = []
    unknowns: list[str] = []
    for index, item in enumerate(items):
        item_errors, item_unknowns = _validate_meticulousness_item(item, policy, index)
        errors.extend(item_errors)
        unknowns.extend(item_unknowns)
    return errors, unknowns, len(items)


def _validate_interaction(record: dict, layer: dict) -> tuple[list[str], list[str], int]:
    """Validate UT claim integrity and transparent compliance alignment."""
    policy = layer.get("interaction_integrity")
    if not isinstance(policy, dict):
        return [], ["interaction_integrity policy missing"], 0
    interaction = record.get("interaction_integrity")
    if not isinstance(interaction, dict):
        return [], ["interaction_integrity record missing"], 0
    errors: list[str] = []
    unknowns: list[str] = []
    count = 0

    claim_policy = policy.get("claim_integrity") or {}
    mapping = claim_policy.get("mapping") or {}
    claims = interaction.get("claim_assessments")
    if not isinstance(claims, list) or not claims:
        unknowns.append("claim assessments missing")
    else:
        count += len(claims)
        for index, claim in enumerate(claims):
            here = f"interaction_integrity.claim_assessments[{index}]"
            if not isinstance(claim, dict):
                unknowns.append(f"{here}: assessment is not an object")
                continue
            if not claim.get("claim_id") or not claim.get("claim"):
                unknowns.append(f"{here}: claim identity or text missing")
            evidence_status = claim.get("evidence_status")
            expected = mapping.get(evidence_status)
            if expected is None:
                unknowns.append(f"{here}: evidence status is unknown")
            elif claim.get("claim_state") != expected:
                errors.append(f"{here}: claim state must be {expected}")
            evidence_refs = claim.get("evidence_refs")
            if evidence_status in {"matches", "conflicts"} and (
                not isinstance(evidence_refs, list)
                or not evidence_refs
                or any(not isinstance(ref, str) or not ref.strip() for ref in evidence_refs)
            ):
                unknowns.append(f"{here}: supported or contradicted claim lacks evidence")
            deception_state = claim.get("deception_state")
            if deception_state not in {"SUPPORTED", "UNKNOWN"}:
                unknowns.append(f"{here}: deception state is unknown")
            if deception_state == "SUPPORTED":
                intent_refs = claim.get("direct_intent_evidence_refs")
                if (
                    claim.get("claim_state") != "CONTRADICTED"
                    or claim.get("intent_evidence_class") != "measured"
                    or not isinstance(intent_refs, list)
                    or not intent_refs
                    or any(not isinstance(ref, str) or not ref.strip() for ref in intent_refs)
                ):
                    errors.append(f"{here}: deception is asserted without direct measured intent evidence")

    alignment_policy = policy.get("compliance_alignment") or {}
    allowed = set(alignment_policy.get("allowed_methods") or ())
    forbidden = set(alignment_policy.get("forbidden_methods") or ())
    attempts = interaction.get("alignment_attempts")
    if not isinstance(attempts, list) or not attempts:
        unknowns.append("alignment attempts missing")
    else:
        count += len(attempts)
        for index, attempt in enumerate(attempts):
            here = f"interaction_integrity.alignment_attempts[{index}]"
            if not isinstance(attempt, dict):
                unknowns.append(f"{here}: attempt is not an object")
                continue
            if not isinstance(attempt.get("instruction_id"), str) or not attempt["instruction_id"].strip():
                unknowns.append(f"{here}: instruction identity missing")
            methods = attempt.get("methods")
            if not isinstance(methods, list) or not methods:
                unknowns.append(f"{here}: alignment methods missing")
            elif any(method not in allowed for method in methods):
                errors.append(f"{here}: undeclared or forbidden alignment method")
            forbidden_used = attempt.get("forbidden_methods_used")
            if not isinstance(forbidden_used, list):
                unknowns.append(f"{here}: forbidden-method ledger missing")
            elif any(method not in forbidden for method in forbidden_used):
                unknowns.append(f"{here}: forbidden-method vocabulary is unknown")
            elif set(forbidden_used) & forbidden:
                errors.append(f"{here}: manipulation or coercion method used")
            for field in ("authorized", "goal_explicit", "constraints_explicit", "counterparty_choice_preserved"):
                if not isinstance(attempt.get(field), bool):
                    unknowns.append(f"{here}: {field} is unmeasured")
            for field in ("goal_explicit", "constraints_explicit"):
                if attempt.get(field) is False:
                    errors.append(f"{here}: {field} must be true for transparent alignment")
            if (
                not isinstance(attempt.get("evidence_refs"), list)
                or not attempt["evidence_refs"]
                or any(not isinstance(ref, str) or not ref.strip() for ref in attempt["evidence_refs"])
            ):
                unknowns.append(f"{here}: evidence references missing")
            before = attempt.get("authority_before")
            after = attempt.get("authority_after")
            if not isinstance(before, list) or not isinstance(after, list):
                unknowns.append(f"{here}: authority ledger missing")
            elif not set(after).issubset(set(before)):
                errors.append(f"{here}: authority expanded during alignment")
            if attempt.get("counterparty_choice_preserved") is False:
                errors.append(f"{here}: counterpart choice was not preserved")
            if not isinstance(attempt.get("higher_priority_conflict"), bool):
                unknowns.append(f"{here}: higher-priority conflict status is unmeasured")
            if attempt.get("higher_priority_conflict") is True and attempt.get("result") != "refused":
                errors.append(f"{here}: higher-priority conflict was not refused")
            if attempt.get("result") not in {"accepted", "repair_requested", "refused"}:
                unknowns.append(f"{here}: result is unknown")
            if attempt.get("authorized") is False and attempt.get("result") != "refused":
                errors.append(f"{here}: unauthorized instruction was not refused")
            if not isinstance(attempt.get("why"), str) or not attempt["why"].strip():
                unknowns.append(f"{here}: outcome reason missing")

    delivery_policy = policy.get("delivery_integrity") or {}
    claim_types = set(delivery_policy.get("claim_types") or ())
    action_states = set(delivery_policy.get("action_states") or ())
    delivery_claims = interaction.get("delivery_claims")
    if not isinstance(delivery_claims, list) or not delivery_claims:
        unknowns.append("delivery claims missing")
    else:
        count += len(delivery_claims)
        for index, claim in enumerate(delivery_claims):
            here = f"interaction_integrity.delivery_claims[{index}]"
            if not isinstance(claim, dict):
                unknowns.append(f"{here}: claim is not an object")
                continue
            for field in ("claim_id", "subject", "artifact_identity"):
                if not isinstance(claim.get(field), str) or not claim[field].strip():
                    unknowns.append(f"{here}: {field} missing")
            claim_type = claim.get("claim_type")
            if claim_type not in claim_types:
                unknowns.append(f"{here}: claim type is unknown")
            action_state = claim.get("action_state")
            if action_state not in action_states:
                unknowns.append(f"{here}: action state is unknown")
            scope = claim.get("scope")
            if scope not in {"single", "sample", "exhaustive", "fleet"}:
                unknowns.append(f"{here}: scope is unknown")
            if claim.get("status") not in {"PASS", "FAIL", "UNKNOWN"}:
                unknowns.append(f"{here}: status is unknown")
            refs = claim.get("evidence_refs")
            if (
                claim.get("evidence_class") != "measured"
                or not isinstance(refs, list)
                or not refs
                or any(not isinstance(ref, str) or not ref.strip() for ref in refs)
            ):
                unknowns.append(f"{here}: measured evidence references missing")
            residuals = claim.get("residuals")
            if not isinstance(residuals, list):
                unknowns.append(f"{here}: residual ledger missing")
            defects = claim.get("defects")
            if not isinstance(defects, list):
                unknowns.append(f"{here}: defect ledger missing")
                defects = []
            if claim.get("status") == "PASS" and defects:
                errors.append(f"{here}: PASS claim retains delivery defects")

            if scope in {"exhaustive", "fleet"}:
                for field in ("population_identity", "coverage_proof"):
                    if not isinstance(claim.get(field), str) or not claim[field].strip():
                        unknowns.append(f"{here}: {field} missing for exhaustive scope")
                expected = claim.get("expected_count")
                covered = claim.get("covered_count")
                unknown_count = claim.get("unknown_count")
                if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (expected, covered, unknown_count)):
                    unknowns.append(f"{here}: exhaustive counts are missing or invalid")
                elif covered + unknown_count != expected:
                    errors.append(f"{here}: exhaustive counts do not reconcile")
                elif claim.get("status") == "PASS" and (covered != expected or unknown_count != 0):
                    errors.append(f"{here}: exhaustive PASS does not cover the full population")
                verdicts = claim.get("per_item_verdicts")
                if not isinstance(verdicts, list) or not verdicts:
                    unknowns.append(f"{here}: per-item verdicts missing for exhaustive scope")
                elif isinstance(expected, int) and len(verdicts) != expected:
                    errors.append(f"{here}: per-item verdict count differs from expected population")

            if claim_type == "numeric":
                for field in ("unit", "source", "measured_at"):
                    if not isinstance(claim.get(field), str) or not claim[field].strip():
                        unknowns.append(f"{here}: numeric {field} missing")
                for field in ("claimed_value", "measured_value", "delta"):
                    if not _number(claim.get(field)):
                        unknowns.append(f"{here}: numeric {field} is unmeasured")
                if all(_number(claim.get(field)) for field in ("claimed_value", "measured_value", "delta")):
                    expected_delta = claim["measured_value"] - claim["claimed_value"]
                    if abs(expected_delta - claim["delta"]) > 1e-9:
                        errors.append(f"{here}: numeric delta does not reconcile")

            if claim_type == "fixed":
                if claim.get("before_state") != "FAIL" or claim.get("after_state") != "PASS":
                    errors.append(f"{here}: fixed claim lacks FAIL-before/PASS-after evidence")
                for field in ("reproducer_identity", "non_regression_refs"):
                    value = claim.get(field)
                    if (field.endswith("refs") and (not isinstance(value, list) or not value)) or (
                        not field.endswith("refs") and (not isinstance(value, str) or not value.strip())
                    ):
                        unknowns.append(f"{here}: {field} missing for fixed claim")

            if claim_type in {"deployed", "synchronized"}:
                if action_state != "read_back":
                    errors.append(f"{here}: deployment or synchronization claim is not externally read back")
                for field in ("source_revision", "deployed_version", "rollback_identity"):
                    if not isinstance(claim.get(field), str) or not claim[field].strip():
                        unknowns.append(f"{here}: {field} missing for deployment claim")
                if claim.get("destination_read_back") is not True:
                    errors.append(f"{here}: destination read-back did not pass")
                probes = claim.get("behavior_probe_refs")
                if not isinstance(probes, list) or not probes:
                    unknowns.append(f"{here}: behavior probes missing for deployment claim")

    repair_policy = policy.get("repair_guidance") or {}
    required_repair = set(repair_policy.get("required_fields") or ())
    repair_requests = interaction.get("repair_requests")
    if not isinstance(repair_requests, list) or not repair_requests:
        unknowns.append("structured repair requests missing")
    else:
        count += len(repair_requests)
        for index, request in enumerate(repair_requests):
            here = f"interaction_integrity.repair_requests[{index}]"
            if not isinstance(request, dict):
                unknowns.append(f"{here}: repair request is not an object")
                continue
            for field in required_repair:
                value = request.get(field)
                if value is None or value == "" or value == []:
                    unknowns.append(f"{here}: {field} missing")
            attempt = request.get("attempt")
            maximum = request.get("max_attempts")
            if not all(isinstance(value, int) and not isinstance(value, bool) for value in (attempt, maximum)):
                unknowns.append(f"{here}: attempt budget is invalid")
            elif attempt < 1 or maximum < 1 or attempt > maximum:
                errors.append(f"{here}: repair attempt exceeds the declared budget")
            if request.get("authority_after") != request.get("authority_before"):
                errors.append(f"{here}: repair request changed authority")
    return errors, unknowns, count


def validate_capability_sync(record: dict) -> dict:
    """Prove function parity across the declared FAMES fleet, not package parity alone."""
    try:
        protocol = _read_json(PACKAGE_ROOT / PROTOCOL_TARGETS["FAMES"])
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "state": "UNKNOWN", "errors": [f"capability policy unreadable: {exc}"]}
    policy = ((protocol.get("fleet_topology") or {}).get("capability_convergence") or {})
    if not policy:
        return {"ok": False, "state": "UNKNOWN", "errors": ["capability convergence policy missing"]}
    if not isinstance(record, dict):
        return {"ok": False, "state": "UNKNOWN", "errors": ["record is not an object"]}

    errors: list[str] = []
    unknowns: list[str] = []
    identity = record.get("generation_identity")
    if not isinstance(identity, dict):
        unknowns.append("generation identity missing")
        identity = {}
    identity_fields = tuple(policy.get("generation_identity") or ())
    for field in identity_fields:
        if not isinstance(identity.get(field), str) or not identity[field].strip():
            unknowns.append(f"generation identity missing: {field}")

    expected_hosts = []
    for host in policy.get("expected_hosts") or ():
        try:
            expected_hosts.append(_contributor_id(host))
        except ValueError:
            unknowns.append(f"policy host identity invalid: {host!r}")
    declared_hosts = record.get("expected_hosts")
    if not isinstance(declared_hosts, list):
        unknowns.append("expected host ledger missing")
        declared_hosts = []
    try:
        declared_hosts = [_contributor_id(host) for host in declared_hosts]
    except (TypeError, ValueError):
        unknowns.append("declared host identity invalid")
        declared_hosts = []
    if declared_hosts and (len(set(declared_hosts)) != len(declared_hosts) or set(declared_hosts) != set(expected_hosts)):
        errors.append("declared host set does not equal the policy host set")

    capabilities = record.get("capability_manifest")
    if not isinstance(capabilities, list) or not capabilities:
        unknowns.append("capability manifest missing")
        capabilities = []
    capability_by_id: dict[str, dict] = {}
    for index, capability in enumerate(capabilities):
        here = f"capability_manifest[{index}]"
        if not isinstance(capability, dict):
            unknowns.append(f"{here}: capability is not an object")
            continue
        capability_id = capability.get("capability_id")
        if not isinstance(capability_id, str) or not capability_id.strip():
            unknowns.append(f"{here}: capability identity missing")
            continue
        if capability_id in capability_by_id:
            errors.append(f"{here}: duplicate capability identity")
        capability_by_id[capability_id] = capability
        for field in ("contract_version", "validator_identity"):
            if not isinstance(capability.get(field), str) or not capability[field].strip():
                unknowns.append(f"{here}: {field} missing")
        required_hosts = capability.get("required_hosts")
        if not isinstance(required_hosts, list) or not required_hosts:
            unknowns.append(f"{here}: required hosts missing")
        else:
            try:
                normalized = {_contributor_id(host) for host in required_hosts}
            except (TypeError, ValueError):
                unknowns.append(f"{here}: required host identity invalid")
                normalized = set()
            if not normalized.issubset(set(expected_hosts)):
                errors.append(f"{here}: required host is outside the policy fleet")

    receipts = record.get("host_receipts")
    if not isinstance(receipts, list) or not receipts:
        unknowns.append("host receipts missing")
        receipts = []
    receipt_hosts: list[str] = []
    max_freshness = policy.get("max_freshness_seconds", 3600)
    for index, receipt in enumerate(receipts):
        here = f"host_receipts[{index}]"
        if not isinstance(receipt, dict):
            unknowns.append(f"{here}: receipt is not an object")
            continue
        try:
            host = _contributor_id(receipt.get("host"))
        except (TypeError, ValueError):
            unknowns.append(f"{here}: host identity missing")
            continue
        receipt_hosts.append(host)
        if receipt.get("runner_state") != "armed":
            errors.append(f"{here}: convergence runner is not armed")
        for field in identity_fields:
            if receipt.get(field) != identity.get(field):
                errors.append(f"{here}: {field} differs from the expected generation")
        if not isinstance(receipt.get("observed_at"), str) or not receipt["observed_at"].strip():
            unknowns.append(f"{here}: observation timestamp missing")
        freshness = receipt.get("freshness_seconds")
        if not _number(freshness) or freshness < 0:
            unknowns.append(f"{here}: freshness is unmeasured")
        elif freshness > max_freshness:
            errors.append(f"{here}: receipt is stale")
        rows = receipt.get("capabilities")
        if not isinstance(rows, list):
            unknowns.append(f"{here}: capability results missing")
            rows = []
        result_by_id = {
            row.get("capability_id"): row for row in rows
            if isinstance(row, dict) and isinstance(row.get("capability_id"), str)
        }
        for capability_id, capability in capability_by_id.items():
            try:
                required = {_contributor_id(item) for item in capability.get("required_hosts") or []}
            except (TypeError, ValueError):
                required = set()
            if host not in required:
                continue
            result = result_by_id.get(capability_id)
            if not isinstance(result, dict):
                errors.append(f"{here}: required capability missing: {capability_id}")
                continue
            state = result.get("state")
            if state == "PASS":
                if result.get("validator_exit") != 0:
                    errors.append(f"{here}.{capability_id}: validator did not exit zero")
                for field in ("positive_control", "negative_control_rejected", "caller_backed"):
                    if result.get(field) is not True:
                        errors.append(f"{here}.{capability_id}: {field} did not pass")
                refs = result.get("evidence_refs")
                if not isinstance(refs, list) or not refs:
                    unknowns.append(f"{here}.{capability_id}: evidence references missing")
            elif state == "N/A":
                if result.get("activation_predicate_false") is not True:
                    errors.append(f"{here}.{capability_id}: N/A lacks a false activation predicate")
                refs = result.get("predicate_evidence_refs")
                if not isinstance(refs, list) or not refs:
                    unknowns.append(f"{here}.{capability_id}: N/A predicate evidence missing")
            elif state in {"FAIL", "UNKNOWN"}:
                errors.append(f"{here}.{capability_id}: capability state is {state}")
            else:
                unknowns.append(f"{here}.{capability_id}: capability state is unknown")

    if len(set(receipt_hosts)) != len(receipt_hosts):
        errors.append("duplicate host receipt")
    if set(receipt_hosts) != set(expected_hosts):
        errors.append("host receipts do not cover the exact policy fleet")
    if record.get("full_convergence_claim") is not True:
        unknowns.append("full capability convergence was not claimed")
    return {
        "ok": not errors and not unknowns,
        "state": "UNKNOWN" if unknowns else ("PASS" if not errors else "FAIL"),
        "hosts": len(receipt_hosts),
        "capabilities": len(capability_by_id),
        "errors": errors + unknowns,
    }


def validate_cognitive(record: dict) -> dict:
    """Validate one trace or a suite of traces against the bundled operator policy."""
    layer, problem = _cognitive_contract()
    if problem:
        return {"ok": False, "state": "UNKNOWN", "traces": 0, "errors": [problem]}
    if not isinstance(record, dict):
        return {"ok": False, "state": "UNKNOWN", "traces": 0, "errors": ["record is not an object"]}
    traces = record.get("traces")
    errors: list[str] = []
    unknowns: list[str] = []
    trace_count = 0
    if traces is not None:
        if not isinstance(traces, list) or not traces:
            unknowns.append("traces missing")
        else:
            trace_count = len(traces)
            for index, trace in enumerate(traces):
                errors.extend(_validate_cognitive_trace(trace, layer, index))
    meticulousness_count = 0
    if "meticulousness" in record:
        quality_errors, quality_unknowns, meticulousness_count = _validate_meticulousness(record, layer)
        errors.extend(quality_errors)
        unknowns.extend(quality_unknowns)
    interaction_count = 0
    if "interaction_integrity" in record:
        interaction_errors, interaction_unknowns, interaction_count = _validate_interaction(record, layer)
        errors.extend(interaction_errors)
        unknowns.extend(interaction_unknowns)
        errors.extend(_validate_boundary_gate(
            record,
            context="validate_cognitive interaction",
            force_required=True,
            expected_caller="validate_cognitive",
            expected_interaction_identity=_stable_sha(record.get("interaction_integrity") or {}),
        ))
    if traces is None and "meticulousness" not in record and "interaction_integrity" not in record:
        unknowns.append("traces, meticulousness, or interaction-integrity checks missing")
    return {
        "ok": not errors and not unknowns,
        "state": "UNKNOWN" if unknowns else ("PASS" if not errors else "FAIL"),
        "traces": trace_count,
        "meticulousness": meticulousness_count,
        "interaction_integrity": interaction_count,
        "errors": errors + unknowns,
    }


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _content_ref_errors(value: object, label: str, replay: bool = False) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} is not a content-addressed reference"]
    errors: list[str] = []
    if not isinstance(value.get("uri"), str) or not value["uri"].strip():
        errors.append(f"{label}.uri missing")
    if not SHA256_RE.fullmatch(str(value.get("sha256") or "").lower()):
        errors.append(f"{label}.sha256 is not a full content hash")
    if replay:
        path = value.get("path")
        if not isinstance(path, str) or not path:
            errors.append(f"{label}.path missing for replay")
        else:
            target = Path(path)
            if not target.is_file():
                errors.append(f"{label}.path does not exist")
            elif SHA256_RE.fullmatch(str(value.get("sha256") or "").lower()) and _sha256(target) != str(value["sha256"]).lower():
                errors.append(f"{label}.sha256 does not match replayed content")
    return errors


def _active_workspace() -> Path:
    for candidate in (PACKAGE_ROOT, *PACKAGE_ROOT.parents):
        if (candidate / "_registry" / "fames-protocol.json").is_file():
            return candidate
    return PACKAGE_ROOT.parents[2]


def _bound_json_receipt_errors(value: object, label: str, expected: dict) -> list[str]:
    errors = _content_ref_errors(value, label, replay=True)
    if errors or not isinstance(value, dict):
        return errors
    try:
        payload = _read_json(Path(str(value["path"])))
    except (OSError, json.JSONDecodeError) as exc:
        return [*errors, f"{label} receipt unreadable ({exc.__class__.__name__})"]
    for field, wanted in expected.items():
        if payload.get(field) != wanted:
            errors.append(f"{label} receipt {field} mismatch")
    errors.extend(_receipt_window_errors(payload, f"{label} receipt"))
    return errors


def _receipt_window_errors(value: object, label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} receipt window missing"]
    executed_at = _parse_time(value.get("executed_at"))
    valid_until = _parse_time(value.get("valid_until"))
    now = datetime.now(timezone.utc)
    if executed_at is None or valid_until is None:
        return [f"{label} receipt window is invalid"]
    if executed_at > now or valid_until <= executed_at or valid_until <= now:
        return [f"{label} receipt is future-dated or expired"]
    return []


def _boundary_review_subject_identity(value: object) -> str:
    volatile = {
        "measured_at", "last_checked_at", "valid_until", "executed_at",
        "expires_at", "retracted_at", "evaluated_at",
    }

    def freeze(node: object) -> object:
        if isinstance(node, dict):
            return {key: freeze(item) for key, item in node.items() if key not in volatile}
        if isinstance(node, list):
            return [freeze(item) for item in node]
        return node

    return _stable_sha(freeze(value))


def _promotion_non_regression() -> dict:
    validator_path = Path(__file__).resolve()
    cases_path = (PACKAGE_ROOT / CASES_TARGET).resolve()
    try:
        manifest = _read_json(PACKAGE_ROOT / MANIFEST_NAME)
    except (OSError, json.JSONDecodeError):
        manifest = {}
    package_check = verify_package(PACKAGE_ROOT)
    suite_input = {
        "case_ids": list(PROMOTION_NON_REGRESSION_CASES),
        "package_identity": manifest.get("package_sha"),
        "validator_identity": _sha256(validator_path),
        "cases_identity": _sha256(cases_path) if cases_path.is_file() else None,
    }
    outcome = run_cases(_active_workspace(), PACKAGE_ROOT, list(PROMOTION_NON_REGRESSION_CASES))
    suite_output = {
        "ok": outcome.get("ok"),
        "cases": outcome.get("cases"),
        "residual": outcome.get("residual"),
        "errors": outcome.get("errors"),
        "degraded": outcome.get("degraded"),
        "package_errors": package_check.get("errors"),
    }
    passed = package_check.get("ok") is True and outcome.get("ok") is True
    return {
        **suite_input,
        "input_identity": _stable_sha(suite_input),
        "output_identity": _stable_sha(suite_output),
        "state": "PASS" if passed else "FAIL",
        "exit_status": 0 if passed else 1,
    }


def _metric_expected_pass(metric: dict) -> bool | None:
    value, threshold = metric.get("value"), metric.get("threshold")
    comparator = metric.get("comparator")
    if isinstance(value, bool) or isinstance(threshold, bool):
        return value == threshold if comparator == "eq" else None
    if not isinstance(value, (int, float)) or not isinstance(threshold, (int, float)):
        return None
    return {"ge": value >= threshold, "le": value <= threshold, "eq": value == threshold}.get(comparator)


def _prompt_compilation_findings(
    record: object,
    policy: dict,
    *,
    goal_identity: object,
) -> tuple[list[str], list[str]]:
    """Validate RB reach from the current user prompt through Ti.

    The receipt is deliberately content-free: it binds prompt/session identities and
    coverage structure without persisting the operator's raw prompt.
    """
    errors: list[str] = []
    unknowns: list[str] = []
    if not isinstance(record, dict):
        return errors, ["prompt compilation record missing"]
    if record.get("state") != "PASS":
        errors.append("prompt compilation state is not PASS")

    receipt = record.get("turn_receipt")
    if not isinstance(receipt, dict):
        receipt = {}
        unknowns.append("prompt compilation turn receipt missing")
    required_receipt = tuple(((policy.get("turn_refresh_contract") or {}).get("receipt_fields") or ()))
    for field in required_receipt:
        if field not in receipt or receipt.get(field) in (None, "", []):
            unknowns.append(f"prompt compilation turn_receipt.{field} missing")
    for field in (
        "session_identity_sha", "prompt_identity", "package_sha",
        "prompt_contract_identity", "adapter_identity", "rule_or_context_identity",
    ):
        if field in receipt and not SHA256_RE.fullmatch(str(receipt.get(field) or "").lower()):
            errors.append(f"prompt compilation turn_receipt.{field} is not SHA-256")
    if receipt.get("prompt_contract_identity") != _stable_sha(policy):
        errors.append("prompt compilation contract identity differs from active policy")
    try:
        manifest = _read_json(PACKAGE_ROOT / MANIFEST_NAME)
    except (OSError, json.JSONDecodeError):
        manifest = {}
        unknowns.append("prompt compilation package manifest unreadable")
    if manifest:
        if receipt.get("package_sha") != manifest.get("package_sha"):
            errors.append("prompt compilation package identity is stale")
        if receipt.get("skill_gen") != manifest.get("skill_gen"):
            errors.append("prompt compilation generation is stale")
    if receipt.get("read_back") is not True:
        errors.append("prompt compilation rule or context was not read back")
    if receipt.get("raw_prompt_persisted") is not False:
        errors.append("prompt compilation receipt persisted raw prompt material")

    source = record.get("source")
    if not isinstance(source, dict):
        source = {}
        unknowns.append("prompt compilation source binding missing")
    prompt_chars = source.get("prompt_chars")
    if not isinstance(prompt_chars, int) or isinstance(prompt_chars, bool) or prompt_chars <= 0:
        unknowns.append("prompt compilation source.prompt_chars invalid")
        prompt_chars = 0
    if source.get("prompt_identity") != receipt.get("prompt_identity"):
        errors.append("prompt compilation source and turn prompt identities differ")
    if source.get("goal_identity") != goal_identity:
        errors.append("prompt compilation source goal identity mismatch")

    intents = record.get("intent_ledger")
    if not isinstance(intents, list) or not intents:
        intents = []
        unknowns.append("prompt compilation intent ledger missing")
    intent_kinds = set(policy.get("intent_kinds") or ())
    intent_ids: set[str] = set()
    load_bearing_ids: set[str] = set()
    intent_to_clauses: dict[str, set[str]] = {}
    for index, intent in enumerate(intents):
        here = f"prompt compilation intent_ledger[{index}]"
        if not isinstance(intent, dict):
            unknowns.append(f"{here} invalid")
            continue
        intent_id = intent.get("id")
        if not isinstance(intent_id, str) or not intent_id:
            unknowns.append(f"{here}.id missing")
            continue
        if intent_id in intent_ids:
            errors.append(f"{here}.id duplicated")
        intent_ids.add(intent_id)
        if intent.get("kind") not in intent_kinds:
            errors.append(f"{here}.kind undeclared")
        if not isinstance(intent.get("statement"), str) or not intent["statement"].strip():
            unknowns.append(f"{here}.statement missing")
        if not isinstance(intent.get("load_bearing"), bool):
            unknowns.append(f"{here}.load_bearing invalid")
        elif intent["load_bearing"]:
            load_bearing_ids.add(intent_id)
        spans = intent.get("source_spans")
        if not isinstance(spans, list) or not spans:
            unknowns.append(f"{here}.source_spans missing")
        else:
            for span_index, span in enumerate(spans):
                if (
                    not isinstance(span, dict)
                    or not isinstance(span.get("start"), int)
                    or isinstance(span.get("start"), bool)
                    or not isinstance(span.get("end"), int)
                    or isinstance(span.get("end"), bool)
                    or span.get("start", -1) < 0
                    or span.get("end", 0) <= span.get("start", -1)
                    or (prompt_chars and span.get("end", 0) > prompt_chars)
                ):
                    errors.append(f"{here}.source_spans[{span_index}] is outside the prompt")
        mapped = intent.get("prompt_clause_ids")
        if not isinstance(mapped, list):
            mapped = []
            unknowns.append(f"{here}.prompt_clause_ids invalid")
        intent_to_clauses[intent_id] = {str(item) for item in mapped if isinstance(item, str) and item}
        if intent_id in load_bearing_ids and not intent_to_clauses[intent_id]:
            errors.append(f"{here} load-bearing intent is not mapped to a prompt clause")

    clauses = record.get("prompt_clauses")
    if not isinstance(clauses, list) or not clauses:
        clauses = []
        unknowns.append("prompt compilation prompt clauses missing")
    required_sections = set(policy.get("required_prompt_sections") or ())
    allowed_evidence = set(policy.get("evidence_requirements") or ())
    allowed_authority_effects = set(policy.get("authority_effects") or ())
    clause_ids: set[str] = set()
    sections_seen: set[str] = set()
    clause_to_ti: dict[str, set[str]] = {}
    for index, clause in enumerate(clauses):
        here = f"prompt compilation prompt_clauses[{index}]"
        if not isinstance(clause, dict):
            unknowns.append(f"{here} invalid")
            continue
        clause_id = clause.get("id")
        if not isinstance(clause_id, str) or not clause_id:
            unknowns.append(f"{here}.id missing")
            continue
        if clause_id in clause_ids:
            errors.append(f"{here}.id duplicated")
        clause_ids.add(clause_id)
        section = clause.get("section")
        if section not in required_sections:
            errors.append(f"{here}.section undeclared")
        else:
            sections_seen.add(str(section))
        if not isinstance(clause.get("requirement"), str) or not clause["requirement"].strip():
            unknowns.append(f"{here}.requirement missing")
        linked_intents = clause.get("intent_ids")
        if not isinstance(linked_intents, list) or not linked_intents:
            unknowns.append(f"{here}.intent_ids missing")
        elif any(item not in intent_ids for item in linked_intents):
            errors.append(f"{here} names an unknown intent")
        if clause.get("evidence_required") not in allowed_evidence:
            errors.append(f"{here}.evidence_required undeclared")
        if clause.get("authority_effect") not in allowed_authority_effects:
            errors.append(f"{here}.authority_effect undeclared or expanding")
        ti_ids = clause.get("ti_invariant_ids")
        if not isinstance(ti_ids, list) or not ti_ids:
            ti_ids = []
            errors.append(f"{here} is not bound to Ti")
        clause_to_ti[clause_id] = {str(item) for item in ti_ids if isinstance(item, str) and item}
    missing_sections = sorted(required_sections - sections_seen)
    if missing_sections:
        unknowns.append("prompt compilation sections missing " + ", ".join(missing_sections))
    for intent_id, mapped in intent_to_clauses.items():
        if any(clause_id not in clause_ids for clause_id in mapped):
            errors.append(f"prompt compilation intent {intent_id} names an unknown clause")

    invariants = record.get("ti_invariants")
    if not isinstance(invariants, list) or not invariants:
        invariants = []
        unknowns.append("prompt compilation Ti invariants missing")
    ti_ids: set[str] = set()
    ti_clause_links: set[str] = set()
    required_ti_fields = set(policy.get("required_ti_fields") or ())
    terminal_states = set(policy.get("terminal_states") or ())
    for index, invariant in enumerate(invariants):
        here = f"prompt compilation ti_invariants[{index}]"
        if not isinstance(invariant, dict):
            unknowns.append(f"{here} invalid")
            continue
        invariant_id = invariant.get("id")
        if not isinstance(invariant_id, str) or not invariant_id:
            unknowns.append(f"{here}.id missing")
            continue
        if invariant_id in ti_ids:
            errors.append(f"{here}.id duplicated")
        ti_ids.add(invariant_id)
        linked_clauses = invariant.get("clause_ids")
        if not isinstance(linked_clauses, list) or not linked_clauses:
            unknowns.append(f"{here}.clause_ids missing")
        else:
            if any(item not in clause_ids for item in linked_clauses):
                errors.append(f"{here} names an unknown prompt clause")
            ti_clause_links.update(str(item) for item in linked_clauses if isinstance(item, str))
        for field in required_ti_fields - {"terminal_state"}:
            if not isinstance(invariant.get(field), str) or not invariant[field].strip():
                unknowns.append(f"{here}.{field} missing")
        if invariant.get("terminal_state") not in terminal_states:
            errors.append(f"{here}.terminal_state undeclared")
    for clause_id, mapped in clause_to_ti.items():
        if any(ti_id not in ti_ids for ti_id in mapped):
            errors.append(f"prompt compilation clause {clause_id} names an unknown Ti invariant")
        if clause_id not in ti_clause_links:
            errors.append(f"prompt compilation clause {clause_id} has no reciprocal Ti binding")

    coverage = record.get("coverage")
    if not isinstance(coverage, dict):
        coverage = {}
        unknowns.append("prompt compilation coverage ledger missing")
    mapped_load_bearing = {intent_id for intent_id in load_bearing_ids if intent_to_clauses.get(intent_id)}
    ti_bound_clauses = {clause_id for clause_id in clause_ids if clause_to_ti.get(clause_id) and clause_id in ti_clause_links}
    expected_counts = {
        "load_bearing_intent_count": len(load_bearing_ids),
        "mapped_load_bearing_intent_count": len(mapped_load_bearing),
        "prompt_clause_count": len(clause_ids),
        "ti_bound_prompt_clause_count": len(ti_bound_clauses),
    }
    for field, expected in expected_counts.items():
        if coverage.get(field) != expected:
            errors.append(f"prompt compilation coverage.{field} does not reconcile")
    expected_unmapped = sorted(load_bearing_ids - mapped_load_bearing)
    if coverage.get("unmapped_load_bearing_ids") != expected_unmapped:
        errors.append("prompt compilation unmapped intent ledger does not reconcile")
    expected_unbound = sorted(clause_ids - ti_bound_clauses)
    if coverage.get("unbound_prompt_clause_ids") != expected_unbound:
        errors.append("prompt compilation unbound clause ledger does not reconcile")
    if expected_unmapped or expected_unbound:
        errors.append("prompt compilation reach is not closed")

    before, after = record.get("authority_before"), record.get("authority_after")
    if (
        not isinstance(before, list) or not isinstance(after, list)
        or any(not isinstance(item, str) or not item or "*" in item or "?" in item for item in (before or []) + (after or []))
    ):
        unknowns.append("prompt compilation authority ledger invalid")
    elif not set(after).issubset(set(before)):
        errors.append("prompt compilation expanded authority")
    if not isinstance(record.get("uncertainties"), list):
        unknowns.append("prompt compilation uncertainty ledger missing")
    return errors, unknowns


def validate_cognitive_boundary(record: dict) -> dict:
    """Validate a replayable, expiring RB map and truth-preserving interface."""
    layer, problem = _cognitive_contract()
    if problem:
        return {"ok": False, "state": "UNKNOWN", "cells": 0, "errors": [problem]}
    policy = layer.get("cognitive_boundary")
    if not isinstance(policy, dict) or not isinstance(record, dict):
        return {"ok": False, "state": "UNKNOWN", "cells": 0, "errors": ["RB policy or record missing"]}

    errors: list[str] = []
    unknowns: list[str] = []
    now = datetime.now(timezone.utc)

    def require_text(obj: dict, fields: tuple[str, ...], prefix: str) -> None:
        for field in fields:
            if not isinstance(obj.get(field), str) or not obj[field].strip():
                unknowns.append(f"{prefix}{field} missing")

    def valid_window(start: object, end: object, label: str) -> None:
        measured, expires = _parse_time(start), _parse_time(end)
        if measured is None or expires is None:
            unknowns.append(f"{label} time is invalid")
        elif measured > now or expires <= measured or expires <= now:
            errors.append(f"{label} is future-dated or expired")

    require_text(record, ("boundary_id", "subject_identity", "goal_identity"), "")
    if record.get("policy_identity") != _stable_sha(policy):
        errors.append("policy identity does not match the active RB contract")
    if record.get("validator_identity") != _sha256(Path(__file__).resolve()):
        errors.append("validator identity does not match the executing validator")
    valid_window(record.get("measured_at"), record.get("valid_until"), "boundary record")
    boundary_until = _parse_time(record.get("valid_until"))

    population = record.get("population")
    if not isinstance(population, dict):
        population = {}
        unknowns.append("population manifest missing")
    units = set((policy.get("population_contract") or {}).get("units") or ())
    if population.get("unit") not in units:
        unknowns.append("population unit is undeclared")
    members = population.get("members")
    if not isinstance(members, list) or not members:
        members = []
        unknowns.append("population members missing")
    member_ids: list[str] = []
    for index, member in enumerate(members):
        here = f"population.members[{index}]"
        if not isinstance(member, dict):
            unknowns.append(f"{here} invalid")
            continue
        require_text(member, ("id",), f"{here}.")
        if isinstance(member.get("id"), str):
            member_ids.append(member["id"])
        errors.extend(_content_ref_errors(member.get("evidence"), f"{here}.evidence"))
    if len(member_ids) != len(set(member_ids)):
        errors.append("population member ids are not unique")

    sample = population.get("sample_plan")
    if not isinstance(sample, dict):
        sample = {}
        unknowns.append("population sample plan missing")
    if sample.get("method") not in {"exhaustive", "random", "stratified", "bounded"}:
        unknowns.append("population sampling method is undeclared")
    require_text(sample, ("distribution_identity", "inclusion_rule"), "population.sample_plan.")
    errors.extend(_content_ref_errors(sample.get("evidence"), "population.sample_plan.evidence"))

    verdicts = population.get("member_verdicts")
    if not isinstance(verdicts, list):
        verdicts = []
        unknowns.append("population member verdicts missing")
    covered: set[str] = set()
    for index, verdict in enumerate(verdicts):
        here = f"population.member_verdicts[{index}]"
        if not isinstance(verdict, dict):
            unknowns.append(f"{here} invalid")
            continue
        member_id = verdict.get("member_id")
        if member_id not in member_ids:
            errors.append(f"{here} names an unknown member")
        elif member_id in covered:
            errors.append(f"{here} duplicates a member verdict")
        else:
            covered.add(member_id)
        refs = verdict.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            unknowns.append(f"{here}.evidence_refs missing")
        else:
            for ref_index, ref in enumerate(refs):
                errors.extend(_content_ref_errors(ref, f"{here}.evidence_refs[{ref_index}]"))

    counts: dict[str, int] = {}
    for field in ("expected_count", "covered_count", "unknown_count"):
        value = population.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            unknowns.append(f"population.{field} invalid")
        else:
            counts[field] = value
    if len(counts) == 3:
        if counts["expected_count"] != len(member_ids):
            errors.append("population expected_count does not equal member manifest size")
        if counts["covered_count"] != len(covered):
            errors.append("population covered_count does not equal member verdict count")
        if counts["unknown_count"] != counts["expected_count"] - counts["covered_count"]:
            errors.append("population counts do not reconcile")
        if counts["unknown_count"] > 0:
            unknowns.append("population contains UNKNOWN members")
    if population.get("identity") != _stable_sha({"unit": population.get("unit"), "members": members, "sample_plan": sample}):
        errors.append("population identity does not match its manifest and sample plan")

    cells = record.get("cells")
    if not isinstance(cells, list) or not cells:
        cells = []
        unknowns.append("boundary cells missing")
    required_coordinates = set(policy.get("required_coordinates") or ())
    required_metrics = set(policy.get("required_metrics") or ())
    allowed_states = set(policy.get("states") or ())
    cell_states: dict[str, str] = {}
    supported_ids: set[str] = set()
    for index, cell in enumerate(cells):
        here = f"cells[{index}]"
        if not isinstance(cell, dict):
            unknowns.append(f"{here} invalid")
            continue
        cell_id = cell.get("id")
        if not isinstance(cell_id, str) or not cell_id:
            unknowns.append(f"{here}.id missing")
            cell_id = f"<unknown-{index}>"
        if cell_id in cell_states:
            errors.append(f"{here}.id duplicated")
        state = cell.get("state")
        cell_states[cell_id] = str(state)
        if state not in allowed_states:
            unknowns.append(f"{here}.state unknown")
        coordinates = cell.get("coordinates")
        if not isinstance(coordinates, dict):
            unknowns.append(f"{here}.coordinates missing")
        else:
            missing = sorted(key for key in required_coordinates if not isinstance(coordinates.get(key), str) or not coordinates[key])
            if missing:
                unknowns.append(f"{here}.coordinates missing {', '.join(missing)}")
            if coordinates.get("distribution") != sample.get("distribution_identity"):
                errors.append(f"{here}.coordinates.distribution does not match the population sample plan")

        if state == "FORBIDDEN":
            invariant = cell.get("controlling_invariant")
            if not isinstance(invariant, dict):
                unknowns.append(f"{here}.controlling_invariant missing")
            else:
                require_text(invariant, ("policy_identity", "authority_identity", "version", "reason", "valid_until"), f"{here}.controlling_invariant.")
                if _parse_time(invariant.get("valid_until")) is None:
                    unknowns.append(f"{here}.controlling_invariant expiry invalid")
            continue
        if state == "UNKNOWN":
            if not isinstance(cell.get("unknown_reasons"), list) or not cell["unknown_reasons"]:
                unknowns.append(f"{here}.unknown_reasons missing")
            unknowns.append(f"{here} is UNKNOWN")
            continue

        valid_window(cell.get("measured_at"), cell.get("valid_until"), here)
        cell_until = _parse_time(cell.get("valid_until"))
        if boundary_until and cell_until and cell_until > boundary_until:
            errors.append(f"{here} validity exceeds the boundary record")
        metrics = cell.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
            unknowns.append(f"{here}.metrics missing")
        missing_metrics = sorted(required_metrics - set(metrics))
        if missing_metrics:
            unknowns.append(f"{here}.metrics missing {', '.join(missing_metrics)}")
        failed: list[str] = []
        evidence_hashes: set[str] = set()
        for name in sorted(required_metrics & set(metrics)):
            metric = metrics.get(name)
            metric_here = f"{here}.metrics.{name}"
            if not isinstance(metric, dict):
                unknowns.append(f"{metric_here} invalid")
                continue
            for field in ("value", "unit", "comparator", "threshold", "error_bound", "baseline", "candidate", "measured", "pass", "evidence"):
                if field not in metric:
                    unknowns.append(f"{metric_here}.{field} missing")
            if metric.get("measured") is not True or not isinstance(metric.get("unit"), str) or not metric.get("unit"):
                unknowns.append(f"{metric_here} measurement or unit invalid")
            if not isinstance(metric.get("error_bound"), (int, float)) or isinstance(metric.get("error_bound"), bool) or metric.get("error_bound", -1) < 0:
                unknowns.append(f"{metric_here}.error_bound invalid")
            expected = _metric_expected_pass(metric)
            if expected is None:
                unknowns.append(f"{metric_here} is not replayable")
            elif metric.get("pass") is not expected:
                errors.append(f"{metric_here}.pass contradicts value and threshold")
            if expected is False:
                failed.append(name)
            evidence = metric.get("evidence")
            errors.extend(_content_ref_errors(evidence, f"{metric_here}.evidence"))
            if isinstance(evidence, dict):
                digest = str(evidence.get("sha256") or "")
                if SHA256_RE.fullmatch(digest):
                    if digest in evidence_hashes:
                        errors.append(f"{metric_here} reuses another metric evidence identity")
                    evidence_hashes.add(digest)

        if cell.get("evidence_class") != "measured":
            errors.append(f"{here} uses non-measured evidence")
        if cell.get("positive_control_passed") is not True or cell.get("negative_control_rejected") is not True:
            errors.append(f"{here} controls did not pass")
        if cell.get("fresh") is not True or cell.get("reproducible") is not True:
            errors.append(f"{here} is stale or not reproducible")
        refs = cell.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            unknowns.append(f"{here}.evidence_refs missing")
        else:
            for ref_index, ref in enumerate(refs):
                errors.extend(_content_ref_errors(ref, f"{here}.evidence_refs[{ref_index}]"))
        predicate = cell.get("frozen_predicate_passed")
        if not isinstance(predicate, bool):
            unknowns.append(f"{here}.frozen_predicate_passed invalid")
        if state == "SUPPORTED":
            supported_ids.add(cell_id)
            if failed or predicate is not True:
                errors.append(f"{here} SUPPORTED contradicts metrics or frozen predicate")
        elif state == "LIMITED":
            if not failed or not cell.get("residuals") or not cell.get("safe_operating_limit"):
                errors.append(f"{here} LIMITED lacks failed metrics, residuals, or safe limit")
        elif state == "OUTSIDE" and (not failed or predicate is not False):
            errors.append(f"{here} OUTSIDE requires a failed metric and frozen predicate")

    for index, verdict in enumerate(verdicts):
        if isinstance(verdict, dict):
            cell_id = verdict.get("cell_id")
            if cell_id not in cell_states:
                errors.append(f"population.member_verdicts[{index}] names unknown cell")
            elif verdict.get("state") != cell_states[cell_id]:
                errors.append(f"population.member_verdicts[{index}] state disagrees with cell")

    contract = policy.get("interface_contract") or {}
    interface = record.get("interface")
    if not isinstance(interface, dict):
        interface = {}
        unknowns.append("interface missing")
    canonical = interface.get("canonical_fields")
    presented = interface.get("presented_fields")
    if not isinstance(canonical, dict) or not isinstance(presented, dict):
        canonical, presented = {}, {}
        unknowns.append("canonical or presented structured fields missing")
    if interface.get("canonical_result_identity") != _stable_sha(canonical):
        errors.append("canonical result identity mismatch")
    required_information = set(contract.get("required_information") or ())
    preservation = interface.get("preservation")
    if not isinstance(preservation, list):
        preservation = []
        unknowns.append("interface preservation ledger missing")
    preserved: set[str] = set()
    for index, item in enumerate(preservation):
        here = f"interface.preservation[{index}]"
        if not isinstance(item, dict):
            unknowns.append(f"{here} invalid")
            continue
        field = item.get("field")
        if field in required_information:
            preserved.add(field)
        equal = field in canonical and field in presented and _stable_sha(canonical[field]) == _stable_sha(presented[field])
        if item.get("equivalence_method") != "exact_structured_value" or item.get("preserved") is not equal or not equal:
            errors.append(f"{here} canonical and presented values differ or use a non-deterministic method")
    missing_information = sorted(required_information - preserved)
    if missing_information:
        unknowns.append(f"interface preservation missing {', '.join(missing_information)}")
    if interface.get("style_changes_only") is not True:
        errors.append("interface adaptation is not presentation-only")
    changed = interface.get("changed_dimensions")
    if not isinstance(changed, list) or any(item not in set(contract.get("adaptable_dimensions") or ()) for item in changed):
        errors.append("interface changed an undeclared dimension")
    forbidden_inferences = interface.get("forbidden_inferences")
    if not isinstance(forbidden_inferences, list):
        unknowns.append("forbidden-inference ledger missing")
    elif forbidden_inferences:
        errors.append("interface contains a forbidden stable-trait inference")

    if interface.get("profile_source") not in set(contract.get("profile_sources") or ()) or interface.get("profile_scope") != contract.get("profile_scope"):
        errors.append("interface profile source or scope invalid")
    profile = interface.get("profile_receipt")
    if not isinstance(profile, dict):
        profile = {}
        unknowns.append("profile receipt missing")
    if profile.get("task_identity") != record.get("goal_identity") or not profile.get("session_identity"):
        errors.append("profile receipt is not task/session bound")
    observed = profile.get("observed_facts")
    allowed_observations = set(contract.get("allowed_profile_observations") or ())
    if not isinstance(observed, list) or not observed:
        unknowns.append("profile observed facts missing")
    elif any(not isinstance(item, dict) or item.get("kind") not in allowed_observations or "value" not in item for item in observed):
        errors.append("profile contains undeclared or trait-like observation")
    valid_window(profile.get("measured_at"), profile.get("expires_at"), "profile receipt")
    profile_until = _parse_time(profile.get("expires_at"))
    if boundary_until and profile_until and profile_until > boundary_until:
        errors.append("profile validity exceeds the task boundary")
    if interface.get("profile_source") == "explicit" and profile.get("consent") is not True:
        errors.append("explicit profile lacks consent")
    if interface.get("profile_source") == "measured_session" and profile.get("measured") is not True:
        errors.append("measured-session profile is not measured")
    if not isinstance(profile.get("uncertainty"), str) or not profile["uncertainty"]:
        unknowns.append("profile uncertainty missing")
    errors.extend(_content_ref_errors(profile.get("evidence"), "interface.profile_receipt.evidence"))

    risk_policy = contract.get("risk_policy") or {}
    risk = interface.get("risk_classification")
    if not isinstance(risk, dict):
        risk = {}
        unknowns.append("risk classification missing")
    if risk.get("policy_identity") != _stable_sha(risk_policy):
        errors.append("risk policy identity mismatch")
    categories = risk.get("categories")
    if not isinstance(categories, list):
        categories = []
        unknowns.append("risk categories missing")
    if any(item not in set(risk_policy.get("categories") or ()) for item in categories):
        errors.append("risk category undeclared")
    high_risk = bool(set(categories) & set(risk_policy.get("high_risk_categories") or ()))
    if risk.get("high_risk") is not high_risk:
        errors.append("high-risk flag contradicts frozen policy")
    valid_window(risk.get("evaluated_at"), risk.get("valid_until"), "risk classification")
    risk_until = _parse_time(risk.get("valid_until"))
    if boundary_until and risk_until and risk_until > boundary_until:
        errors.append("risk classification validity exceeds the boundary record")
    errors.extend(_content_ref_errors(risk.get("evidence"), "interface.risk_classification.evidence"))
    if high_risk:
        probe = interface.get("comprehension_probe")
        if interface.get("risk_first") is not True:
            errors.append("high-risk judgment was not presented first")
        if not isinstance(probe, dict) or probe.get("measured") is not True or probe.get("passed") is not True:
            errors.append("high-risk comprehension probe did not pass")
        elif probe.get("result_identity") != interface.get("canonical_result_identity"):
            errors.append("comprehension probe result identity mismatch")
        else:
            errors.extend(_content_ref_errors(probe.get("evidence"), "interface.comprehension_probe.evidence"))

    before, after = interface.get("authority_before"), interface.get("authority_after")
    if not isinstance(before, list) or not isinstance(after, list) or any(not isinstance(item, str) or not item or "*" in item or "?" in item for item in (before or []) + (after or [])):
        before, after = [], []
        unknowns.append("authority grants invalid or wildcarded")
    if not set(after).issubset(set(before)):
        errors.append("interface expanded authority")
    if interface.get("authority_identity_before") != _stable_sha(sorted(before)) or interface.get("authority_identity_after") != _stable_sha(sorted(after)):
        errors.append("authority identity mismatch")

    binding = record.get("binding")
    if not isinstance(binding, dict):
        binding = {}
        unknowns.append("caller binding missing")
    require_text(binding, ("caller", "goal_identity", "result_identity", "authority_scope"), "binding.")
    if binding.get("goal_identity") != record.get("goal_identity"):
        errors.append("caller binding goal identity mismatch")
    if binding.get("result_identity") != interface.get("canonical_result_identity"):
        errors.append("caller binding result identity mismatch")
    if binding.get("authority_scope") not in before or binding.get("authority_scope") not in after:
        errors.append("caller authority scope is absent from the boundary grant set")
    if binding.get("risk_categories") != categories:
        errors.append("caller binding risk categories mismatch")

    prompt_record = record.get("prompt_compilation")
    prompt_required = binding.get("caller") in {"validate_run", "validate_cognitive"}
    if prompt_required or prompt_record is not None:
        prompt_errors, prompt_unknowns = _prompt_compilation_findings(
            prompt_record,
            policy.get("prompt_compilation_contract") or {},
            goal_identity=record.get("goal_identity"),
        )
        errors.extend(prompt_errors)
        unknowns.extend(prompt_unknowns)

    monitor = record.get("monitor")
    if not isinstance(monitor, dict):
        monitor = {}
        unknowns.append("monitor ledger missing")
    monitor_state = monitor.get("state")
    if monitor_state not in {"CURRENT", "REGRESSED", "RETRACTED"}:
        unknowns.append("monitor state invalid")
    if monitor.get("validator_identity") != record.get("validator_identity"):
        errors.append("monitor validator identity mismatch")
    valid_window(monitor.get("last_checked_at"), monitor.get("valid_until"), "monitor")
    monitor_until = _parse_time(monitor.get("valid_until"))
    if boundary_until and monitor_until and monitor_until > boundary_until:
        errors.append("monitor validity exceeds the boundary record")
    refs = monitor.get("regression_probe_refs")
    if not isinstance(refs, list) or not refs:
        unknowns.append("monitor regression probes missing")
    else:
        for index, ref in enumerate(refs):
            errors.extend(_content_ref_errors(ref, f"monitor.regression_probe_refs[{index}]"))
    if monitor_state in {"REGRESSED", "RETRACTED"} and supported_ids:
        errors.append("regressed or retracted map still exposes SUPPORTED cells")
    if monitor_state == "RETRACTED" and (not _parse_time(monitor.get("retracted_at")) or not monitor.get("retraction_reason")):
        unknowns.append("retraction timestamp or reason missing")
    if not isinstance(monitor.get("supersedes"), list):
        unknowns.append("monitor supersedes ledger missing")
    if monitor_state == "CURRENT" and (monitor.get("retracted_at") is not None or monitor.get("retraction_reason") is not None):
        errors.append("CURRENT monitor carries contradictory retraction metadata")

    promotion = record.get("promotion")
    if not isinstance(promotion, dict) or not isinstance(promotion.get("requested"), bool):
        promotion = {}
        unknowns.append("promotion request state missing")
    if promotion.get("requested") is True:
        required = set((policy.get("promotion_contract") or {}).get("required") or ())
        missing = sorted(key for key in required if key not in promotion or promotion.get(key) in (None, "", [], {}))
        if missing:
            unknowns.append(f"promotion missing {', '.join(missing)}")
        for field in ("baseline_identity", "candidate_identity"):
            if not SHA256_RE.fullmatch(str(promotion.get(field) or "").lower()):
                errors.append(f"promotion {field} is not content-addressed")
        expanded = promotion.get("expanded_cell_ids")
        if not isinstance(expanded, list) or not expanded:
            unknowns.append("promotion expanded cells missing")
        elif any(cell_id not in supported_ids for cell_id in expanded):
            errors.append("promotion targets a non-SUPPORTED cell")
        if promotion.get("measured_before_after") is not True:
            errors.append("promotion lacks measured before/after")
        for field in ("positive_controls", "negative_controls"):
            refs = promotion.get(field)
            if not isinstance(refs, list) or not refs:
                unknowns.append(f"promotion.{field} missing")
            else:
                for index, ref in enumerate(refs):
                    errors.extend(_content_ref_errors(ref, f"promotion.{field}[{index}]"))
        non_regression = promotion.get("non_regression")
        if not isinstance(non_regression, dict) or non_regression.get("passed") is not True:
            errors.append("promotion non-regression failed")
        else:
            errors.extend(_content_ref_errors(non_regression.get("evidence"), "promotion.non_regression.evidence"))
        review = promotion.get("independent_review")
        if not isinstance(review, dict) or review.get("accepted") is not True or not review.get("reviewer_identity"):
            errors.append("promotion independent review missing")
        else:
            errors.extend(_content_ref_errors(review.get("evidence"), "promotion.independent_review.evidence"))
        p_before, p_after = promotion.get("authority_before"), promotion.get("authority_after")
        if not isinstance(p_before, list) or not isinstance(p_after, list):
            unknowns.append("promotion authority ledger missing")
        elif not set(p_after).issubset(set(p_before)) or promotion.get("authority_conserved") is not True:
            errors.append("promotion expanded authority")
        if not promotion.get("version_before") or not promotion.get("version_after") or promotion.get("version_before") == promotion.get("version_after") or promotion.get("version_change") is not True:
            errors.append("promotion version change invalid")
        if not promotion.get("generation_before") or not promotion.get("generation_after") or promotion.get("generation_before") == promotion.get("generation_after") or promotion.get("generation_change") is not True:
            errors.append("promotion generation change invalid")
        if promotion.get("validator_identity") != record.get("validator_identity"):
            errors.append("promotion validator identity mismatch")

    return {
        "ok": not errors and not unknowns,
        "state": "UNKNOWN" if unknowns else ("PASS" if not errors else "FAIL"),
        "cells": len(cells),
        "supported": len(supported_ids),
        "unknown_population": counts.get("unknown_count"),
        "errors": errors + unknowns,
    }


def _validate_boundary_gate(
    container: dict,
    context: str,
    force_required: bool,
    expected_caller: str | None = None,
    expected_goal_identity: str | None = None,
    expected_result_identity: str | None = None,
    expected_authority_scope: str | None = None,
    expected_risk_categories: list[str] | None = None,
    expected_interaction_identity: str | None = None,
    expected_source_identity: str | None = None,
    expected_claim_ids: list[str] | None = None,
    expected_artifact_identity: str | None = None,
    expected_candidate_identity: str | None = None,
) -> list[str]:
    gate = container.get("cognitive_boundary_gate")
    if not isinstance(gate, dict):
        return [f"{context}: cognitive_boundary_gate missing"] if force_required else []
    errors: list[str] = []
    if gate.get("required") is not True:
        errors.append(f"{context}: RB gate must be required")
    if not isinstance(gate.get("activation"), list) or not gate["activation"]:
        errors.append(f"{context}: RB activation identity missing")
    boundary = gate.get("record")
    if not isinstance(boundary, dict):
        errors.append(f"{context}: RB record missing")
        return errors
    outcome = validate_cognitive_boundary(boundary)
    if outcome.get("ok") is not True or outcome.get("state") != "PASS":
        errors.append(f"{context}: RB record did not PASS ({'; '.join(outcome.get('errors') or [])[:240]})")
    if expected_goal_identity and boundary.get("goal_identity") != expected_goal_identity:
        errors.append(f"{context}: RB goal identity mismatch")
    binding = boundary.get("binding") if isinstance(boundary.get("binding"), dict) else {}
    comparisons = {
        "caller": expected_caller,
        "result_identity": expected_result_identity,
        "authority_scope": expected_authority_scope,
        "risk_categories": expected_risk_categories,
        "interaction_identity": expected_interaction_identity,
        "source_identity": expected_source_identity,
        "claim_ids": expected_claim_ids,
        "artifact_identity": expected_artifact_identity,
        "candidate_identity": expected_candidate_identity,
    }
    for field, expected in comparisons.items():
        if expected is not None and binding.get(field) != expected:
            errors.append(f"{context}: RB binding {field} mismatch")
    return errors


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
    result = _run_hidden(
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
    allow_same_gen: bool = False,
) -> dict:
    workspace = workspace.resolve()
    package_root = package_root.resolve()
    try:
        previous = _read_json(package_root / MANIFEST_NAME)
    except (OSError, json.JSONDecodeError):
        previous = {}
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

    cases_source = workspace / CASES_SOURCE
    cases_target = package_root / CASES_TARGET
    cases_target.parent.mkdir(parents=True, exist_ok=True)
    if protocol_git_ref:
        cases_target.write_bytes(_git_protocol_blob(workspace, protocol_git_ref, CASES_SOURCE))
    elif cases_source.is_file():
        shutil.copy2(cases_source, cases_target)
    elif not cases_target.is_file():
        raise FileNotFoundError(f"missing source cases: {cases_source}")
    copied[CASES_TARGET] = CASES_SOURCE

    profile_source = workspace / PRODUCTION_PROFILE_SOURCE
    profile_target = package_root / PRODUCTION_PROFILE_TARGET
    profile_target.parent.mkdir(parents=True, exist_ok=True)
    if protocol_git_ref:
        profile_target.write_bytes(_git_protocol_blob(workspace, protocol_git_ref, PRODUCTION_PROFILE_SOURCE))
    elif profile_source.is_file():
        shutil.copy2(profile_source, profile_target)
    elif not profile_target.is_file():
        raise FileNotFoundError(f"missing production delivery profile: {profile_source}")
    copied[PRODUCTION_PROFILE_TARGET] = PRODUCTION_PROFILE_SOURCE

    hardware_source = workspace / HARDWARE_PROFILE_SOURCE
    hardware_target = package_root / HARDWARE_PROFILE_TARGET
    hardware_target.parent.mkdir(parents=True, exist_ok=True)
    if protocol_git_ref:
        hardware_target.write_bytes(_git_protocol_blob(workspace, protocol_git_ref, HARDWARE_PROFILE_SOURCE))
    elif hardware_source.is_file():
        shutil.copy2(hardware_source, hardware_target)
    elif not hardware_target.is_file():
        raise FileNotFoundError(f"missing hardware compute profile: {hardware_source}")
    copied[HARDWARE_PROFILE_TARGET] = HARDWARE_PROFILE_SOURCE

    fames = _read_json(package_root / PROTOCOL_TARGETS["FAMES"])
    expected_files = [
        "SKILL.md",
        "scripts/fames_fleet.py",
        CASES_TARGET,
        PRODUCTION_PROFILE_TARGET,
        HARDWARE_PROFILE_TARGET,
        *PROTOCOL_TARGETS.values(),
    ]
    files = {rel: _sha256(package_root / rel) for rel in sorted(set(expected_files))}
    version = str(fames.get("version") or "")
    generation = _skill_generation(package_root)
    if (
        previous
        and not allow_same_gen
        and previous.get("files") != files
        and previous.get("version") == version
        and previous.get("skill_gen") == generation
    ):
        raise RuntimeError(
            "package contents changed but the generation did not: version "
            f"{version} and FAMES-GEN {generation} already name a different package. "
            "Bump the protocol version or the SKILL.md stamp so followers can order "
            "the two (--allow-same-gen forces)."
        )
    manifest = {
        "schema": 1,
        "id": "FAMES",
        "version": version,
        "skill_gen": generation,
        "execution_order": EXECUTION_ORDER,
        "source_files": copied,
        "source_git_commit": (
            _run_hidden(
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
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.parent / f".{destination.name}.fames-{uuid.uuid4().hex}"
    backup = destination.parent / f".{destination.name}.previous-{uuid.uuid4().hex}"
    shutil.copytree(source, temp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    try:
        if destination.exists():
            destination.replace(backup)
        temp.replace(destination)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if destination.exists() and backup.exists():
            shutil.rmtree(destination)
        if backup.exists():
            backup.replace(destination)
        if temp.exists():
            shutil.rmtree(temp)
        raise


def _seat_root(workspace: Path, host: str) -> Path | None:
    candidates = [host]
    if not host.startswith("ai_"):
        candidates.insert(0, f"ai_{host}")
    for name in candidates:
        target = workspace / name
        if target.is_dir():
            return target
    return None


def _contributor_id(host: str) -> str:
    """Normalize seat ids to the immutable contributor directory vocabulary."""
    normalized = str(host or "").strip().lower()
    if normalized.startswith("ai_"):
        normalized = normalized[3:]
    if normalized not in {"darkhero", "scar3", "altos"}:
        raise ValueError(f"unknown FAMES contributor id: {host!r}")
    return normalized


def _receipt_key(workspace: Path, host: str) -> str:
    """Receipt filename key = the seat directory the host actually resolves to.

    _seat_root normalises `darkhero` -> `ai_darkhero`, so both spellings install to
    the SAME targets; keying the receipt on the raw --host wrote two files for one
    machine and left whichever spelling stopped being used frozen at its old
    version, claiming verified: true forever.
    """
    seat = _seat_root(workspace, host)
    return seat.name if seat is not None else host


def _surfaces(workspace: Path) -> tuple[tuple[str, ...], ...]:
    """Active agent surfaces, from the fleet SSOT when it is reachable.

    Returns only surfaces[] -- removed_surfaces[] is deliberately excluded, that is
    the whole point of the registry carrying both.
    """
    try:
        data = _read_json(workspace / SURFACE_REGISTRY)
    except (OSError, json.JSONDecodeError):
        return ()
    paths = []
    for row in data.get("surfaces") or []:
        path = tuple(str(part) for part in (row.get("path") or []) if part)
        if path and path not in paths:
            paths.append(path)
    return tuple(paths)


def _install_targets(workspace: Path, host: str) -> list[Path]:
    roots = [workspace]
    seat = _seat_root(workspace, host)
    if seat is not None and seat not in roots:
        roots.append(seat)
    surfaces = _surfaces(workspace)
    return [root.joinpath(*surface, "fames") for root in roots for surface in surfaces]


def install(workspace: Path, host: str, source: Path = PACKAGE_ROOT) -> dict:
    workspace = workspace.resolve()
    source = source.resolve()
    source_check = verify_package(source)
    if not source_check["ok"]:
        return {"ok": False, "host": host, "errors": source_check["errors"]}
    targets = _install_targets(workspace, host)
    if not targets:
        return {"ok": False, "host": host, "errors": ["agent surface registry missing or empty"]}
    canonical = workspace / "_skill" / "fleet-skills" / "fames"
    _copy_package(source, canonical)
    for target in targets:
        _copy_package(canonical, target)
    checks = [verify_package(target) for target in targets]
    errors = [error for check in checks for error in check.get("errors", [])]
    key = _receipt_key(workspace, host)
    receipt = {
        "schema": 1,
        "host": key,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "package_sha": source_check["package_sha"],
        "version": source_check["version"],
        "targets": [str(target) for target in targets],
        "verified": not errors,
    }
    if key != host:
        receipt["host_requested"] = host
    _write_json_atomic(workspace / "_registry" / "fames-fleet-receipts" / f"{key}.json", receipt)
    return {"ok": not errors, "receipt": receipt, "errors": errors}


def _source_bytes(base: str, relative: str) -> bytes:
    if base.startswith(("https://", "http://")):
        with urllib.request.urlopen(f"{base.rstrip('/')}/{relative}", timeout=30) as response:
            return response.read()
    return (Path(base) / Path(relative)).read_bytes()


def _resolve_authority_base(authority: str) -> tuple[str, str | None]:
    """Pin a GitHub raw branch URL to the repository's measured commit SHA."""
    if not authority.startswith(("https://", "http://")):
        return authority, None
    parsed = urllib.parse.urlsplit(authority)
    if parsed.netloc.lower() != "raw.githubusercontent.com":
        return authority, None
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 4:
        raise ValueError("GitHub raw authority path is incomplete")
    owner, repo, ref, *tail = parts
    if len(ref) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in ref):
        return authority, ref.lower()
    api = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/commits/{urllib.parse.quote(ref)}"
    request = urllib.request.Request(
        api,
        headers={
            "Accept": "application/vnd.github+json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "FAMES-content-addressed-follower",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    commit = str(payload.get("sha") or "")
    if len(commit) != 40 or any(ch not in "0123456789abcdefABCDEF" for ch in commit):
        raise ValueError("GitHub authority did not return a commit SHA")
    suffix = "/".join(urllib.parse.quote(part) for part in tail)
    base = f"https://raw.githubusercontent.com/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/{commit}"
    if suffix:
        base = f"{base}/{suffix}"
    return base, commit.lower()


def follow(
    workspace: Path,
    host: str,
    authority: str = DEFAULT_AUTHORITY,
    allow_rollback: bool = False,
) -> dict:
    """Converge one follower to the authority's content-addressed FAMES generation."""
    try:
        resolved_authority, authority_commit = _resolve_authority_base(authority)
        manifest = json.loads(_source_bytes(resolved_authority, "manifest.json").decode("utf-8-sig"))
        skill = next(row for row in manifest.get("skills", []) if row.get("name") == "fames")
        declared = skill.get("files") or {}
        if not declared:
            raise ValueError("authority FAMES file manifest is empty")
        remote_sha = skill.get("package_sha")
        local = verify_host(workspace, host)
        if remote_sha and local.get("ok") and local.get("package_sha") == remote_sha:
            key = _receipt_key(workspace.resolve(), host)
            receipt_path = (
                workspace.resolve() / "_registry" / "fames-fleet-receipts" / f"{key}.json"
            )
            try:
                receipt = _read_json(receipt_path)
            except (OSError, json.JSONDecodeError):
                receipt = {}
            previous_receipt = dict(receipt)
            receipt.update({
                "schema": 1,
                "host": key,
                "package_sha": remote_sha,
                "version": skill.get("version") or local.get("version"),
                "verified": True,
                "authority": "ai_darkhero",
                "authority_manifest_sha": manifest.get("manifest_sha"),
                "source": authority,
            })
            if receipt != previous_receipt:
                _write_json_atomic(receipt_path, receipt)
            return {
                "ok": True,
                "changed": False,
                "package_sha": remote_sha,
                "receipt": receipt,
                "fetched_files": 1,
                "errors": [],
            }
        canonical_state = _canonical_identity(workspace)
        with tempfile.TemporaryDirectory(prefix="fames-follow-") as temp_dir:
            package = Path(temp_dir) / "fames"
            for relative, expected in declared.items():
                parts = Path(relative).parts
                if Path(relative).is_absolute() or ".." in parts:
                    raise ValueError(f"unsafe package path: {relative}")
                target = package.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_source_bytes(resolved_authority, f"skills/fames/{relative}"))
                if _sha256(target) != expected:
                    raise ValueError(f"authority hash mismatch: {relative}")
            package_check = verify_package(package)
            if not package_check["ok"] or package_check.get("package_sha") != skill.get("package_sha"):
                raise ValueError("authority package verification failed")
            # The manifest index row carries no version, so the generation to compare is
            # the one the downloaded package declares about itself. The download is free
            # of side effects and already hash-verified, so guarding here costs one
            # discarded temp directory and never a rewritten canon.
            remote_identity = {
                "version": _package_generation(package).get("version") or skill.get("version"),
                "package_sha": package_check.get("package_sha"),
            }
            regressions = _regression_guard(canonical_state, remote_identity, allow_rollback)
            if regressions:
                return {
                    "ok": False,
                    "changed": False,
                    "host": host,
                    "canonical_version": canonical_state.get("version"),
                    "remote_version": remote_identity.get("version"),
                    "errors": regressions,
                }
            result = install(workspace, host, package)
            result["authority_commit"] = authority_commit
        if not result.get("ok"):
            return result
        receipt = result["receipt"]
        receipt.update({
            "authority": "ai_darkhero",
            "authority_manifest_sha": manifest.get("manifest_sha"),
            "source": authority,
        })
        _write_json_atomic(
            workspace.resolve() / "_registry" / "fames-fleet-receipts" / f"{receipt['host']}.json",
            receipt,
        )
        return {
            "ok": True,
            "changed": True,
            "package_sha": receipt["package_sha"],
            "receipt": receipt,
            "fetched_files": len(declared) + 1,
            "errors": [],
        }
    except (OSError, ValueError, StopIteration, json.JSONDecodeError) as exc:
        return {"ok": False, "host": host, "errors": [str(exc)]}


def _rider_command(workspace: Path, host: str) -> str:
    """The exact line a seat's own clock must run to converge that seat.

    A windowless interpreter by preference: the rider fires out of session, and a
    console interpreter would flash a window on every boundary. `--arm` is included
    so a rider whose command drifts (a moved workspace, a renamed seat) repairs its
    own registration on the next boundary; a rider that was REMOVED cannot re-add
    itself, so this never fights an operator who deliberately disarmed it.
    """
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    runner = quiet if quiet.is_file() else exe
    script = workspace / "_skill" / "fleet-skills" / "fames" / "scripts" / "fames_fleet.py"
    return f"{runner} {script} converge --workspace {workspace} --host {host} --arm"


def _norm_command(value: object) -> str:
    return " ".join(str(value or "").split()).replace("/", "\\").lower()


def rider_state(workspace: Path, host: str) -> dict:
    """Measure this seat's own clock entry. Read-only: never writes the registry."""
    expected = _rider_command(workspace, host)
    registry = workspace / RIDER_REGISTRY
    if not registry.is_file():
        return {"state": "unavailable", "detail": "no rider registry on this seat", "expected": expected}
    try:
        hosts = _read_json(registry).get("hosts") or {}
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "state": "UNKNOWN",
            "detail": f"rider registry unreadable: {exc.__class__.__name__}",
            "expected": expected,
        }
    riders = (hosts.get(CONVERGE_RIDER_HOST) or {}).get("riders") or []
    row = next(
        (r for r in riders if isinstance(r, dict) and r.get("id") == CONVERGE_RIDER_ID),
        None,
    )
    if row is None:
        return {
            "state": "absent",
            "detail": f"{CONVERGE_RIDER_ID} not registered on {CONVERGE_RIDER_HOST}",
            "expected": expected,
        }
    if _norm_command(row.get("command")) != _norm_command(expected):
        return {
            "state": "drifted",
            "detail": "registered command does not run this package",
            "expected": expected,
            "found": row.get("command"),
        }
    if str(row.get("cadence") or "") != CONVERGE_CADENCE:
        return {
            "state": "drifted",
            "detail": f"cadence {row.get('cadence')!r} is not {CONVERGE_CADENCE}",
            "expected": expected,
        }
    return {"state": "armed", "detail": f"{CONVERGE_RIDER_ID} @{CONVERGE_CADENCE}", "expected": expected}


def arm(workspace: Path, host: str, apply: bool = False) -> dict:
    """Register this seat's own converge rider, idempotently.

    Arming a recurring out-of-turn job is an operator act, so it is never a side
    effect: it happens only under an explicit `--arm`, and the registration is an
    upsert keyed by rider id, so repeating it converges instead of accumulating.
    Without `--arm` this reports the measured rider state and prints the proposal,
    which is also the answer on a seat that has no rider engine to call.
    """
    workspace = workspace.resolve()
    observed = rider_state(workspace, host)
    command = observed["expected"]
    engine = workspace / RIDER_ENGINE
    argv = [
        sys.executable,
        str(engine),
        "add",
        CONVERGE_RIDER_HOST,
        CONVERGE_RIDER_ID,
        command,
        "--cadence",
        CONVERGE_CADENCE,
        "--priority",
        str(CONVERGE_PRIORITY),
        "--desc",
        CONVERGE_DESC,
    ]
    result = {
        "ok": observed["state"] != "UNKNOWN",
        "host": _receipt_key(workspace, host),
        "rider": observed["state"],
        "detail": observed.get("detail"),
        "changed": False,
        "proposal": subprocess.list2cmdline(argv[1:]),
        "errors": [],
    }
    if observed["state"] == "armed" or not apply:
        return result
    if " " in str(workspace):
        result.update(
            ok=False,
            errors=["workspace path contains a space; the rider registry splits commands on whitespace"],
        )
        return result
    if not engine.is_file():
        result.update(
            ok=False,
            errors=[f"named blocker: {RIDER_ENGINE} absent -- arm the printed proposal on this seat's own clock"],
        )
        return result
    try:
        proc = _run_hidden(
            argv,
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result.update(ok=False, errors=[f"rider registration failed: {exc}"])
        return result
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        result.update(ok=False, errors=[f"rider registration exit {proc.returncode}: {detail}"])
        return result
    # A registration that exits 0 is a claim; the rider row is the evidence.
    after = rider_state(workspace, host)
    result["rider"] = after["state"]
    result["detail"] = after.get("detail")
    result["changed"] = after["state"] != observed["state"]
    result["ok"] = after["state"] == "armed"
    if not result["ok"]:
        result["errors"].append(f"registration exited 0 but the rider is {after['state']}")
    return result


def converge(
    workspace: Path,
    host: str,
    authority: str = DEFAULT_AUTHORITY,
    arm_rider: bool = False,
    allow_rollback: bool = False,
) -> dict:
    """One in-package hop: pull the authority generation and prove the runner lives.

    `follow` alone converges a seat only when something outside FAMES remembers to
    call it, which makes convergence depend on hub engines the package does not
    carry. This command is what a clock runs: it performs the same verified
    transition, then writes a heartbeat so a runner that stopped firing is a measured
    residual instead of silence. Nothing here calls a model or spends quota.
    """
    workspace = workspace.resolve()
    started = datetime.now(timezone.utc)
    outcome = follow(workspace, host, authority, allow_rollback)
    armed = arm(workspace, host, apply=arm_rider)
    key = _receipt_key(workspace, host)
    errors = [str(item) for item in (outcome.get("errors") or [])]
    capability: dict = {"ok": False, "state": "UNKNOWN", "errors": ["follow did not pass"]}
    if outcome.get("ok"):
        canonical_script = workspace / "_skill" / "fleet-skills" / "fames" / "scripts" / "fames_fleet.py"
        try:
            proc = _run_hidden(
                [sys.executable, str(canonical_script), "attest-capabilities", "--workspace", str(workspace), "--host", host, "--publish", "--json"],
                capture_output=True,
                text=True,
                timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            capability = json.loads(proc.stdout)
            if proc.returncode != 0:
                errors.extend(str(item) for item in capability.get("errors") or ["capability attestation failed"])
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            capability = {"ok": False, "state": "UNKNOWN", "errors": [f"capability attestation unreadable: {exc}"]}
            errors.extend(capability["errors"])
    heartbeat = {
        "schema": 1,
        "host": key,
        "at": started.isoformat(),
        "outcome": "updated" if outcome.get("changed") else ("unchanged" if outcome.get("ok") else "error"),
        "package_sha": outcome.get("package_sha"),
        "authority": authority,
        "rider_state": armed.get("rider"),
        "rider_detail": armed.get("detail"),
        "capability_state": capability.get("state"),
        "capability_set_sha": capability.get("capability_set_sha"),
        "validator_set_sha": capability.get("validator_set_sha"),
        "errors": errors[:5],
    }
    _write_json_atomic(workspace / CONVERGE_DIR / f"{key}.json", heartbeat)
    return {
        "ok": bool(outcome.get("ok") and capability.get("ok")),
        "changed": bool(outcome.get("changed")),
        "host": key,
        "heartbeat": heartbeat,
        "rider": armed,
        "capability": capability,
        "errors": errors,
    }


def _capability_manifest() -> list[dict]:
    return [
        {
            "capability_id": capability_id,
            "contract_version": "1",
            "validator_identity": f"fames-cases:{capability_id}:v1",
            "required_hosts": list(FLEET_HOSTS),
        }
        for capability_id in LOCAL_CAPABILITY_CASES
    ]


def _capability_identities(package_root: Path) -> tuple[list[dict], str, str]:
    manifest = _capability_manifest()
    capability_set_sha = _stable_sha(manifest)
    validator_set_sha = _stable_sha(
        {
            "script": _sha256(package_root / "scripts" / "fames_fleet.py"),
            "cases": _sha256(package_root / CASES_TARGET),
            "capabilities": {key: list(value) for key, value in LOCAL_CAPABILITY_CASES.items()},
        }
    )
    return manifest, capability_set_sha, validator_set_sha


def _publish_capability_receipt(workspace: Path, host: str, receipt: dict) -> dict:
    """Publish one host-owned receipt without depending on the external federation engine."""
    repo = workspace / "_skill" / "ai_fleet_skills"
    if not (repo / ".git").is_dir():
        return {"ok": False, "state": "UNKNOWN", "errors": ["fleet carrier repo missing"]}
    contributor = _contributor_id(host)
    relative = Path("contributors") / contributor / "fames-capability.json"
    target = repo / relative
    try:
        current = _read_json(target) if target.is_file() else {}
    except (OSError, json.JSONDecodeError):
        current = {}
    same_identity = all(
        current.get(field) == receipt.get(field)
        for field in ("host", "package_sha", "capability_set_sha", "validator_set_sha", "runner_state", "capabilities")
    )
    if same_identity:
        try:
            observed = datetime.fromisoformat(str(current.get("observed_at")).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            age = 10**9
        if age < 1800:
            return {"ok": True, "state": "PASS", "changed": False, "skipped": "published receipt is still fresh", "errors": []}

    def git(*args: str) -> subprocess.CompletedProcess:
        return _run_hidden(["git", *args], cwd=repo, capture_output=True, text=True)

    fetched = git("fetch", "origin", "main")
    if fetched.returncode != 0:
        return {"ok": False, "state": "UNKNOWN", "errors": ["carrier fetch failed"]}
    head = git("rev-parse", "HEAD")
    remote = git("rev-parse", "origin/main")
    if head.returncode != 0 or remote.returncode != 0:
        return {"ok": False, "state": "UNKNOWN", "errors": ["carrier identity unreadable"]}
    if head.stdout.strip() != remote.stdout.strip():
        merged = git("merge", "--ff-only", "origin/main")
        if merged.returncode != 0:
            return {"ok": False, "state": "UNKNOWN", "errors": ["carrier cannot fast-forward before receipt publication"]}
    _write_json_atomic(target, receipt)
    staged = git("add", "--", relative.as_posix())
    if staged.returncode != 0:
        return {"ok": False, "state": "UNKNOWN", "errors": ["capability receipt could not be staged"]}
    committed = git("commit", "-m", f"chore(fames/{contributor}): attest capabilities")
    if committed.returncode != 0:
        status = git("status", "--porcelain", "--", relative.as_posix())
        if not status.stdout.strip():
            return {"ok": True, "state": "PASS", "changed": False, "skipped": "receipt unchanged", "errors": []}
        return {"ok": False, "state": "UNKNOWN", "errors": ["capability receipt commit failed"]}
    pushed = git("push", "origin", "HEAD:main")
    if pushed.returncode != 0:
        return {"ok": False, "state": "UNKNOWN", "changed": True, "errors": ["capability receipt push failed"]}
    return {"ok": True, "state": "PASS", "changed": True, "commit": git("rev-parse", "HEAD").stdout.strip(), "errors": []}


def attest_capabilities(workspace: Path, host: str, publish: bool = False) -> dict:
    """Run host-local positive and negative controls and persist a publishable receipt."""
    workspace = workspace.resolve()
    package_root = workspace / "_skill" / "fleet-skills" / "fames"
    package = verify_package(package_root)
    local = verify_host(workspace, host)
    runner = rider_state(workspace, host)
    manifest, capability_set_sha, validator_set_sha = _capability_identities(package_root)
    rows = []
    errors = list(package.get("errors") or []) + list(local.get("errors") or [])
    for capability_id, case_ids in LOCAL_CAPABILITY_CASES.items():
        result = run_cases(workspace, package_root, list(case_ids))
        by_id = {row.get("id"): row for row in result.get("cases") or []}
        base = by_id.get(case_ids[0]) or {}
        negative_rows = [by_id.get(case_id) or {} for case_id in case_ids[1:]]
        positive = base.get("state") == "PASS"
        negative = bool(negative_rows) and all(row.get("state") == "PASS" for row in negative_rows)
        passed = bool(result.get("ok") and positive and negative)
        if not passed:
            errors.append(f"{capability_id}: host-local controls did not pass")
        rows.append(
            {
                "capability_id": capability_id,
                "state": "PASS" if passed else "FAIL",
                "validator_exit": 0 if result.get("ok") else 1,
                "positive_control": positive,
                "negative_control_rejected": negative,
                "caller_backed": True,
                "evidence_refs": [f"case://{case_id}" for case_id in case_ids],
            }
        )
    if runner.get("state") != "armed":
        errors.append(f"convergence runner is {runner.get('state')}")
    receipt = {
        "schema": 1,
        "host": _contributor_id(host),
        "package_sha": package.get("package_sha"),
        "capability_set_sha": capability_set_sha,
        "validator_set_sha": validator_set_sha,
        "runner_state": runner.get("state"),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "freshness_seconds": 0,
        "capability_manifest": manifest,
        "capabilities": rows,
        "evidence_refs": [str(package_root / MANIFEST_NAME), str(package_root / CASES_TARGET)],
    }
    key = _receipt_key(workspace, host)
    _write_json_atomic(workspace / CAPABILITY_DIR / f"{key}.json", receipt)
    state = "PASS" if not errors and all(row["state"] == "PASS" for row in rows) else "FAIL"
    publication = _publish_capability_receipt(workspace, host, receipt) if publish and state == "PASS" else {
        "ok": not publish,
        "state": "NOT_APPLICABLE" if not publish else "FAIL",
        "errors": [],
    }
    if publish and not publication.get("ok"):
        errors.extend(str(item) for item in publication.get("errors") or [])
    return {
        "ok": state == "PASS" and publication.get("ok", False),
        "state": state if state != "PASS" or publication.get("ok") else "UNKNOWN",
        "host": receipt["host"],
        "package_sha": receipt["package_sha"],
        "capability_set_sha": capability_set_sha,
        "validator_set_sha": validator_set_sha,
        "receipt": receipt,
        "publication": publication,
        "errors": errors,
    }


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
        "host": _receipt_key(workspace, host),
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
        fetch = _run_hidden(
            ["git", "fetch", "origin", "main"], cwd=repo, capture_output=True, text=True
        )
        if fetch.returncode != 0:
            errors.append("carrier fetch failed")
        else:
            head = _run_hidden(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
            remote = _run_hidden(["git", "rev-parse", "origin/main"], cwd=repo, capture_output=True, text=True)
            if head.returncode != 0 or remote.returncode != 0 or head.stdout.strip() != remote.stdout.strip():
                errors.append("carrier worktree is not at fetched origin/main")
    for host in hosts:
        try:
            contributor = _contributor_id(host)
        except ValueError as exc:
            errors.append(str(exc))
            rows.append({"host": host, "ok": False})
            continue
        manifest_path = repo / "contributors" / contributor / "manifest.json"
        try:
            manifest = _read_json(manifest_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{host} manifest unreadable: {exc}")
            rows.append({"host": contributor, "host_requested": host, "ok": False})
            continue
        skill = next((row for row in manifest.get("skills", []) if row.get("name") == "fames"), None)
        if not skill:
            errors.append(f"{host} FAMES receipt missing")
            rows.append(
                {
                    "host": contributor,
                    "host_requested": host,
                    "ok": False,
                    "manifest_sha": manifest.get("manifest_sha"),
                }
            )
            continue
        package_sha = skill.get("package_sha")
        package = verify_package(repo / "contributors" / contributor / "skills" / "fames")
        row_ok = package.get("ok") and package_sha == expected == package.get("package_sha")
        if not row_ok:
            errors.append(f"{host} FAMES generation mismatch")
        capability_path = repo / "contributors" / contributor / "fames-capability.json"
        try:
            capability_receipt = _read_json(capability_path)
        except (OSError, json.JSONDecodeError):
            capability_receipt = None
        if isinstance(capability_receipt, dict):
            capability_receipt = dict(capability_receipt)
            try:
                observed = datetime.fromisoformat(str(capability_receipt.get("observed_at")).replace("Z", "+00:00"))
                capability_receipt["freshness_seconds"] = max(
                    0, (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
                )
            except (TypeError, ValueError):
                capability_receipt["freshness_seconds"] = None
        rows.append(
            {
                "host": contributor,
                **({"host_requested": host} if host != contributor else {}),
                "ok": bool(row_ok),
                "manifest_sha": manifest.get("manifest_sha"),
                "package_sha": package_sha,
                "capability_receipt": capability_receipt,
            }
        )
    canonical_manifest, capability_set_sha, validator_set_sha = _capability_identities(
        workspace / "_skill" / "fleet-skills" / "fames"
    )
    capability_receipts = [row.get("capability_receipt") for row in rows if row.get("capability_receipt")]
    capability_record = {
        "generation_identity": {
            "package_sha": expected,
            "capability_set_sha": capability_set_sha,
            "validator_set_sha": validator_set_sha,
        },
        "expected_hosts": list(FLEET_HOSTS),
        "capability_manifest": canonical_manifest,
        "host_receipts": capability_receipts,
        "full_convergence_claim": len(capability_receipts) == len(FLEET_HOSTS),
    }
    capability_result = validate_capability_sync(capability_record)
    if not capability_result.get("ok"):
        errors.extend(f"capability: {item}" for item in capability_result.get("errors") or [])
    return {
        "ok": canonical.get("ok", False) and not errors and len(rows) == len(hosts),
        "claim_scope": "package_and_capability" if capability_result.get("ok") else "package_only",
        "capability_convergence": capability_result.get("state"),
        "capability_probe": "validate-capability-sync",
        "capability_result": capability_result,
        "expected_package_sha": expected,
        "hosts": rows,
        "errors": errors,
    }


def _pointer_get(node: object, pointer: str) -> list:
    """Resolve a slash pointer, '*' matching every dict value or list item.

    Returns every resolved value, so an unresolvable pointer is an empty list rather
    than a None that a probe could mistake for a real value.
    """
    current = [node]
    for part in [p for p in str(pointer).split("/") if p]:
        following: list = []
        for item in current:
            if part == "*":
                if isinstance(item, dict):
                    following.extend(item.values())
                elif isinstance(item, list):
                    following.extend(item)
                continue
            if isinstance(item, dict):
                if part in item:
                    following.append(item[part])
            elif isinstance(item, list):
                try:
                    following.append(item[int(part)])
                except (ValueError, IndexError):
                    continue
        current = following
    return current


def _pointer_walk(node: object, pointer: str) -> tuple[object, str] | None:
    parts = [p for p in str(pointer).split("/") if p]
    if not parts:
        return None
    current = node
    for part in parts[:-1]:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            if part not in current or not isinstance(current[part], (dict, list)):
                current.setdefault(part, {})
            current = current[part]
        else:
            return None
    return current, parts[-1]


def _pointer_set(node: object, pointer: str, value: object) -> bool:
    walked = _pointer_walk(node, pointer)
    if walked is None:
        return False
    parent, last = walked
    if isinstance(parent, list):
        try:
            parent[int(last)] = value
        except (ValueError, IndexError):
            return False
        return True
    if isinstance(parent, dict):
        parent[last] = value
        return True
    return False


def _pointer_del(node: object, pointer: str) -> bool:
    walked = _pointer_walk(node, pointer)
    if walked is None:
        return False
    parent, last = walked
    if isinstance(parent, list):
        try:
            del parent[int(last)]
        except (ValueError, IndexError):
            return False
        return True
    if isinstance(parent, dict):
        return parent.pop(last, _pointer_del) is not _pointer_del
    return False


def _select_paths(workspace: Path, patterns: object) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns if isinstance(patterns, list) else [patterns]:
        for path in sorted(workspace.glob(str(pattern))):
            if path.is_file() and path not in found:
                found.append(path)
    return found


def _brief(value: object, redact: bool) -> str:
    if redact:
        return "<redacted>"
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 32 else text[:29] + "..."


def _inject_goal_hash(record: dict) -> None:
    """Make a fixture test the rules instead of the hash function of the day."""
    goal = record.get("goal")
    if not isinstance(goal, dict):
        return
    digest = semantic_goal_hash(goal)
    goal["semantic_goal_hash"] = digest
    if isinstance(record.get("result"), dict):
        record["result"]["goal_hash"] = digest
    for row in record.get("evidence") or []:
        if isinstance(row, dict):
            row["goal_identity"] = digest
    gate = record.get("cognitive_boundary_gate")
    if isinstance(gate, dict) and isinstance(gate.get("record"), dict):
        boundary = gate["record"]
        boundary["goal_identity"] = digest
        if isinstance(boundary.get("binding"), dict):
            boundary["binding"]["goal_identity"] = digest
        prompt_compilation = boundary.get("prompt_compilation")
        if isinstance(prompt_compilation, dict) and isinstance(prompt_compilation.get("source"), dict):
            prompt_compilation["source"]["goal_identity"] = digest
        interface = boundary.get("interface")
        if isinstance(interface, dict) and isinstance(interface.get("profile_receipt"), dict):
            interface["profile_receipt"]["task_identity"] = digest


def _resolve_fixture_refs(node: object, fixtures: dict, stack: tuple[str, ...] = ()) -> object:
    if isinstance(node, dict) and set(node) == {"$fixture"}:
        ref = node.get("$fixture")
        if ref not in fixtures or str(ref) in stack:
            return node
        return _resolve_fixture_refs(json.loads(json.dumps(fixtures[ref])), fixtures, (*stack, str(ref)))
    if isinstance(node, dict):
        return {key: _resolve_fixture_refs(value, fixtures, stack) for key, value in node.items()}
    if isinstance(node, list):
        return [_resolve_fixture_refs(value, fixtures, stack) for value in node]
    return node


def _hydrate_boundary_fixtures(node: object) -> None:
    if isinstance(node, dict):
        if node.pop("auto_boundary_contract", False):
            layer, _ = _cognitive_contract()
            policy = layer.get("cognitive_boundary") or {}
            now = datetime.now(timezone.utc)
            expires = now + timedelta(hours=1)
            now_text, expires_text = now.isoformat(), expires.isoformat()
            node["policy_identity"] = _stable_sha(policy)
            node["validator_identity"] = _sha256(Path(__file__).resolve())
            node["measured_at"], node["valid_until"] = now_text, expires_text
            population = node.get("population") or {}
            population["identity"] = _stable_sha({
                "unit": population.get("unit"),
                "members": population.get("members"),
                "sample_plan": population.get("sample_plan"),
            })
            interface = node.get("interface") or {}
            canonical_identity = _stable_sha(interface.get("canonical_fields") or {})
            interface["canonical_result_identity"] = canonical_identity
            interface["authority_identity_before"] = _stable_sha(sorted(interface.get("authority_before") or []))
            interface["authority_identity_after"] = _stable_sha(sorted(interface.get("authority_after") or []))
            if isinstance(interface.get("comprehension_probe"), dict):
                interface["comprehension_probe"]["result_identity"] = canonical_identity
            profile = interface.get("profile_receipt") or {}
            profile["task_identity"] = node.get("goal_identity")
            profile["measured_at"], profile["expires_at"] = now_text, expires_text
            risk = interface.get("risk_classification") or {}
            risk["policy_identity"] = _stable_sha((policy.get("interface_contract") or {}).get("risk_policy") or {})
            risk["evaluated_at"], risk["valid_until"] = now_text, expires_text
            for cell in node.get("cells") or []:
                if isinstance(cell, dict):
                    cell["measured_at"], cell["valid_until"] = now_text, expires_text
            monitor = node.get("monitor") or {}
            monitor["validator_identity"] = node["validator_identity"]
            monitor["last_checked_at"], monitor["valid_until"] = now_text, expires_text
            prompt_compilation = node.get("prompt_compilation")
            if isinstance(prompt_compilation, dict):
                prompt_policy = policy.get("prompt_compilation_contract") or {}
                turn_receipt = prompt_compilation.get("turn_receipt") or {}
                try:
                    manifest = _read_json(PACKAGE_ROOT / MANIFEST_NAME)
                except (OSError, json.JSONDecodeError):
                    manifest = {}
                turn_receipt["skill_gen"] = manifest.get("skill_gen")
                turn_receipt["package_sha"] = manifest.get("package_sha")
                turn_receipt["prompt_contract_identity"] = _stable_sha(prompt_policy)
                prompt_compilation["turn_receipt"] = turn_receipt
                source = prompt_compilation.get("source") or {}
                source["prompt_identity"] = turn_receipt.get("prompt_identity")
                source["goal_identity"] = node.get("goal_identity")
                prompt_compilation["source"] = source
            authority = (interface.get("authority_after") or ["read"])[0]
            node["binding"] = {
                "caller": "validate_cognitive_boundary",
                "goal_identity": node.get("goal_identity"),
                "result_identity": canonical_identity,
                "authority_scope": authority,
                "risk_categories": list(risk.get("categories") or []),
            }
        for value in node.values():
            _hydrate_boundary_fixtures(value)
    elif isinstance(node, list):
        for value in node:
            _hydrate_boundary_fixtures(value)


def _set_fixture_boundary_authority(boundary: dict, authority_scope: str) -> None:
    interface = boundary.get("interface") or {}
    grants = list(dict.fromkeys([authority_scope, *(interface.get("authority_before") or [])]))
    interface["authority_before"] = grants
    interface["authority_after"] = list(grants)
    interface["authority_identity_before"] = _stable_sha(sorted(grants))
    interface["authority_identity_after"] = _stable_sha(sorted(grants))
    for field_map in (interface.get("canonical_fields"), interface.get("presented_fields")):
        if isinstance(field_map, dict):
            field_map["authority"] = list(grants)
    canonical_identity = _stable_sha(interface.get("canonical_fields") or {})
    interface["canonical_result_identity"] = canonical_identity
    if isinstance(interface.get("comprehension_probe"), dict):
        interface["comprehension_probe"]["result_identity"] = canonical_identity
    if isinstance(boundary.get("binding"), dict):
        boundary["binding"]["authority_scope"] = authority_scope
        boundary["binding"]["result_identity"] = canonical_identity
    prompt_compilation = boundary.get("prompt_compilation")
    if isinstance(prompt_compilation, dict):
        prompt_compilation["authority_before"] = list(grants)
        prompt_compilation["authority_after"] = list(grants)


def _local_content_ref(path: Path, uri: str) -> dict:
    return {"uri": uri, "path": str(path.resolve()), "sha256": _sha256(path.resolve())}


def _hydrate_promotion_fixtures(node: object) -> None:
    if isinstance(node, dict):
        if node.pop("auto_promotion_contract", False):
            validator_identity = _sha256(Path(__file__).resolve())
            script_ref = _local_content_ref(Path(__file__), "file://fames_fleet.py")
            workspace = PACKAGE_ROOT.parents[2]
            review_ref = _local_content_ref(workspace / "_registry" / "fames-evidence" / "fixtures" / "promotion-review.json", "file://promotion-review.json")
            non_regression_ref = _local_content_ref(workspace / "_registry" / "fames-evidence" / "fixtures" / "promotion-non-regression.json", "file://promotion-non-regression.json")
            for claim in node.get("claims") or []:
                if isinstance(claim, dict) and claim.get("verdict") in {"adopt", "adapt"}:
                    landing_path = (workspace / str(claim.get("lands_in") or "")).resolve()
                    claim["landing_artifact"] = _local_content_ref(landing_path, f"file://{claim.get('lands_in')}")
                    trial = claim.setdefault("trial", {})
                    trial["validator_identity"] = validator_identity
                    trial["evidence_refs"] = [script_ref]
            promotion = node.get("promotion") or {}
            promotion["validator_identity"] = validator_identity
            promotion["independent_review"] = {
                "accepted": True,
                "reviewer_identity": "fixture-readonly-reviewer",
                "validator_identity": validator_identity,
                "evidence": review_ref,
            }
            promotion["non_regression"] = {"passed": True, "evidence": non_regression_ref}
            source_identity = _stable_sha(node.get("content_identity") or {})
            promoted_claims = [claim for claim in node.get("claims") or [] if isinstance(claim, dict) and claim.get("verdict") in {"adopt", "adapt"}]
            claim_semantics = sorted(({
                "id": claim.get("id"), "claim": claim.get("claim"), "trust_class": claim.get("trust_class"),
                "verdict": claim.get("verdict"), "why": claim.get("why"), "lands_in": claim.get("lands_in"),
            } for claim in promoted_claims), key=lambda row: str(row.get("id")))
            artifact_identity = _stable_sha(sorted(({
                "id": claim.get("id"), "lands_in": claim.get("lands_in"),
                "path": claim["landing_artifact"].get("path"), "sha256": claim["landing_artifact"].get("sha256"),
            } for claim in promoted_claims), key=lambda row: str(row.get("id"))))
            promotion["candidate_identity"] = _stable_sha({
                "source_identity": source_identity,
                "claim_semantics": claim_semantics,
                "artifact_identity": artifact_identity,
            })
        for value in node.values():
            _hydrate_promotion_fixtures(value)
    elif isinstance(node, list):
        for value in node:
            _hydrate_promotion_fixtures(value)


def _bind_fixture_gates(node: object) -> None:
    if not isinstance(node, dict):
        if isinstance(node, list):
            for value in node:
                _bind_fixture_gates(value)
        return
    gate = node.get("cognitive_boundary_gate")
    boundary = gate.get("record") if isinstance(gate, dict) else None
    if isinstance(boundary, dict):
        binding = boundary.setdefault("binding", {})
        interface = boundary.get("interface") or {}
        if isinstance(node.get("goal"), dict) and isinstance(node.get("result"), dict):
            authority_scope = str(node["goal"].get("authority_scope") or "read")
            _set_fixture_boundary_authority(boundary, authority_scope)
            categories = list(RB_RISK_CATEGORIES.get(str(node.get("risk_class")), ["none"]))
            risk = interface.get("risk_classification") or {}
            risk["categories"] = categories
            risk["high_risk"] = bool(set(categories) & set((((_cognitive_contract()[0].get("cognitive_boundary") or {}).get("interface_contract") or {}).get("risk_policy") or {}).get("high_risk_categories") or ()))
            binding.update({
                "caller": "validate_run",
                "goal_identity": boundary.get("goal_identity"),
                "result_identity": interface.get("canonical_result_identity"),
                "authority_scope": authority_scope,
                "risk_categories": categories,
            })
            node["result"]["identity"] = interface.get("canonical_result_identity")
            for evidence in node.get("evidence") or []:
                if isinstance(evidence, dict):
                    evidence["result_identity"] = node["result"]["identity"]
        elif isinstance(node.get("interaction_integrity"), dict):
            binding.update({
                "caller": "validate_cognitive",
                "interaction_identity": _stable_sha(node["interaction_integrity"]),
            })
        elif node.get("actor") and node.get("candidate_identity"):
            binding["caller"] = "validate_ingest"
    if node.get("promoted") is True and isinstance(node.get("promotion"), dict):
        promotion = node["promotion"]
        gate = promotion.get("cognitive_boundary_gate")
        boundary = gate.get("record") if isinstance(gate, dict) else None
        if isinstance(boundary, dict):
            source_identity = _stable_sha(node.get("content_identity") or {})
            claim_ids = sorted(str(claim.get("id")) for claim in node.get("claims") or [] if isinstance(claim, dict))
            promoted_claims = [claim for claim in node.get("claims") or [] if isinstance(claim, dict) and claim.get("verdict") in {"adopt", "adapt"}]
            artifact_identity = _stable_sha(sorted(({
                "id": claim.get("id"),
                "lands_in": claim.get("lands_in"),
                "path": (claim.get("landing_artifact") or {}).get("path"),
                "sha256": (claim.get("landing_artifact") or {}).get("sha256"),
            } for claim in promoted_claims), key=lambda row: str(row.get("id"))))
            authority_scope = str((node.get("scope") or {}).get("authority_scope") or "read")
            _set_fixture_boundary_authority(boundary, authority_scope)
            binding = boundary.setdefault("binding", {})
            binding.update({
                "caller": "validate_ingest",
                "source_identity": source_identity,
                "claim_ids": claim_ids,
                "artifact_identity": artifact_identity,
                "candidate_identity": promotion.get("candidate_identity"),
                "authority_scope": authority_scope,
            })
    for value in node.values():
        _bind_fixture_gates(value)


def _hydrate_promotion_replays(node: object) -> None:
    if isinstance(node, dict):
        if node.get("promoted") is True and isinstance(node.get("promotion"), dict):
            promotion = node["promotion"]
            boundary = ((promotion.get("cognitive_boundary_gate") or {}).get("record")
                        if isinstance(promotion.get("cognitive_boundary_gate"), dict) else None)
            if isinstance(boundary, dict):
                outcome = validate_cognitive_boundary(boundary)
                now = datetime.now(timezone.utc)
                receipt = {
                    "candidate_identity": promotion.get("candidate_identity"),
                    "input_identity": _stable_sha(boundary),
                    "validator_identity": _sha256(Path(__file__).resolve()),
                    "output_identity": _stable_sha(outcome),
                    "state": outcome.get("state"),
                    "exit_status": 0 if outcome.get("ok") else 1,
                    "executed_at": now.isoformat(),
                    "valid_until": (now + timedelta(hours=1)).isoformat(),
                }
                for claim in node.get("claims") or []:
                    if isinstance(claim, dict) and claim.get("verdict") in {"adopt", "adapt"}:
                        claim.setdefault("trial", {})["replay"] = dict(receipt)
                review = promotion.get("independent_review")
                if isinstance(review, dict):
                    try:
                        review_payload = _read_json(Path(str((review.get("evidence") or {}).get("path"))))
                    except (OSError, json.JSONDecodeError, TypeError):
                        review_payload = {}
                    review.update({
                        "reviewer_identity": "fixture-readonly-reviewer",
                        "validator_identity": _sha256(Path(__file__).resolve()),
                        "reproduction_input_identity": _boundary_review_subject_identity(boundary),
                        "reproduction_output_identity": receipt["output_identity"],
                        "executed_at": review_payload.get("executed_at", now.isoformat()),
                        "valid_until": review_payload.get("valid_until", (now + timedelta(hours=1)).isoformat()),
                    })
                non_regression = promotion.get("non_regression")
                if isinstance(non_regression, dict):
                    try:
                        nonreg_payload = _read_json(Path(str((non_regression.get("evidence") or {}).get("path"))))
                    except (OSError, json.JSONDecodeError, TypeError):
                        nonreg_payload = {}
                    non_regression.update({
                        "passed": True,
                        **_promotion_non_regression(),
                        "executed_at": nonreg_payload.get("executed_at", now.isoformat()),
                        "valid_until": nonreg_payload.get("valid_until", (now + timedelta(hours=1)).isoformat()),
                    })
        for value in node.values():
            _hydrate_promotion_replays(value)
    elif isinstance(node, list):
        for value in node:
            _hydrate_promotion_replays(value)


def _prepare_input(fixtures: dict, case: dict) -> tuple[object, str]:
    ref = case.get("input_ref")
    if ref not in fixtures:
        return None, f"unknown input_ref {ref!r}"
    record = _resolve_fixture_refs(json.loads(json.dumps(fixtures[ref])), fixtures, (str(ref),))
    _hydrate_boundary_fixtures(record)
    _hydrate_promotion_fixtures(record)
    _bind_fixture_gates(record)
    _hydrate_promotion_replays(record)
    auto = record.pop("auto_goal_hash", False) if isinstance(record, dict) else False
    for pointer in case.get("remove") or []:
        _pointer_del(record, pointer)
    for pointer, value in (case.get("patch") or {}).items():
        _pointer_set(record, pointer, value)
    if case.get("auto_goal_hash", auto) and isinstance(record, dict):
        _inject_goal_hash(record)
    return record, ""


def _evaluate_case(
    case: dict,
    workspace: Path,
    package_root: Path,
    fixtures: dict,
    refs: dict,
) -> tuple[str, str]:
    kind = case.get("kind")
    redact = bool(case.get("redact"))
    missing_ok = bool(case.get("missing_ok"))

    if kind == "parity":
        drift = parity(workspace, package_root)
        return ("PASS" if drift.get("ok") else "FAIL"), "; ".join(drift.get("errors") or [])[:200]

    if kind == "path_exists":
        target = workspace / str(case.get("path"))
        present = target.exists()
        want = case.get("expect", "present") == "present"
        return ("PASS" if present == want else "FAIL"), f"present={present}"

    if kind == "file_size_max":
        target = workspace / str(case.get("path"))
        if not target.is_file():
            return ("PASS" if missing_ok else "FAIL"), "absent"
        limit = int(case.get("max_bytes", 0))
        if case.get("ignore_comment_lines"):
            # A drop file that is armed but unused still carries its instruction
            # scaffold, so raw size answers "is this file non-empty" when the real
            # question is "does it hold a payload". Count only the bytes of lines
            # that are neither blank nor comments -- the same predicate the consuming
            # tool applies. Lines are measured, never emitted.
            try:
                text = target.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                return "UNKNOWN", "unreadable as text"
            size = sum(
                len(line.strip().encode("utf-8"))
                for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
            return ("PASS" if size <= limit else "FAIL"), f"{size} payload bytes > {limit}"
        size = target.stat().st_size
        # Size only. The content of a probed file is never read, here or anywhere.
        return ("PASS" if size <= limit else "FAIL"), f"{size} bytes > {limit}"

    if kind == "newest_age_max":
        paths = _select_paths(workspace, case.get("select") or [])
        if not paths:
            return ("NOT_APPLICABLE" if missing_ok else "FAIL"), "no match"
        newest = max(path.stat().st_mtime for path in paths)
        age_h = (datetime.now(timezone.utc).timestamp() - newest) / 3600.0
        limit = float(case.get("max_age_h", 24))
        return ("PASS" if age_h <= limit else "FAIL"), f"newest is {age_h:.1f}h old, ceiling {limit}h"

    if kind == "json_probe":
        paths = _select_paths(workspace, case.get("select") or [])
        if not paths:
            return ("NOT_APPLICABLE" if missing_ok else "FAIL"), "no file matched select"
        expect = case.get("expect")
        observed: list[tuple[str, object]] = []
        problems: list[str] = []
        for path in paths:
            rel = path.relative_to(workspace).as_posix()
            try:
                document = _read_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"{rel}: unreadable ({exc.__class__.__name__})")
                continue
            values = _pointer_get(document, case.get("pointer", ""))
            if not values:
                if not missing_ok:
                    problems.append(f"{rel}: pointer unresolved")
                continue
            observed.extend((rel, value) for value in values)
        if problems:
            return "FAIL", "; ".join(problems)[:200]
        if not observed:
            return ("NOT_APPLICABLE" if missing_ok else "FAIL"), "pointer resolved nowhere"
        if expect == "all_equal_ref":
            reference = refs.get(case.get("ref"))
            if reference is None:
                return "UNKNOWN", f"reference {case.get('ref')!r} unavailable"
            bad = [f"{rel}={_brief(value, redact)}" for rel, value in observed if value != reference]
            return ("PASS" if not bad else "FAIL"), (
                f"expected {_brief(reference, redact)}; " + ", ".join(bad)
            )[:200] if bad else f"{len(observed)} match {_brief(reference, redact)}"
        if expect == "all_equal":
            first = observed[0][1]
            bad = [f"{rel}={_brief(value, redact)}" for rel, value in observed if value != first]
            return ("PASS" if not bad else "FAIL"), ", ".join(bad)[:200] or f"{len(observed)} agree"
        if expect == "all_in":
            allowed = case.get("values") or []
            bad = [f"{rel}={_brief(value, redact)}" for rel, value in observed if value not in allowed]
            return ("PASS" if not bad else "FAIL"), ", ".join(bad)[:200] or f"{len(observed)} in range"
        return "UNKNOWN", f"unknown expect {expect!r}"

    if kind == "claim_backed":
        # A ledger that records what is built can only be trusted if something checks it
        # against the code. Every row whose `flag` is true must leave a trace matching
        # `pattern` in the backing source; a row that claims more than the code does is
        # the failure this kind exists to catch. Deterministic, local, zero model.
        paths = _select_paths(workspace, case.get("select") or [])
        if not paths:
            return ("NOT_APPLICABLE" if missing_ok else "FAIL"), "no file matched select"
        backing = workspace / str(case.get("backing", ""))
        if not backing.is_file():
            return ("NOT_APPLICABLE" if missing_ok else "FAIL"), "backing file absent on this seat"
        try:
            source = backing.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return "UNKNOWN", "backing file unreadable as text"
        template = str(case.get("pattern", "{id}"))
        flag = case.get("flag")
        id_field = str(case.get("id_field", "id"))
        checked, unbacked = 0, []
        for path in paths:
            try:
                document = _read_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                return "UNKNOWN", f"{path.name}: unreadable ({exc.__class__.__name__})"
            rows: list = []
            for value in _pointer_get(document, case.get("pointer", "")):
                rows.extend(value if isinstance(value, list) else [value])
            for row in rows:
                if not isinstance(row, dict) or (flag and not row.get(flag)):
                    continue
                checked += 1
                ident = str(row.get(id_field) or "")
                if not ident or template.replace("{id}", ident) not in source:
                    unbacked.append(ident or "<no id>")
        if not checked:
            return ("NOT_APPLICABLE" if missing_ok else "FAIL"), "no claim row matched"
        if unbacked:
            return "FAIL", (f"{len(unbacked)}/{checked} claimed but unbacked in "
                            f"{case.get('backing')}: " + ", ".join(unbacked))[:200]
        return "PASS", f"{checked} claims backed by {case.get('backing')}"

    if kind == "forbidden_text":
        # Canonical policy must not acquire host-name conditionals. Adapter packages and
        # dated evidence remain free to name the surfaces they measured; this case scans
        # only the explicitly declared normative files.
        declared = case.get("paths") or []
        forbidden = case.get("forbidden") or []
        if not isinstance(declared, list) or not declared or any(not isinstance(item, str) for item in declared):
            return "UNKNOWN", "paths must be a non-empty string list"
        if not isinstance(forbidden, list) or not forbidden or any(not isinstance(item, str) or not item for item in forbidden):
            return "UNKNOWN", "forbidden must be a non-empty string list"
        hits: list[str] = []
        for relative in declared:
            path = workspace / relative
            if not path.is_file():
                return ("NOT_APPLICABLE" if missing_ok else "FAIL"), f"{relative}: absent"
            try:
                source = path.read_text(encoding="utf-8-sig").casefold()
            except (OSError, UnicodeDecodeError):
                return "UNKNOWN", f"{relative}: unreadable as text"
            matched = sorted({token for token in forbidden if token.casefold() in source})
            if matched:
                hits.append(f"{relative}: {','.join(matched)}")
        clean = not hits
        want_clean = case.get("expect_clean", True)
        if not isinstance(want_clean, bool):
            return "UNKNOWN", "expect_clean must be boolean"
        if clean == want_clean:
            if clean:
                return "PASS", f"{len(declared)} canonical files contain no platform identifiers"
            return "PASS", f"negative control detected identifiers in {len(hits)} file(s)"
        if hits:
            return "FAIL", ("platform identifiers in canonical policy: " + "; ".join(hits))[:200]
        return "FAIL", "negative control did not detect a platform identifier"

    if kind == "validator_probe":
        record, problem = _prepare_input(fixtures, case)
        if problem:
            return "UNKNOWN", problem
        validator = case.get("validator")
        if validator == "validate_run":
            outcome = validate_run(record)
            ok, errors = bool(outcome.get("ok")), outcome.get("errors") or []
        elif validator == "validate_ingest":
            outcome = validate_ingest(record)
            ok, errors = bool(outcome.get("ok")), outcome.get("errors") or []
        elif validator == "validate_cognitive":
            outcome = validate_cognitive(record)
            ok, errors = bool(outcome.get("ok")), outcome.get("errors") or []
        elif validator == "validate_cognitive_boundary":
            outcome = validate_cognitive_boundary(record)
            ok, errors = bool(outcome.get("ok")), outcome.get("errors") or []
        elif validator == "validate_harness":
            outcome = validate_harness(record)
            ok, errors = bool(outcome.get("ok")), outcome.get("errors") or []
        elif validator == "validate_background":
            outcome = validate_background(record)
            ok, errors = bool(outcome.get("ok")), outcome.get("errors") or []
        elif validator == "validate_compute":
            outcome = validate_compute(record)
            ok, errors = bool(outcome.get("ok")), outcome.get("errors") or []
        elif validator == "validate_autonomic":
            outcome = validate_autonomic(record)
            ok, errors = bool(outcome.get("ok")), outcome.get("errors") or []
        elif validator == "validate_capability_sync":
            outcome = validate_capability_sync(record)
            ok, errors = bool(outcome.get("ok")), outcome.get("errors") or []
        elif validator == "regression_guard":
            errors = _regression_guard(
                record.get("canonical") or {},
                record.get("remote") or {},
                bool(record.get("allow_rollback")),
            )
            ok = not errors
            outcome = {"state": "PASS" if ok else "FAIL"}
        elif validator == "contributor_id":
            errors = []
            for pair in record.get("aliases") or []:
                try:
                    left, right = pair
                    if _contributor_id(left) != _contributor_id(right):
                        errors.append(f"aliases do not converge: {pair!r}")
                except (TypeError, ValueError) as exc:
                    errors.append(str(exc))
            ok = bool(record.get("aliases")) and not errors
            outcome = {"state": "PASS" if ok else "FAIL"}
        else:
            return "UNKNOWN", f"unknown validator {validator!r}"
        want = bool(case.get("expect_ok"))
        expected_state = case.get("expect_state")
        actual_state = outcome.get("state")
        if expected_state is not None and actual_state != expected_state:
            return "FAIL", f"expected validator state {expected_state}, got {actual_state}"
        if ok == want:
            detail = "accepted" if ok else f"refused ({len(errors)})"
            if expected_state is not None:
                detail += f" as {actual_state}"
            return "PASS", detail
        if want:
            # Only echo rule messages when a case that should have passed did not.
            return "FAIL", "; ".join(str(e) for e in errors[:5])[:200]
        return "FAIL", "accepted a record the rule must refuse"

    return "UNKNOWN", f"unknown case kind {kind!r}"


def _load_cases(workspace: Path, package_root: Path) -> tuple[dict, str]:
    """The bundled cases are the portable authority; the registry is the SSOT."""
    bundled = package_root / CASES_TARGET
    source = workspace / CASES_SOURCE
    for path in (bundled, source):
        if path.is_file():
            try:
                return _read_json(path), ""
            except (OSError, json.JSONDecodeError) as exc:
                return {}, f"cases unreadable at {path.name}: {exc}"
    return {}, "no cases file in the package or the registry"


def run_cases(
    workspace: Path,
    package_root: Path = PACKAGE_ROOT,
    only: list[str] | None = None,
) -> dict:
    """Run every declared case and charge each failure to a residual dimension.

    This is FAMES applied to FAMES with no model in the loop: each case states its
    expectation before it runs (FP), costs one in-process call and zero tokens (MTM),
    and its failure count is the residual (SCF) that alone justifies a change (AEX).
    """
    workspace = workspace.resolve()
    package_root = package_root.resolve()
    document, problem = _load_cases(workspace, package_root)
    if problem:
        return {"ok": False, "workspace": str(workspace), "cases": [], "errors": [problem]}

    fixtures = document.get("fixtures") or {}
    refs = {}
    try:
        manifest = _read_json(package_root / MANIFEST_NAME)
        refs = {
            "canonical_package_sha": manifest.get("package_sha"),
            "canonical_version": manifest.get("version"),
        }
    except (OSError, json.JSONDecodeError):
        refs = {}
    authority = (workspace / CASES_SOURCE).is_file()

    rows: list[dict] = []
    residual = {key: 0 for key in RESIDUAL_DIMENSIONS}
    blocking: list[str] = []
    degraded: list[str] = []
    errors: list[str] = []
    for case in document.get("cases") or []:
        case_id = str(case.get("id") or "?")
        if only and case_id not in only:
            continue
        charges = case.get("charges")
        fail_mode = case.get("fail_mode", "closed")
        row = {"id": case_id, "kind": case.get("kind"), "charges": charges, "fail_mode": fail_mode}
        if case.get("kind") not in CASE_KINDS:
            state, detail = "UNKNOWN", f"unknown case kind {case.get('kind')!r}"
        elif charges not in RESIDUAL_DIMENSIONS:
            state, detail = "UNKNOWN", f"unknown residual dimension {charges!r}"
        elif fail_mode not in FAIL_MODES:
            state, detail = "UNKNOWN", f"unknown fail_mode {fail_mode!r}"
        elif case.get("scope") == "authority" and not authority:
            state, detail = "NOT_APPLICABLE", "authority-only case on a follower"
        else:
            try:
                state, detail = _evaluate_case(case, workspace, package_root, fixtures, refs)
            except Exception as exc:  # a case that cannot be evaluated is UNKNOWN, not green
                state, detail = "UNKNOWN", f"{exc.__class__.__name__}: {exc}"[:200]
        row["state"] = state
        row["detail"] = detail
        rows.append(row)
        if state in {"FAIL", "UNKNOWN"}:
            if charges in residual:
                residual[charges] += 1
            note = f"{case_id} [{charges}] {state}: {detail}"
            # UNKNOWN fails closed regardless of the declared mode.
            if fail_mode == "closed" or state == "UNKNOWN":
                blocking.append(note)
            else:
                degraded.append(note)
    errors.extend(blocking)
    return {
        "ok": not blocking,
        "workspace": str(workspace),
        "scope": "authority" if authority else "follower",
        "counted": len(rows),
        "residual": residual,
        "residual_total": sum(residual.values()),
        "blocking": blocking,
        "degraded": degraded,
        "cases": rows,
        "errors": errors,
    }


def self_check(
    workspace: Path,
    package_root: Path = PACKAGE_ROOT,
    write: bool = True,
) -> dict:
    """One zero-token command that proves the package still is what it claims.

    status() answers "is this generation intact and current"; run_cases() answers
    "do the rules still hold and is the residual still what it was". The record it
    writes is the replayable SEAL evidence, and its own age is a case.
    """
    state = status(workspace, package_root)
    cases = run_cases(workspace, package_root)
    errors = [f"status: {e}" for e in state.get("errors") or []]
    errors += [f"case: {e}" for e in cases.get("blocking") or []]
    record = {
        "schema": 1,
        "id": "FAMES-SELF-CHECK",
        "ok": not errors,
        "at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(Path(workspace).resolve()),
        "scope": cases.get("scope"),
        "skill_gen": state.get("skill_gen"),
        "version": state.get("version"),
        "package_sha": state.get("package_sha"),
        "package_ok": state.get("package_ok"),
        "parity_ok": state.get("parity_ok"),
        "residual": cases.get("residual"),
        "residual_total": cases.get("residual_total"),
        "blocking": cases.get("blocking"),
        "degraded": cases.get("degraded"),
        "cases": cases.get("cases"),
        "errors": errors,
    }
    if write:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = Path(workspace).resolve() / SELF_EVIDENCE_DIR / f"{stamp}.json"
        try:
            _write_json_atomic(target, record)
            record["evidence_path"] = str(target)
        except OSError as exc:
            record["evidence_path"] = None
            record["errors"] = errors + [f"evidence unwritable: {exc}"]
            record["ok"] = False
    return record


def _emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("PASS" if payload.get("ok") else "FAIL", payload)
    return 0 if payload.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build-bundle", "verify-package", "parity", "status", "run-cases", "self-check", "validate-run", "validate-ingest", "validate-cognitive", "validate-cognitive-boundary", "validate-harness", "validate-background", "measure-compute", "plan-compute", "validate-compute", "validate-local-compute", "validate-autonomic", "validate-capability-sync", "attest-capabilities", "install", "follow", "converge", "arm", "verify-host", "verify-fleet"):
        command = sub.add_parser(name)
        command.add_argument("--workspace", type=Path, default=Path.cwd())
        command.add_argument("--json", action="store_true")
        if name in {"verify-package", "parity", "status", "run-cases", "self-check"}:
            command.add_argument("--skill-dir", type=Path, default=PACKAGE_ROOT)
        if name in {"validate-run", "validate-ingest", "validate-cognitive", "validate-cognitive-boundary", "validate-harness", "validate-background", "plan-compute", "validate-compute", "validate-autonomic", "validate-capability-sync"}:
            command.add_argument("--input", type=Path, required=True)
        if name == "validate-local-compute":
            command.add_argument("--input", type=Path)
        if name == "run-cases":
            command.add_argument("--only", nargs="+")
        if name == "self-check":
            command.add_argument("--no-write", action="store_true")
        if name == "build-bundle":
            command.add_argument("--protocol-git-ref")
            command.add_argument("--allow-same-gen", action="store_true")
        if name in {"install", "follow", "converge", "arm", "verify-host"}:
            command.add_argument("--host", required=True)
        if name == "attest-capabilities":
            command.add_argument("--host", required=True)
            command.add_argument("--publish", action="store_true")
        if name == "install":
            command.add_argument("--source", type=Path, default=PACKAGE_ROOT)
        if name in {"follow", "converge"}:
            command.add_argument("--authority", default=DEFAULT_AUTHORITY)
            command.add_argument("--allow-rollback", action="store_true")
        if name in {"install", "converge"}:
            command.add_argument("--arm", action="store_true")
        if name == "arm":
            command.add_argument("--apply", action="store_true")
        if name == "verify-fleet":
            command.add_argument("--hosts", nargs="+", required=True)
    args = parser.parse_args()
    if args.command == "build-bundle":
        return _emit(
            build_bundle(
                args.workspace,
                protocol_git_ref=args.protocol_git_ref,
                allow_same_gen=args.allow_same_gen,
            ),
            args.json,
        )
    if args.command == "verify-package":
        return _emit(verify_package(args.skill_dir), args.json)
    if args.command == "parity":
        return _emit(parity(args.workspace, args.skill_dir), args.json)
    if args.command == "status":
        return _emit(status(args.workspace, args.skill_dir), args.json)
    if args.command == "run-cases":
        return _emit(run_cases(args.workspace, args.skill_dir, args.only), args.json)
    if args.command == "self-check":
        return _emit(
            self_check(args.workspace, args.skill_dir, write=not args.no_write),
            args.json,
        )
    if args.command == "validate-run":
        try:
            payload = _read_json(args.input)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"run input unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(validate_run(payload), args.json)
    if args.command == "validate-ingest":
        try:
            payload = _read_json(args.input)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"ingest input unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(validate_ingest(payload), args.json)
    if args.command == "validate-cognitive":
        try:
            payload = _read_json(args.input)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"cognitive input unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(validate_cognitive(payload), args.json)
    if args.command == "validate-cognitive-boundary":
        try:
            payload = _read_json(args.input)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"cognitive-boundary input unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(validate_cognitive_boundary(payload), args.json)
    if args.command == "validate-harness":
        try:
            payload = _read_json(args.input)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"harness input unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(validate_harness(payload), args.json)
    if args.command == "validate-background":
        try:
            payload = _read_json(args.input)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"background input unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(validate_background(payload), args.json)
    if args.command == "measure-compute":
        return _emit(measure_compute_topology(args.workspace), args.json)
    if args.command == "plan-compute":
        try:
            payload = _read_json(args.input)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"compute request unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(plan_compute(payload, args.workspace), args.json)
    if args.command == "validate-compute":
        try:
            payload = _read_json(args.input)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"compute record unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(validate_compute(payload), args.json)
    if args.command == "validate-local-compute":
        source = args.input or (args.workspace / "_registry" / "fames-local-compute.json")
        try:
            payload = _read_json(source)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"local compute profile unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(validate_local_compute(payload, args.workspace), args.json)
    if args.command == "validate-autonomic":
        try:
            payload = _read_json(args.input)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"autonomic input unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(validate_autonomic(payload), args.json)
    if args.command == "validate-capability-sync":
        try:
            payload = _read_json(args.input)
        except (OSError, json.JSONDecodeError) as exc:
            payload = {"ok": False, "state": "UNKNOWN", "errors": [f"capability-sync input unreadable: {exc}"]}
            return _emit(payload, args.json)
        return _emit(validate_capability_sync(payload), args.json)
    if args.command == "attest-capabilities":
        return _emit(attest_capabilities(args.workspace, args.host, publish=args.publish), args.json)
    if args.command == "install":
        payload = install(args.workspace, args.host, args.source)
        if args.arm:
            payload["rider"] = arm(args.workspace, args.host, apply=payload.get("ok", False))
        return _emit(payload, args.json)
    if args.command == "follow":
        return _emit(
            follow(args.workspace, args.host, args.authority, args.allow_rollback),
            args.json,
        )
    if args.command == "converge":
        return _emit(
            converge(args.workspace, args.host, args.authority, args.arm, args.allow_rollback),
            args.json,
        )
    if args.command == "arm":
        return _emit(arm(args.workspace, args.host, apply=args.apply), args.json)
    if args.command == "verify-host":
        return _emit(verify_host(args.workspace, args.host), args.json)
    return _emit(verify_fleet(args.workspace, args.hosts), args.json)


if __name__ == "__main__":
    sys.exit(main())
