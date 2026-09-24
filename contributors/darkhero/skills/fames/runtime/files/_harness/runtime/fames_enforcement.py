"""Mandatory lifecycle admission using the shared FAMES and Lean validators.

This is a host tool boundary, not an OS sandbox or a semantic obedience proof.
The managed entry verifies dependency identity before starting this worker.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone

HUB = Path(__file__).resolve().parents[2]
PROMPT_HOOK = HUB / '_skill/fleet-skills/token-preflight/scripts/claude_session_hook.py'
CLAIM_HOOK = HUB / '_skill/engines/claude-claim-integrity-hook.py'
AUDIT = HUB / '_registry/fames-enforcement'
SUPPORTED = {'SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop', 'SubagentStop', 'ConfigChange'}


def digest(data: str | bytes) -> str:
    return hashlib.sha256(data.encode('utf-8') if isinstance(data, str) else data).hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError('missing_module')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('invalid_document')
    return value


def denial(event: str, reason: str) -> dict:
    message = 'FAMES admission denied: ' + reason + '. No completion or execution proof was accepted.'
    if event == 'PreToolUse':
        return {'hookSpecificOutput': {'hookEventName': event, 'permissionDecision': 'deny', 'permissionDecisionReason': message}}
    if event in {'UserPromptSubmit', 'Stop', 'SubagentStop', 'ConfigChange'}:
        return {'decision': 'block', 'reason': message}
    return {'continue': False, 'stopReason': message}


def claim_module():
    module = load_module('fames_enforcement_claim', CLAIM_HOOK)
    # The managed policy chooses these sources. Child environment variables
    # cannot relocate validators, receipts, or the evidence trust root.
    module.HUB = HUB
    module.FAMES_TURN_RECEIPT_ROOT = HUB / '_registry/fames-turn'
    module.FAMES_MANIFEST = HUB / '_skill/fleet-skills/fames/bundle-manifest.json'
    module.FAMES_PROMPT_HOOK = PROMPT_HOOK
    module.RECEIPT_DIR = HUB / '_registry/fames-evidence/claude-claim-integrity'
    module.LEAN_GATE = HUB / '_lean/fames/lean_gate.py'
    module.EFFICIENCY_VALIDATOR = HUB / '_skill/fleet-skills/fames/scripts/work_efficiency.py'
    return module


def parent_event(doc: dict) -> dict:
    """Subagent tools inherit the actual parent user prompt, not a new scope."""
    result = dict(doc)
    result['hook_event_name'] = 'Stop'
    result.pop('agent_transcript_path', None)
    path = Path(str(doc.get('transcript_path') or ''))
    session = str(doc.get('session_id') or '')
    if (doc.get('agent_id') or doc.get('hook_event_name') == 'SubagentStop') and 'subagents' in path.parts:
        # Native Claude layout: <project>/<session>/subagents/<agent>.jsonl.
        at = path.parts.index('subagents')
        session_dir = Path(*path.parts[:at])
        parent = session_dir.parent / (session + '.jsonl')
        parent.resolve().relative_to((Path.home() / '.claude/projects').resolve())
        if not session or session_dir.name != session or not parent.is_file():
            raise ValueError('parent_transcript_unverified')
        result['transcript_path'] = str(parent)
    return result


def intake_status(doc: dict, surface: str, *, not_before: float | None = None, previous_identity: str | None = None) -> dict:
    session = str(doc.get('session_id') or '')
    prompt = doc.get('prompt') or doc.get('user_message') or doc.get('message')
    if not session or not isinstance(prompt, str) or not prompt.strip():
        return {'state': 'UNKNOWN', 'failed_checks': ['native_prompt_identity']}
    session_hash = digest(surface + '\0' + session)
    path = HUB / '_registry/fames-turn' / surface / (session_hash + '.json')
    receipt = read_json(path)
    manifest = read_json(HUB / '_skill/fleet-skills/fames/bundle-manifest.json')
    checks = {
        'state': receipt.get('state') == 'PASS',
        'type': receipt.get('id') == 'FAMES-RB-TI-TURN',
        'session': receipt.get('session_identity_sha') == session_hash,
        'prompt': receipt.get('prompt_identity') == digest(prompt),
        'surface': receipt.get('surface_id') == surface,
        'package': receipt.get('package_sha') == manifest.get('package_sha') and bool(manifest.get('package_sha')),
        'generation': receipt.get('skill_gen') == manifest.get('skill_gen'),
        'adapter': receipt.get('adapter_identity') == digest(PROMPT_HOOK.read_bytes()),
        'native_event': receipt.get('runtime_event_observed') is True and receipt.get('activation_evidence') == 'lifecycle_hook',
        'read_back': receipt.get('read_back') is True,
        'privacy': receipt.get('raw_prompt_persisted') is False,
        'jev_assessed': isinstance(receipt.get('jev_advisor'),dict) and bool(receipt.get('jev_advisor',{}).get('state')),
        'lean_applicability_recorded': bool(receipt.get('fames_capabilities',{}).get('components',{}).get('lean',{}).get('state')),
    }
    if not_before is not None:
        try:
            generated=datetime.fromisoformat(str(receipt.get('generated') or '').replace('Z','+00:00')).timestamp()
            # NTFS and time.time() can differ below the timestamp quantum.
            # A changed receipt (turn_count/generation) provides the decisive
            # current-invocation witness; mtime only bounds coarse freshness.
            checks['current_invocation']=(path.stat().st_mtime>=not_before-2 and generated>=not_before-2
                and previous_identity is not None and digest(path.read_bytes())!=previous_identity)
        except (ValueError,OSError):
            checks['current_invocation']=False
    return {'state': 'PASS' if all(checks.values()) else 'UNKNOWN', 'failed_checks': [k for k,v in checks.items() if not v]}


def call_prompt_hook(doc: dict) -> dict:
    module = load_module('fames_managed_prompt', PROMPT_HOOK)
    module.HUB = HUB
    module.STATUS = HUB / '_registry/token-preflight/claude-hook-status.json'
    module.CODEX_STATUS = HUB / '_registry/token-preflight/codex-hook-status.json'
    stream = io.StringIO()
    old_stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(json.dumps(doc, ensure_ascii=True))
        with contextlib.redirect_stdout(stream):
            module.main()
    finally:
        sys.stdin = old_stdin
    return json.loads(stream.getvalue() or '{}')


def protected_operation(doc: dict) -> str | None:
    """Deny direct policy edits and known bypass launches; not shell semantics."""
    name=str(doc.get('tool_name') or '')
    data=doc.get('tool_input')
    if not isinstance(data,dict):
        return 'invalid_tool_input'
    if re.search(r'(?i)read|list|stat|search|grep|glob|find',name) and not re.search(r'(?i)write|edit|patch|delete|remove|exec|shell',name):
        return None
    critical=[str(p).replace('\\','/').casefold() for p in (
        HUB/'_harness/runtime',HUB/'_skill/fleet-skills/fames',
        HUB/'_skill/fleet-skills/token-preflight',CLAIM_HOOK,
        HUB/'_lean/fames',HUB/'_registry/fames-enforcement.json',
        Path.home()/'.claude/hooks',Path.home()/'.claude/settings.json',
    )]
    text=re.sub(r'/+', '/', json.dumps(data,ensure_ascii=False).replace('\\\\','/').replace('\\','/').casefold())
    bypass=re.search(r'(?i)--bare\b|claude_code_simple|disableallhooks|(?:hkey_current_user|hkcu|hkey_local_machine|hklm).{0,40}software.{0,4}policies.{0,4}claudecode|install_fames_enforcement\.py',text)
    if bypass:
        return 'managed_policy_or_known_bypass'
    mutating=bool(re.search(r'(?i)write|edit|patch|delete|remove|move|rename',name))
    command=str(data.get('command') or data.get('cmd') or '')
    if command:
        mutating=mutating or bool(re.search(r'(?i)>|\bset-content\b|\badd-content\b|\bout-file\b|\bmove-item\b|\bcopy-item\b|\brename-item\b|\breg\s+(add|delete|import|restore)\b|write_text|write_bytes|writefile|\bopen\s*\(|\b(?:rm|mv|cp|tee)\b',command))
    # Unknown tool aliases and code/payload fields must not turn protected
    # operations into implicit permission. Explicit read tools returned above.
    if any(path in text for path in critical):
        return 'trusted_dependency_write' if mutating else 'trusted_dependency_unclassified_operation'
    if re.search(r'(?i)(?:\.\./|\.\./\.\./)?_harness/runtime|_skill/(?:fleet-skills/(?:fames|token-preflight)|engines/claude-claim-integrity-hook)|(?:~/|\.claude/)?hooks/fames_managed|fames_managed_(?:gate|manifest)',text):
        return 'trusted_dependency_write' if mutating else 'trusted_dependency_unclassified_operation'
    return None


def evaluate(doc: dict, *, surface: str = 'claude') -> tuple[dict, dict]:
    event = str(doc.get('hook_event_name') or '')
    if event not in SUPPORTED or surface != 'claude':
        return denial(event, 'unsupported native host or event'), {'state': 'UNKNOWN', 'reason': 'unsupported_host_event'}
    if event in {'SessionStart', 'UserPromptSubmit'}:
        started=time.time()
        receipt_path=HUB/'_registry/fames-turn'/surface/(digest(surface+'\0'+str(doc.get('session_id') or ''))+'.json')
        previous_identity=digest(receipt_path.read_bytes()) if receipt_path.is_file() else 'MISSING'
        payload = call_prompt_hook(doc)
        if event == 'SessionStart':
            return payload, {'state': 'CONTEXT_ONLY', 'reason': 'tool admission requires a current prompt receipt'}
        status = intake_status(doc, surface, not_before=started,previous_identity=previous_identity)
        return (payload if status['state'] == 'PASS' else denial(event, 'current prompt receipt ' + ','.join(status['failed_checks']))), status
    module = claim_module()
    if event == 'ConfigChange':
        # Managed hooks cannot be removed by lower-precedence settings. The
        # existing operator guard separately checks local configuration edits.
        return {}, {'state': 'OBSERVED', 'reason': 'managed policy remains authoritative'}
    lifecycle = module._fames_turn_lifecycle(parent_event(doc))
    if lifecycle.get('state') != 'PASS':
        reason = 'current parent turn ' + ','.join(lifecycle.get('failed_checks', ['UNKNOWN']))
        if event in {'Stop','SubagentStop'} and doc.get('stop_hook_active') is True:
            return {'continue': False, 'stopReason': 'FAMES UNKNOWN: ' + reason}, lifecycle
        return denial(event, reason), lifecycle
    if event == 'PreToolUse':
        violation=protected_operation(doc)
        if violation:
            return denial(event,violation), {'state':'DENIED','reason':violation}
        return {}, lifecycle
    payload, receipt = module.evaluate_hook(doc)
    protocol = read_json(HUB / '_skill/fleet-skills/fames/references/protocols/fames-protocol.json')
    if ((protocol.get('unified_entrypoint') or {}).get('phase_execution') or {}).get('required') is True and receipt.get('claim_count', 0) > 0 and receipt.get('state') == 'PASS':
        parent = parent_event(doc)
        identity = digest(surface + '\0' + str(parent.get('session_id') or ''))
        turn = read_json(HUB / '_registry/fames-turn' / surface / (identity + '.json'))
        phase_runtime = load_module('fames_phase_completion', HUB / '_harness/runtime/fames_phase_runtime.py')
        phase = phase_runtime.completion_status(HUB, turn)
        if phase.get('state') != 'PASS':
            return denial(event, 'SEAL phase evidence is missing or stale'), {'state': 'UNKNOWN', 'phase_execution': phase}
    return payload, {'state': receipt.get('state', 'UNKNOWN'), 'action': receipt.get('action'), 'reason': 'claim and Lean evidence gate', 'lifecycle': lifecycle.get('state')}


def write_audit(doc: dict, result: dict, payload: dict) -> None:
    AUDIT.mkdir(parents=True, exist_ok=True)
    row = {
        'schema': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'session_sha256': digest(str(doc.get('session_id') or '')),
        'event': str(doc.get('hook_event_name') or 'invalid'),
        'state': result.get('state', 'UNKNOWN'),
        'blocked': bool(payload.get('decision') == 'block' or payload.get('continue') is False or payload.get('hookSpecificOutput',{}).get('permissionDecision') == 'deny'),
        'failed_checks': result.get('failed_checks',[]),
        'probe': doc.get('fames_probe_mode') in {'direct','synthetic'},
        'raw_prompt_persisted': False, 'raw_tool_input_persisted': False,
    }
    with (AUDIT/'events.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(row,ensure_ascii=True)+'\n')


def main() -> int:
    doc = {}
    try:
        raw = sys.stdin.buffer.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:
            raise ValueError('oversized_input')
        doc = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(doc,dict):
            raise ValueError('invalid_input')
        payload,result = evaluate(doc)
        write_audit(doc,result,payload)
    except Exception:
        payload=denial(str(doc.get('hook_event_name') or '') if isinstance(doc,dict) else '', 'validator unavailable or malformed evidence')
    sys.stdout.write(json.dumps(payload,ensure_ascii=True)+'\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
