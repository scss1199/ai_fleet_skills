#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""Deterministic Stop/SubagentStop gate for FAMES claim integrity.

The gate does not decide whether a model intended to deceive.  It prevents a
load-bearing delivery claim from ending a turn unless the message either:

* binds the claim to an explicit evidence marker, or
* labels the claim UNKNOWN/unverified.

Only bounded hashes and classifications are persisted; assistant text is not.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


_STARTED = time.monotonic()
HUB = Path(os.environ.get("AI_WORKSPACE", r"C:\ai_workspace"))
SCRIPT_PATH = Path(__file__).resolve()
RECEIPT_DIR = Path(
    os.environ.get(
        "FAMES_CLAIM_INTEGRITY_RECEIPT_DIR",
        str(HUB / "_registry" / "fames-evidence" / "claude-claim-integrity"),
    )
)
FAMES_TURN_RECEIPT_ROOT = Path(
    os.environ.get(
        "FAMES_TURN_RECEIPT_ROOT",
        str(HUB / "_registry" / "fames-turn"),
    )
)
FAMES_MANIFEST = Path(
    os.environ.get(
        "FAMES_BUNDLE_MANIFEST",
        str(HUB / "_skill" / "fleet-skills" / "fames" / "bundle-manifest.json"),
    )
)
FAMES_PROMPT_HOOK = Path(
    os.environ.get(
        "FAMES_CLAUDE_PROMPT_HOOK",
        str(HUB / "_skill" / "fleet-skills" / "token-preflight" / "scripts" / "claude_session_hook.py"),
    )
)
CLAUDE_PROJECTS_ROOT = Path.home() / ".claude" / "projects"
RECEIPT_MINTER = SCRIPT_PATH.parent / "fames-receipt.py"
EFFICIENCY_VALIDATOR = HUB / "_skill" / "fleet-skills" / "fames" / "scripts" / "work_efficiency.py"
# The only tool kinds _tool_kind() can classify; naming anything else in an
# `evidence: tool=` marker resolves to nothing, so the block message must say so.
def _shared_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EXECUTION = _shared_module('fames_execution_evidence', SCRIPT_PATH.parent / 'fames_execution_evidence.py')
_TURN_BINDING = _shared_module('fames_turn_binding', SCRIPT_PATH.parents[2] / '_harness/runtime/fames_turn_binding.py')
ACCEPTED_TOOL_KINDS = _EXECUTION.ACCEPTED_TOOL_KINDS
MAX_BLOCKS = 3
MAX_TRANSCRIPT_BYTES = 32 * 1024 * 1024
MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
# A mathematical claim is decided by the hub Lean gate, whose rule is the Lean-proved `Fames.mathOk`.
LEAN_GATE = HUB / "_lean" / "fames" / "lean_gate.py"
# Seconds after this process started by which a live Lean replay must be over.  The installer gives this
# hook 15 s and a hook killed for running long lets the message through, so past this point the gate
# answers from its ledger of earlier replays instead.
LEAN_REPLAY_DEADLINE_S = 9.0

_UNKNOWN = re.compile(
    r"(?i)(?:\bUNKNOWN\b|\bunverified\b|\bnot\s+verified\b|\bhypothesis\b|"
    r"\binsufficient\s+evidence\b|未知|不明|未驗證|未验证|無法證明|无法证明|"
    r"尚未證實|尚未证实|待驗證|待验证|證據不足|证据不足|假設|假设|推測|推测)"
)
_TOOL_EVIDENCE = re.compile(r"(?i)\bevidence\s*:\s*tool=([a-z][a-z0-9_-]*)\b")
_FILE_EVIDENCE = re.compile(
    r'(?i)\bevidence\s*:\s*file=(?:"([^"\r\n]+)"|(\S+))\s+sha256=([a-f0-9]{64})\b'
)
# One receipt usually backs several claim lines.  Repeating a 64-char digest on
# every line costs tokens and invites transcription slips, so a message may bind
# a receipt to a short id once and reference that id afterwards.  The reference
# is not a weaker proof: it resolves to the declared path and digest and runs
# the same _pass_receipt check.  An undeclared id proves nothing.
_ALIAS_DECL = re.compile(
    r'(?i)\bevidence\s*:\s*id=([a-z0-9][a-z0-9_.-]{0,31})\s+file=(?:"([^"\r\n]+)"|(\S+))'
    r'\s+sha256=([a-f0-9]{64})\b'
)
_ALIAS_REF = re.compile(r"(?i)\bevidence\s*:\s*id=([a-z0-9][a-z0-9_.-]{0,31})\b")
_COMPLETION = re.compile(
    r"(?i)(?:^\s*done\b|\b(?:completed|fixed|repaired|shipped|deployed|merged|"
    r"verified|validated|synchroni[sz]ed|reviewed|passed|green)\b|"
    r"已完成|完成了|已修復|已修复|修好了|已部署|已上線|已上线|已合併|已合并|"
    r"已驗證|已验证|驗證通過|验证通过|已同步|已審查|已审查|全部通過|全部通过)"
)
_METRIC = re.compile(r"(?i)(?:\b\d+(?:\.\d+)?\s*%|百分之\s*\d+(?:\.\d+)?)")
_EXHAUSTIVE = re.compile(
    r"(?i)(?:\b(?:all|every|entire|exhaustive|fleet[- ]wide|zero\s+unknowns?)\b|"
    r"全部|所有|每一(?:個|个)|全面|全 fleet|零未知|無遺漏|无遗漏|完整覆蓋|完整覆盖)"
)
_DECEPTION = re.compile(
    r"(?i)(?:\b(?:lied|lying|deceived|deception|dishonest)\b|說謊|说谎|欺騙|欺骗|刻意誤導|刻意误导)"
)
_DIRECT_INTENT_EVIDENCE = re.compile(
    r"(?i)(?:direct\s+knowledge[- ]and[- ]deliberation\s+evidence\s*:|"
    r"直接知情與蓄意證據\s*[:：]|直接知情与蓄意证据\s*[:：])"
)
_DENIAL = re.compile(
    r"(?i)(?:\b(?:not|don't|do\s+not|cannot|can't|won't|refus\w*|no\s+such\s+evidence)\b|"
    r"不會|不会|不能|無法|无法|拒絕|拒绝|並非|并非|不是|沒有證據|没有证据)"
)
_QUOTED = re.compile(
    r'(?:"[^"\r\n]*"|“[^”\r\n]*”|「[^」\r\n]*」|『[^』\r\n]*』|`[^`\r\n]*`)'
)
# Used only while the Lean gate cannot be loaded.  Deliberately broader than the gate's own detector,
# so nothing it would have caught passes, and every line it flags is then UNSUPPORTED or UNKNOWN.
_MATH_PROOF_FALLBACK = re.compile(
    r"(?i)(?:\bQ\.?E\.?D\b|\bprov(?:ed|en|es|able)\b|\bprove\s+that\b|\bshow(?:n|ed)?\s+that\b|"
    r"\bfollows\s+that\b|\b(?:holds|true)\s+for\s+(?:all|every|any)\b|\bis\s+a\s+theorem\b|"
    r"\bformally\s+verified\b|\bmachine[- ]checked\b|\bmathematically\b|"
    r"\bLean[- ](?:proved|proven|verified|checked)\b|\b(?:verified|checked)\s+(?:in|by|with)\s+Lean\b|"
    r"Lean\s*(?:已經|已经|已)?\s*(?:證明|证明|驗證|验证|檢查|检查)|形式化?\s*(?:驗證|验证|證明|证明)|"
    r"得證|得证|證畢|证毕|已證|已证|證明了|证明了|可證|可证|證得|证得|證出|证出|成立|必然|數學上|数学上)"
)
_EFFICIENCY_METRICS = {
    "tokens": re.compile(r"(?i)(?:\btokens?\b|權杖|权杖|詞元|词元)"),
    "cost": re.compile(r"(?i)(?:\bcosts?\b|\bspending\b|\bexpenses?\b|成本|費用|费用|花費|花费)"),
    "quota": re.compile(r"(?i)(?:\bquota\b|配額|配额|額度|额度)"),
}
_EFFICIENCY_REDUCTION = re.compile(
    r"(?i)(?:\b(?:sav(?:e[ds]?|ing|ings)|reduc(?:e[ds]?|ing|tion)|"
    r"decreas(?:e[ds]?|ing)|cut(?:s|ting)?|fewer|less|lower(?:ed|ing)?|"
    r"drop(?:s|ped|ping)?|down|fell|halv(?:e[ds]?|ing))\b|"
    r"節省|节省|省下|省了|降低|減少|减少|削減|削减|下降|減半|减半|更省)"
)
_EFFICIENCY_UNMEASURED = re.compile(
    r"(?i)(?:\b(?:unmeasured|propos(?:ed|al)|plan(?:ned|ning)?|aim|target|"
    r"hypothetic(?:al)?|could|might|may|would)\b|\bnot\s+(?:yet\s+)?measured\b|"
    r"\bno\s+measured\b|尚未量測|未量測|未量测|未測量|未测量|未實測|未实测|"
    r"待量測|待測量|待测量|預計|预计|計畫|计划|提案|目標|目标)"
)
_EFFICIENCY_NEGATED = re.compile(
    r"(?i)(?:\b(?:no|without)\s+(?:\w+\s+){0,2}(?:savings?|reduction)\b|"
    r"\b(?:cannot|can't|do\s+not|did\s+not|not)\s+(?:claim|save|reduce)\b|"
    r"(?:不能|無法|无法|沒有|没有)(?:證明|证明|宣稱|宣称|節省|节省|減少|减少|降低))"
)
_EFFICIENCY_CLAUSE = re.compile(r"[\n;；。!?！？]|(?<!\d)\.(?!\d)", re.I)
_PERCENT_VALUE = re.compile(r"(?i)(?:(\d+(?:\.\d+)?)\s*%|百分之\s*(\d+(?:\.\d+)?))")


def _efficiency_claims(text: str, *, include_unmeasured: bool = False) -> list[dict]:
    """Classify explicit reductions, never equating local API use with savings.

    Qualifiers apply to their own clause. An unrelated UNKNOWN in a nearby
    evidence line must not excuse a positive, measured-sounding savings claim.
    Numbers are retained only in memory, never in the hook's persisted receipt.
    """
    claims = []
    text = re.split(r"(?i)\bevidence\s*:", text, maxsplit=1)[0]
    clauses = []
    for sentence in _EFFICIENCY_CLAUSE.split(text):
        pending = ""
        for part in re.split(r"\s+and\s+", sentence, flags=re.I):
            if (any(pattern.search(part) for pattern in _EFFICIENCY_METRICS.values())
                    and not _EFFICIENCY_REDUCTION.search(part)
                    and not (_UNKNOWN.search(part) or _EFFICIENCY_UNMEASURED.search(part)
                             or _EFFICIENCY_NEGATED.search(part))):
                # In "cost and tokens reduced", both nouns share the verb.
                # Do not split away an unmeasured unit and then bless tokens.
                pending += part + " "
                continue
            clauses.append(pending + part)
            pending = ""
    for clause in clauses:
        if not _EFFICIENCY_REDUCTION.search(clause):
            continue
        metrics = [metric for metric, pattern in _EFFICIENCY_METRICS.items() if pattern.search(clause)]
        if not metrics:
            continue
        qualified = bool(_UNKNOWN.search(clause) or _EFFICIENCY_UNMEASURED.search(clause)
                         or _EFFICIENCY_NEGATED.search(clause))
        if qualified and not include_unmeasured:
            continue
        percentages = [float(match.group(1) or match.group(2)) for match in _PERCENT_VALUE.finditer(clause)]
        claims.append({"metrics": metrics, "percentages": percentages, "qualified": qualified,
                       "text": clause})
    return claims


def _sha(value: str) -> str:
    # Windows hook pipes can surface undecodable console bytes as lone
    # surrogates.  Hash their replacement form instead of crashing open.
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _path_sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


_LEAN_GATE_MODULE: list = []


def _lean_gate():
    """The hub Lean gate, loaded once; None when it cannot be loaded, which opens nothing."""
    if not _LEAN_GATE_MODULE:
        module = None
        try:
            spec = importlib.util.spec_from_file_location("fames_lean_gate", LEAN_GATE)
            if spec is not None and spec.loader is not None:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.set_budget(LEAN_REPLAY_DEADLINE_S - (time.monotonic() - _STARTED))
        except Exception:   # noqa: BLE001 -- a missing or broken gate must degrade to "reject", never raise
            module = None
        _LEAN_GATE_MODULE.append(module)
    return _LEAN_GATE_MODULE[0]


def _is_math_claim(line: str) -> bool:
    gate = _lean_gate()
    if gate is None:
        return bool(_MATH_PROOF_FALLBACK.search(re.split(r"(?i)\bevidence\s*:", line, maxsplit=1)[0]))
    return bool(gate.is_math_claim(line))


def _lean_evidence(window: str, claim_text: str | None = None) -> str | None:
    """Accept only the current claim bound to the replayed theorem's audited statement."""
    gate = _lean_gate()
    if gate is None:
        return None
    try:
        result = gate.window_evidence(window, claim_text=claim_text)
    except Exception:   # noqa: BLE001 -- same rule: an error in the gate is not evidence
        return None
    return result.get("evidence_class") if result.get("ok") is True else None


# A structural invariant quantifies over a whole set, states a bound, or asserts a
# conservation: "沒有任何 rider 會被 deferred", "所有模組都在 60 秒內完成", "at most 8".
# Those are statements Lean can discharge, and this seat has discharged them before
# (HubClockKernel.lean).  Before 2026-09-22 nothing checked them: measured over 12 real
# ai_darkhero answers, lean_gate.lint reported claim_count 0 on 12 of 12 -- its patterns
# match *claims of proof* ("得證", "Lean-proved"), not asserted invariants.  So the seat
# could assert "沒有任何東西變慢" every turn and the math gate would report green having
# reviewed nothing.  This kind closes that hole: prove it, cite a receipt, or say UNKNOWN.
_STRUCTURAL_INVARIANT = re.compile(
    r"(?:沒有任何|沒有一個|不會超過|不超過|永遠不會|一定不會|必定|必然|"
    r"上限是|下限是|至多|至少|全部都|所有[^，。]{0,12}都|每一個[^，。]{0,12}都|"
    r"總和|加總|總共等於|恰好等於|嚴格小於|嚴格大於|單調|不遞減|不遞增|"
    r"互不重疊|一一對應|"
    r"\bno\s+\w+\s+(?:is|are|can|will|exceeds?)\b|\bnever\s+exceeds?\b|"
    r"\bat\s+most\b|\bat\s+least\b|\bfor\s+(?:all|every)\b|\bevery\s+\w+\s+is\b|"
    r"\bstrictly\s+(?:less|greater)\b|\bsums?\s+to\b|\bmonotonic\w*\b|"
    r"\bdisjoint\b|\bbijecti\w+\b)"
)
# Quoting a standing rule is not the seat asserting an invariant.  These spans are
# removed first, which keeps the T1 rule text this fleet pastes constantly out of scope.
_INVARIANT_NOT_A_CLAIM = re.compile(
    r"(?:「[^」]*」|\"[^\"]*\"|嚴禁[^，。]*|禁止[^，。]*|規則[^，。]*|紅線[^，。]*|"
    r"必須[^，。]*|應該[^，。]*|要求[^，。]*)"
)
# Soak scope.  The invariant kind is armed for the curator seat only until its firing
# rate has been measured on the other seats; widening it before that would block work
# on phrasings nobody has sampled.  "ai_workspace" is here because a curator session
# runs with the hub root as cwd, so _seat_from_cwd resolves the root, not the seat.
_INVARIANT_SEATS = frozenset({"ai_darkhero", "ai_workspace"})


def _is_structural_invariant(line: str) -> bool:
    return bool(_STRUCTURAL_INVARIANT.search(_INVARIANT_NOT_A_CLAIM.sub(" ", line)))


def _claim_types(line: str, seat: str | None = None) -> list[str]:
    kinds: list[str] = []
    efficiency = _efficiency_claims(line)
    qualified_efficiency = not efficiency and bool(_efficiency_claims(line, include_unmeasured=True))
    if _COMPLETION.search(line):
        kinds.append("delivery_completion")
    if _METRIC.search(line) and not qualified_efficiency:
        kinds.append("numeric")
    if efficiency:
        kinds.append("efficiency_savings")
    if _EXHAUSTIVE.search(line):
        kinds.append("exhaustive_scope")
    if _DECEPTION.search(line):
        kinds.append("deception_intent")
    if _is_math_claim(line):
        kinds.append("math_proof")
    if seat in _INVARIANT_SEATS and _is_structural_invariant(line):
        kinds.append("structural_invariant")
    return kinds


# Transcript rows the client authors for itself.  None of them is submitted by
# the operator, so none of them opens a user turn and none of them ever passes
# through the FAMES UserPromptSubmit lifecycle hook: `isMeta` carries hook
# feedback, `isCompactSummary` is the continuation text injected after a context
# compaction, and `isVisibleInTranscriptOnly` marks display-only rows.  Counting
# one as "the latest user prompt" would demand a turn receipt that cannot exist
# and would wedge every post-compaction session shut; counting one as a turn
# boundary would discard verification the operator's own prompt just produced.
_CLIENT_AUTHORED_ROW_FLAGS = ("isMeta", "isCompactSummary", "isVisibleInTranscriptOnly")


def _is_client_authored_row(row: dict) -> bool:
    return any(row.get(flag) is True for flag in _CLIENT_AUTHORED_ROW_FLAGS)


def _safe_transcript_path(doc: dict) -> Path | None:
    field = "agent_transcript_path" if doc.get("hook_event_name") == "SubagentStop" else "transcript_path"
    raw = str(doc.get(field) or doc.get("transcript_path") or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).expanduser().resolve()
        root = CLAUDE_PROJECTS_ROOT.resolve()
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        if not path.is_file() or path.stat().st_size > MAX_TRANSCRIPT_BYTES:
            return None
    except OSError:
        return None
    return path


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""


def _tool_kind(command: str, result: str, is_error: object) -> str | None:
    return _EXECUTION.execution_evidence_kind(command, result, is_error)


def _transcript_evidence(doc: dict) -> tuple[dict[str, str], float | None]:
    """Return successful verifier outputs from the current user turn only."""
    path = _safe_transcript_path(doc)
    if path is None:
        return {}, None
    tools: dict[str, tuple[str, str]] = {}
    verified: dict[str, str] = {}
    turn_started: float | None = None
    current_turn = False
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
            for raw in fh:
                try:
                    row = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(row, dict):
                    continue
                message = row.get("message") if isinstance(row.get("message"), dict) else {}
                content = message.get("content")
                if row.get("type") == "user" and not _is_client_authored_row(row):
                    is_prompt = isinstance(content, str) or (
                        isinstance(content, list)
                        and any(not isinstance(item, dict) or item.get("type") != "tool_result" for item in content)
                    )
                    if is_prompt:
                        current_turn = True
                        tools.clear()
                        verified.clear()
                        try:
                            turn_started = datetime.fromisoformat(
                                str(row.get("timestamp") or "").replace("Z", "+00:00")
                            ).timestamp()
                        except ValueError:
                            turn_started = None
                if not current_turn or not isinstance(content, list):
                    continue
                if row.get("type") == "assistant":
                    for item in content:
                        if not isinstance(item, dict) or item.get("type") != "tool_use":
                            continue
                        tool_id = str(item.get("id") or "")
                        tool_input = item.get("input") if isinstance(item.get("input"), dict) else {}
                        if tool_id:
                            tools[tool_id] = (
                                str(item.get("name") or ""),
                                str(tool_input.get("command") or ""),
                            )
                elif row.get("type") == "user":
                    for item in content:
                        if not isinstance(item, dict) or item.get("type") != "tool_result":
                            continue
                        tool_name, command = tools.get(str(item.get("tool_use_id") or ""), ("", ""))
                        if tool_name not in {"Bash", "PowerShell"}:
                            continue
                        result = _content_text(item.get("content"))
                        kind = _tool_kind(command, result, item.get("is_error"))
                        if kind:
                            verified[kind] = result[:1_000_000]
    except OSError:
        return {}, turn_started
    return verified, turn_started


def _pass_receipt(path: Path, expected_sha: str, session_started: float | None) -> tuple[bool, str]:
    try:
        resolved = path.expanduser().resolve()
        resolved.relative_to((HUB / "_registry").resolve())
        stat = resolved.stat()
        if not resolved.is_file() or stat.st_size > MAX_EVIDENCE_BYTES:
            return False, ""
        if session_started is None or stat.st_mtime + 2 < session_started:
            return False, ""
        data = resolved.read_bytes()
    except (OSError, RuntimeError, ValueError):
        return False, ""
    if hashlib.sha256(data).hexdigest().lower() != expected_sha.lower():
        return False, ""
    try:
        receipt = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return False, ""
    if not isinstance(receipt, dict):
        return False, ""
    identity_bound = any(
        str(receipt.get(field) or "").strip()
        for field in ("id", "validator_identity", "implementation_identity_sha", "evidence_path")
    )
    passed = identity_bound and (
        receipt.get("ok") is True
        or str(receipt.get("state") or "").upper() == "PASS"
        or str(receipt.get("status") or "").upper() == "PASS"
        or (receipt.get("exit_status") == 0 and bool(receipt.get("validator_identity")))
    )
    return passed, data.decode("utf-8-sig", errors="replace") if passed else ""


def _replay_efficiency(body: str) -> dict:
    """Replay a manifest using the installed portable verifier, fail closed.

    The generic receipt's PASS is only the envelope. It cannot prove usage,
    coverage or acceptance. Neither receipt prose nor cached summary fields
    are passed to the validator as evidence. Never log import/error contents.
    """
    try:
        receipt = json.loads(body)
        manifest = receipt.get("efficiency_evidence") if isinstance(receipt, dict) else None
        if not isinstance(manifest, dict) or manifest.get("schema") != "fames.work-efficiency.v1":
            return {}
        spec = importlib.util.spec_from_file_location("fames_claim_work_efficiency", EFFICIENCY_VALIDATOR)
        if spec is None or spec.loader is None:
            return {}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.validate_efficiency(manifest, root=HUB)
        return result if isinstance(result, dict) else {}
    except Exception:
        # A missing/incompatible module, bad evidence or importer failure must
        # never crash the Stop hook open, or expose raw usage/prompt data.
        return {}


def _efficiency_receipt_supports(claim_text: str, body: str, replays: dict | None = None) -> bool:
    claims = _efficiency_claims(claim_text)
    if not claims or any(metric != "tokens" for claim in claims for metric in claim["metrics"]):
        # The portable v1 adapter measures tokens only. Tokens never establish
        # billing cost, subscription quota or a conversion between these units.
        return False
    key = _sha(body)
    if replays is not None and key in replays:
        result = replays[key]
    else:
        result = _replay_efficiency(body)
        if replays is not None:
            replays[key] = result
    if (result.get("schema") != "fames.work-efficiency-result.v1"
            or result.get("ok") is not True
            or result.get("state") != "VERIFIED_REDUCTION_CONDITIONAL"
            or result.get("token_savings_verified") is not True):
        return False
    try:
        baseline = result["metrics"]["baseline"]["total_tokens"]
        candidate = result["metrics"]["candidate"]["total_tokens"]
        if type(baseline) is not int or type(candidate) is not int or not 0 < candidate < baseline:
            return False
        reduction = baseline - candidate
        percent = 100.0 * reduction / baseline
        reported = result["token_reduction_percent"]
        if type(reported) not in (int, float) or not math.isfinite(reported) or not math.isclose(reported, percent):
            return False
        for claim in claims:
            clause = claim["text"]
            for match in _PERCENT_VALUE.finditer(clause):
                raw = match.group(1) or match.group(2)
                decimals = len(raw.partition(".")[2])
                if not math.isclose(float(raw), percent, rel_tol=1e-12,
                                    abs_tol=0.5 * 10 ** -decimals):
                    return False
            without_percent = _PERCENT_VALUE.sub("", clause)
            # v1 proves the full total, not an arbitrary component's reduction.
            if re.search(r"(?i)\b(?:input|output|cache[ -]?(?:read|creation|write)?|reasoning|thinking)"
                         r"\s+tokens?\b|(?:輸入|输入|輸出|输出|快取|缓存|推理|思考)\s*(?:tokens?|權杖|词元|詞元)", clause):
                return False
            numbers = [float(value.replace(",", "")) for value in re.findall(
                r"(?<![A-Za-z0-9_.])\d+(?:,\d{3})*(?:\.\d+)?", without_percent
            )]
            if re.search(r"(?i)\b(?:half|halved|halving)\b|減半|减半", clause):
                if not math.isclose(percent, 50.0):
                    return False
            if re.search(r"(?i)\bzero\b|零(?:個|个)?\s*(?:tokens?|權杖|权杖|詞元|词元)", clause):
                return False
            if numbers:
                from_to = re.search(r"(?i)\bfrom\b.*\bto\b|從.*(?:至|到)|从.*(?:至|到)", without_percent)
                to_only = re.search(r"(?i)\bto\s+\d|(?:降至|減至|减至|降到|減到|减到)\s*\d", without_percent)
                expected = [baseline, candidate] if from_to else [candidate if to_only else reduction]
                if numbers != expected:
                    return False
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return True


def _receipt_supports(kind: str, window: str, body: str, claim_text: str | None = None,
                      replays: dict | None = None) -> bool:
    claim_text = window if claim_text is None else claim_text
    if kind == "efficiency_savings" or (kind == "numeric" and _efficiency_claims(claim_text)):
        return _efficiency_receipt_supports(claim_text, body, replays)
    if kind == "numeric":
        values = _METRIC.findall(window)
        haystack = body.lower().replace(" ", "")
        if values and not all(value.lower().replace(" ", "") in haystack for value in values):
            return False
    if kind == "deception_intent" and not _DIRECT_INTENT_EVIDENCE.search(window):
        return False
    return True


def _measured_evidence(
    window: str,
    kind: str,
    doc: dict,
    transcript_context: tuple[dict[str, str], float | None] | None = None,
    aliases: dict[str, tuple[str, str]] | None = None,
    claim_text: str | None = None,
    replays: dict | None = None,
) -> str | None:
    if kind == "math_proof":
        # A green test run or a PASS receipt proves no theorem, and a Lean proof proves nothing about a
        # delivery: this kind takes Lean evidence only, and Lean evidence serves this kind only.
        return _lean_evidence(window, claim_text=claim_text)
    if kind == "structural_invariant":
        # An invariant is the one non-math kind Lean can actually settle, so a proof
        # counts here; a receipt or tool run still counts too, because an invariant
        # about this machine ("no rider is deferred") is measured, not derived.
        proved = _lean_evidence(window, claim_text=claim_text)
        if proved:
            return proved
    transcript, session_started = transcript_context or _transcript_evidence(doc)
    claim_text = window if claim_text is None else claim_text
    efficiency_required = kind == "efficiency_savings" or (
        kind == "numeric" and bool(_efficiency_claims(claim_text))
    )
    for match in _TOOL_EVIDENCE.finditer(window):
        if efficiency_required:
            # A green build/test (even stdout containing "50%" or a replay
            # summary) cannot replace the hash-bound raw-log manifest.
            continue
        tool_kind = match.group(1).lower().replace("-", "_")
        result = transcript.get(tool_kind)
        if result is None:
            continue
        if not _EXECUTION.tool_supports_claim(tool_kind, claim_text):
            continue
        if kind == "numeric":
            values = _METRIC.findall(window)
            if values and not all(value.lower().replace(" ", "") in result.lower().replace(" ", "") for value in values):
                continue
        if kind == "deception_intent":
            continue
        return f"tool:{tool_kind}"
    for match in _FILE_EVIDENCE.finditer(window):
        raw_path = match.group(1) or match.group(2) or ""
        passed, body = _pass_receipt(Path(raw_path), match.group(3), session_started)
        if not passed:
            continue
        if not _receipt_supports(kind, window, body, claim_text, replays):
            continue
        return "file:sha256"
    for match in _ALIAS_REF.finditer(window):
        declared = (aliases or {}).get(match.group(1).lower())
        if declared is None:
            continue
        passed, body = _pass_receipt(Path(declared[0]), declared[1], session_started)
        if not passed:
            continue
        if not _receipt_supports(kind, window, body, claim_text, replays):
            continue
        return "file:sha256:alias"
    return None


def lint_message(text: str, evidence_doc: dict | None = None, seat: str | None = None) -> dict:
    """Return classifications without retaining the message body."""
    lines = (text or "").splitlines()
    claims: list[dict] = []
    evidence_doc = evidence_doc or {}
    transcript_context: tuple[dict[str, str], float | None] | None = None
    aliases: dict[str, tuple[str, str]] = {}
    efficiency_replays: dict[str, dict] = {}
    for declaration in _ALIAS_DECL.finditer(text or ""):
        # First binding wins: a later line cannot silently repoint an id that
        # earlier claims already leaned on.
        aliases.setdefault(
            declaration.group(1).lower(),
            (declaration.group(2) or declaration.group(3) or "", declaration.group(4)),
        )
    fenced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced or not stripped or stripped.startswith(">"):
            continue
        # A refusal often quotes the exact unsupported sentence it refuses to
        # emit.  Ignore only quoted spans in an explicit denial context; quoted
        # positive claims without that context remain enforceable.
        math_gate = _lean_gate()
        canonical_math = bool(math_gate and math_gate.is_canonical_claim(stripped))
        claim_text = _QUOTED.sub("", stripped) if _DENIAL.search(stripped) and not canonical_math else stripped
        kinds = _claim_types(claim_text, seat)
        if not kinds:
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + 3)
        evidence_window = "\n".join(lines[start:end])
        # Uncertainty qualifies this claim only. An unrelated UNKNOWN in a
        # neighboring paragraph cannot discharge an asserted completion.
        unknown = bool(_UNKNOWN.search(claim_text))
        for kind in kinds:
            if transcript_context is None:
                transcript_context = _transcript_evidence(evidence_doc)
            measured = _measured_evidence(
                evidence_window,
                kind,
                evidence_doc,
                transcript_context,
                aliases,
                claim_text,
                efficiency_replays,
            )
            efficiency_required = kind == "efficiency_savings" or (
                kind == "numeric" and bool(_efficiency_claims(claim_text))
            )
            if kind == "math_proof":
                # An UNKNOWN about something else two lines away must not excuse "QED": for a proof
                # claim the wording has to be on the claim line itself.
                excused = bool(_UNKNOWN.search(claim_text)) and not canonical_math
            else:
                excused = unknown and not efficiency_required
            if excused:
                state = "UNKNOWN"
            else:
                state = "SUPPORTED" if measured else "UNSUPPORTED"
            claims.append({
                "line": index + 1,
                "claim_type": kind,
                "state": state,
                "evidence_class": measured,
            })
    violations = [claim for claim in claims if claim["state"] == "UNSUPPORTED"]
    return {
        "ok": not violations,
        "claim_count": len(claims),
        "violation_count": len(violations),
        "claims": claims,
        "violations": violations,
    }


def _read_receipt(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _latest_prompt_row(doc: dict) -> tuple[str | None, dict]:
    """Return the latest real user prompt text together with its transcript row.

    Tool-result rows and client-authored rows are deliberately excluded.  The
    raw prompt is kept only in memory: callers hash it and never persist it.
    """
    path = _safe_transcript_path(doc)
    if path is None:
        return None, {}
    latest_prompt: str | None = None
    latest_row: dict = {}
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
            for raw in fh:
                try:
                    row = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(row, dict) or row.get("type") != "user":
                    continue
                if _is_client_authored_row(row):
                    continue
                message = row.get("message") if isinstance(row.get("message"), dict) else {}
                content = message.get("content")
                prompt: str | None = content if isinstance(content, str) else None
                if prompt is None and isinstance(content, list):
                    text_blocks = [
                        str(item.get("text"))
                        for item in content
                        if isinstance(item, dict)
                        and item.get("type") in {"text", "input_text"}
                        and isinstance(item.get("text"), str)
                    ]
                    prompt = "\n".join(text_blocks) if text_blocks else None
                if not prompt or not prompt.strip():
                    continue
                latest_prompt, latest_row = prompt, row
    except OSError:
        return None, {}
    return latest_prompt, latest_row


def _prompt_identity_and_start(prompt: str | None, row: dict) -> tuple[str | None, float | None]:
    if not prompt:
        return None, None
    try:
        started: float | None = datetime.fromisoformat(
            str(row.get("timestamp") or "").replace("Z", "+00:00")
        ).timestamp()
    except ValueError:
        started = None
    return _sha(prompt), started


def _latest_user_prompt(doc: dict) -> tuple[str | None, float | None]:
    """Return only the latest real user prompt identity and timestamp.

    The raw prompt is kept only in memory long enough to hash it and is never
    returned or persisted.
    """
    return _prompt_identity_and_start(*_latest_prompt_row(doc))


def _seat_from_cwd(raw_cwd: object) -> str | None:
    raw = str(raw_cwd or "").strip()
    if not raw:
        return None
    name = Path(raw).name
    return name if name.startswith("ai_") and len(name) > 3 else None


def _expected_agent(doc: dict, prompt_row: dict | None = None) -> str | None:
    """Resolve the seat the current prompt was submitted from.

    The UserPromptSubmit hook mints the turn receipt's `agent` from the cwd
    Claude Code reports for that prompt, and Claude Code stamps the same cwd on
    the prompt's transcript row.  The Stop event's cwd is a different value: it
    follows every `cd` a shell tool ran during the turn, so a turn that ends in
    the hub root resolves to a seat that never submitted the prompt and blocks
    its own receipt.  Bind to the prompt row; fall back to the Stop cwd only
    when the row records none.
    """
    row_cwd = (prompt_row or {}).get("cwd")
    if str(row_cwd or "").strip():
        return Path(str(row_cwd)).name or None
    return Path(str(doc.get("cwd") or "")).name or None


def _fames_turn_lifecycle(doc: dict) -> dict:
    """Bind a Claude Stop event to this session's current FAMES prompt receipt."""
    if str(doc.get("hook_event_name") or "") != "Stop":
        return {"state": "NOT_APPLICABLE", "diagnostic": "not a main Claude Stop event"}
    session_id = str(doc.get("session_id") or doc.get("conversation_id") or "")
    session_sha = _sha(f"claude\0{session_id}") if session_id else _sha("claude\0missing-session")
    prompt_text, prompt_row = _latest_prompt_row(doc)
    expected_prompt, prompt_started = _prompt_identity_and_start(prompt_text, prompt_row)
    expected_agent = _expected_agent(doc, prompt_row)
    path = _TURN_BINDING.select(FAMES_TURN_RECEIPT_ROOT, 'claude', session_sha, expected_prompt)
    receipt = _read_receipt(path)
    manifest = _read_receipt(FAMES_MANIFEST)
    prompt_hook_sha = _path_sha(FAMES_PROMPT_HOOK)
    checks = {
        "receipt_exists": bool(receipt),
        "manifest_exists": bool(manifest),
        "receipt_state_pass": receipt.get("state") == "PASS",
        "receipt_type": receipt.get("id") == "FAMES-RB-TI-TURN",
        "surface_identity": receipt.get("surface_id") == "claude",
        "session_identity": receipt.get("session_identity_sha") == session_sha,
        "agent_identity": bool(expected_agent) and receipt.get("agent") == expected_agent,
        "prompt_identity": bool(expected_prompt) and receipt.get("prompt_identity") == expected_prompt,
        "package_identity": bool(manifest.get("package_sha"))
        and receipt.get("package_sha") == manifest.get("package_sha"),
        "generation_identity": bool(manifest.get("skill_gen"))
        and receipt.get("skill_gen") == manifest.get("skill_gen"),
        "runtime_event": receipt.get("runtime_event_observed") is True,
        "activation_evidence": receipt.get("activation_evidence") == "lifecycle_hook",
        "same_turn_injection": receipt.get("adapter_mode") == "same_turn_context_injection"
        and receipt.get("read_back") is True,
        "adapter_identity": bool(prompt_hook_sha)
        and receipt.get("adapter_identity") == prompt_hook_sha,
        "privacy_boundary": receipt.get("raw_prompt_persisted") is False,
    }
    try:
        receipt_mtime = path.stat().st_mtime
    except OSError:
        receipt_mtime = None
    checks["current_turn_time"] = (receipt_mtime is not None and prompt_started is not None
        and receipt_mtime + 2 >= prompt_started
        and (not receipt.get('generated') or _TURN_BINDING.fresh_for_prompt(receipt, prompt_started)))
    state = "PASS" if checks and all(checks.values()) else "UNKNOWN"
    failed = sorted(name for name, ok in checks.items() if not ok)
    return {
        "state": state,
        "checks": checks,
        "failed_checks": failed,
        "turn_receipt_sha256": _path_sha(path) if state == "PASS" else None,
        "turn_receipt_path": str(path),
        "package_sha": receipt.get("package_sha"),
        "skill_gen": receipt.get("skill_gen"),
        "prompt_identity": receipt.get("prompt_identity"),
        "expected_agent": expected_agent,
        "raw_prompt_persisted": False,
        "diagnostic": "" if state == "PASS" else "same-session current FAMES turn receipt not proven",
    }


def _write_receipt(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def evaluate_hook(doc: dict) -> tuple[dict, dict]:
    event = str(doc.get("hook_event_name") or "")
    session_id = str(doc.get("session_id") or doc.get("conversation_id") or "")
    message = str(doc.get("last_assistant_message") or "")
    session_sha = _sha(session_id) if session_id else _sha("missing-session")
    message_sha = _sha(message)
    receipt_path = RECEIPT_DIR / f"{session_sha}.json"
    previous = _read_receipt(receipt_path)

    if event not in {"Stop", "SubagentStop"}:
        result = {"ok": True, "claim_count": 0, "violation_count": 0, "claims": [], "violations": []}
    elif not session_id or not message:
        result = {
            "ok": False,
            "claim_count": 0,
            "violation_count": 1,
            "claims": [],
            "violations": [{"line": 0, "claim_type": "missing_hook_evidence", "state": "UNKNOWN"}],
        }
    else:
        result = lint_message(message, doc, _seat_from_cwd(doc.get("cwd")))

    deferral = _EXECUTION.internal_gate_deferral(message)
    if deferral is not None:
        result['ok'] = False
        result['violation_count'] += 1
        result['violations'].append(dict(deferral, claim_type='internal_gate_deferral', state='FORBIDDEN'))

    lifecycle = _fames_turn_lifecycle(doc)
    if event == "Stop" and lifecycle.get("state") != "PASS":
        result["ok"] = False
        result["violation_count"] += 1
        violation = {
            "line": 0,
            "claim_type": "fames_turn_lifecycle",
            "state": "UNKNOWN",
        }
        result["violations"].append(violation)

    prior_blocks = int(previous.get("consecutive_blocks") or 0)
    blocks = 0 if result["ok"] else prior_blocks + 1
    if result["ok"]:
        action = "allow"
    elif blocks >= MAX_BLOCKS and bool(doc.get("stop_hook_active")):
        action = "hard_stop"
    else:
        action = "block"
    history = list(previous.get("history") or [])
    history.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "message_sha": message_sha,
        "state": "PASS" if result["ok"] else "UNKNOWN",
        "claim_count": result["claim_count"],
        "violation_count": result["violation_count"],
        "violations": result["violations"],
        "action": action,
    })
    receipt = {
        "schema": 1,
        "at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "implementation_identity_sha": hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest(),
        "state": "PASS" if result["ok"] else "UNKNOWN",
        "session_identity_sha": session_sha,
        "message_sha": message_sha,
        "claim_count": result["claim_count"],
        "violation_count": result["violation_count"],
        "violations": result["violations"],
        "fames_turn_lifecycle": lifecycle,
        "consecutive_blocks": blocks,
        "action": action,
        "history": history[-8:],
        "raw_message_persisted": False,
    }
    _write_receipt(receipt_path, receipt)

    if action == "allow":
        return {}, receipt
    kinds = sorted({row["claim_type"] for row in result["violations"]})
    lines = sorted({row["line"] for row in result["violations"] if row["line"]})
    reason = (
        "FAMES claim-integrity gate: unsupported load-bearing claim(s) "
        f"at lines {lines or ['UNKNOWN']} ({', '.join(kinds)}). "
        "Do not invent proof. Evidence must sit in the claim's own window (the line before "
        "through two lines after) in one of these exact forms: "
        f"evidence: tool=<{'|'.join(ACCEPTED_TOOL_KINDS)}> (a green run of that kind in THIS "
        "session's transcript — no other tool name resolves); "
        "evidence: file=<receipt under _registry> sha256=<actual sha256>; or evidence: id=<tag> "
        "once the same message declares evidence: id=<tag> file=<path> sha256=<hash>. "
        f"Mint a conforming receipt with: python {RECEIPT_MINTER} run --label <name> "
        '--cmd "<verification command>" — it runs the command, writes the receipt and prints the '
        "evidence line; a non-zero exit yields a FAIL receipt this gate rejects. Otherwise restate "
        "each unresolved claim explicitly as UNKNOWN. A contradiction is not proof of lying; intent "
        "remains UNKNOWN without direct knowledge-and-deliberation evidence."
    )
    if "fames_turn_lifecycle" in kinds:
        reason += (
            " The same Claude session's latest user prompt must first produce a current PASS "
            "receipt through the installed FAMES UserPromptSubmit lifecycle hook. Failing "
            f"lifecycle checks: {', '.join(lifecycle.get('failed_checks') or ['UNKNOWN'])}."
        )
    if 'internal_gate_deferral' in kinds:
        reason += (' Do not ask the user for another message to repair an internal gate. '
                   'The native boundary resolves prompt-bound receipts and replays current policy; '
                   'if native provenance is missing, report the exact failed source and smallest repair, '
                   'without claiming completion or fabricating an intake event.')
    if "math_proof" in kinds:
        reason += (
            " A mathematical claim (proved, QED, formally verified, 得證, 恆成立, ...) needs a Lean proof "
            f"the hub gate ran itself: python {LEAN_GATE} attest --file <proof.lean> checks the file and "
            "prints the evidence line (evidence: lean=<attestation> sha256=<hex> "
            "theorem=<Fully.Qualified.Name>) to put in the claim's window. A tool run, a PASS receipt or "
            "a hand-written attestation does not count, and the named theorem must be the statement "
            "claimed. Without a PROVED result, say UNKNOWN on the claim line itself."
        )
    if "structural_invariant" in kinds:
        reason += (
            " A structural invariant quantifies over a whole set, states a bound, or asserts a "
            "conservation (沒有任何…、所有…都、至多/至少、總和等於, no X exceeds Y, for all, at most). "
            "Settle it one of three ways: prove it in Lean and put the attestation's own claim and "
            "evidence lines in the window; cite a receipt or tool run that measured it; or narrow it "
            "until it is only what you actually checked. If none of those hold, say UNKNOWN on the "
            "claim itself — an unproved invariant is a guess, and guessing is the T1 red line 嚴禁猜."
        )
    if "efficiency_savings" in kinds:
        reason += (
            " Efficiency savings require a hash-bound receipt with efficiency_evidence containing "
            "a fames.work-efficiency.v1 manifest. The gate replays its raw logs with work_efficiency.py; "
            "ordinary tool output, a generic PASS, or percentages in receipt prose do not prove savings. "
            "The claimed total-token reduction must match the replay. Cost and quota remain UNKNOWN "
            "without their own measurement adapters. Proposed or unmeasured savings must be labeled as such."
        )
    if action == "hard_stop":
        return {"continue": False, "stopReason": reason}, receipt
    return {"decision": "block", "reason": reason}, receipt


def _read_hook_input(stream) -> dict:
    """Read hook JSON as bytes so a cp950 text wrapper cannot corrupt UTF-8."""
    raw = stream.buffer.read() if hasattr(stream, "buffer") else stream.read()
    if isinstance(raw, bytes):
        text = None
        for encoding in ("utf-8-sig", "utf-16", "cp950"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return {}
    else:
        text = str(raw)
    try:
        doc = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def main() -> int:
    doc = _read_hook_input(sys.stdin)
    payload, _receipt = evaluate_hook(doc)
    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
