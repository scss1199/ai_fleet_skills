#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bind `Fames.ClaimContract.admissible` (ClaimContract.lean) to the running PROOF hook.

The Lean file proves the admission rule's properties (fail closed, one evidence kind per class,
monotone). This runner is what ties those theorems to `_skill/engines/claude-proof-hook.py`:
it evaluates `Fames.ClaimContract.table` with leanctl (10 classes x 2048 evidence vectors) and
compares every cell with the hook's `claim_table()`. On success it writes the hash-bound receipt
`evidence/claim-conformance.json`; `tests/test_claim_contract.py` fails whenever the hook or the
Lean file no longer hashes to what was compared here.

  python claim_conformance.py                  # exit 0 iff Lean PROVED and 0 mismatching cells
  python claim_conformance.py --prove-detection   # seeded mismatch control: must exit 1

No network, no model calls, child processes never open a console window.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parents[1]
LEAN_FILE = HERE / "ClaimContract.lean"
HOOK = HUB / "_skill" / "engines" / "claude-proof-hook.py"
LEAN_GATE = HERE / "lean_gate.py"
LEANCTL = HERE.parent / "leanctl.py"
RECEIPT = HERE / "evidence" / "claim-conformance.json"
SCHEMA = "fames-claim-conformance/1"
N_CELLS = 10 * 2048


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decode(text: str) -> str:
    text = text.strip()
    try:
        value = json.loads(text)
        if isinstance(value, str):
            return value
    except ValueError:
        pass
    return text[1:-1] if len(text) >= 2 and text[0] == '"' and text[-1] == '"' else text


def lean_table(gate, timeout: float = 600.0) -> dict:
    source = LEAN_FILE.read_text(encoding="utf-8") + "\n#eval Fames.ClaimContract.table\n"
    tmp = Path(tempfile.mkdtemp(prefix="fames-claim-conf-")) / "ClaimEval.lean"
    tmp.write_text(source, encoding="utf-8")
    receipt = gate.run_lean(tmp, timeout, grace=180.0)
    msgs = receipt.get("messages") if isinstance(receipt.get("messages"), list) else []
    infos = [m for m in msgs if isinstance(m, dict) and m.get("severity") == "information" and isinstance(m.get("text"), str)]
    theorems = [t.get("name") for t in ((receipt.get("audit") or {}).get("theorems") or [])
                if isinstance(t, dict) and not t.get("synthetic")]
    return {
        "verdict": receipt.get("verdict"),
        "table": _decode(infos[-1]["text"]) if infos else "",
        "n_information": len(infos),
        "theorems": theorems,
        "elapsed_s": receipt.get("elapsed_s"),
        "reasons": receipt.get("reasons") or [],
        "error": receipt.get("error"),
    }


def compare(lean: str, hook: str) -> dict:
    lc = {c.split("=")[0]: c.split("=")[1] for c in lean.split(";") if "=" in c}
    hc = {c.split("=")[0]: c.split("=")[1] for c in hook.split(";") if "=" in c}
    mismatches = [k for k in sorted(set(lc) | set(hc)) if lc.get(k) != hc.get(k)]
    return {"lean_cells": len(lc), "hook_cells": len(hc), "mismatches": mismatches[:20], "n_mismatch": len(mismatches)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prove-detection", action="store_true", help="flip one hook cell; must report a mismatch and exit 1")
    ap.add_argument("--timeout", type=float, default=600.0)
    a = ap.parse_args()
    gate = _load("fames_lean_gate_for_claims", LEAN_GATE)
    hook = _load("claude_proof_hook_for_claims", HOOK)
    started = time.time()
    lean = lean_table(gate, a.timeout)
    hook_table = hook.claim_table()
    if a.prove_detection:
        cells = hook_table.split(";")
        cells[5] = cells[5][:-1] + ("0" if cells[5].endswith("1") else "1")
        hook_table = ";".join(cells)
    cmp = compare(lean["table"], hook_table)
    ok = lean["verdict"] == "PROVED" and cmp["n_mismatch"] == 0 and cmp["lean_cells"] == N_CELLS and cmp["hook_cells"] == N_CELLS
    doc = {
        "schema": SCHEMA, "ok": ok, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(time.time() - started, 2), "prove_detection": a.prove_detection,
        "lean": {k: lean[k] for k in ("verdict", "n_information", "theorems", "elapsed_s", "reasons", "error")},
        "compare": cmp,
        "bound": {
            "lean_file": {"path": str(LEAN_FILE), "sha256": _sha(LEAN_FILE)},
            "hook": {"path": str(HOOK), "sha256": _sha(HOOK)},
            "leanctl": {"path": str(LEANCTL), "sha256": _sha(LEANCTL)},
            "runner": {"path": str(Path(__file__).resolve()), "sha256": _sha(Path(__file__).resolve())},
        },
    }
    if not a.prove_detection:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("ok", "lean", "compare", "elapsed_s", "prove_detection")}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
