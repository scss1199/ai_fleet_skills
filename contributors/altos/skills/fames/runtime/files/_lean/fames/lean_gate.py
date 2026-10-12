#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""FAMES <-> Lean gate: a mathematical claim counts only with a Lean proof this gate replayed.

Any model can write "QED".  This gate makes that sentence cost a proof: a line that asserts a
mathematical result passes only when it cites an attestation this gate produced by running the hub
Lean checker (`leanctl.py`) itself, and only while the gate's own replay of the same bytes agrees.
The decision rule is `Fames.mathOk` in `FamesKernel.lean`; `evidence_ok` below is its Python twin
and `conformance.py` compares the two on every one of the 256 inputs.

    lean_gate.py attest --file proof.lean    run Lean, store source + attestation, print evidence lines
    lean_gate.py verify --lean <attestation> --sha256 <hex> --theorem <Name>
    lean_gate.py lint --file message.txt     exit 1 when a mathematical claim has no valid evidence
    lean_gate.py audit                       re-run Lean on every attested source, report disagreements
    lean_gate.py status                      Lean install, conformance binding, store counts

Evidence form, inside the claim's window (the line before, the claim line, the two lines after):

    evidence: lean=<attestation path> sha256=<attestation sha256> theorem=<Fully.Qualified.Name>

Honest exit: say UNKNOWN (or 未驗證, not verified, ...) on the claim line itself.

Limits, stated once.  This is not a sandbox: a same-user process that can write files can forge the
store or edit this gate; `audit` finds a forged record afterwards, nothing here prevents one.  Claim
detection is a regex over explicit proof wording, so an implicit mathematical assertion is not seen.
The gate never checks semantic equivalence of prose. Claim consumers accept only the exact
`claim_lines` emitted by `attest`: a named, JSON-quoted audited Lean statement, with any audit
context retained. Bare `verify` verifies theorem evidence only, never surrounding prose.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

GATE_PATH = Path(__file__).resolve()
ROOT = GATE_PATH.parent.parent                  # C:\ai_workspace\_lean
HUB = ROOT.parent
LEANCTL = ROOT / "leanctl.py"
KERNEL = GATE_PATH.parent / "FamesKernel.lean"
CONFORMANCE = GATE_PATH.parent / "evidence" / "conformance.json"
STATE = ROOT / "state" / "fames"                # runtime store; `_lean/.gitignore` already covers state/

ATTEST_SCHEMA = "fames-lean-attestation/2"
LEDGER_SCHEMA = "fames-lean-ledger/2"
CONFORMANCE_SCHEMA = "fames-lean-conformance/1"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT_S = 600
DEFAULT_BUDGET_S = 120.0        # CLI lint/verify; a Stop hook sets a few seconds with set_budget()
CORE_REPLAY_S = 6.0             # planning guess for a source with no ledger entry yet
MATHLIB_REPLAY_S = 30.0
LIVE_MARGIN_S = 4.0             # kept free of the budget around a live replay: start-up, kill, report

# leanctl verdicts.  Anything outside these two tuples means nothing was checked.
ACCEPTING = ("PROVED",)
REJECTING = ("CHECKED", "FAILED", "INCOMPLETE", "UNVERIFIED", "UNSOUND_AXIOMS", "UNSUPPORTED", "TIMEOUT",
             "ELABORATED")

# What the files are bound to in the conformance receipt, and the subset a math decision rests on.
BOUND_FILES = {
    "kernel": KERNEL,
    "conformance": GATE_PATH.parent / "conformance.py",
    "lean_gate": GATE_PATH,
    "leanctl": LEANCTL,
    "fames_fleet": HUB / "_skill" / "fleet-skills" / "fames" / "scripts" / "fames_fleet.py",
    "claim_hook": HUB / "_skill" / "engines" / "claude-claim-integrity-hook.py",
    "claim_linter": HUB / "_skill" / "engines" / "claim-linter.py",
}
GATE_BOUND = ("kernel", "conformance", "lean_gate", "leanctl")

# --- claim detection -------------------------------------------------------------------------------
# Wording that asserts a proof on its own.
MATH_STRONG = re.compile(
    r"(?i)(?:\bQ\.?E\.?D\b|得證|得证|證畢|证毕|恆成立|恒成立|"
    r"\bmathematically\s+(?:proven|proved|guaranteed|impossible|certain|sound|correct|true)\b|"
    r"\bformally\s+(?:verified|proven|proved)\b|\bmachine[- ]checked\b|"
    r"(?:已|經|经|通過|通过)\s*形式化?\s*(?:驗證|验证|證明|证明)|"
    r"形式化?(?:驗證|验证|證明|证明)\s*(?:通過|通过|完成|成功)|"
    r"(?:已|經|经|被|由|通過|通过)\s*Lean\s*(?:證明|证明|驗證|验证|檢查|检查)|"
    r"Lean\s*(?:已|已經|已经)\s*(?:證明|证明|驗證|验证)|"
    r"\bLean[- ](?:proved|proven|verified|checked)\b|"
    r"\b(?:proved|proven|verified|checked)\s+(?:in|by|with)\s+Lean\b|"
    r"數學上\s*(?:保證|成立|必然|不可能|已證|正確|嚴格)|数学上\s*(?:保证|成立|必然|不可能|已证|正确|严格))"
)
# Wording that asserts a proof only next to a mathematical object (MATH_CONTEXT) on the same line.
MATH_ASSERT = re.compile(
    r"(?i)(?:\b(?:proved|proven|proves|prove\s+that|we\s+(?:have\s+)?show(?:n|ed)?\s+that|it\s+follows\s+that|"
    r"holds\s+for\s+(?:all|every|any)|is\s+(?:always\s+)?true\s+for\s+(?:all|every|any)|is\s+a\s+theorem|"
    r"is\s+provable)\b|已證明|已证明|證明了|证明了|已證(?!實|据|據)|已证(?!实|据)|可證|可证|證得|证得|"
    r"證出|证出|成立|必然為真|必然为真|"
    r"\bverdicts?\s*(?:[:=]|is\b|are\b|皆為|皆为)\s*PROVED\b)"
)
# A mathematical object.  The guards keep 真實數據, 調整數值, 品質數據 and "for all seats" out: a quantifier
# counts only in front of a one-letter variable.
MATH_CONTEXT = re.compile(
    r"(?i)(?:\b(?:theorems?|lemmas?|corollar(?:y|ies)|propositions?|inequalit(?:y|ies)|there\s+exists?|"
    r"converges?|convergence|primes?|integers?|real\s+numbers?|natural\s+numbers?|rational\s+numbers?|"
    r"induction|bijecti\w+|injecti\w+|surjecti\w+|monoton\w+|commutativ\w+|associativ\w+)\b|"
    r"\bfor\s+(?:all|every|any)\s+[A-Za-zα-ωΑ-Ω](?![A-Za-z])|"
    r"(?:對|对)(?:於|于)?(?:所有|任意|任何|每個|每个|每一個|每一个)\s*(?:的\s*)?[A-Za-zα-ωΑ-Ω](?![A-Za-z])|"
    r"定理|引理|推論|推论|命題|命题|不等式|恆等式|恒等式|等式|方程|收斂|收敛|歸納法|归纳法|數學歸納|数学归纳|"
    r"(?<![真確确調调品要])(?:整數|整数|實數|实数|質數|质数|素數|素数|自然數|自然数|有理數|有理数)"
    r"(?![據据值量字目位])|[∀∃∑∏≤≥≠∈⊆])"
)
# Spans that say the opposite, state an obligation or a condition: removed before the two searches
# above, so "A is proved; B is not proved" still reads as a claim about A.
MATH_NOT_A_CLAIM = re.compile(
    r"(?i)(?:\b(?:not|never|cannot|can't|isn't|aren't|wasn't|weren't|hasn't|haven't)"
    r"(?:\s+(?:yet|been|be|formally|mathematically))*\s+(?:proved|proven|verified|checked|shown)\b|"
    r"\bunprove[dn]\b|\bno\s+proof\b|"
    r"\b(?:must|should|shall|need(?:s|ed)?\s+to|ha(?:s|ve|d)\s+to|to)\s+be\s+(?:formally\s+|mathematically\s+)?"
    r"(?:proved|proven|verified|checked)\b|"
    r"\b(?:until|unless|if|once|when|whether|before)\s+(?:(?:it|this|that|they)\s+(?:is|are|was|were|has\s+been)\s+)?"
    r"(?:formally\s+|mathematically\s+)?(?:proved|proven|verified|checked)\b|"
    r"(?:未|尚未|沒有|没有|未能|無法|无法|不能|並未|并未|未經|未经)\s*(?:以|用|被|由|經|经)?\s*(?:Lean\s*)?"
    r"(?:形式化?)?\s*(?:證明|证明|驗證|验证|得證|得证|證|证)|"
    r"(?:必須|必须|須|须|需要|需|應該|应该|應|应|要求|除非|如果|若|倘若|一旦|直到|待)\s*(?:先\s*)?(?:已\s*)?"
    r"(?:經過|经过|經|经|由|被|以|用|通過|通过)?\s*(?:Lean\s*)?(?:形式化?)?\s*(?:證明|证明|驗證|验证|檢查|检查)|"
    r"不成立|未必成立|不一定成立|是否成立|能否成立|成立與否|成立与否)"
)
# The three below are the Stop gate's own; tests/test_claim_hooks.py fails when a copy drifts.
UNKNOWN_WORDING = re.compile(
    r"(?i)(?:\bUNKNOWN\b|\bunverified\b|\bnot\s+verified\b|\bhypothesis\b|"
    r"\binsufficient\s+evidence\b|未知|不明|未驗證|未验证|無法證明|无法证明|"
    r"尚未證實|尚未证实|待驗證|待验证|證據不足|证据不足|假設|假设|推測|推测)"
)
DENIAL = re.compile(
    r"(?i)(?:\b(?:not|don't|do\s+not|cannot|can't|won't|refus\w*|no\s+such\s+evidence)\b|"
    r"不會|不会|不能|無法|无法|拒絕|拒绝|並非|并非|不是|沒有證據|没有证据)"
)
QUOTED = re.compile(
    r'(?:"[^"\r\n]*"|“[^”\r\n]*”|「[^」\r\n]*」|『[^』\r\n]*』|`[^`\r\n]*`)'
)
LEAN_EVIDENCE = re.compile(
    r'(?i)\bevidence\s*:\s*lean=(?:"([^"\r\n]+)"|(\S+))\s+sha256=([a-f0-9]{64})\s+theorem=([^\s,;，；]+)'
)
_EVIDENCE_MARKER = re.compile(r"(?i)\bevidence\s*:")
_IMPORTS_MATHLIB = re.compile(r"(?m)^\s*import\s+Mathlib\b")
_HEX64 = re.compile(r"[a-f0-9]{64}")

_DEADLINE: float | None = None
_REPLAYS: dict[tuple[str, ...], tuple[str, str]] = {}
_IDENTITY_HASHES: dict[str, tuple[tuple[int, ...], str]] = {}
_LEANCTL = None


def math_claim_text(line: str) -> str:
    """The part of a line that can assert a result: no evidence marker, no negated or modal proof wording."""
    return MATH_NOT_A_CLAIM.sub(" ", _EVIDENCE_MARKER.split(line or "", maxsplit=1)[0])


def is_math_claim(line: str) -> bool:
    text = math_claim_text(line)
    return bool(MATH_STRONG.search(text) or (MATH_ASSERT.search(text) and MATH_CONTEXT.search(text)))


def evidence_ok(*, receipt_intact, source_intact, checker_current, verdict, theorem_stated, replay) -> bool:
    """`Fames.mathOk`.  Identity tests on purpose: 1 is not True, "proved" is not "PROVED"."""
    return (receipt_intact is True and source_intact is True and checker_current is True
            and verdict == "PROVED" and theorem_stated is True and replay == "agrees")


def set_budget(seconds: float) -> None:
    """Seconds this process may still spend on live Lean replays; past it the ledger answers."""
    global _DEADLINE
    _DEADLINE = time.monotonic() + max(0.0, float(seconds))


def _remaining() -> float:
    return DEFAULT_BUDGET_S if _DEADLINE is None else _DEADLINE - time.monotonic()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return None


def _identity_sha(path: Path) -> str | None:
    """Hash executable identity bytes once per unchanged file in this process.

    Metadata caching is an ordinary-change detector, not protection against a same-user
    attacker. No cached digest is persisted or trusted across processes.
    """
    try:
        stat = path.stat()
        signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        key = str(path.resolve())
        previous = _IDENTITY_HASHES.get(key)
        if previous and previous[0] == signature:
            return previous[1]
        digest = _file_sha(path)
        after = path.stat()
        if signature != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            return None
        if digest:
            _IDENTITY_HASHES[key] = (signature, digest)
        return digest
    except OSError:
        return None


def _read_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes((json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    os.replace(tmp, path)       # a reader sees the old file or the new one, never half of either


def _leanctl():
    global _LEANCTL
    if _LEANCTL is None:
        spec = importlib.util.spec_from_file_location("hub_leanctl_for_gate", LEANCTL)
        if spec is None or spec.loader is None:
            raise ImportError(str(LEANCTL))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LEANCTL = module
    return _LEANCTL


def checker_now() -> dict | None:
    """Identity of the installed checker, or None where Lean cannot be run at all."""
    try:
        toolchain_path = Path(_leanctl().toolchain_dir())
        toolchain = str(toolchain_path)
    except Exception:   # noqa: BLE001 -- no leanctl, no toolchain: the same answer, there is no checker
        return None
    leanctl_sha = _file_sha(LEANCTL)
    if not leanctl_sha:
        return None
    runtime_paths = [toolchain_path / "bin" / "lean.exe", *sorted((toolchain_path / "bin").glob("*.dll"))]
    runtime = {str(path.relative_to(toolchain_path)): _identity_sha(path) for path in runtime_paths}
    if not all(runtime.values()):
        return None
    metadata_paths = [ROOT / "state" / "mathlib.json", ROOT / "hubmath" / "lake-manifest.json",
                      ROOT / "hubmath" / "lean-toolchain"]
    ident = {"leanctl_sha256": leanctl_sha, "toolchain": toolchain,
             "mathlib_rev": _read_json(ROOT / "state" / "mathlib.json").get("mathlib_rev"),
             "runtime_sha256": runtime,
             "dependency_metadata_sha256": {str(p.relative_to(ROOT)): _file_sha(p) for p in metadata_paths},
             "identity_scope": "checker source, executable/DLL bytes and dependency metadata; "
                               "compiled imports are not content-attested"}
    ident["id"] = _sha(json.dumps(ident, sort_keys=True).encode("utf-8"))
    return ident


def binding_status() -> dict:
    """Is each bound file still the one the conformance run compared with the Lean kernel?"""
    doc = _read_json(CONFORMANCE)
    bindings = doc.get("bindings") if isinstance(doc.get("bindings"), dict) else {}
    passed = doc.get("schema") == CONFORMANCE_SCHEMA and doc.get("ok") is True and doc.get("mismatches") == 0
    components = {}
    for name, path in BOUND_FILES.items():
        recorded = bindings.get(name) if isinstance(bindings.get(name), dict) else {}
        current = _file_sha(path)
        components[name] = ("missing" if not current else
                            "fresh" if passed and recorded.get("sha256") == current else "stale")
    return {"receipt": str(CONFORMANCE), "present": bool(doc), "passed": passed,
            "generated_at": doc.get("generated_at"), "components": components,
            "gate_bound": all(components[name] == "fresh" for name in GATE_BOUND),
            "all_bound": all(state == "fresh" for state in components.values())}


def _python_exe() -> str:
    exe = Path(sys.executable or "python")
    if exe.name.lower() == "pythonw.exe":       # leanctl answers on stdout and pythonw has none
        console = exe.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(exe)


def run_lean(source: Path, timeout: float, *, grace: float = 60.0) -> dict:
    """One `leanctl check` of a stored source.  Never raises: what cannot be run is GATE_ERROR.

    leanctl stops Lean itself after `timeout`; `grace` is what its start-up and report may add before
    this call gives up on it, so a caller on a deadline can bound the whole call.
    """
    timeout = max(1.0, float(timeout))
    cmd = [_python_exe(), str(LEANCTL), "--ascii", "check", "--file", str(source), "--timeout", f"{timeout:.1f}"]
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout + grace, creationflags=NO_WINDOW, check=False)
        doc = json.loads(proc.stdout.decode("utf-8", "replace"))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"verdict": "GATE_ERROR", "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    return doc if isinstance(doc, dict) else {"verdict": "GATE_ERROR", "ok": False, "error": "not a JSON object"}


def _stated(receipt: dict) -> list[dict]:
    """Theorems the caller wrote, as leanctl's audit printed them."""
    audit = receipt.get("audit") if isinstance(receipt.get("audit"), dict) else {}
    keep = ("name", "kind", "line", "statement", "statement_form", "statement_typed", "statement_pretty",
            "axioms", "local_deps", "shadow_instances")
    return [{key: item[key] for key in keep if key in item} for item in audit.get("theorems") or []
            if isinstance(item, dict) and not item.get("synthetic") and isinstance(item.get("name"), str)]


def _statement_of(theorems, name: str) -> str | None:
    for item in theorems if isinstance(theorems, list) else []:
        if isinstance(item, dict) and item.get("name") == name and isinstance(item.get("statement"), str):
            return item["statement"]
    return None


def _theorem_of(theorems, name: str) -> dict | None:
    for item in theorems if isinstance(theorems, list) else []:
        if isinstance(item, dict) and item.get("name") == name and isinstance(item.get("statement"), str):
            return item
    return None


def render_verified_claim(theorem_name: str, statement: str, *, audit_context: dict | None = None) -> str:
    """Canonical single-line claim; exact text equality, not a prose-equivalence assertion."""
    line = f"Lean-proved theorem {theorem_name}: {json.dumps(statement, ensure_ascii=False)}"
    if audit_context:
        line += " audit=" + json.dumps(audit_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return line


def is_canonical_claim(line: str) -> bool:
    """Recognize the reserved claim prefix, including malformed claims that must not be excused.

    This is not validation. Only window_evidence's exact comparison can accept the claim.
    UNKNOWN/denial words inside its quoted Lean statement are not prose disclaimers.
    """
    return (line or "").strip().startswith("Lean-proved theorem ")


def _claim_line(theorem: dict, cautions: list) -> str:
    # Typed numerals retain domains that default pretty printing can hide. Local definitions,
    # shadow instances and printer changes must travel with the statement they qualify.
    context = {key: theorem[key] for key in ("local_deps", "shadow_instances") if theorem.get(key)}
    if theorem.get("statement_form") not in (None, "pretty"):
        context["statement_form"] = theorem["statement_form"]
    if cautions:
        context["cautions"] = cautions
    return render_verified_claim(theorem["name"], theorem.get("statement_typed") or theorem["statement"],
                                 audit_context=context)


def _ledger_path(source_sha: str, checker_id: str) -> Path:
    return STATE / "ledger" / f"{source_sha}.{checker_id}.json"


def _record_replay(source_sha: str, checker: dict, receipt: dict, origin: str) -> dict:
    entry = {"schema": LEDGER_SCHEMA, "source_sha256": source_sha, "checker": checker,
             "verdict": receipt.get("verdict"), "elapsed_s": receipt.get("elapsed_s"),
             "theorems": _stated(receipt), "cautions": receipt.get("cautions") or [],
             "recorded_by": origin, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _write_json(_ledger_path(source_sha, checker["id"]), entry)
    _REPLAYS.clear()
    return entry


def _compare(attested_theorem: dict | None, attested_cautions: list, verdict, theorems,
             cautions: list, theorem: str) -> str:
    """Does a gate-run Lean result say what the attestation says about this theorem?"""
    current = _theorem_of(theorems, theorem)
    same = (verdict == "PROVED" and current is not None and current == attested_theorem
            and cautions == attested_cautions)
    return "agrees" if same else "disagrees"


def _replay(source: Path, source_sha: str, checker: dict, attested_theorem: dict | None,
            attested_cautions: list, theorem: str, mode: str) -> tuple[str, str]:
    """(replay, how): a live Lean run while the budget allows it, else the gate's own earlier run."""
    attested_sha = _sha(json.dumps([attested_theorem, attested_cautions], sort_keys=True).encode("utf-8"))
    key = (source_sha, checker["id"], theorem, attested_sha, mode)
    if mode != "live" and key in _REPLAYS:
        return _REPLAYS[key]
    ledger = _read_json(_ledger_path(source_sha, checker["id"]))
    if (ledger.get("schema") != LEDGER_SCHEMA or ledger.get("source_sha256") != source_sha
            or (ledger.get("checker") or {}).get("id") != checker["id"]):
        ledger = {}
    try:
        mathlib = bool(_IMPORTS_MATHLIB.search(source.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        mathlib = False
    known = ledger.get("elapsed_s")
    expected = float(known) if isinstance(known, (int, float)) and not isinstance(known, bool) else (
        MATHLIB_REPLAY_S if mathlib else CORE_REPLAY_S)
    remaining = _remaining()
    result: tuple[str, str] | None = None
    # A caller on a deadline (a Stop hook that is killed, and so lets the message through, when it runs
    # long) gets a live run only when one fits with room to spare, and the run ends a second early.
    if mode == "live" or (mode == "auto" and remaining >= expected * 1.5 + LIVE_MARGIN_S):
        receipt = (run_lean(source, DEFAULT_TIMEOUT_S) if mode == "live" else
                   run_lean(source, remaining - LIVE_MARGIN_S, grace=LIVE_MARGIN_S - 1.0))
        verdict = receipt.get("verdict")
        conclusive = verdict in ACCEPTING + REJECTING and receipt.get("source_sha256") == source_sha
        if conclusive and not (verdict == "TIMEOUT" and mode != "live"):
            _record_replay(source_sha, checker, receipt, "replay")
            result = (_compare(attested_theorem, attested_cautions, verdict, _stated(receipt),
                               receipt.get("cautions") or [], theorem), "live")
    if result is None and ledger and mode != "live":
        result = (_compare(attested_theorem, attested_cautions, ledger.get("verdict"),
                           ledger.get("theorems"), ledger.get("cautions") or [], theorem), "ledger")
    if result is None:
        result = ("pending", "none")
    _REPLAYS[key] = result
    return result


def verify_evidence(raw_path: str, sha256: str, theorem: str, *, mode: str = "auto", binding=None) -> dict:
    """Gather the six facts `Fames.mathOk` takes and decide.  `binding` is for tests only."""
    facts = {"receipt_intact": False, "source_intact": False, "checker_current": False, "verdict": None,
             "theorem_stated": False, "replay": "pending"}
    out = {"ok": False, "facts": facts, "reasons": [], "theorem": theorem, "statement": None,
           "evidence_class": None, "claim_line": None,
           "verification_scope": "audited_lean_theorem_only", "informal_claim_verified": False}

    def done(reason: str | None = None) -> dict:
        if reason:
            out["reasons"].append(reason)
        out["ok"] = evidence_ok(**facts)
        if not out["ok"]:
            out["evidence_class"] = None
        return out

    try:
        path = Path(raw_path).resolve(strict=True)
        inside = path.parent == (STATE / "attest").resolve() and path.suffix.lower() == ".json"
        data = path.read_bytes() if inside and path.stat().st_size <= MAX_EVIDENCE_BYTES else None
    except (OSError, RuntimeError, ValueError):
        return done("the attestation path does not resolve to a file")
    if data is None:
        return done(f"the attestation is not a file of the gate's store ({STATE / 'attest'})")
    if _sha(data) != str(sha256).lower():
        return done("sha256 does not match the attestation bytes")
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError:
        return done("the attestation is not JSON")
    source_doc = doc.get("source") if isinstance(doc, dict) and isinstance(doc.get("source"), dict) else {}
    source_sha = source_doc.get("sha256")
    if (not isinstance(doc, dict) or doc.get("schema") != ATTEST_SCHEMA or not isinstance(source_sha, str)
            or not _HEX64.fullmatch(source_sha) or path.stem != source_sha):
        return done("the attestation does not have the gate's schema")
    facts["receipt_intact"] = True

    source = STATE / "sources" / f"{source_sha}.lean"
    facts["source_intact"] = _file_sha(source) == source_sha
    if not facts["source_intact"]:
        out["reasons"].append("the stored source is missing or no longer has the attested sha256")

    checker = checker_now()
    bound = (binding or binding_status)()
    attested_checker = doc.get("checker") if isinstance(doc.get("checker"), dict) else {}
    facts["checker_current"] = bool(checker) and attested_checker == checker and bound.get("gate_bound") is True
    if checker and attested_checker != checker:
        out["reasons"].append("attested by another leanctl, toolchain or Mathlib than the installed one: "
                              "run `lean_gate.py attest` again")
    if bound.get("gate_bound") is not True:
        out["reasons"].append("the conformance binding of the kernel, this gate or leanctl is stale: run "
                              f"`python {GATE_PATH.parent / 'conformance.py'}`")

    facts["verdict"] = doc.get("verdict")
    if facts["verdict"] != "PROVED":
        out["reasons"].append(f"the attested verdict is {facts['verdict']!r}, not PROVED")
    attested_theorem = _theorem_of(doc.get("theorems"), theorem)
    cautions = doc.get("cautions") or []
    out["statement"] = _statement_of(doc.get("theorems"), theorem)
    facts["theorem_stated"] = out["statement"] is not None
    if not facts["theorem_stated"]:
        out["reasons"].append(f"`{theorem}` is not among the theorems the attested source states")

    if not checker:
        facts["replay"] = "unavailable"
        return done("Lean cannot be run here (no leanctl or no toolchain), so nothing can be replayed")
    if not facts["source_intact"]:
        return done()
    facts["replay"], how = _replay(source, source_sha, checker, attested_theorem, cautions, theorem, mode)
    facts["source_intact"] = _file_sha(source) == source_sha
    if not facts["source_intact"]:
        out["reasons"].append("the stored source changed during verification")
    if checker_now() != checker:
        facts["checker_current"] = False
        out["reasons"].append("the checker identity changed during verification")
    if facts["replay"] == "pending":
        out["reasons"].append("no gate-run Lean replay of these bytes is on record and none fits the time left: "
                              "run `lean_gate.py attest --file <source>` (it replays and records), then retry")
    elif facts["replay"] == "disagrees":
        out["reasons"].append(f"the gate's own Lean run ({how}) does not confirm this theorem with this statement")
    else:
        out["evidence_class"] = f"lean:{how}"
        out["claim_line"] = _claim_line(attested_theorem, cautions)
        out["audit_theorem"], out["cautions"] = attested_theorem, cautions
    return done()


def find_evidence(window: str) -> list[tuple[str, str, str]]:
    return [(m.group(1) or m.group(2) or "", m.group(3), m.group(4)) for m in LEAN_EVIDENCE.finditer(window or "")]


def window_evidence(window: str, *, claim_text: str | None = None, mode: str = "auto") -> dict:
    """Evidence supports only its exact emitted claim line. Missing claim text fails closed."""
    reasons: list[str] = []
    for raw_path, digest, theorem in find_evidence(window):
        result = verify_evidence(raw_path, digest, theorem, mode=mode)
        if result["ok"]:
            # Only a complete marker suffix may follow the canonical claim. Splitting on the
            # word "evidence" would hide arbitrary mathematical assertions after the marker.
            candidate = (claim_text or "").strip()
            for marker in reversed(list(LEAN_EVIDENCE.finditer(candidate))):
                if not candidate[marker.end():].strip():
                    candidate = candidate[:marker.start()].rstrip()
            if candidate == result["claim_line"]:
                return {**result, "claim_bound": True, "verification_scope": "exact_audited_lean_statement"}
            reasons.append(f"{theorem}: evidence verifies only its audited Lean statement; "
                           "the claim must exactly match the attestation's claim_lines")
            continue
        reasons.extend(f"{theorem}: {reason}" for reason in result["reasons"])
    return {"ok": False, "evidence_class": None, "theorem": None, "statement": None,
            "reasons": reasons or ["no `evidence: lean=<attestation> sha256=<hex> theorem=<Name>` in the claim "
                                   "window (line before, claim line, two lines after)"]}


def lint_text(text: str, *, mode: str = "auto") -> dict:
    """Every mathematical claim line of a message: SUPPORTED, UNKNOWN or UNSUPPORTED.  No text is kept."""
    lines = (text or "").splitlines()
    claims: list[dict] = []
    fenced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced or not stripped or stripped.startswith(">"):
            continue
        claim_text = QUOTED.sub("", stripped) if DENIAL.search(stripped) and not is_canonical_claim(stripped) else stripped
        if not is_math_claim(claim_text):
            continue
        claim = {"line": index + 1, "claim_type": "math_proof", "evidence_class": None}
        if UNKNOWN_WORDING.search(claim_text) and not is_canonical_claim(stripped):
            claim["state"] = "UNKNOWN"
        else:
            result = window_evidence("\n".join(lines[max(0, index - 1):min(len(lines), index + 3)]),
                                     claim_text=stripped, mode=mode)
            claim["state"] = "SUPPORTED" if result["ok"] else "UNSUPPORTED"
            claim["evidence_class"] = result["evidence_class"]
            if result["ok"]:
                claim["theorem"], claim["statement"] = result["theorem"], result["statement"]
                claim["claim_bound"], claim["verification_scope"] = True, result["verification_scope"]
            else:
                claim["reasons"] = result["reasons"]
        claims.append(claim)
    violations = [claim for claim in claims if claim["state"] == "UNSUPPORTED"]
    return {"ok": not violations, "claim_count": len(claims), "violation_count": len(violations),
            "claims": claims, "violations": violations}


def attest(data: bytes, origin: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """Run Lean on the source, keep the bytes and what Lean said, return the evidence lines."""
    checker = checker_now()
    if not checker:
        return {"ok": False, "verdict": "GATE_ERROR", "error": "Lean cannot be run here: no leanctl or no toolchain"}
    if len(data) > MAX_SOURCE_BYTES:
        return {"ok": False, "verdict": "GATE_ERROR", "error": f"source over {MAX_SOURCE_BYTES} bytes"}
    try:
        text, _ = _leanctl().decode_source(data, origin)
    except Exception as exc:    # noqa: BLE001 -- leanctl's InputError says how to fix the encoding
        return {"ok": False, "verdict": "GATE_ERROR", "error": str(exc)[:300]}
    canonical = text.encode("utf-8")        # what leanctl hashes: the stored file's sha256 is `source_sha256`
    source_sha = _sha(canonical)
    source = STATE / "sources" / f"{source_sha}.lean"
    if _file_sha(source) != source_sha:
        source.parent.mkdir(parents=True, exist_ok=True)
        tmp = source.with_name(f"{source.name}.{os.getpid()}.tmp")
        tmp.write_bytes(canonical)
        os.replace(tmp, source)
    receipt = run_lean(source, timeout)
    if checker_now() != checker:
        return {"ok": False, "verdict": "GATE_ERROR", "error": "the checker identity changed during attestation"}
    if _file_sha(source) != source_sha:
        return {"ok": False, "verdict": "GATE_ERROR", "error": "the stored source changed during attestation"}
    verdict = receipt.get("verdict")
    if verdict not in ACCEPTING + REJECTING or receipt.get("source_sha256") != source_sha:
        return {"ok": False, "verdict": "GATE_ERROR", "leanctl_verdict": verdict,
                "error": str(receipt.get("error") or "leanctl did not check the stored bytes")[:300]}
    theorems = _stated(receipt)
    audit = receipt.get("audit") if isinstance(receipt.get("audit"), dict) else {}
    # No clock and no timing in here: the same bytes under the same checker give the same attestation,
    # so an evidence line stays valid when someone attests the file again.
    doc = {"schema": ATTEST_SCHEMA, "verdict": verdict, "ok": verdict == "PROVED",
           "source": {"sha256": source_sha, "bytes": len(canonical), "stored": str(source)},
           "checker": checker, "imports": receipt.get("imports"), "mathlib": receipt.get("mathlib"),
           "theorems": theorems, "theorems_stated": audit.get("theorems_stated"),
           "theorems_truncated": bool(audit.get("theorems_truncated")),
           "reasons": receipt.get("reasons") or [], "cautions": receipt.get("cautions") or []}
    path = STATE / "attest" / f"{source_sha}.json"
    _write_json(path, doc)
    _record_replay(source_sha, checker, receipt, "attest")
    digest = _file_sha(path)
    lines = [f"evidence: lean={path.as_posix()} sha256={digest} theorem={t['name']}" for t in theorems
             ] if verdict == "PROVED" else []
    return {"ok": verdict == "PROVED", "verdict": verdict, "origin": origin, "attestation": str(path),
            "attestation_sha256": digest, "source_sha256": source_sha, "elapsed_s": receipt.get("elapsed_s"),
            "theorems": [{"name": t["name"], "statement": t.get("statement")} for t in theorems],
            "theorems_truncated": doc["theorems_truncated"], "reasons": doc["reasons"],
            "cautions": doc["cautions"], "evidence_lines": lines,
            "claim_lines": [_claim_line(t, doc["cautions"]) for t in theorems] if verdict == "PROVED" else [],
            "verification_scope": "audited_lean_theorem_only", "informal_claim_verified": False}


def audit_store(*, limit: int | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """Re-run Lean on attested sources and compare: the detective control for a forged record."""
    checker = checker_now()
    if not checker:
        return {"ok": False, "error": "Lean cannot be run here", "checked": 0, "disagreements": []}
    rows, disagreements = [], []
    paths = sorted((STATE / "attest").glob("*.json"))
    for path in paths[:limit] if limit else paths:
        doc = _read_json(path)
        source_sha = str((doc.get("source") or {}).get("sha256") or "")
        source = STATE / "sources" / f"{source_sha}.lean"
        row = {"attestation": path.name, "attested_verdict": doc.get("verdict")}
        if doc.get("schema") != ATTEST_SCHEMA or path.stem != source_sha or _file_sha(source) != source_sha:
            row["finding"] = "attestation or stored source is not intact"
        else:
            receipt = run_lean(source, timeout)
            row["verdict"] = receipt.get("verdict")
            if receipt.get("verdict") not in ACCEPTING + REJECTING or receipt.get("source_sha256") != source_sha:
                row["finding"] = "Lean could not be run on the stored source"
            else:
                _record_replay(source_sha, checker, receipt, "audit")
                named = [t for t in doc.get("theorems") or [] if isinstance(t, dict)]
                differs = [t.get("name") for t in named
                           if _theorem_of(_stated(receipt), t.get("name")) != t]
                if (receipt.get("verdict") != doc.get("verdict") or differs
                        or (receipt.get("cautions") or []) != (doc.get("cautions") or [])):
                    row["finding"] = "Lean does not say what the attestation says"
                    row["theorems_differing"] = differs[:10]
        rows.append(row)
        if "finding" in row:
            disagreements.append(row)
    return {"ok": not disagreements, "checked": len(rows), "disagreements": disagreements, "rows": rows}


def status() -> dict:
    checker = checker_now()
    bound = binding_status()
    counts = {name: len(list((STATE / name).glob("*"))) if (STATE / name).is_dir() else 0
              for name in ("attest", "sources", "ledger")}
    return {"ok": bool(checker) and bound["all_bound"], "lean_available": bool(checker), "checker": checker,
            # False does not open the gate: it means every mathematical claim is rejected until this is fixed.
            "lean_evidence_accepted": bool(checker) and bound["gate_bound"], "conformance": bound,
            "store": {"root": str(STATE), **counts}}


def _emit(doc: dict, ascii_only: bool) -> None:
    sys.stdout.buffer.write((json.dumps(doc, indent=2, ensure_ascii=ascii_only) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _read_input(args: argparse.Namespace) -> tuple[bytes, str]:
    if args.file:
        return Path(args.file).read_bytes(), f"--file {args.file}"
    return sys.stdin.buffer.read(), "stdin"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lean_gate", description="FAMES mathematical-claim gate over the hub Lean.")
    ap.add_argument("--ascii", action="store_true", help="escape non-ASCII in the JSON on stdout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    at = sub.add_parser("attest", help="run Lean on a source and record an attestation")
    lt = sub.add_parser("lint", help="check every mathematical claim of a message")
    for parser in (at, lt):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--file")
        source.add_argument("--stdin", action="store_true")
    at.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    lt.add_argument("--budget", type=float, default=DEFAULT_BUDGET_S, help="seconds for live Lean replays")
    lt.add_argument("--mode", choices=("auto", "live", "ledger"), default="auto")
    vf = sub.add_parser("verify", help="decide one evidence marker")
    vf.add_argument("--lean", required=True)
    vf.add_argument("--sha256", required=True)
    vf.add_argument("--theorem", required=True)
    vf.add_argument("--mode", choices=("auto", "live", "ledger"), default="live")
    au = sub.add_parser("audit", help="re-run Lean on every attested source")
    au.add_argument("--limit", type=int)
    au.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    sub.add_parser("status", help="Lean install, conformance binding, store counts")
    args = ap.parse_args(argv)

    if args.cmd == "status":
        doc = status()
    elif args.cmd == "audit":
        doc = audit_store(limit=args.limit, timeout=args.timeout)
    elif args.cmd == "verify":
        doc = verify_evidence(args.lean, args.sha256, args.theorem, mode=args.mode)
    else:
        try:
            data, origin = _read_input(args)
        except OSError as exc:
            _emit({"ok": False, "verdict": "GATE_ERROR", "error": f"cannot read the input: {exc.strerror or exc}"},
                  args.ascii)
            return 2
        if args.cmd == "attest":
            doc = attest(data, origin, timeout=args.timeout)
            if doc.get("verdict") == "GATE_ERROR":
                _emit(doc, args.ascii)
                return 2
        else:
            set_budget(args.budget)
            doc = lint_text(data.decode("utf-8-sig", errors="replace"), mode=args.mode)
    _emit(doc, args.ascii)
    return 0 if doc.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
