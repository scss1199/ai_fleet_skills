#!/usr/bin/env python3
"""Bounded, host-neutral execution evidence and internal-gate deferral rules.

This module classifies observed command/result pairs; it does not execute a
command, mint proof, call a provider, or elevate test evidence into live behavior.
The caller must bind the result to an actual tool call in the current turn.
"""
from __future__ import annotations

import json
import re


ACCEPTED_TOOL_KINDS = (
    "pytest", "python_test", "unittest", "py_compile", "npm_test",
    "npm_build", "fames_self_check",
)
EVIDENCE_SCOPE = {
    "pytest": "test_run", "python_test": "test_run", "unittest": "test_run",
    "py_compile": "syntax_only", "npm_test": "test_run",
    "npm_build": "build_only", "fames_self_check": "self_check_only",
}
_UNVERIFIED_SCOPE = re.compile(
    r"\b(?:UNKNOWN|unverified|not\s+verified|not\s+tested|pending)\b|"
    r"未(?:驗證|验证|測試|测试|部署|上線)|尚未|待(?:驗證|验证|測試|测试)|"
    r"無法(?:確認|證實|证明)|无法(?:确认|证实|证明)", re.I,
)
_LIVE_SCOPE = re.compile(
    r"\b(?:production|prod|deployed|deployment|deploying|online|shipped)\b|"
    r"\blive\s+(?:site|app|service|behavior|behaviour|runtime|deployment|health)\b|"
    r"線上|线上|正式環境|正式环境|(?:已|完成|成功).{0,6}(?:部署|出貨|上線)|"
    r"(?:部署|出貨|上線).{0,8}(?:成功|完成|通過|正常)", re.I,
)
_RUNTIME_SCOPE = re.compile(
    r"\b(?:browser|runtime|playwright|selenium|e2e)\b|"
    r"\bend[- ]to[- ]end\b|瀏覽器|浏览器|實際(?:行為|操作|運作)|"
    r"实际(?:行为|操作|运作)|執行時|运行时|端到端|實機|實測|真实行為|真實行為|"
    r"(?:頁面|页面|介面|界面).{0,20}(?:互動|交互|連續追問|连续追问|正常運作|正常运行)", re.I,
)
_BUILD_SCOPE = re.compile(r"\b(?:build|bundle|bundled)\b|(?:建置|打包).{0,10}(?:成功|通過|完成)", re.I)


def tool_supports_claim(tool_kind: str, claim_text: str) -> bool:
    """Reject known scope elevation; this is not a semantic proof of a claim.

    Recognized test output supports a local test run. No command kind accepted
    here establishes a deployed destination's state. Browser/runtime claims
    additionally cannot be established by compilation, building or self-checks.
    A separately identity-bound receipt remains the path for richer evidence.
    """
    scope = EVIDENCE_SCOPE.get(tool_kind)
    if scope is None or not isinstance(claim_text, str):
        return False
    clauses = re.split(r"[;；\n。]|\bbut\b|但(?:是)?|然而", claim_text, flags=re.I)
    asserted = [clause for clause in clauses if not _UNVERIFIED_SCOPE.search(clause)]
    if any(_LIVE_SCOPE.search(clause) for clause in asserted):
        return False
    if scope in {"syntax_only", "build_only", "self_check_only"}:
        if any(_RUNTIME_SCOPE.search(clause) for clause in asserted):
            return False
    if scope == "syntax_only" and any(_BUILD_SCOPE.search(clause) for clause in asserted):
        return False
    return True


_TOKEN = re.compile(r'''"[^"\r\n]*"|'[^'\r\n]*'|[^\s]+''')
_PYTHON = re.compile(r"(?:python(?:\d+(?:\.\d+)*)?|py)(?:\.exe)?$", re.I)
_FAILED_COUNT = re.compile(r"\b[1-9]\d*\s+(?:failed|failures?|errors?)\b", re.I)
_TAP_FAILED = re.compile(r"^\s*(?:#|\u2139)\s*(?:fail|cancelled)\s+[1-9]\d*\s*$", re.I | re.M)
_NONZERO_EXIT = re.compile(
    r"\b(?:process\s+exited\s+with(?:\s+(?:code|status))?|"
    r"exit(?:ed)?[ _]+(?:code|status))\s*[:=]?\s*(-?\d+)\b", re.I,
)
_ERROR_LINE = re.compile(
    r"^\s*(?:Traceback \(most recent call last\):|FAILED\b|"
    r"(?:npm\s+(?:ERR!|error))\b|ERROR collecting\b)", re.I | re.M,
)


def _basename(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _runner_tokens(command: str) -> list[str]:
    """Accept one runner, optionally after a literal cd prefix; reject masking.

    Shell pipelines, redirects, substitutions, assignments, output-generating
    wrappers and trailing commands cannot prove which process emitted a result.
    A caller may instead supply the actual child command and its exit status.
    """
    if not isinstance(command, str) or len(command) > 16_384:
        return []
    command = command.strip()
    if command.startswith("& "):
        command = command[2:].lstrip()  # PowerShell's executable call operator.
    cd = re.match(r'''(?is)^cd\s+(?:/d\s+)?(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s;&|]+)\s*(?:&&|;)\s*(.+)$''', command)
    if cd:
        command = cd.group(1).strip()
        if command.startswith("& "):
            command = command[2:].lstrip()
    # Conservatively reject metacharacters even in quoted arguments. Test
    # selectors containing them can use a receipt with explicit process status.
    if re.search(r"[;&|<>\r\n`]|\$|%[A-Za-z_][A-Za-z_0-9]*%", command):
        return []
    tokens = _TOKEN.findall(command)
    if not tokens or " ".join(tokens).replace(" ", "") != command.replace(" ", "").replace("\t", ""):
        return []
    return [token[1:-1] if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'" else token for token in tokens]


def _result_text(result: object) -> str:
    if not isinstance(result, str):
        return ""
    # Claude tool_result.content can be a text-block array. The parent hook's
    # content serializer passes that array as JSON; inspect only text blocks.
    if result.lstrip().startswith("["):
        try:
            blocks = json.loads(result)
        except ValueError:
            return result
        if isinstance(blocks, list):
            return "\n".join(
                str(block.get("text", "")) for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
    return result


def _unittest_green(result: str) -> bool:
    ran = re.search(r"^Ran\s+([1-9]\d*)\s+tests?\s+in\s+.+$", result, re.M)
    ok = re.search(r"^OK(?:\s+\(([^\n]*)\))?\s*$", result, re.M)
    skipped = re.search(r"\bskipped=(\d+)\b", ok.group(1) or "") if ok else None
    return bool(ran and ok and (not skipped or int(skipped.group(1)) < int(ran.group(1))))


def _test_green(result: str, kind: str) -> bool:
    if kind == "unittest":
        return _unittest_green(result)
    if kind == "python_test":
        return _unittest_green(result) or bool(re.search(
            r"^\s*(?:=+\s*)?[1-9]\d*\s+passed,\s*0\s+failed\s*(?:=+)?\s*$",
            result, re.I | re.M,
        ))
    if kind == "pytest":
        return bool(re.search(
            r"^\s*(?:=+\s*)?(?:\d+\s+[a-z]+,\s*)*[1-9]\d*\s+passed"
            r"(?:,\s*\d+\s+[a-z]+)*(?:\s+in\s+[\d.]+s)?\s*(?:=+)?\s*$",
            result, re.I | re.M,
        ))
    if kind == "npm_test":
        return bool(
            re.search(r"^\s*Tests\s*:?\s+[1-9]\d*\s+passed\b", result, re.I | re.M)
            or (re.search(r"^\s*(?:#|\u2139)\s*pass\s+[1-9]\d*\s*$", result, re.M)
                and re.search(r"^\s*(?:#|\u2139)\s*fail\s+0\s*$", result, re.M))
        )
    return False


def execution_evidence_kind(
    command: str, result: str, is_error: object, exit_status: object = None,
) -> str | None:
    """Classify a green observed verifier, never just a mentioned command.

    ``is_error=False`` is required from the tool envelope. If an explicit exit
    status is available it must be the integer zero. A missing status is allowed
    for Claude's tool_result schema, which conveys failures using is_error.
    """
    if is_error is not False or (exit_status is not None and (type(exit_status) is not int or exit_status != 0)):
        return None
    text = _result_text(result)
    if _FAILED_COUNT.search(text) or _TAP_FAILED.search(text) or _ERROR_LINE.search(text):
        return None
    if any(int(match.group(1)) != 0 for match in _NONZERO_EXIT.finditer(text)):
        return None
    tokens = _runner_tokens(command)
    if not tokens:
        return None
    executable, args = _basename(tokens[0]), tokens[1:]
    kind = None
    if _PYTHON.fullmatch(executable):
        # Permit standard unbuffered/isolation flags, never -c code execution.
        while args and args[0] in {"-u", "-B", "-I", "-E", "-s"}:
            args = args[1:]
        if len(args) >= 2 and args[0] == "-m":
            kind = {"pytest": "pytest", "unittest": "unittest", "py_compile": "py_compile"}.get(args[1])
            if kind == "py_compile" and (len(args) < 3 or not any(arg.endswith(".py") for arg in args[2:])):
                return None
        elif args and re.fullmatch(r"(?:test_.+|.+_test|tests?)\.py", _basename(args[0])):
            kind = "python_test"
        elif args and _basename(args[0]) == "fames_fleet.py" and "self-check" in args[1:]:
            kind = "fames_self_check"
    elif executable in {"pytest", "pytest.exe"}:
        kind = "pytest"
    elif executable in {"npm", "npm.cmd", "npm.exe"}:
        if (args and args[0] == "test") or (len(args) >= 2 and args[:2] == ["run", "test"]):
            kind = "npm_test"
        elif len(args) >= 2 and args[:2] == ["run", "build"]:
            kind = "npm_build"
    if kind == "fames_self_check":
        try:
            body = json.loads(text)
        except (TypeError, ValueError):
            return None
        return kind if isinstance(body, dict) and body.get("ok") is True else None
    if kind in {"pytest", "python_test", "unittest", "npm_test"}:
        return kind if _test_green(text, kind) else None
    return kind


_HOOK_CONTEXT = re.compile(
    r"prompt[_ -]identity|UserPromptSubmit|(?:Stop|PreToolUse|PostToolUse)\s*hook|"
    r"\bhook\b.{0,50}(?:identity|receipt|block|reject|unlock|拒絕|擋|閘|放行)|"
    r"FAMES.{0,50}(?:閘|hook|identity)", re.I,
)
_MESSAGE_REQUEST = re.compile(
    r"(?:請|麻煩|需要你|等你|必須由你).{0,30}(?:傳|發|送|回覆|輸入|說|給).{0,40}"
    r"(?:新.{0,4}訊息|另一.{0,4}訊息|下一.{0,4}訊息|繼續|重新.{0,4}提問)|"
    r"(?:please\s+)?(?:send|submit|post|reply|type)\s+(?:(?:me|with)\s+)?"
    r"(?:(?:a|one|another|new|the\s+next)\s+){0,3}"
    r"(?:message|prompt|reply|[\"']?continue[\"']?)", re.I,
)
_NEGATED_REQUEST = re.compile(
    r"(?:不(?:要|需|必|應|得)|無需|禁止|避免).{0,45}(?:傳|發|送|回覆|輸入|要求|請)|"
    r"\b(?:do\s+not|don't|never|need\s+not|must\s+not|without\s+(?:asking|requiring))\b", re.I,
)
_OWNER_AUTH_ACTION = re.compile(
    r"(?:完成|進行|操作|點選|接受|核准).{0,30}OAuth.{0,20}(?:同意|授權)|"
    r"(?:輸入|填寫).{0,15}(?:密碼|驗證碼|MFA)|"
    r"(?:complete|approve|accept).{0,25}OAuth.{0,25}(?:consent|authorization)|"
    r"(?:enter|type).{0,25}(?:password|MFA|verification\s+code)", re.I,
)
_REPAIR_TARGET = re.compile(r"(?:讓|以便|用來|to\s+(?:regenerate|unlock|repair)).{0,50}(?:hook|identity|receipt|放行|解鎖)", re.I)
_QUOTED_EXAMPLE = re.compile(r"(?:錯誤範例|拒絕輸出|反例|原文|舊版輸出|rejected\s+(?:output|response)|example)\s*[:：]", re.I)


def internal_gate_deferral(text: str) -> dict | None:
    """Find a requested new user turn used to repair an internal hook gate.

    Truthful UNKNOWN, actual owner OAuth/password consent, quoted failure
    examples and negated requests remain allowed. Return only a line number and
    stable reason; never persist the assistant's message or source transcript.
    """
    if not isinstance(text, str):
        return None
    lines = text[:100_000].replace("\\_", "_").splitlines()
    visible: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(lines, 1):
        if line.strip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or line.lstrip().startswith(">"):
            continue
        visible.append((number, line.replace("**", "")))
    for index, (number, line) in enumerate(visible):
        if not _MESSAGE_REQUEST.search(line) or _NEGATED_REQUEST.search(line) or _QUOTED_EXAMPLE.search(line):
            continue
        if _OWNER_AUTH_ACTION.search(line) and not _REPAIR_TARGET.search(line):
            continue
        context = "\n".join(value for _, value in visible[max(0, index - 5):index + 3])[-1400:]
        if _HOOK_CONTEXT.search(context):
            return {
                "reason": "internal_hook_recovery_delegated_to_user",
                "line": number,
                "required_action": "repair_current_turn_identity_or_report_concrete_unrecoverable_blocker",
            }
    return None
