"""Prompt-bound native admission; queued prompts must not evict an active turn.

Recovery reads existing native provenance. It cannot create operator authority or
completion evidence. Raw prompts remain exclusively in the host transcript.
"""
from __future__ import annotations
import hashlib
import contextlib
import importlib.util
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

HEX = re.compile(r"[0-9a-f]{64}")


def load(path):
    spec = importlib.util.spec_from_file_location('binding_' + hashlib.sha256(str(path).encode()).hexdigest()[:12], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    try:
        result = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def write(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    stage.write_text(json.dumps(doc, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    os.replace(stage, path)
    if read(path) != doc:
        raise ValueError('turn_binding_readback_failed')


def archive_path(root, surface, session, prompt):
    if not HEX.fullmatch(str(session)) or not HEX.fullmatch(str(prompt)) or not re.fullmatch(r'[\w-]+', surface):
        raise ValueError('invalid_turn_key')
    return Path(root) / surface / 'by-prompt' / session / (prompt + '.json')


def order(receipt):
    value = receipt.get('native_intake_observed_ns')
    if type(value) is int:
        return value
    try:
        return int(datetime.fromisoformat(str(receipt['generated']).replace('Z', '+00:00')).timestamp() * 1_000_000_000)
    except (ValueError, TypeError, KeyError):
        return 0


@contextlib.contextmanager
def locked(path):
    """Retained lock file; bounded cross-process serialization without deletion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        deadline = time.monotonic() + 2
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError('turn_store_busy')
                time.sleep(0.01)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def preserve(root, receipt):
    """Persist an exact native receipt independently of the session latest pointer."""
    path = archive_path(root, receipt['surface_id'], receipt['session_identity_sha'], receipt['prompt_identity'])
    with locked(path.with_suffix('.lock')):
        previous = read(path)
        if previous and order(previous) > order(receipt):
            return path
        if previous and previous != receipt:
            # Preserve prior same-text submissions too; generated time still gates reuse.
            history = path.parent / 'history' / (sha(path) + '.json')
            if not history.exists():
                write(history, previous)
        write(path, receipt)
    return path


def publish_latest(path, receipt):
    path = Path(path)
    with locked(path.with_suffix('.lock')):
        previous = read(path)
        if not previous or order(previous) <= order(receipt):
            write(path, receipt)


def select(root, surface, session, prompt):
    current = Path(root) / surface / (session + '.json')
    if prompt:
        archived = archive_path(root, surface, session, prompt)
        if archived.is_file():
            return archived
    return current


def fresh_for_prompt(receipt, started):
    try:
        native_time = receipt.get('native_rebind', {}).get('original_generated', receipt.get('generated'))
        generated = datetime.fromisoformat(str(native_time).replace('Z', '+00:00')).timestamp()
        return started is not None and generated + 2 >= started
    except (ValueError, TypeError, KeyError):
        return False


def migrate_legacy(workspace, template, prompt, agent, started):
    """Recover an overwritten pre-history receipt only from a replayed native FP.

The old snapshot lacks some envelope fields. Those fields come from the same
session/package/contract template, while all prompt-specific fields come from
the hash-bound native snapshot. This provenance is retained explicitly.
"""
    workspace = Path(workspace)
    phase = load(workspace / '_harness/runtime/fames_phase_runtime.py')
    key = dict(template, prompt_identity=prompt)
    folder = workspace / '_registry/fames-phase' / phase.goal_identity(key)
    snapshot_path, guard_path = folder / 'turn.json', folder / 'fp.json'
    snapshot, guard = read(snapshot_path), read(guard_path)
    required = ('session_identity_sha', 'package_sha', 'prompt_contract_identity')
    if (not snapshot or any(snapshot.get(k) != template.get(k) for k in required)
            or snapshot.get('prompt_identity') != prompt or snapshot.get('agent') != agent
            or snapshot.get('state') != 'PASS' or snapshot.get('runtime_event_observed') is not True
            or snapshot.get('activation_evidence') != 'lifecycle_hook'
            or not fresh_for_prompt(snapshot, started)):
        return None
    checker = load(workspace / '_lean/fames/phase_contract.py')
    verified = checker.evaluate_phase('FP', guard, conformance_path=workspace / '_registry/fames-phase-conformance.json')
    if verified.get('state') != 'PASS' or verified.get('goal_identity') != phase.goal_identity(snapshot):
        return None
    recovered = dict(template)
    recovered.update(snapshot)
    recovered['legacy_recovery'] = {
        'kind': 'replayed_native_fp_snapshot', 'completion_authorized': False,
        'source_refs': [{'path': str(p), 'sha256': sha(p)} for p in (snapshot_path, guard_path)],
        'verified_guard_sha256': verified.get('guard_sha256'),
    }
    path = preserve(workspace / '_registry/fames-turn', recovered)
    return path


def recovery_admission(workspace, receipt_path, *, session, prompt, agent, started):
    """Check the source of a bounded native rebind, before current policy replay."""
    receipt_path = Path(receipt_path)
    source_sha = sha(receipt_path)
    receipt = read(receipt_path)
    native = (receipt.get('state') == 'PASS' and receipt.get('runtime_event_observed') is True
              and receipt.get('activation_evidence') == 'lifecycle_hook'
              and receipt.get('read_back') is True and receipt.get('raw_prompt_persisted') is False
              and receipt.get('adapter_registration', {}).get('state') == 'PASS'
              and bool(HEX.fullmatch(str(receipt.get('package_sha', '')))))
    refs = receipt.get('legacy_recovery', {}).get('source_refs', [])
    refs_bound = all(Path(r['path']).is_file() and sha(r['path']) == r['sha256'] for r in refs)
    facts = {'same_session': receipt.get('session_identity_sha') == session,
             'exact_prompt': receipt.get('prompt_identity') == prompt,
             'same_seat': receipt.get('agent') == agent,
             'native_origin_verified': native,
             'original_receipt_fresh': fresh_for_prompt(receipt, started),
             'source_hash_bound': refs_bound and sha(receipt_path) == source_sha}
    contract = load(Path(workspace) / '_lean/fames/turn_recovery_contract.py')
    decision = contract.verified_recovery_decision(facts, ['within_user_request'], ['within_user_request'],
        conformance_path=Path(workspace) / '_registry/fames-turn-recovery-conformance.json')
    if decision.get('admitted') is True:
        frozen = receipt_path.parent / 'history' / (source_sha + '.json')
        if not frozen.exists():
            frozen.parent.mkdir(parents=True, exist_ok=True)
            with frozen.open('xb') as stream:
                stream.write(receipt_path.read_bytes())
        if sha(frozen) != source_sha:
            raise ValueError('native_source_changed')
        receipt_path = frozen
    return dict(decision, source_path=str(receipt_path), source_sha256=source_sha, facts=facts,
                original_generated=receipt.get('native_rebind', {}).get('original_generated', receipt.get('generated')),
                native_intake_observed_ns=order(receipt))
