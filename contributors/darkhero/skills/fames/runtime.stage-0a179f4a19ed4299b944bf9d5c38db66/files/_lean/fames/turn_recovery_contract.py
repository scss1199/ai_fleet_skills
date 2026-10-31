"""Strict recovery admission and source-bound Lean/Python finite conformance.

Facts are inputs from a verifier, never evidence on their own. This module does
not rebuild a prompt, fabricate a native event, call a provider, or grant task
completion. Only the caller can establish facts from real retained artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = HERE / "FamesTurnRecovery.lean"
FACTS = ("same_session", "exact_prompt", "same_seat", "native_origin_verified",
         "original_receipt_fresh", "source_hash_bound")
THEOREMS = ("recovery_iff", "accepted_recovery_requires_original_identity",
            "accepted_recovery_preserves_authority", "recovery_never_authorizes_completion",
            "jev_advice_cannot_change_admission", "absent_native_evidence_rejects_even_with_advice")
EVAL_BLOCK = "\n#eval Fames.TurnRecovery.admissionTable\n#eval Fames.TurnRecovery.completionTable\n"
AUTHORITIES = ([], ["read"], ["repair"], ["read", "repair"])
DOMAIN_CASES = 64 * 4 * 4 * 2


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


LOADED_SOURCE_SHA256 = _sha(Path(__file__).read_bytes())


def _authority_valid(scopes):
    return (type(scopes) in (list, tuple) and
            all(type(scope) is str and bool(scope.strip()) for scope in scopes))


def recovery_allowed(facts, authority_before, authority_after):
    """Return a Bool; missing, non-Bool, malformed or extra fact fields fail closed."""
    if type(facts) is not dict or set(facts) != set(FACTS):
        return False
    if not all(type(facts[key]) is bool and facts[key] is True for key in FACTS):
        return False
    if not (_authority_valid(authority_before) and _authority_valid(authority_after)):
        return False
    return all(scope in authority_before for scope in authority_after)


def recovery_decision(facts, authority_before, authority_after, *, jev_advice=False):
    """Advice is deliberately non-authoritative; completion always stays separate."""
    return {"admitted": recovery_allowed(facts, authority_before, authority_after),
            "completion_authorized": False}


def fact_bits(mask):
    return {key: bool(mask & (1 << index)) for index, key in enumerate(FACTS)}


def _tables():
    tables = {"admission": [], "completion": []}
    for mask in range(64):
        for before in AUTHORITIES:
            for after in AUTHORITIES:
                for advice in (False, True):
                    row = recovery_decision(fact_bits(mask), before, after, jev_advice=advice)
                    tables["admission"].append("1" if row["admitted"] else "0")
                    tables["completion"].append("1" if row["completion_authorized"] else "0")
    return {key: "".join(value) for key, value in tables.items()}


def _ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": _sha(path.read_bytes())}


def _read_ref(ref):
    if type(ref) is not dict or not Path(ref.get("path", "")).is_absolute():
        raise ValueError("invalid_artifact_reference")
    raw = Path(ref["path"]).read_bytes()
    if _sha(raw) != ref.get("sha256"):
        raise ValueError("artifact_identity_changed")
    return raw


def _bindings():
    return {name: _ref(path) for name, path in {
        "model": MODEL, "runtime": Path(__file__),
        "lean_gate": HERE / "lean_gate.py", "leanctl": HERE.parent / "leanctl.py",
    }.items()}


def _gate():
    path = HERE / "lean_gate.py"
    raw = path.read_bytes()
    module = types.ModuleType("fames_turn_recovery_lean_gate")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    if raw != path.read_bytes():
        raise ValueError("lean_gate_changed_during_load")
    return module


def _proof_tables(proof):
    infos = [row["text"] for row in proof.get("messages", [])
             if row.get("severity") == "information" and type(row.get("text")) is str]
    if len(infos) != 2:
        raise ValueError("missing_lean_tables")
    decoded = [json.loads(text.strip()) for text in infos]
    if not all(type(table) is str and set(table) <= {"0", "1"} for table in decoded):
        raise ValueError("invalid_lean_tables")
    return dict(zip(("admission", "completion"), decoded))


def _proof_valid(proof, source):
    names = {row.get("name") for row in proof.get("audit", {}).get("theorems", [])
             if not row.get("synthetic")}
    required = {"Fames.TurnRecovery." + name for name in THEOREMS}
    return (proof.get("verdict") == "PROVED" and proof.get("source_sha256") == _sha(source)
            and required <= names)


def run_conformance(out_path, *, prove_detection=False):
    out_path = Path(out_path).resolve()
    if out_path.exists():
        raise FileExistsError("Retained evidence is never overwritten; choose a new output path")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    retained = out_path.parent / ("turn-recovery-" + uuid.uuid4().hex)
    retained.mkdir()
    initial = _bindings()
    if initial["runtime"]["sha256"] != LOADED_SOURCE_SHA256:
        raise ValueError("loaded_runtime_identity_changed")
    gate = _gate()
    checker_before = gate.checker_now()
    source = (MODEL.read_text(encoding="utf-8") + EVAL_BLOCK).encode("utf-8")
    source_path = retained / "FamesTurnRecoveryEval.lean"
    source_path.write_bytes(source)
    proof = gate.run_lean(source_path, 120, grace=30)
    proof_path = retained / "proof.json"
    proof_path.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    actual = _proof_tables(proof) if proof.get("verdict") == "PROVED" else {}
    if prove_detection and actual.get("admission"):
        old = actual["admission"]
        actual["admission"] = ("1" if old[0] == "0" else "0") + old[1:]
    domains = {}
    for name, expected in _tables().items():
        observed = actual.get(name, "")
        mismatches = sum(a != b for a, b in zip(expected, observed)) + abs(len(expected) - len(observed))
        domains[name] = {"cases": len(expected), "lean_cases": len(observed), "mismatches": mismatches}
    final = _bindings()
    drift = sorted(key for key in initial if initial[key] != final[key])
    checker_after = gate.checker_now()
    total = sum(row["mismatches"] for row in domains.values())
    ok = (_proof_valid(proof, source) and total == 0 and not drift and
          checker_before is not None and checker_before == checker_after)
    report = {
        "schema": "fames-turn-recovery-conformance/1", "ok": ok,
        "generated_at": datetime.now(timezone.utc).isoformat(), "bindings": final,
        "binding_drift": drift, "checker_id": (checker_after or {}).get("id"),
        "proof_receipt": _ref(proof_path), "proof_source": _ref(source_path),
        "lean_verdict": proof.get("verdict"), "lean_cautions": proof.get("cautions", []),
        "required_theorems": ["Fames.TurnRecovery." + name for name in THEOREMS],
        "domains": domains, "mismatches": total, "prove_detection": prove_detection,
        "seeded_mismatch_detected": bool(prove_detection and total),
        "scope": "Admission over six evidence predicates and authority subset; finite Python/Lean parity. Caller must separately verify real native provenance and completion evidence.",
    }
    with out_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return report


def conformance_status(path):
    """Replay proof tables and current identities; do not trust the summary PASS bit."""
    try:
        report = json.loads(Path(path).read_bytes())
        if (report.get("schema") != "fames-turn-recovery-conformance/1" or
                report.get("ok") is not True or report.get("prove_detection") is not False or
                report.get("binding_drift") != [] or report.get("mismatches") != 0):
            raise ValueError("conformance_not_passing")
        current = _bindings()
        if current != report.get("bindings") or current["runtime"]["sha256"] != LOADED_SOURCE_SHA256:
            raise ValueError("conformance_binding_changed")
        proof = json.loads(_read_ref(report["proof_receipt"]))
        source = _read_ref(report["proof_source"])
        if source != (MODEL.read_text(encoding="utf-8") + EVAL_BLOCK).encode("utf-8"):
            raise ValueError("proof_model_changed")
        if not _proof_valid(proof, source):
            raise ValueError("proof_not_current")
        if _proof_tables(proof) != _tables():
            raise ValueError("conformance_table_mismatch")
        for name in ("admission", "completion"):
            if report.get("domains", {}).get(name) != {"cases": DOMAIN_CASES, "lean_cases": DOMAIN_CASES, "mismatches": 0}:
                raise ValueError("conformance_domain_incomplete")
        checker = _gate().checker_now()
        if not checker or checker.get("id") != report.get("checker_id"):
            raise ValueError("checker_identity_changed")
        return {"ok": True, "reason": "current_proof_and_exhaustive_parity", "receipt": str(Path(path).resolve())}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return {"ok": False, "reason": str(error)}


def verified_recovery_decision(facts, authority_before, authority_after, *, conformance_path, jev_advice=False):
    status = conformance_status(conformance_path)
    row = recovery_decision(facts, authority_before, authority_after, jev_advice=jev_advice)
    row["admitted"] = row["admitted"] and status["ok"]
    return {**row, "conformance": status}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prove-detection", action="store_true")
    args = parser.parse_args(argv)
    report = run_conformance(args.out, prove_detection=args.prove_detection)
    print(json.dumps({key: report[key] for key in ("ok", "lean_verdict", "mismatches", "seeded_mismatch_detected")}, ensure_ascii=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
