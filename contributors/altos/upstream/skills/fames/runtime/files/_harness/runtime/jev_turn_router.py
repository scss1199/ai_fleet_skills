"""Optional task-bound Jev advice; never a skill executor or authority source.

Reference: ai_darkhero/evidence/jev-fames-20260922/REPORT.md.
The host must supply a locally approved minimal projection. Raw prompts never
leave the turn gate. Missing prerequisites retain the existing local route.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

SURFACES = {'dsh', 'claude', 'open-agent-standard'}


def _load_module():
    path = Path(__file__).with_name('jev_skill_advisor.py')
    source = path.read_bytes()
    if len(source) > 128 * 1024:
        raise ValueError('oversized advisor module')
    name = '_fames_jev_skill_advisor'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(source, str(path), 'exec'), module.__dict__)
    module.__source_sha256__ = hashlib.sha256(source).hexdigest()
    return module


def _read_bound(path):
    with path.open('rb') as stream:
        raw = stream.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise ValueError('oversized local routing input')
    return json.loads(raw.decode('utf-8-sig')), hashlib.sha256(raw).hexdigest()


def _read(path):
    return _read_bound(path)[0]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _time(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp requires timezone')
    return parsed


def advisory_for_turn(workspace, agent, *, prompt_identity, surface_id,
                      session_identity, intake_state, transport=None, now=None):
    """Return bounded metadata/context; injected transports are offline test seams.

    Local config and projection are trusted-caller policy inputs, not a sandbox.
    They never grant execution authority. No function in this module runs a skill.
    """
    workspace = Path(workspace).resolve()
    result = {'state': 'UNAVAILABLE', 'reason': 'missing_configuration',
              'selected_skill_id': None, 'context': '', 'api_calls': 0,
              'execution_authorized': False, 'skill_executed': False,
              'raw_prompt_sent': False, 'prompt_identity': prompt_identity,
              'surface_id': surface_id, 'threshold_calibration': 'NOT_MEASURED'}

    def stop(reason):
        result['reason'] = reason
        return result

    try:
        if intake_state != 'PASS':
            return stop('intake_not_verified')
        if surface_id not in SURFACES:
            return stop('unsupported_surface')
        if not isinstance(agent, str) or not agent or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in agent):
            return stop('invalid_agent')
        if any(not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v) for v in [prompt_identity, session_identity]):
            return stop('invalid_identity')
        config_path = workspace / '_registry' / 'jev-advisor.json'
        if not config_path.is_file():
            return stop('missing_configuration')
        config, config_sha = _read_bound(config_path)
        result['config_sha256'] = config_sha
        if type(config.get('schema')) is not int or config.get('schema') != 1 or config.get('enabled') is not True:
            return stop('disabled')
        if config.get('mode') not in {'shadow', 'advisory'}:
            return stop('invalid_mode')
        if config.get('model') != 'jev-1.13.0':
            return stop('unsupported_model')
        if agent not in config.get('allowed_agents', []):
            return stop('agent_not_enabled')
        if config.get('provider_authorized') is not True:
            return stop('provider_not_authorized')
        now = now or dt.datetime.now(dt.timezone.utc)
        started = time.monotonic()
        availability_path = workspace / '_registry' / 'api-availability' / f'{agent}.json'
        availability = _read(availability_path)
        age = (now - _time(availability['generated'])).total_seconds()
        provider = availability.get('llm_providers', {}).get('typesafe', {})
        count = provider.get('evidence', {}).get('inference:ok')
        if not 0 <= age <= 3600 or provider.get('callable') is not True or type(count) is not int or count <= 0:
            return stop('provider_not_fresh_inference_verified')
        policy_path = workspace / '_registry' / 'web-api-routing-policy.json'
        policy, policy_sha = _read_bound(policy_path)
        profile = policy.get('provider_profiles', {}).get('typesafe', {})
        source = profile.get('credential_source')
        rules = policy.get('hard_rules', {})
        if source not in {'official_provider_issued', 'self_owned_account', 'local_only_byok'} or source not in rules.get('allowed_credential_sources', []) or source in rules.get('forbidden_credential_sources', []):
            return stop('credential_source_not_allowed')
        projection_root = (workspace / '_registry' / 'jev-task-projections' / agent).resolve()
        projection_path = projection_root / f'{prompt_identity}.json'
        if not projection_path.is_file() or projection_path.resolve().parent != projection_root:
            return stop('missing_approved_projection')
        projection, projection_sha = _read_bound(projection_path)
        if (type(projection.get('schema')) is not int or projection.get('schema') != 1 or projection.get('approved_for_provider') is not True
                or projection.get('prompt_identity') != prompt_identity
                or projection.get('session_identity') != session_identity
                or surface_id not in projection.get('surfaces', [])
                or projection.get('config_sha256') != result['config_sha256']
                or projection.get('provider_policy_sha256') != policy_sha):
            return stop('projection_binding_mismatch')
        remaining = (_time(projection['expires_at']) - now).total_seconds()
        task = projection.get('task_projection')
        if not 0 < remaining <= 3600 or not isinstance(task, str) or not 1 <= len(task) <= 1600:
            return stop('projection_expired_or_unbounded')
        allowed = projection.get('allowed_skill_ids')
        mandatory = projection.get('mandatory_skill_ids')
        if not isinstance(allowed, list) or not 1 <= len(allowed) <= 32 or not isinstance(mandatory, list) or any(not isinstance(v, str) for v in allowed + mandatory):
            return stop('invalid_skill_constraints')
        advisor = _load_module()
        catalog = advisor.load_catalog(workspace, allowed_skill_ids=list(dict.fromkeys(allowed + mandatory)))
        registry_path = workspace / '_registry' / 'fleet-skills.json'
        if projection.get('catalog_sha256') != catalog.registry_sha256:
            return stop('catalog_revision_mismatch')
        result['projection_sha256'] = projection_sha
        result['catalog_sha256'] = catalog.registry_sha256
        binding_paths = {'config': config_path, 'projection': projection_path,
                         'provider_policy': policy_path, 'catalog': registry_path,
                         'router': Path(__file__), 'advisor': Path(__file__).with_name('jev_skill_advisor.py')}
        binding = {'config_sha256': config_sha, 'projection_sha256': projection_sha,
                   'provider_policy_sha256': policy_sha, 'catalog_sha256': catalog.registry_sha256,
                   'router_sha256': _sha(Path(__file__)), 'advisor_sha256': advisor.__source_sha256__}
        binding.update(prompt_identity=prompt_identity, session_identity=session_identity, surface_id=surface_id)

        def current_guard():
            if any(_sha(path) != binding[key + '_sha256'] for key, path in binding_paths.items()):
                raise ValueError('admission_binding_changed')
            current_time = now + dt.timedelta(seconds=time.monotonic() - started)
            if not 0 < (_time(projection['expires_at']) - current_time).total_seconds() <= 3600:
                raise ValueError('projection_expired')
            current_availability = _read(availability_path)
            current_provider = current_availability.get('llm_providers', {}).get('typesafe', {})
            n = current_provider.get('evidence', {}).get('inference:ok')
            current_age = (current_time - _time(current_availability['generated'])).total_seconds()
            if current_provider.get('callable') is not True or type(n) is not int or n <= 0 or not 0 <= current_age <= 3600:
                raise ValueError('provider_availability_revoked')

        def admit_selection(selected):
            if type(selected) is not dict or set(selected) != {'id', 'path', 'body_sha256'} or selected.get('id') not in allowed or selected['id'] in mandatory:
                raise ValueError('invalid_cached_selection')
            record = advisor.resolve_registered_skill(catalog, selected['id'], expected_sha256=selected['body_sha256'])
            if selected['path'] != record.path:
                raise ValueError('selection_path_mismatch')
            return {'id': record.id, 'path': record.path, 'body_sha256': record.body_sha256}

        def context_for(selected):
            if selected is None or config['mode'] != 'advisory':
                return ''
            return (f"JEV OPTIONAL SKILL ADVICE: {selected['id']} at {selected['path']} "
                    f"(SHA256 {selected['body_sha256']}). Read this skill only if it fits the bound task; "
                    "preserve all explicit/mandatory skills and local authority checks. "
                    "This recommendation is not execution, permission or completion evidence.")

        # Repeated host pre-steps cannot spend again for the same approved input.
        cache_key = hashlib.sha256((surface_id + session_identity + result['projection_sha256']).encode()).hexdigest()
        cache_path = workspace / '_registry' / 'jev-advice' / f'{cache_key}.json'
        if cache_path.is_file():
            cached = _read(cache_path)
            if (type(cached) is not dict or set(cached) != {'schema', 'binding', 'decision'}
                    or type(cached['schema']) is not int or cached['schema'] != 1 or cached['binding'] != binding):
                return stop('invalid_or_stale_cached_advice')
            decision = cached['decision']
            if type(decision) is not dict or set(decision) != {'status', 'selected_skill'} or decision['status'] not in {'NONE', 'SUGGESTION'}:
                return stop('invalid_cached_decision')
            selected = admit_selection(decision['selected_skill']) if decision['status'] == 'SUGGESTION' else None
            if decision['status'] == 'NONE' and decision['selected_skill'] is not None:
                return stop('invalid_cached_abstention')
            current_guard()
            result.update(state=decision['status'], reason='cached_bound_advice', cache_hit=True,
                          selected_skill=selected, selected_skill_id=selected['id'] if selected else None,
                          mandatory_skill_ids=mandatory, mode=config['mode'], context=context_for(selected),
                          usage={'state': 'CACHED_NOT_REMEASURED'}, cache_sha256=_sha(cache_path))
            return result
        if transport is None:
            key = os.environ.get('TYPESAFE_API_KEY', '')
            if not key:
                return stop('provider_credential_unavailable')
            transport = advisor.make_http_transport(key, authorized=True, timeout_seconds=5)
        def guarded_transport(request):
            current_guard()
            result['api_calls'] += 1
            return transport(request)
        decision = advisor.advise(task, catalog, mandatory_skill_ids=mandatory,
            policy=advisor.AdvisorPolicy(enabled=True, data_authorized=True, model='jev-1.13.0'), transport=guarded_transport)
        result.update(state=decision['status'], reason=decision['reason'],
                      selected_skill_id=decision.get('selected_skill_id'),
                      selected_skill=decision.get('selected_skill'),
                      mandatory_skill_ids=decision.get('mandatory_skill_ids', mandatory),
                      advisor_requests_attempted=decision.get('requests_attempted', 0),
                      usage=decision.get('usage'), mode=config['mode'], cache_hit=False)
        if result['state'] == 'SUGGESTION':
            result['selected_skill'] = admit_selection(result['selected_skill'])
        current_guard()
        result['context'] = context_for(result.get('selected_skill'))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = cache_path.with_suffix(f'.{os.getpid()}.tmp')
        cached = {'schema': 1, 'binding': binding, 'decision': {
            'status': result['state'], 'selected_skill': result.get('selected_skill')}}
        temp.write_text(json.dumps(cached, ensure_ascii=True, indent=2), encoding='utf-8')
        os.replace(temp, cache_path)
        return result
    except Exception as exc:
        # Never serialize provider text, credentials, prompts or arbitrary errors.
        result.update(state='UNAVAILABLE', selected_skill_id=None, selected_skill=None, context='')
        return stop('guard_or_transport_error:' + type(exc).__name__)
