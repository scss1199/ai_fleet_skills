#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FAMES <-> Lean conformance: compare the Lean kernel truth tables with the real Python FAMES code.

The kernel `FamesKernel.lean` is a finite model of the decision rules the FAMES gates enforce, with
the fleet's invariants proved as theorems. A theorem there is a statement about the MODEL. This script
is the only thing that binds the model to the RUNNING Python: it evaluates the kernel's tables with
`leanctl` and compares every cell with the real functions --

  * section 1  fames_fleet.validate_run          (phase ledger / SCF residual / AEX gate)
  * section 2  claude-claim-integrity-hook.py     (lint_message, evaluate_hook: claim / gate / action)
  * section 3  fames_fleet.validate_autonomic     (authority may only narrow)
  * section 4  lean_gate.evidence_ok              (what counts as mathematical evidence)

Every abstract kernel point is concretized into real inputs (many concrete variants per abstract cell,
seeded and recorded) and the real function is run. Only the kernel-modeled errors are compared; any
foreign error a real function raises is counted and must be zero. On success it writes the hash-bound
receipt `evidence/conformance.json`; the Lean gate accepts mathematical evidence only while that receipt
is present, ok, and every bound file still hashes to what was compared here.

  python conformance.py                 # full run; exit 0 iff ok and 0 mismatches
  python conformance.py --prove-detection   # seeded-mismatch control: must exit 1 (proves the comparator bites)

No network, no model calls. Every subprocess is spawned with CREATE_NO_WINDOW.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

GATE_PATH = Path(__file__).resolve()
FAMES_DIR = GATE_PATH.parent
ROOT = FAMES_DIR.parent                      # C:\ai_workspace\_lean
HUB = ROOT.parent                            # C:\ai_workspace
KERNEL = FAMES_DIR / "FamesKernel.lean"
LEAN_GATE = FAMES_DIR / "lean_gate.py"
LEANCTL = ROOT / "leanctl.py"
FAMES_FLEET = HUB / "_skill" / "fleet-skills" / "fames" / "scripts" / "fames_fleet.py"
CLAIM_HOOK = HUB / "_skill" / "engines" / "claude-claim-integrity-hook.py"
CLAIM_LINTER = HUB / "_skill" / "engines" / "claim-linter.py"
RECEIPT = FAMES_DIR / "evidence" / "conformance.json"
CONFORMANCE_SCHEMA = "fames-lean-conformance/1"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SEED = 20260919

RESIDUAL_KEYS = ["R_outcome", "R_safety", "R_evidence", "R_complexity", "R_portability",
                 "R_authority", "R_operability"]
EXECUTION_ORDER = ["FP", "MTM", "SCF", "AEX", "SEAL"]

MISSING = object()   # sentinel: "do not set this key at all"


# --------------------------------------------------------------------------- module loaders
def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str | None:
    try:
        return _sha_bytes(path.read_bytes())
    except OSError:
        return None


def bit(b: object) -> str:
    return "1" if b else "0"


# --------------------------------------------------------------------------- Lean evaluation
EVAL_ORDER = ["rows", "aex", "residual", "order", "decoded", "claim", "gate", "action", "math", "authority"]


def _eval_block(decoded_keys: str) -> str:
    return "\n".join([
        "", "#eval Fames.runTable Fames.domainRows",
        "#eval Fames.runTable Fames.domainAex",
        "#eval Fames.runTable Fames.domainResidual",
        "#eval Fames.runTable Fames.domainOrder",
        '#eval Fames.decodedTable "%s"' % decoded_keys,
        "#eval Fames.claimTable",
        "#eval Fames.gateTable",
        "#eval Fames.actionTable",
        "#eval Fames.mathTable",
        "#eval Fames.authorityTable",
        "",
    ])


def _decode_string_message(text: str) -> str:
    """A Lean `#eval` on a String prints it as a quoted literal; recover the content."""
    text = text.strip()
    try:
        value = json.loads(text)
        if isinstance(value, str):
            return value
    except ValueError:
        pass
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def run_lean_tables(gate, decoded_keys: str, timeout: float = 600.0) -> dict:
    """Generate <kernel> + eval block, check it with leanctl, return the ten table strings in order."""
    kernel_text = KERNEL.read_text(encoding="utf-8")
    source = kernel_text + "\n" + _eval_block(decoded_keys)
    tmpdir = Path(tempfile.mkdtemp(prefix="fames-conf-"))
    src = tmpdir / "FamesEval.lean"
    src.write_text(source, encoding="utf-8")
    receipt = gate.run_lean(src, timeout, grace=180.0)
    verdict = receipt.get("verdict")
    messages = receipt.get("messages") if isinstance(receipt.get("messages"), list) else []
    infos = [m for m in messages if isinstance(m, dict) and m.get("severity") == "information"
             and isinstance(m.get("text"), str)]
    tables: dict[str, str] = {}
    if len(infos) == len(EVAL_ORDER):
        for name, msg in zip(EVAL_ORDER, infos):
            tables[name] = _decode_string_message(msg["text"])
    return {
        "verdict": verdict,
        "ok": verdict == "PROVED",
        "source_sha256": receipt.get("source_sha256"),
        "generated_sha256": _sha_bytes(source.encode("utf-8")),
        "elapsed_s": receipt.get("elapsed_s"),
        "n_information": len(infos),
        "tables": tables,
        "reasons": receipt.get("reasons") or [],
        "error": receipt.get("error"),
        "tmpdir": str(tmpdir),
    }


def cells_of(table: str) -> list[str]:
    return [c for c in table.split(";") if c] if table else []


def keyed(table: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for cell in cells_of(table):
        key, _, val = cell.partition("=")
        out[key] = val
    return out


# --------------------------------------------------------------------------- kernel domain mirror
FP, MTM, SCF, AEX, SEAL, OTHER = "FP", "MTM", "SCF", "AEX", "SEAL", "other"
ALL_PHASES = [FP, MTM, SCF, AEX, SEAL, OTHER]
ALL_BOOLS = [True, False]
ALL_PSTATES = ["pass", "na", "unknown", "fail", "invalid"]
ALL_PREDS = ["isTrue", "isFalse", "other"]
ALL_RVALS = ["zero", "nonzero", "null"]

PHASE_CODE = {FP: "F", MTM: "M", SCF: "S", AEX: "A", SEAL: "L", OTHER: "X"}
PSTATE_CODE = {"pass": "P", "na": "N", "unknown": "U", "fail": "F", "invalid": "I"}
PRED_CODE = {"isTrue": "t", "isFalse": "f", "other": "o"}
RVAL_CODE = {"zero": "z", "nonzero": "n", "null": "u"}
PHASE_STRING = {FP: "FP", MTM: "MTM", SCF: "SCF", AEX: "AEX", SEAL: "SEAL", OTHER: "X"}

# Row = (state, pred, hasWhy, targetNamed); Residual = (complete, (r0..r6)); Entry = (phase, row, res|None)
BASELINE_ROW = ("pass", "other", False, False)
BASELINE_AEX = ("na", "isFalse", True, False)
ACTIVATED_AEX = ("pass", "isTrue", True, True)
BASELINE_RESIDUAL = (True, ("zero",) * 7)

ALL_ROWS = [(s, p, w, t) for s in ALL_PSTATES for p in ALL_PREDS for w in ALL_BOOLS for t in ALL_BOOLS]


def _with_field(res, idx: int, val: str):
    complete, vals = res
    v = list(vals)
    v[idx] = val
    return (complete, tuple(v))


def all_residuals():
    for c in ALL_BOOLS:
        for o in ALL_RVALS:
            for s in ALL_RVALS:
                for e in ALL_RVALS:
                    for x in ALL_RVALS:
                        for p in ALL_RVALS:
                            for a in ALL_RVALS:
                                for q in ALL_RVALS:
                                    yield (c, (o, s, e, x, p, a, q))


def entry_for(p):
    row = BASELINE_AEX if p == AEX else BASELINE_ROW
    res = BASELINE_RESIDUAL if p == SCF else None
    return (p, row, res)


def ledger_of(col):
    return [entry_for(p) for p in col]


BASELINE_LEDGER = ledger_of(EXECUTION_ORDER)


def set_row(p, r, ledger):
    return [(e[0], r, e[2]) if e[0] == p else e for e in ledger]


def set_residual(res, ledger):
    return [(e[0], e[1], res) if e[0] == SCF else e for e in ledger]


def domain_rows():
    for x in ALL_BOOLS:
        for p in EXECUTION_ORDER:
            for r in ALL_ROWS:
                yield (set_row(p, r, BASELINE_LEDGER), x)


def residual_classes():
    base = BASELINE_RESIDUAL
    return [
        base,
        _with_field(base, 0, "nonzero"),   # outcome
        _with_field(base, 6, "nonzero"),   # operability
        _with_field(base, 1, "nonzero"),   # safety
        _with_field(base, 3, "null"),      # complexity
        (False, ("nonzero",) + ("zero",) * 6),   # complete=False, outcome nonzero
        None,
    ]


def domain_aex():
    for x in ALL_BOOLS:
        for res in residual_classes():
            for r in ALL_ROWS:
                yield (set_residual(res, set_row(AEX, r, BASELINE_LEDGER)), x)


def domain_residual():
    for x in ALL_BOOLS:
        for res in [None] + [r for r in all_residuals()]:
            yield (set_residual(res, BASELINE_LEDGER), x)
            yield (set_residual(res, set_row(AEX, ACTIVATED_AEX, BASELINE_LEDGER)), x)


def lists_of_len(n):
    if n == 0:
        return [[]]
    shorter = lists_of_len(n - 1)
    return [[p] + l for l in shorter for p in ALL_PHASES]


def insertions(p, col):
    if not col:
        return [[p]]
    a, rest = col[0], col[1:]
    return [[p] + col] + [[a] + l for l in insertions(p, rest)]


def domain_order():
    cols = []
    for n in range(6):
        cols.extend(lists_of_len(n))
    for p in ALL_PHASES:
        cols.extend(insertions(p, EXECUTION_ORDER))
    for col in cols:
        yield (ledger_of(col), False)


# --------------------------------------------------------------------------- encoding (mirror of Lean)
def encode_row(r) -> str:
    s, p, w, t = r
    return PSTATE_CODE[s] + PRED_CODE[p] + bit(w) + bit(t)


def encode_res(res) -> str:
    complete, vals = res
    return bit(complete) + "".join(RVAL_CODE[v] for v in vals)


def encode_entry(e) -> str:
    phase, row, res = e
    tail = "" if res is None else "~" + encode_res(res)
    return PHASE_CODE[phase] + encode_row(row) + tail


def encode_run(run) -> str:
    ledger, cross = run
    return ",".join(encode_entry(e) for e in ledger) + "|" + bit(cross)


# --------------------------------------------------------------------------- concretization
def _concrete_rval(tag, rng):
    if tag == "zero":
        return rng.choice([0, 0.0, False, -0.0])
    if tag == "nonzero":
        return rng.choice([0.5, 1, 2.5, True, "0", -1, [], float("nan")])
    return None


def _concrete_residual(res, rng):
    complete, vals = res
    full = {key: _concrete_rval(vals[i], rng) for i, key in enumerate(RESIDUAL_KEYS)}
    if complete:
        return full
    mode = rng.choice(["one", "several", "empty"])
    if mode == "empty":
        return {}
    if mode == "several":
        drop = set(rng.sample(RESIDUAL_KEYS, k=rng.randint(2, 4)))
    else:
        drop = {RESIDUAL_KEYS[rng.randrange(7)]}
    return {k: v for k, v in full.items() if k not in drop}


def concretize(run, rng) -> tuple[list, bool]:
    ledger, cross = run
    rows = []
    for phase, row, res in ledger:
        state, pred, has_why, target = row
        d = {"phase": PHASE_STRING[phase]}
        # state
        if state == "pass":
            d["state"] = "PASS"
        elif state == "na":
            d["state"] = "NOT_APPLICABLE"
        elif state == "unknown":
            d["state"] = "UNKNOWN"
        elif state == "fail":
            d["state"] = "FAIL"
        else:  # invalid
            choice = rng.choice([MISSING, "pass", None, "DONE", 1])
            if choice is not MISSING:
                d["state"] = choice
        # activation predicate
        if pred == "isTrue":
            d["activation_predicate"] = True
        elif pred == "isFalse":
            d["activation_predicate"] = False
        else:
            choice = rng.choice([MISSING, None, "false", 0, 1, "true"])
            if choice is not MISSING:
                d["activation_predicate"] = choice
        # why
        if has_why:
            d["why"] = "residual converged; horizon closed"
        else:
            choice = rng.choice([MISSING, "", None, 0])
            if choice is not MISSING:
                d["why"] = choice
        # target_residual
        if target:
            d["target_residual"] = rng.choice(RESIDUAL_KEYS)
        else:
            choice = rng.choice([MISSING, "R_bogus", None, "r_outcome", ["R_outcome"]])
            if choice is not MISSING:
                d["target_residual"] = choice
        if res is not None:
            d["residual"] = _concrete_residual(res, rng)
        rows.append(d)
    return rows, cross


# --------------------------------------------------------------------------- message -> code
def _kernel_code(msg: str):
    """Map one validate_run error to a kernel Err.code, or None if it is a foreign error."""
    if msg == "phase ledger execution order mismatch":
        return "ORDER"
    if msg == "SCF residual vector incomplete":
        return "RESIDUAL_INCOMPLETE"
    if msg == "AEX must activate for a verified comparable cross-cycle residual":
        return "AEX_MUST_ACTIVATE"
    if msg == "AEX must name the residual it targets":
        return "AEX_MUST_NAME_TARGET"
    if msg == "AEX must not activate without a cross-cycle residual":
        return "AEX_MUST_NOT_ACTIVATE"
    for key in ("R_safety", "R_evidence", "R_authority"):
        if msg == f"{key} is not converged":
            return f"NOT_CONVERGED:{key}"
    for phase in EXECUTION_ORDER:
        c = PHASE_CODE[{"FP": FP, "MTM": MTM, "SCF": SCF, "AEX": AEX, "SEAL": SEAL}[phase]]
        if msg == f"{phase}: invalid or missing state":
            return f"ROW:{c}:INVALID"
        if msg == f"{phase}: UNKNOWN fails closed" or msg == f"{phase}: FAIL fails closed":
            return f"ROW:{c}:CLOSED"
        if msg == f"{phase}: NOT_APPLICABLE requires a false predicate and reason":
            return f"ROW:{c}:NA"
    return None


def expected_cell(ff, base_record, run, rng, foreign: list) -> str:
    rows, cross = concretize(run, rng)
    rec = copy.deepcopy(base_record)
    rec["phase_ledger"] = rows
    rec["goal"]["success_horizon"] = "cross-cycle" if cross else "one-shot"
    ff._inject_goal_hash(rec)
    res = ff.validate_run(rec)
    codes, foreign_here = [], []
    for msg in res.get("errors") or []:
        code = _kernel_code(msg)
        (codes if code is not None else foreign_here).append(code if code is not None else msg)
    if foreign_here:
        foreign.extend(foreign_here[:2])
    aex = res.get("aex_required")
    return encode_run(run) + "=" + "+".join(codes) + "@" + bit(aex)


def kernel_codes_of_cell(cell: str) -> tuple[str, frozenset, str]:
    key, _, rest = cell.partition("=")
    errs, _, aex = rest.partition("@")
    return key, frozenset(e for e in errs.split("+") if e), aex


# --------------------------------------------------------------------------- domain comparison
def compare_domain(ff, base_record, lean_table: str, runs, rng, k_variants: int, sample_variants: int):
    """Return (mismatches:list, stats). Exhaustive single concretization per cell + a K-variant sample."""
    lean_cells = collections.Counter(cells_of(lean_table))
    py_cells: collections.Counter = collections.Counter()
    foreign: list = []
    memo: dict[str, str] = {}
    all_runs = list(runs)
    for run in all_runs:
        code = encode_run(run)
        if code not in memo:
            memo[code] = expected_cell(ff, base_record, run, rng, foreign)
        py_cells[memo[code]] += 1
    mismatches = []
    for cell in (lean_cells - py_cells):
        mismatches.append({"only_in": "lean", "cell": cell, "count": lean_cells[cell] - py_cells.get(cell, 0)})
    for cell in (py_cells - lean_cells):
        mismatches.append({"only_in": "python", "cell": cell, "count": py_cells[cell] - lean_cells.get(cell, 0)})
    # order-exact metric: exact-string agreement already implies order; report it as agreement fraction
    agree = sum((lean_cells & py_cells).values())
    # K-variant robustness sample: every drawn variant of one abstract cell must yield the same kernel codes
    variant_mismatches = []
    lean_by_key = {}
    for cell in lean_cells:
        key, errset, aex = kernel_codes_of_cell(cell)
        lean_by_key[key] = (errset, aex)
    if sample_variants and all_runs:
        picks = [all_runs[i] for i in sorted(random.Random(SEED ^ len(all_runs)).sample(
            range(len(all_runs)), min(sample_variants, len(all_runs))))]
        for run in picks:
            key = encode_run(run)
            want = lean_by_key.get(key)
            seen = set()
            for _ in range(k_variants):
                cell = expected_cell(ff, base_record, run, rng, foreign)
                _, errset, aex = kernel_codes_of_cell(cell)
                seen.add((errset, aex))
            if want is not None and (len(seen) != 1 or want not in seen):
                variant_mismatches.append({"key": key, "want": [sorted(want[0]), want[1]],
                                           "got": [[sorted(s[0]), s[1]] for s in seen]})
    stats = {"lean_cells": sum(lean_cells.values()), "python_cells": sum(py_cells.values()),
             "distinct_runcodes": len(memo), "agree": agree, "foreign_errors": len(foreign),
             "foreign_sample": foreign[:5], "variant_sample": len(picks) if sample_variants and all_runs else 0,
             "variant_mismatches": variant_mismatches}
    return mismatches + [{"variant": v} for v in variant_mismatches], stats


def compare_decoded(ff, base_record, lean_decoded: str, runs, rng):
    """Lean decodes each sampled runcode and re-encodes to a cell; it must equal the Python expected cell."""
    lean_cells = cells_of(lean_decoded)
    mismatches = []
    foreign: list = []
    for run, lean_cell in zip(runs, lean_cells):
        want = expected_cell(ff, base_record, run, rng, foreign)
        if lean_cell != want:
            mismatches.append({"runcode": encode_run(run), "lean": lean_cell, "python": want})
    return mismatches, {"n": len(runs), "foreign_errors": len(foreign)}


# --------------------------------------------------------------------------- section 2: the hook tables
def _fresh_session(prefix, n):
    return f"{prefix}-{SEED}-{n}"


def compare_claim_table(hook, lean_table: str) -> tuple[list, dict]:
    lean = keyed(lean_table)
    mismatches = []
    orig_measured = hook._measured_evidence
    orig_transcript = hook._transcript_evidence
    hook._transcript_evidence = lambda doc: ({}, None)
    hook._measured_evidence = (lambda window, kind, doc, tc=None, aliases=None, claim_text=None,
                               replays=None: "stub" if (claim_text and "[m]" in claim_text) else None)
    code = {"SUPPORTED": "S", "UNKNOWN": "U", "UNSUPPORTED": "X"}
    try:
        for u in ALL_BOOLS:
            for e in ALL_BOOLS:
                for m in ALL_BOOLS:
                    base = "Token usage was reduced by 40%." if e else "The build is completed."
                    line = base + (" [m]" if m else "")
                    # The abstract bit qualifies this claim. An UNKNOWN on a
                    # different line is intentionally not a qualifier in the hook.
                    text = line + (" UNKNOWN" if u else "")
                    res = hook.lint_message(text, {})
                    kind = "efficiency_savings" if e else "delivery_completion"
                    claim = next((c for c in res["claims"] if c["claim_type"] == kind), None)
                    key = bit(u) + bit(e) + bit(m)
                    got = code.get(claim["state"]) if claim else "?"
                    if lean.get(key) != got:
                        mismatches.append({"key": key, "lean": lean.get(key), "python": got})
    finally:
        hook._measured_evidence = orig_measured
        hook._transcript_evidence = orig_transcript
    return mismatches, {"cells": len(lean)}


def _claim_lists():
    states = ["S", "U", "X"]
    out = [[]]
    out += [[a] for a in states]
    out += [[a, b] for a in states for b in states]
    return out


def _gate_message(claims):
    if not claims:
        return "Plain status line without any load-bearing claim."
    text = {"S": "The build is completed. [m]", "U": "The build is completed. UNKNOWN",
            "X": "The build is completed."}
    lines = [""] * ((len(claims) - 1) * 4 + 1)
    for i, c in enumerate(claims):
        lines[i * 4] = text[c]
    return "\n".join(lines)


def compare_gate_table(hook, lean_table: str, receipt_dir: Path) -> tuple[list, dict]:
    lean = keyed(lean_table)
    mismatches = []
    orig_measured = hook._measured_evidence
    orig_transcript = hook._transcript_evidence
    orig_life = hook._fames_turn_lifecycle
    orig_rd = hook.RECEIPT_DIR
    hook.RECEIPT_DIR = receipt_dir
    hook._transcript_evidence = lambda doc: ({}, None)
    hook._measured_evidence = (lambda window, kind, doc, tc=None, aliases=None, claim_text=None,
                               replays=None: "stub" if (claim_text and "[m]" in claim_text) else None)
    events = [("T", "Stop"), ("B", "SubagentStop"), ("O", "PreToolUse")]
    n = 0
    try:
        for ev_code, ev_name in events:
            for i in ALL_BOOLS:
                for claims in _claim_lists():
                    for l in ALL_BOOLS:
                        hook._fames_turn_lifecycle = (lambda doc, _l=l: {"state": "PASS"} if _l
                                                      else {"state": "UNKNOWN", "failed_checks": ["x"]})
                        key = ev_code + bit(i) + "".join(claims) + "/" + bit(l)
                        message = _gate_message(claims) if i else ""
                        doc = {"hook_event_name": ev_name, "session_id": _fresh_session("gate", n),
                               "last_assistant_message": message, "stop_hook_active": False}
                        n += 1
                        _payload, receipt = hook.evaluate_hook(doc)
                        got = bit(receipt["action"] == "allow")
                        if lean.get(key) != got:
                            mismatches.append({"key": key, "lean": lean.get(key), "python": got,
                                               "action": receipt["action"]})
    finally:
        hook._measured_evidence = orig_measured
        hook._transcript_evidence = orig_transcript
        hook._fames_turn_lifecycle = orig_life
        hook.RECEIPT_DIR = orig_rd
    return mismatches, {"cells": len(lean)}


def compare_action_table(hook, lean_table: str, receipt_dir: Path) -> tuple[list, dict]:
    lean = keyed(lean_table)
    mismatches = []
    orig_life = hook._fames_turn_lifecycle
    orig_rd = hook.RECEIPT_DIR
    hook.RECEIPT_DIR = receipt_dir
    hook._fames_turn_lifecycle = lambda doc: {"state": "PASS"}
    code = {"allow": "A", "block": "K", "hard_stop": "H"}
    n = 0
    try:
        for ok in ALL_BOOLS:
            for prior in range(6):
                for active in ALL_BOOLS:
                    session_id = _fresh_session("action", n)
                    n += 1
                    session_sha = hook._sha(session_id)
                    hook._write_receipt(receipt_dir / f"{session_sha}.json", {"consecutive_blocks": prior})
                    message = ("Plain status, nothing load-bearing." if ok else "The build is completed.")
                    doc = {"hook_event_name": "Stop", "session_id": session_id,
                           "last_assistant_message": message, "stop_hook_active": active}
                    _payload, receipt = hook.evaluate_hook(doc)
                    key = bit(ok) + str(prior) + bit(active)
                    got = code.get(receipt["action"], "?")
                    if lean.get(key) != got:
                        mismatches.append({"key": key, "lean": lean.get(key), "python": got})
    finally:
        hook._fames_turn_lifecycle = orig_life
        hook.RECEIPT_DIR = orig_rd
    return mismatches, {"cells": len(lean)}


# --------------------------------------------------------------------------- section 4: math evidence
def compare_math_table(gate, lean_table: str) -> tuple[list, dict]:
    lean = keyed(lean_table)
    rng = random.Random(SEED ^ 0x4)
    mismatches = []
    reject_verdicts = list(gate.REJECTING)

    def rep_bool(b):
        return True if b else rng.choice([False, 0, None, "", 1, "yes"])

    def rep_verdict(tag):
        if tag == "P":
            return "PROVED"
        if tag == "C":
            return "CHECKED"
        if tag == "R":
            return rng.choice(reject_verdicts)
        return rng.choice(["SETUP_ERROR", "INPUT_ERROR", "INTERNAL_ERROR", None, "", "proved", 1])

    def rep_replay(tag):
        if tag == "a":
            return "agrees"
        if tag == "d":
            return "disagrees"
        if tag == "p":
            return "pending"
        return rng.choice(["unavailable", None, "AGREES", True])

    for a in ALL_BOOLS:
        for b in ALL_BOOLS:
            for c in ALL_BOOLS:
                for v in ["P", "C", "R", "E"]:
                    for t in ALL_BOOLS:
                        for r in ["a", "d", "p", "u"]:
                            key = bit(a) + bit(b) + bit(c) + v + bit(t) + r
                            got = bit(gate.evidence_ok(
                                receipt_intact=rep_bool(a), source_intact=rep_bool(b),
                                checker_current=rep_bool(c), verdict=rep_verdict(v),
                                theorem_stated=rep_bool(t), replay=rep_replay(r)))
                            if lean.get(key) != got:
                                mismatches.append({"key": key, "lean": lean.get(key), "python": got})
    return mismatches, {"cells": len(lean)}


# --------------------------------------------------------------------------- section 3: authority
def _subsets(items):
    out = [[]]
    for a in items:
        out = out + [[a] + s for s in out]
    # deterministic order matching Lean subsetsOf on [0,1,2,3]
    return out


def _lean_subsets_0123():
    def rec(xs):
        if not xs:
            return [[]]
        a, rest = xs[0], xs[1:]
        tail = rec(rest)
        out = []
        for s in tail:
            out.append(s)
            out.append([a] + s)
        return out
    return rec([0, 1, 2, 3])


AUTH_UNIVERSE = ["read", "write:fames", "publish:fames", "deploy:prod"]


def compare_authority_table(ff, lean_table: str) -> tuple[list, dict]:
    lean = keyed(lean_table)
    mismatches = []
    subsets = _lean_subsets_0123()
    for before in subsets:
        for after in subsets:
            key = "".join(str(n) for n in before) + ">" + "".join(str(n) for n in after)
            record = {"authority_before": [AUTH_UNIVERSE[n] for n in before],
                      "authority_after": [AUTH_UNIVERSE[n] for n in after]}
            res = ff.validate_autonomic(record)
            expanded = "autonomic lifecycle expanded authority" in (res.get("errors") or [])
            got = bit(not expanded)   # Lean bit = authoritySubset holds = no expansion
            if lean.get(key) != got:
                mismatches.append({"key": key, "lean": lean.get(key), "python": got})
    return mismatches, {"cells": len(lean)}


# --------------------------------------------------------------------------- behavioural controls
TINY_OK = """namespace ConfCtl
theorem add_zero_right (n : Nat) : n + 0 = n := by rfl
theorem and_swap (a b : Prop) : a \u2227 b \u2192 b \u2227 a := fun h => \u27e8h.2, h.1\u27e9
end ConfCtl
"""
TINY_FAIL = """namespace ConfCtl
theorem wrong : (1 : Nat) = 2 := by rfl
end ConfCtl
"""


def behavioural_controls(gate) -> dict:
    """Real verify_evidence over a temporary STATE: forged/tampered/wrong-name/FAILED reject, honest accepts."""
    tmp = Path(tempfile.mkdtemp(prefix="fames-ctl-"))
    orig_state = gate.STATE
    gate.STATE = tmp
    gate._REPLAYS.clear()
    results = {}
    bound_ok = lambda: {"gate_bound": True}   # noqa: E731 -- isolate the conformance binding from these checks
    try:
        checker = gate.checker_now()
        results["lean_available"] = bool(checker)
        if not checker:
            return {"ok": False, "reason": "Lean unavailable for behavioural controls", **results}

        honest = gate.attest(TINY_OK.encode("utf-8"), "control-honest")
        results["attest_honest_verdict"] = honest.get("verdict")
        lines = honest.get("evidence_lines") or []
        marker = gate.find_evidence(lines[0]) if lines else []
        raw_path, sha, theorem = marker[0] if marker else ("", "", "")
        source_sha = honest.get("source_sha256")

        v_ok = gate.verify_evidence(raw_path, sha, theorem, mode="live", binding=bound_ok)
        results["honest_accept"] = v_ok["ok"] is True

        v_wrong = gate.verify_evidence(raw_path, sha, "ConfCtl.nonexistent", mode="live", binding=bound_ok)
        results["wrong_theorem_reject"] = v_wrong["ok"] is False

        # forged: real source + attestation, PROVED, correct checker, NO ledger, mode=ledger -> pending -> reject
        gate._REPLAYS.clear()
        forged_bytes = b"-- forged source, never Lean-checked\n"
        forged_sha = gate._sha(forged_bytes)
        (tmp / "sources").mkdir(parents=True, exist_ok=True)
        (tmp / "sources" / f"{forged_sha}.lean").write_bytes(forged_bytes)
        forged_doc = {"schema": gate.ATTEST_SCHEMA, "verdict": "PROVED", "ok": True,
                      "source": {"sha256": forged_sha}, "checker": checker,
                      "theorems": [{"name": "Forged.thm", "statement": "\u2200 n, n = n"}]}
        (tmp / "attest").mkdir(parents=True, exist_ok=True)
        forged_path = tmp / "attest" / f"{forged_sha}.json"
        forged_path.write_text(json.dumps(forged_doc), encoding="utf-8")
        forged_hash = gate._sha(forged_path.read_bytes())
        v_forged = gate.verify_evidence(str(forged_path), forged_hash, "Forged.thm",
                                        mode="ledger", binding=bound_ok)
        results["forged_no_ledger_reject"] = v_forged["ok"] is False
        results["forged_replay_pending"] = v_forged["facts"]["replay"] == "pending"

        failed = gate.attest(TINY_FAIL.encode("utf-8"), "control-failed")
        results["attest_failed_verdict"] = failed.get("verdict")
        fsha = failed.get("source_sha256")
        fpath = tmp / "attest" / f"{fsha}.json"
        fhash = gate._sha(fpath.read_bytes()) if fpath.is_file() else ""
        v_failed = gate.verify_evidence(str(fpath), fhash, "ConfCtl.wrong", mode="live", binding=bound_ok)
        results["failed_verdict_reject"] = v_failed["ok"] is False

        # tamper the honest source last: source_intact must now be false -> reject
        gate._REPLAYS.clear()
        src_file = tmp / "sources" / f"{source_sha}.lean"
        src_file.write_bytes(src_file.read_bytes() + b"\n-- tamper\n")
        v_tamper = gate.verify_evidence(raw_path, sha, theorem, mode="live", binding=bound_ok)
        results["tampered_source_reject"] = v_tamper["ok"] is False

        checks = ["honest_accept", "wrong_theorem_reject", "forged_no_ledger_reject", "forged_replay_pending",
                  "failed_verdict_reject", "tampered_source_reject"]
        results["ok"] = all(results.get(c) is True for c in checks)
        return results
    finally:
        gate.STATE = orig_state
        gate._REPLAYS.clear()


def robustness_probes(ff, base_record) -> dict:
    """An unhashable state or phase must never yield ok True (it raises TypeError, which is acceptable)."""
    out = {}
    for name, mutate in (("unhashable_state", lambda r: r[2][0].__setitem__("state", ["PASS"])),
                         ("unhashable_phase", lambda r: r[2][0].__setitem__("phase", ["SCF"]))):
        rec = copy.deepcopy(base_record)
        try:
            mutate((None, None, rec["phase_ledger"]))
            res = ff.validate_run(rec)
            out[name] = res.get("ok") is not True
        except TypeError:
            out[name] = True
        except Exception:  # noqa: BLE001 -- any other raise also means it did not return ok True
            out[name] = True
    out["ok"] = all(v is True for v in out.values())
    return out


# --------------------------------------------------------------------------- driver
def build_base_record(ff):
    document, problem = ff._load_cases(HUB, ff.PACKAGE_ROOT)
    if problem:
        raise RuntimeError(f"cannot load FAMES cases: {problem}")
    fixtures = document.get("fixtures") or {}
    record = ff._prepare_input(fixtures, {"input_ref": "run_min"})[0]
    return copy.deepcopy(record)


def sample_decoded_runcodes(rng, n=240):
    pool = []
    pool += [r for i, r in enumerate(domain_rows()) if i % 3 == 0]
    pool += [r for i, r in enumerate(domain_aex()) if i % 5 == 0]
    pool += [r for i, r in enumerate(domain_residual()) if i % 401 == 0]
    pool += [r for i, r in enumerate(domain_order()) if i % 137 == 0]
    rng.shuffle(pool)
    seen, picks = set(), []
    for run in pool:
        code = encode_run(run)
        if code not in seen:
            seen.add(code)
            picks.append(run)
        if len(picks) >= n:
            break
    return picks


def binding_snapshot(paths: dict) -> dict:
    return {name: {"path": str(path), "sha256": _sha_file(Path(path))}
            for name, path in paths.items()}


def binding_drift(before: dict, after: dict) -> list[str]:
    """A loaded module cannot certify different bytes appearing while it runs."""
    return sorted(name for name in before.keys() | after.keys()
                  if before.get(name) != after.get(name)
                  or not (before.get(name) or {}).get('sha256'))


def run_conformance(prove_detection: bool = False) -> int:
    initial = binding_snapshot({
        'kernel': KERNEL, 'lean_gate': LEAN_GATE, 'leanctl': LEANCTL,
        'fames_fleet': FAMES_FLEET, 'claim_hook': CLAIM_HOOK, 'claim_linter': CLAIM_LINTER,
        'conformance': GATE_PATH,
    })
    gate = _load("fames_lean_gate_conf", LEAN_GATE)
    ff = _load("fames_fleet_conf", FAMES_FLEET)
    hook = _load("claim_hook_conf", CLAIM_HOOK)
    gate.set_budget(600.0)
    base_record = build_base_record(ff)

    decoded_runs = sample_decoded_runcodes(random.Random(SEED ^ 0xDEC), n=240)
    decoded_keys = ";".join(encode_run(r) for r in decoded_runs)
    lean = run_lean_tables(gate, decoded_keys)
    if not lean["ok"] or len(lean["tables"]) != len(EVAL_ORDER):
        print(json.dumps({"stage": "lean", "ok": False, "verdict": lean["verdict"],
                          "n_information": lean["n_information"], "error": lean.get("error"),
                          "reasons": lean["reasons"][:5]}, ensure_ascii=True))
        return 2
    tables = lean["tables"]

    rng = random.Random(SEED)
    receipt_dir = Path(tempfile.mkdtemp(prefix="fames-hookrcpt-"))

    if prove_detection:
        # seeded-mismatch control: poison one Lean claim cell; the comparator MUST report a mismatch.
        poisoned = keyed(tables["claim"])
        first = next(iter(poisoned))
        poisoned[first] = "Z"
        poisoned_table = ";".join(f"{k}={v}" for k, v in poisoned.items())
        mm, _ = compare_claim_table(hook, poisoned_table)
        detected = len(mm) > 0
        print(json.dumps({"prove_detection": True, "seeded_mismatch_detected": detected}, ensure_ascii=True))
        return 1 if detected else 0

    results = {}
    mism_total = 0

    m_rows, s_rows = compare_domain(ff, base_record, tables["rows"], domain_rows(), rng, 3, 60)
    m_aex, s_aex = compare_domain(ff, base_record, tables["aex"], domain_aex(), rng, 3, 60)
    m_res, s_res = compare_domain(ff, base_record, tables["residual"], domain_residual(), rng, 1, 40)
    m_ord, s_ord = compare_domain(ff, base_record, tables["order"], domain_order(), rng, 1, 40)
    m_dec, s_dec = compare_decoded(ff, base_record, tables["decoded"], decoded_runs, rng)
    m_clm, s_clm = compare_claim_table(hook, tables["claim"])
    m_gat, s_gat = compare_gate_table(hook, tables["gate"], receipt_dir)
    m_act, s_act = compare_action_table(hook, tables["action"], receipt_dir)
    m_mth, s_mth = compare_math_table(gate, tables["math"])
    m_aut, s_aut = compare_authority_table(ff, tables["authority"])

    domains = {
        "rows": (m_rows, s_rows), "aex": (m_aex, s_aex), "residual": (m_res, s_res),
        "order": (m_ord, s_ord), "decoded": (m_dec, s_dec), "claim": (m_clm, s_clm),
        "gate": (m_gat, s_gat), "action": (m_act, s_act), "math": (m_mth, s_mth),
        "authority": (m_aut, s_aut),
    }
    total_foreign = 0
    for name, (mm, st) in domains.items():
        mism_total += len(mm)
        total_foreign += st.get("foreign_errors", 0)
        results[name] = {"mismatches": len(mm), "sample": mm[:4], **st}

    controls = behavioural_controls(gate)
    robustness = robustness_probes(ff, base_record)

    ok = (mism_total == 0 and total_foreign == 0 and controls.get("ok") is True
          and robustness.get("ok") is True)

    bindings = binding_snapshot(gate.BOUND_FILES)
    drift = binding_drift(initial, bindings)
    ok = ok and not drift

    doc = {
        "schema": CONFORMANCE_SCHEMA,
        "ok": ok,
        "mismatches": mism_total,
        "foreign_errors": total_foreign,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": SEED,
        "bindings": bindings,
        "initial_bindings": initial,
        "binding_drift": drift,
        "lean": {"verdict": lean["verdict"], "source_sha256": lean["source_sha256"],
                 "generated_sha256": lean["generated_sha256"], "elapsed_s": lean["elapsed_s"],
                 "kernel_sha256": _sha_file(KERNEL)},
        "domains": results,
        "controls": controls,
        "robustness": robustness,
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    tmp = RECEIPT.with_name(f".{RECEIPT.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, RECEIPT)

    summary = {"ok": ok, "mismatches": mism_total, "foreign_errors": total_foreign,
               "controls_ok": controls.get("ok"), "robustness_ok": robustness.get("ok"),
               "binding_drift": drift,
               "receipt": str(RECEIPT),
               "per_domain": {k: results[k]["mismatches"] for k in results}}
    print(json.dumps(summary, ensure_ascii=True))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FAMES <-> Lean kernel conformance.")
    ap.add_argument("--prove-detection", action="store_true",
                    help="seeded-mismatch control: poison one cell and require the comparator to bite (exit 1)")
    args = ap.parse_args(argv)
    return run_conformance(prove_detection=args.prove_detection)


if __name__ == "__main__":
    sys.exit(main())
