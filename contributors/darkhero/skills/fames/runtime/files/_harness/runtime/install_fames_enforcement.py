"""Plan/apply additive Claude lifecycle policy with exact backups and readback."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import winreg

HUB=Path(__file__).resolve().parents[2]
USER=Path.home()/'.claude'
POLICY_KEY=r'SOFTWARE\Policies\ClaudeCode'
GATE=USER/'hooks/fames_managed_gate.py'
MANIFEST=USER/'hooks/fames_managed_manifest.json'
PYTHON=Path(sys.executable).resolve().with_name('pythonw.exe')
EVENTS=('SessionStart','UserPromptSubmit','PreToolUse','Stop','SubagentStop','ConfigChange')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(data):
    return (json.dumps(data,indent=2,ensure_ascii=True)+'\n').encode('utf-8')


def policy_read():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,POLICY_KEY) as key:
            raw,kind=winreg.QueryValueEx(key,'Settings')
        doc=json.loads(raw)
        if not isinstance(doc,dict):
            raise ValueError('invalid_existing_managed_policy')
        return doc,raw,kind
    except FileNotFoundError:
        return {},None,winreg.REG_SZ


def file_policy_read(path):
    if not path.is_file():
        return {},None,winreg.REG_SZ
    raw=path.read_text(encoding='utf-8-sig')
    doc=json.loads(raw)
    if not isinstance(doc,dict):
        raise ValueError('invalid_existing_policy')
    return doc,raw,winreg.REG_SZ


def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    staging=path.with_name(path.name+'.fames-staging-'+str(os.getpid()))
    with staging.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staging,path)
    if path.read_bytes()!=data:
        raise ValueError('destination_readback_mismatch')


def planned_policy(old,sha):
    policy=json.loads(json.dumps(old))
    hooks=policy.setdefault('hooks',{})
    for event in EVENTS:
        existing=hooks.setdefault(event,[])
        # Idempotent replacement of only this installer-owned entry.
        def owned(handler):
            # Interpreter paths can change after a Python/workspace migration.
            # Ownership is the exact entry script and manifest pair, not the
            # executable or merely a familiar script basename.
            args=handler.get('args')
            if handler.get('type')!='command' or not isinstance(args,list) or not args:
                return False
            def normalized(value):
                return str(value).replace('\\','/').casefold()
            if normalized(args[0])!=normalized(GATE) or args.count('--manifest')!=1:
                return False
            index=args.index('--manifest')+1
            return index<len(args) and normalized(args[index])==normalized(MANIFEST)
        retained=[]
        for entry in existing:
            handlers=entry.get('hooks',[])
            remaining=[handler for handler in handlers if not owned(handler)]
            if len(remaining)==len(handlers):
                retained.append(entry)
            elif remaining:
                entry['hooks']=remaining
                retained.append(entry)
        existing[:]=retained
        hook={'type':'command','command':str(PYTHON).replace('\\','/'),
              'args':[str(GATE).replace('\\','/'),'--manifest',str(MANIFEST).replace('\\','/'),'--sha256',sha,'--event',event],
              'timeout':25}
        entry={'hooks':[hook]}
        if event=='PreToolUse':
            entry['matcher']='.*'
        if event=='ConfigChange':
            entry['matcher']='user_settings|project_settings|local_settings|policy_settings'
        existing.append(entry)
    # Pin this at managed precedence; other hook sources still run.
    policy['disableAllHooks']=False
    return policy


def dependency_manifest(entry_bytes):
    paths=[HUB/'_harness/runtime'/name for name in (
        'fames_session_harness.py','fames_capabilities.py','fames_enforcement.py',
        'fames_managed_entry.py','fames_phase_runtime.py','local_skill_router.py',
        'jev_skill_advisor.py','jev_turn_router.py','jev_task_projection.py','jev_phase_advisor.py')]
    paths += [HUB/'_skill/engines/claude-claim-integrity-hook.py',
              HUB/'_skill/fleet-skills/token-preflight/scripts/claude_session_hook.py',
              HUB/'_skill/fleet-skills/fames/bundle-manifest.json',
              HUB/'_skill/fleet-skills/fames/scripts/fames_fleet.py',
              HUB/'_skill/fleet-skills/fames/scripts/work_efficiency.py',
              HUB/'_lean/fames/lean_gate.py',
              HUB/'_lean/fames/FamesKernel.lean',
              HUB/'_lean/fames/FamesPhaseContract.lean',
              HUB/'_lean/fames/phase_contract.py',
              HUB/'_lean/fames/phase_conformance.py',
              USER/'hooks/operator_intent_guard.py']
    files={str(p.resolve()):digest(p.read_bytes()) for p in paths if p.is_file()}
    files[str(GATE)]=digest(entry_bytes)
    return {'schema':1,'version':'1.0.0','surface':'claude',
            'worker':str((HUB/'_harness/runtime/fames_enforcement.py').resolve()),
            'files':files,
            'limits':{'child_timeout_seconds':12,'hook_timeout_seconds':25},
            'boundary':'Normal Claude lifecycle only; selected policy scope is reported separately. Bare mode, same-user policy rewriting, missing supervisor and host-native failure are not OS-enforced.'}


def main():
    global GATE,MANIFEST
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--scope',choices=('hkcu','user','machine'),default='hkcu')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    if args.apply and not PYTHON.is_file():
        raise ValueError('no_windowless_python')
    file_policy=None
    if args.scope=='user':
        file_policy=USER/'settings.json'
    elif args.scope=='machine':
        base=Path('C:/Program Files/ClaudeCode')
        GATE=base/'hooks/fames_managed_gate.py'
        MANIFEST=base/'hooks/fames_managed_manifest.json'
        file_policy=base/'managed-settings.d/80-fames-enforcement.json'
    reader=(lambda:file_policy_read(file_policy)) if file_policy else policy_read
    old,raw,kind=reader()
    if old.get('disableAllHooks') is True:
        raise ValueError('existing_managed_policy_explicitly_disables_hooks')
    entry_bytes=(HUB/'_harness/runtime/fames_managed_entry.py').read_bytes()
    manifest=dependency_manifest(entry_bytes)
    manifest_bytes=encoded(manifest)
    manifest_sha=digest(manifest_bytes)
    policy=planned_policy(old,manifest_sha)
    plan={'schema':1,'mode':'apply' if args.apply else 'plan','scope':args.scope+' normal Claude lifecycle',
          'events':list(EVENTS),'dependency_count':len(manifest['files']),
          'manifest_sha256':manifest_sha,'policy_sha256':digest(encoded(policy)),
          'policy_path':str(file_policy) if file_policy else 'HKCU/'+POLICY_KEY+'/Settings',
          'windowless_python':str(PYTHON),'windowless_python_available':PYTHON.is_file(),
          'new_schedules':0,'service_restarts':0,'native_tool_adoption':'UNKNOWN',
          'limitations':manifest['boundary']}
    (args.output/('installation-plan-'+args.scope+'.json')).write_bytes(encoded(plan))
    if not args.apply:
        print(json.dumps(plan))
        return
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=USER/'backups'/('fames-enforcement-'+stamp)
    backup.mkdir(parents=True,exist_ok=False)
    # Raw configuration stays in the owner's backup folder, never in reports.
    if raw is not None:
        (backup/'managed-policy.before.json').write_text(raw,encoding='utf-8')
    for p in (GATE,MANIFEST):
        if p.exists():
            shutil.copy2(p,backup/p.name)
    current,current_raw,_=reader()
    if current_raw!=raw:
        raise ValueError('concurrent_policy_change')
    try:
        atomic(GATE,entry_bytes)
        atomic(MANIFEST,manifest_bytes)
        if file_policy:
            atomic(file_policy,encoded(policy))
        else:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,POLICY_KEY,0,winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key,'Settings',0,winreg.REG_SZ,json.dumps(policy,ensure_ascii=True))
    except PermissionError:
        plan.update({'state':'BLOCKED','reason':'OS_ACCESS_DENIED','backup':str(backup),
                     'policy_published':False,'staged_files':[str(p) for p in (GATE,MANIFEST) if p.exists()]})
        (args.output/('installation-'+args.scope+'.json')).write_bytes(encoded(plan))
        print(json.dumps(plan))
        raise SystemExit(2)
    actual,_,_=reader()
    if actual!=policy:
        raise ValueError('managed_policy_readback_mismatch')
    # Verify destination files against the pinned managed digest.
    import importlib.util
    spec=importlib.util.spec_from_file_location('verify_managed_entry',GATE)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify_manifest(MANIFEST,manifest_sha)
    plan.update({'state':'PUBLISHED','generated_at':datetime.now(timezone.utc).isoformat(),
                 'backup':str(backup),'gate':str(GATE),'manifest':str(MANIFEST),
                 'policy_readback_equal':True,'files_readback_equal':True})
    (args.output/('installation-'+args.scope+'.json')).write_bytes(encoded(plan))
    print(json.dumps(plan))


if __name__=='__main__':
    main()
