"""Bind the phase extension to runtime with the existing conformance runner.

All proof/evaluation sources and receipts are retained under the output folder.
The existing kernel, checker installation and production conformance are not edited.
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


def _load_runtime():
    path = HERE / "phase_contract.py"
    raw = path.read_bytes()
    module = types.ModuleType("phase_contract_for_conformance")
    module.__file__ = str(path)
    module.__source_sha256__ = hashlib.sha256(raw).hexdigest()
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def run(producer_path, out_path, *, prove_detection=False, additional_bindings=()):
    runtime = _load_runtime()
    base = runtime.load_module(HERE / "conformance.py", "fames_base_conformance_for_phases")
    gate = runtime.load_module(HERE / "lean_gate.py", "fames_phase_lean_runner")
    producer = runtime.load_module(producer_path, "fames_phase_bound_producer")
    if not callable(getattr(producer, "replay_phase_facts", None)):
        raise ValueError("producer_missing_replay_phase_facts")
    out_path = Path(out_path).resolve()
    if out_path.exists():
        raise FileExistsError("Choose a new retained receipt path; existing receipts are never overwritten")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    retained = out_path.parent / ("phase-check-" + uuid.uuid4().hex)
    retained.mkdir()
    files = {
        "kernel": runtime.KERNEL, "extension": runtime.EXTENSION,
        "runtime": HERE / "phase_contract.py", "runner": Path(__file__),
        "base_runner": HERE / "conformance.py", "lean_gate": HERE / "lean_gate.py",
        "leanctl": HERE.parent / "leanctl.py", "producer": Path(producer_path).resolve(),
    }
    files.update({"dependency_" + str(i): Path(path).resolve() for i, path in enumerate(additional_bindings)})
    initial = base.binding_snapshot(files)
    for key, module in (("runtime", runtime), ("base_runner", base), ("lean_gate", gate), ("producer", producer)):
        if initial[key]["sha256"] != module.__source_sha256__:
            raise ValueError("loaded_source_identity_mismatch:" + key)
    checker_before = gate.checker_now()
    combined = runtime.model_source()
    combined_path = retained / "CombinedKernel.lean"
    combined_path.write_text(combined, encoding="utf-8")
    captured = {}

    def check(source, timeout, *, grace):
        # leanctl hashes decoded LF text. Preserve that exact byte representation
        # so the retained source and the kernel receipt share one identity on Windows.
        source = Path(source)
        source.write_bytes(source.read_text(encoding="utf-8").encode("utf-8"))
        captured["source"] = Path(source)
        captured["proof"] = gate.run_lean(source, timeout, grace=grace)
        return captured["proof"]

    def retain_temp(prefix):
        path = retained / (prefix + uuid.uuid4().hex)
        path.mkdir()
        return str(path)

    # Fresh in-memory runner instance; no shared runner source or global tempfile mutation.
    base.KERNEL = combined_path
    base.EVAL_ORDER = ["phase", "transition"]
    base._eval_block = lambda _keys: runtime.EVAL_BLOCK
    base.tempfile = types.SimpleNamespace(mkdtemp=retain_temp)
    lean = base.run_lean_tables(types.SimpleNamespace(run_lean=check), "", timeout=600.0)
    proof = captured.get("proof", {})
    proof_path = retained / "phase-proof.json"
    proof_path.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    proof_source = captured.get("source", combined_path)
    phase_chars = []
    phases = (*runtime.PHASES, "other")
    for phase in phases:
        for skip in (False, True):
            for why in (False, True):
                for mask in range(4096):
                    phase_chars.append("1" if runtime.admit(phase, skip, why, runtime.fact_bits(mask)) else "0")
    transition_chars = []
    authorities = ([], [0], [1], [0, 1])
    for expected in phases:
        for phase in phases:
            for bound in (False, True):
                for prior in (False, True):
                    for ready in (False, True):
                        for before in authorities:
                            for after in authorities:
                                transition_chars.append("1" if runtime.transition(expected, phase, bound, prior, before, after, ready) else "0")
    tables = dict(lean.get("tables", {}))
    if prove_detection and tables.get("phase"):
        old = tables["phase"]
        tables["phase"] = ("1" if old[0] == "0" else "0") + old[1:]
    domains = {}
    for name, expected_chars in (("phase", phase_chars), ("transition", transition_chars)):
        observed = tables.get(name, "")
        mismatches = [i for i, (a, b) in enumerate(zip(observed, expected_chars)) if a != b]
        mismatch_count = len(mismatches) + abs(len(observed) - len(expected_chars))
        domains[name] = {"cases": len(expected_chars), "lean_cases": len(observed),
                         "mismatches": mismatch_count, "first_mismatch_indexes": mismatches[:8]}
    names = {row.get("name") for row in proof.get("audit", {}).get("theorems", []) if not row.get("synthetic")}
    required = {"Fames.PhaseContract." + name for name in runtime.THEOREMS}
    final = base.binding_snapshot(files)
    drift = base.binding_drift(initial, final)
    checker_after = gate.checker_now()
    mismatch_total = sum(item["mismatches"] for item in domains.values())
    proof_ok = (lean.get("ok") is True and proof.get("verdict") == "PROVED"
                and proof.get("source_sha256") == runtime.file_sha(proof_source)
                and required.issubset(names))
    ok = (proof_ok and mismatch_total == 0 and not drift and checker_before is not None
          and checker_before == checker_after)
    report = {
        "schema": "fames-phase-conformance/1", "ok": ok,
        "generated_at": datetime.now(timezone.utc).isoformat(), "bindings": final,
        "initial_bindings": initial, "binding_drift": drift,
        "checker_id": (checker_after or {}).get("id"),
        "model_sha256": runtime.digest(combined.encode("utf-8")),
        "proof_receipt": {"path": str(proof_path), "sha256": runtime.file_sha(proof_path)},
        "proof_source": {"path": str(proof_source), "sha256": runtime.file_sha(proof_source)},
        "required_theorems": sorted(required), "all_required_theorems_audited": required.issubset(names),
        "lean_verdict": proof.get("verdict"), "lean_cautions": proof.get("cautions", []),
        "domains": domains, "mismatches": mismatch_total,
        "prove_detection": prove_detection, "seeded_mismatch_detected": bool(prove_detection and mismatch_total),
        "scope": "Exhaustive finite phase/transition decisions, universal named model theorems, source-bound producer replay. Actual artifact meaning and host invocation require their separate runtime evidence.",
        "retained_artifacts": str(retained),
    }
    with out_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--producer", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bind", type=Path, action="append", default=[])
    parser.add_argument("--prove-detection", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args.producer, args.out, prove_detection=args.prove_detection, additional_bindings=args.bind)
        print(json.dumps({key: result[key] for key in ("ok", "lean_verdict", "mismatches", "binding_drift", "seeded_mismatch_detected")}, ensure_ascii=True))
        return 0 if result["ok"] else 1
    except Exception as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__, "reason": str(error)}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
