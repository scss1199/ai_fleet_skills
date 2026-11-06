"""Source-bound FAMES phase admission; no provider calls and no Lean run per read.

Fact bits never constitute evidence by themselves. A bound producer recomputes
them from current referenced artifacts on production and every evaluation.
This is an evidence protocol, not a same-user or operating-system sandbox.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KERNEL = ROOT / "FamesKernel.lean"
EXTENSION = ROOT / "FamesPhaseContract.lean"
MARKER = "/-! ## 4. Mathematical evidence -/"
PHASES = ("FP", "MTM", "SCF", "AEX", "SEAL")
FACTS = ("goal_bound", "authority_bound", "acceptance_bound", "skills_bound",
         "result_verified", "identity_fresh", "evidence_fresh", "residual_measured",
         "residual_comparable", "cross_cycle", "boundaries_preserved", "graph_closed")
EVAL_BLOCK = "\n#eval Fames.PhaseContract.phaseTable\n#eval Fames.PhaseContract.transitionTable\n"
THEOREMS = (
    "transition_iff", "accepted_transition_preserves_authority",
    "accepted_transition_cannot_skip_phase", "arbitrarily_long_authority_trace_narrows",
    "fp_admission_binds_goal_authority_acceptance", "mtm_admission_binds_skills",
    "scf_execution_needs_verified_current_result", "aex_execution_needs_measured_comparable_residual",
    "skips_are_only_explicit_inactive_scf_or_aex", "seal_requires_verified_fresh_closed_result",
    "rejected_admission_cannot_advance",
)
HEX = re.compile(r"[0-9a-f]{64}")
_MODULES = {}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def file_sha(path):
    return digest(Path(path).read_bytes())


def load_module(path, name):
    path = Path(path).resolve()
    raw = path.read_bytes()
    key = (str(path), digest(raw))
    if key in _MODULES:
        return _MODULES[key]
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__source_sha256__ = digest(raw)
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    if file_sha(path) != digest(raw):
        raise ValueError("module_source_changed_during_load")
    _MODULES[key] = module
    return module


def model_source():
    kernel = KERNEL.read_text(encoding="utf-8")
    if kernel.count(MARKER) != 1:
        raise ValueError("kernel_extension_point_changed")
    return kernel.replace(MARKER, EXTENSION.read_text(encoding="utf-8") + "\n" + MARKER)


def active(phase, facts):
    if phase == "SCF":
        return facts["result_verified"] and facts["identity_fresh"]
    if phase == "AEX":
        return facts["cross_cycle"] and facts["residual_measured"] and facts["residual_comparable"]
    return phase in PHASES


def admit(phase, skip, has_why, facts):
    if skip:
        return phase in ("SCF", "AEX") and not active(phase, facts) and has_why
    required = {
        "FP": ("goal_bound", "authority_bound", "acceptance_bound"),
        "MTM": ("skills_bound", "authority_bound"),
        "SCF": ("result_verified", "identity_fresh"),
        "AEX": ("result_verified", "identity_fresh", "cross_cycle", "residual_measured", "residual_comparable"),
        "SEAL": ("goal_bound", "authority_bound", "acceptance_bound", "result_verified",
                 "identity_fresh", "evidence_fresh", "boundaries_preserved", "graph_closed"),
    }
    return active(phase, facts) and all(facts[key] for key in required.get(phase, ()))


def transition(expected, phase, bound, prior_valid, before, after, ready):
    return bool(bound and prior_valid and expected == phase and all(scope in before for scope in after) and ready)


def fact_bits(mask):
    return {key: bool(mask & (1 << i)) for i, key in enumerate(FACTS)}


def _ref(ref):
    if not isinstance(ref, dict) or not HEX.fullmatch(str(ref.get("sha256", ""))):
        raise ValueError("invalid_artifact_reference")
    path = Path(ref["path"])
    if not path.is_absolute():
        raise ValueError("relative_artifact_reference")
    raw = path.read_bytes()
    if digest(raw) != ref["sha256"]:
        raise ValueError("artifact_identity_changed")
    return raw


def _bindings_current(bindings):
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("missing_source_bindings")
    for ref in bindings.values():
        _ref(ref)


def _conformance(path):
    raw = Path(path).read_bytes()
    doc = json.loads(raw)
    if doc.get("schema") != "fames-phase-conformance/1" or doc.get("ok") is not True:
        raise ValueError("phase_conformance_not_passing")
    expected = {
        "kernel": KERNEL, "extension": EXTENSION, "runtime": Path(__file__),
        "runner": ROOT / "phase_conformance.py", "base_runner": ROOT / "conformance.py",
        "lean_gate": ROOT / "lean_gate.py", "leanctl": ROOT.parent / "leanctl.py",
    }
    bindings = doc.get("bindings", {})
    for name, target in expected.items():
        if Path(bindings.get(name, {}).get("path", "")).resolve() != target.resolve():
            raise ValueError("wrong_conformance_binding:" + name)
    if "producer" not in bindings:
        raise ValueError("producer_not_bound")
    _bindings_current(bindings)
    if doc.get("model_sha256") != digest(model_source().encode("utf-8")):
        raise ValueError("phase_model_changed")
    proof = json.loads(_ref(doc["proof_receipt"]))
    source = _ref(doc["proof_source"])
    if proof.get("verdict") != "PROVED" or proof.get("source_sha256") != digest(source):
        raise ValueError("phase_proof_not_current")
    if source != (model_source() + "\n" + EVAL_BLOCK).encode("utf-8"):
        raise ValueError("phase_proof_model_mismatch")
    if doc.get("mismatches") != 0 or doc.get("prove_detection") is not False or doc.get("binding_drift") != []:
        raise ValueError("phase_conformance_has_mismatch_or_drift")
    for domain, count in (("phase", 98304), ("transition", 4608)):
        row = doc.get("domains", {}).get(domain, {})
        if row.get("cases") != count or row.get("lean_cases") != count or row.get("mismatches") != 0:
            raise ValueError("phase_conformance_domain_incomplete")
    names = {row.get("name") for row in proof.get("audit", {}).get("theorems", []) if not row.get("synthetic")}
    if not {"Fames.PhaseContract." + name for name in THEOREMS}.issubset(names):
        raise ValueError("required_phase_theorem_missing")
    gate = load_module(ROOT / "lean_gate.py", "fames_phase_checker_identity")
    checker = gate.checker_now()
    if not checker or checker.get("id") != doc.get("checker_id"):
        raise ValueError("phase_checker_changed")
    doc["receipt_sha256"] = digest(raw)
    return doc


def _request_ok(request):
    if not isinstance(request, dict) or request.get("schema") != "fames-phase-input/1":
        raise ValueError("invalid_phase_input")
    if request.get("phase") not in PHASES or request.get("mode") not in ("execute", "skip"):
        raise ValueError("invalid_phase_or_mode")
    if not isinstance(request.get("task_id"), str) or not request["task_id"].strip():
        raise ValueError("missing_task_identity")
    for key in ("goal_identity", "phase_identity"):
        if not HEX.fullmatch(str(request.get(key, ""))):
            raise ValueError("invalid_" + key)
    for key in ("authority_before", "authority_after"):
        scopes = request.get(key)
        if not isinstance(scopes, list) or any(not isinstance(x, str) or not x.strip() for x in scopes):
            raise ValueError("invalid_" + key)
    refs = request.get("receipt_refs")
    if not isinstance(refs, list) or not refs or len(refs) > 256:
        raise ValueError("missing_or_excessive_phase_receipts")
    roles = set()
    for ref in refs:
        role = ref.get("role") if isinstance(ref, dict) else None
        if not isinstance(role, str) or not role or role in roles:
            raise ValueError("invalid_or_duplicate_receipt_role")
        roles.add(role)
        _ref(ref)


def _replay(request, conf):
    _request_ok(request)
    producer_ref = conf["bindings"]["producer"]
    producer = load_module(producer_ref["path"], "fames_phase_evidence_producer")
    replay = getattr(producer, "replay_phase_facts", None)
    if not callable(replay):
        raise ValueError("phase_producer_api_missing")
    facts = replay(json.loads(json.dumps(request)))
    if not isinstance(facts, dict) or set(facts) != set(FACTS) or any(type(v) is not bool for v in facts.values()):
        raise ValueError("phase_producer_returned_invalid_facts")
    _request_ok(request)
    _bindings_current(conf["bindings"])
    return facts


def produce_phase_evidence(request, *, producer_path, conformance_path):
    conf = _conformance(conformance_path)
    if Path(producer_path).resolve() != Path(conf["bindings"]["producer"]["path"]).resolve():
        raise ValueError("unbound_phase_producer")
    facts = _replay(request, conf)
    return {
        "schema": "fames-phase-evidence/1", "request": json.loads(json.dumps(request)),
        "facts": facts, "producer": dict(conf["bindings"]["producer"]),
        "conformance_sha256": conf["receipt_sha256"], "model_sha256": conf["model_sha256"],
    }


def _guard_digest(guard):
    return digest({key: value for key, value in guard.items() if key not in ("guard_sha256", "receipt_sha256")})


def evaluate_phase(phase, value, *, conformance_path, _depth=0, _seen=()):
    evidence = value.get("evidence", value) if isinstance(value, dict) else {}
    request = evidence.get("request", {}) if isinstance(evidence, dict) else {}
    result = {
        "schema": "fames-phase-guard/1", "phase": phase, "state": "UNKNOWN",
        "task_id": request.get("task_id"), "goal_identity": request.get("goal_identity"),
        "phase_identity": request.get("phase_identity"),
        "observed_at": datetime.now(timezone.utc).isoformat(), "reasons": [],
        "facts": {}, "authority_after": request.get("authority_after", []),
        "contract_sha256": None, "conformance_sha256": None,
        "proof_theorems": [], "evidence": evidence,
    }
    try:
        if _depth > 4 or phase not in PHASES:
            raise ValueError("invalid_or_recursive_phase_chain")
        if isinstance(value, dict) and value.get("schema") == "fames-phase-guard/1":
            if value.get("guard_sha256") != _guard_digest(value) or value.get("receipt_sha256") != value.get("guard_sha256"):
                raise ValueError("saved_guard_digest_changed")
        if evidence.get("schema") != "fames-phase-evidence/1" or request.get("phase") != phase:
            raise ValueError("phase_evidence_mismatch")
        conf = _conformance(conformance_path)
        result.update(contract_sha256=conf["model_sha256"], conformance_sha256=conf["receipt_sha256"])
        if evidence.get("conformance_sha256") != conf["receipt_sha256"] or evidence.get("model_sha256") != conf["model_sha256"]:
            raise ValueError("phase_evidence_conformance_changed")
        if evidence.get("producer") != conf["bindings"]["producer"]:
            raise ValueError("phase_evidence_producer_changed")
        facts = _replay(request, conf)
        if evidence.get("facts") != facts:
            raise ValueError("phase_facts_do_not_replay")
        result["facts"] = facts
        before, after = request["authority_before"], request["authority_after"]
        if not all(scope in before for scope in after):
            result["state"] = "FORBIDDEN"
            raise ValueError("authority_expansion")
        previous_ref = request.get("previous_guard")
        if phase == "FP":
            if previous_ref is not None:
                result["state"] = "FORBIDDEN"
                raise ValueError("fp_has_previous_phase")
        else:
            if not isinstance(previous_ref, dict):
                raise ValueError("previous_phase_guard_missing")
            previous_raw = _ref(previous_ref)
            prior_key = previous_ref["sha256"]
            if prior_key in _seen:
                raise ValueError("recursive_previous_guard")
            previous = json.loads(previous_raw)
            expected = PHASES[PHASES.index(phase) - 1]
            if previous.get("phase") != expected:
                result["state"] = "FORBIDDEN"
                raise ValueError("phase_order_violation")
            prior = evaluate_phase(expected, previous, conformance_path=conformance_path,
                                   _depth=_depth + 1, _seen=(*_seen, prior_key))
            if prior.get("state") not in ("PASS", "INACTIVE"):
                raise ValueError("previous_guard_no_longer_admitted")
            if any(prior.get(key) != request.get(key) for key in ("task_id", "goal_identity")):
                raise ValueError("previous_guard_task_mismatch")
            if set(prior["authority_after"]) != set(before):
                result["state"] = "FORBIDDEN"
                raise ValueError("authority_chain_discontinuity")
        skip = request["mode"] == "skip"
        why = isinstance(request.get("skip_reason"), str) and bool(request["skip_reason"].strip())
        ready = admit(phase, skip, why, facts)
        if not transition(phase, phase, True, True, before, after, ready):
            if skip and (phase not in ("SCF", "AEX") or active(phase, facts)):
                result["state"] = "FORBIDDEN"
            raise ValueError("phase_predicate_not_satisfied")
        _request_ok(request)
        _bindings_current(conf["bindings"])
        if previous_ref is not None:
            _ref(previous_ref)
        if file_sha(conformance_path) != conf["receipt_sha256"]:
            raise ValueError("conformance_changed_during_evaluation")
        result.update(state="INACTIVE" if skip else "PASS",
                      proof_theorems=["Fames.PhaseContract." + name for name in THEOREMS])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError, SyntaxError) as error:
        result["reasons"].append(str(error) if isinstance(error, ValueError) else type(error).__name__)
    result["guard_sha256"] = _guard_digest(result)
    result["receipt_sha256"] = result["guard_sha256"]
    return result
