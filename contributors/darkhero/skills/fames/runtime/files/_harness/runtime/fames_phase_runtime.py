"""Source-bound phase evidence producer; formal guards do not prove task semantics.

The native intake freezes a prompt/contract snapshot. Completion requires a
separate task verifier receipt and closed obligations. Advisory output never
supplies facts or execution authority.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

PHASES = ('FP', 'MTM', 'SCF', 'AEX', 'SEAL')
FACTS = ('goal_bound', 'authority_bound', 'acceptance_bound', 'skills_bound',
         'result_verified', 'identity_fresh', 'evidence_fresh', 'residual_measured',
         'residual_comparable', 'cross_cycle', 'boundaries_preserved', 'graph_closed')
HUB = Path(__file__).resolve().parents[2]
HEX = re.compile(r'[0-9a-f]{64}')

def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()

def load(path):
    spec = importlib.util.spec_from_file_location('phase_' + sha(str(path))[:12], path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), mod.__dict__)
    return mod

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_suffix('.tmp')
    stage.write_text(json.dumps(data, indent=2, ensure_ascii=True)+'\n', encoding='utf-8')
    stage.replace(path)
    if json.loads(path.read_text(encoding='utf-8')) != data:
        raise ValueError('phase_receipt_readback')

def ref(role, path):
    return {'role': role, 'path': str(path), 'sha256': sha(path.read_bytes())}

def goal_identity(turn):
    return sha({k: turn.get(k) for k in ('session_identity_sha', 'prompt_identity',
                'prompt_contract_identity', 'package_sha')})

def phase_identity(goal, phase):
    return sha({'goal_identity': goal, 'phase': phase, 'schema': 'fames-phase-input/1'})

def fresh(value, seconds=86400):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        age = (dt.datetime.now(dt.timezone.utc)-parsed).total_seconds()
        return -5 <= age <= seconds
    except (ValueError, TypeError):
        return False

def read_refs(request):
    rows = {}
    for item in request.get('receipt_refs', []):
        path = Path(item['path']).resolve()
        raw = path.read_bytes()
        if sha(raw) != item['sha256'] or item['role'] in rows:
            raise ValueError('receipt_identity_or_duplicate')
        rows[item['role']] = json.loads(raw)
    return rows

def bound_files(rows):
    return bool(rows) and all(isinstance(r, dict) and HEX.fullmatch(str(r.get('sha256', '')))
                             and Path(r['path']).is_file() and sha(Path(r['path']).read_bytes()) == r['sha256']
                             for r in rows)

def replay_phase_facts(request):
    """Re-read concrete artifacts; caller-supplied fact bits are ignored.

Verification receipts establish recorded checks and byte identities. They are
not an OS trust boundary and do not decide whether tests capture user meaning.
"""
    facts = dict.fromkeys(FACTS, False)
    try:
        rows = read_refs(request)
        turn = rows.get('turn', {})
        goal = goal_identity(turn)
        native = (turn.get('state') == 'PASS' and turn.get('runtime_event_observed') is True
                  and turn.get('activation_evidence') in {'lifecycle_hook', 'always_apply_rule_gate'}
                  and turn.get('read_back') is True and turn.get('adapter_registration', {}).get('state') == 'PASS'
                  and bool(turn.get('package_sha')))
        valid = (native and goal == request.get('goal_identity') and request.get('task_id') == goal and
                 request.get('phase_identity') == phase_identity(goal, request.get('phase')))
        work = turn.get('work_contract', {})
        facts['goal_bound'] = valid and bool(HEX.fullmatch(str(turn.get('prompt_identity', ''))))
        facts['authority_bound'] = valid and request.get('authority_before') == ['within_user_request']
        facts['acceptance_bound'] = valid and work.get('state') == 'BOUND_NOT_EXECUTION_PROOF' and bool(work.get('stop_rule'))
        facts['identity_fresh'] = valid and fresh(turn.get('generated'))
        route = turn.get('local_skill_route', {})
        candidates = route.get('candidates', [])
        catalog_module = load(Path(__file__).with_name('jev_skill_advisor.py'))
        # An unmatched lexical hint must still permit model-led catalog discovery.
        # Bind the actual FAMES router skill for that stage; this grants no task
        # skill execution and leaves task-specific selection unresolved.
        discovery = (route.get('state') == 'ABSTAIN' and not candidates
                     and work.get('unified_entrypoint', {}).get('public_trigger') == 'FAMES')
        catalog = catalog_module.load_catalog(HUB, allowed_skill_ids=['fames'] if discovery else [item['id'] for item in candidates])
        skills_current = bool(candidates) and len(candidates) <= 3
        if discovery:
            catalog_module.resolve_registered_skill(catalog, 'fames')
            skills_current = True
        for item in candidates:
            canonical = catalog_module.resolve_registered_skill(catalog, item['id'], expected_sha256=item['body_sha256'])
            skills_current = skills_current and Path(canonical.path).resolve() == Path(item['path']).resolve()
        facts['skills_bound'] = bool(valid and (route.get('state') == 'CANDIDATES' or discovery) and skills_current)
        result = rows.get('result', {})
        result_bound = (valid and result.get('schema') == 'fames-task-verification/1'
                        and result.get('goal_identity') == goal and result.get('state') == 'PASS'
                        and result.get('exit_code') == 0 and bool(result.get('measurement_scope'))
                        and result.get('checks') and all(v is True for v in result['checks'].values())
                        and bound_files(result.get('source_refs', [])) and bound_files(result.get('evidence_refs', [])))
        facts['result_verified'] = bool(result_bound)
        facts['evidence_fresh'] = bool(result_bound and fresh(result.get('observed_at')))
        residual = rows.get('residual', {})
        measured = (result_bound and residual.get('goal_identity') == goal and
                    residual.get('state') == 'PASS' and bound_files(residual.get('measurement_refs', [])))
        facts['residual_measured'] = bool(measured and all(type(residual.get(k)) in (int, float)
                                         and math.isfinite(residual[k]) for k in ('before', 'after')))
        facts['residual_comparable'] = bool(measured and residual.get('before_method_sha256')
                  == residual.get('after_method_sha256') and HEX.fullmatch(str(residual.get('before_method_sha256', ''))))
        facts['cross_cycle'] = bool(measured and residual.get('previous_goal_identity') != goal
                                    and HEX.fullmatch(str(residual.get('previous_goal_identity', ''))))
        closure = rows.get('closure', {})
        closure_bound = result_bound and closure.get('goal_identity') == goal and closure.get('schema') == 'fames-task-closure/1'
        obligations = closure.get('obligations', [])
        facts['graph_closed'] = bool(closure_bound and obligations and all(
            x.get('state') == 'VERIFIED' and bound_files(x.get('evidence_refs', [])) for x in obligations))
        facts['boundaries_preserved'] = bool(closure_bound and closure.get('authority_after') == ['within_user_request']
                                            and closure.get('red_line_violations') == [])
    except (OSError, ValueError, KeyError, TypeError):
        return dict.fromkeys(FACTS, False)
    return facts

def advance(workspace, turn_path, phase, *, previous_guard=None, extra_refs=(), mode='execute', skip_reason=''):
    workspace, turn_path = Path(workspace), Path(turn_path)
    turn = json.loads(turn_path.read_text(encoding='utf-8'))
    goal = goal_identity(turn)
    request = {'schema': 'fames-phase-input/1', 'task_id': goal, 'goal_identity': goal,
               'phase_identity': phase_identity(goal, phase), 'phase': phase, 'mode': mode,
               'skip_reason': skip_reason, 'authority_before': ['within_user_request'],
               'authority_after': ['within_user_request'], 'previous_guard': previous_guard,
               'skill_binding_kind': 'routing_entrypoint_only' if turn.get('local_skill_route', {}).get('state') == 'ABSTAIN' else 'canonical_candidates',
               'task_skill_selection': 'UNRESOLVED_UNTIL_MODEL_JUDGMENT',
               'receipt_refs': [ref('turn', turn_path), *extra_refs]}
    mod = load(workspace / '_lean/fames/phase_contract.py')
    conformance = workspace / '_registry/fames-phase-conformance.json'
    produced = mod.produce_phase_evidence(request, producer_path=Path(__file__), conformance_path=conformance)
    guard = mod.evaluate_phase(phase, produced, conformance_path=conformance)
    folder = workspace / '_registry/fames-phase' / goal
    path = folder / (phase.lower() + '.json')
    write(path, guard)
    # Advice is stored beside the guard, never inside its verified fact chain.
    try:
        advisor = load(workspace / '_harness/runtime/jev_phase_advisor.py')
        candidates = turn.get('local_skill_route', {}).get('candidates', [])
        constraints = turn.get('local_skill_route', {}).get('skill_constraints') or {}
        advice = advisor.advisory_for_phase(workspace, turn.get('jev_agent') or turn.get('agent', ''), phase=phase,
            goal_identity=goal, phase_identity=request['phase_identity'],
            prompt_identity=turn.get('prompt_identity'), session_identity=turn.get('session_identity_sha'),
            surface_id=turn.get('surface_id', ''), intake_state=turn.get('state'),
            allowed_skill_ids=[c['id'] for c in candidates], local_candidates=candidates,
            mandatory_skill_ids=constraints.get('mandatory_skill_ids', []),
            excluded_skill_ids=constraints.get('excluded_skill_ids', []),
            read_only_hint=turn.get('local_skill_route', {}).get('read_only_hint', False),
            phase_guard={'state': guard.get('state', 'UNKNOWN'), 'goal_identity': goal,
                         'phase_identity': request['phase_identity'],
                         'contract_sha256': guard.get('contract_sha256'),
                         'receipt_sha256': guard.get('receipt_sha256'),
                         'observed_at': guard.get('observed_at')})
    except Exception as exc:
        advice = {'state': 'UNKNOWN', 'reason': type(exc).__name__, 'api_calls': 0,
                  'phase_advance_authorized': False}
    write(folder / (phase.lower() + '-advice.json'), advice)
    return guard, ref('previous_guard', path)

def begin_turn(workspace, turn):
    workspace = Path(workspace)
    goal = goal_identity(turn)
    folder = workspace / '_registry/fames-phase' / goal
    snapshot = folder / 'turn.json'
    # Freeze only the fields needed by evidence replay; no prompt text or advice.
    keys = ('agent', 'jev_agent', 'surface_id', 'state', 'runtime_event_observed', 'activation_evidence', 'read_back', 'adapter_registration',
            'package_sha', 'prompt_identity', 'session_identity_sha', 'prompt_contract_identity',
            'work_contract', 'generated', 'local_skill_route')
    write(snapshot, {k: turn.get(k) for k in keys})
    guards, previous = {}, None
    for phase in ('FP', 'MTM'):
        try:
            guard, previous = advance(workspace, snapshot, phase, previous_guard=previous)
        except Exception as exc:
            guard = {'state': 'UNKNOWN', 'reasons': [type(exc).__name__], 'phase': phase,
                     'goal_identity': goal, 'phase_identity': phase_identity(goal, phase)}
        guards[phase] = guard
        if guard.get('state') != 'PASS':
            break
    return {'goal_identity': goal, 'turn_snapshot': str(snapshot), 'guards': guards,
            'state': 'PASS' if set(guards) == {'FP', 'MTM'} and all(g.get('state') == 'PASS' for g in guards.values()) else 'UNKNOWN',
            'completion': 'UNKNOWN_UNTIL_SCF_AEX_SEAL', 'scope': 'formal_phase_admission_not_business_outcome'}

def completion_status(workspace, turn):
    goal = goal_identity(turn)
    root = Path(workspace) / '_registry/fames-phase' / goal
    try:
        mod = load(Path(workspace) / '_lean/fames/phase_contract.py')
        saved = json.loads((root/'seal.json').read_text(encoding='utf-8'))
        guard = mod.evaluate_phase('SEAL', saved, conformance_path=Path(workspace)/'_registry/fames-phase-conformance.json')
        if (guard.get('goal_identity') != goal or guard.get('task_id') != goal
                or guard.get('phase_identity') != phase_identity(goal, 'SEAL')):
            return {'state': 'UNKNOWN', 'goal_identity': goal, 'reason': 'completion_goal_identity_mismatch'}
        return {'state': guard.get('state', 'UNKNOWN'), 'goal_identity': goal, 'receipt_path': str(root/'seal.json')}
    except Exception as exc:
        return {'state': 'UNKNOWN', 'goal_identity': goal, 'reason': type(exc).__name__}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=HUB)
    parser.add_argument('--turn', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--closure', type=Path, required=True)
    parser.add_argument('--residual', type=Path)
    args = parser.parse_args()
    turn = json.loads(args.turn.read_text(encoding='utf-8'))
    begin = begin_turn(args.workspace, turn)
    goal = begin['goal_identity']
    folder = args.workspace/'_registry/fames-phase'/goal
    snapshot = folder/'turn.json'
    previous = ref('previous_guard', folder/'mtm.json') if (folder/'mtm.json').is_file() else None
    extra = [ref('result', args.result), ref('closure', args.closure)]
    if args.residual:
        extra.append(ref('residual', args.residual))
    phases = dict(begin['guards'])
    for phase in ('SCF', 'AEX', 'SEAL'):
        inactive = phase == 'AEX' and not args.residual
        guard, previous = advance(args.workspace, snapshot, phase, previous_guard=previous, extra_refs=extra,
            mode='skip' if inactive else 'execute', skip_reason='No comparable cross-cycle measurement exists' if inactive else '')
        phases[phase] = guard
    print(json.dumps({'state': phases['SEAL']['state'], 'goal_identity': goal,
                      'phases': {p:g['state'] for p,g in phases.items()}, 'path': str(folder)}))
    return 0 if phases['SEAL']['state'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
