"""Small managed supervisor: verify identity, bound runtime, explicitly deny failure."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def blocked(event, reason):
    message='FAMES managed gate denied: '+reason
    if event=='PreToolUse':
        return {'hookSpecificOutput':{'hookEventName':event,'permissionDecision':'deny','permissionDecisionReason':message}}
    if event in {'UserPromptSubmit','Stop','SubagentStop','ConfigChange'}:
        return {'decision':'block','reason':message}
    return {'continue':False,'stopReason':message}


def verify_manifest(path, expected_sha):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha:
        raise ValueError('manifest_identity_mismatch')
    manifest=json.loads(raw)
    if manifest.get('schema')!=1 or not manifest.get('files'):
        raise ValueError('invalid_manifest')
    for name,expected in manifest['files'].items():
        source=Path(name)
        if not source.is_absolute() or hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
            raise ValueError('dependency_identity_mismatch')
    if manifest.get('worker') not in manifest['files']:
        raise ValueError('worker_not_bound')
    return manifest


def supervise(raw, manifest, *, runner=subprocess.run):
    event=''
    try:
        doc=json.loads(raw.decode('utf-8-sig'))
        if not isinstance(doc,dict):
            raise ValueError('invalid_input')
        event=str(doc.get('hook_event_name') or '')
        result=runner([sys.executable,manifest['worker']],input=raw,capture_output=True,
                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=12)
        if result.returncode!=0:
            raise ValueError('worker_failed')
        payload=json.loads(result.stdout.decode('utf-8'))
        if not isinstance(payload,dict):
            raise ValueError('invalid_output')
        allowed={'hookSpecificOutput','decision','reason','continue','stopReason','systemMessage','suppressOutput'}
        if set(payload)-allowed:
            raise ValueError('unknown_output_fields')
        if 'decision' in payload and (payload['decision']!='block' or not isinstance(payload.get('reason'),str)):
            raise ValueError('invalid_decision')
        if 'continue' in payload and (not isinstance(payload['continue'],bool) or event=='PreToolUse'):
            raise ValueError('invalid_continue')
        hook=payload.get('hookSpecificOutput')
        if hook is not None:
            if not isinstance(hook,dict) or hook.get('hookEventName')!=event:
                raise ValueError('event_output_mismatch')
            if set(hook)-{'hookEventName','permissionDecision','permissionDecisionReason','additionalContext'}:
                raise ValueError('unknown_hook_fields')
            if 'permissionDecision' in hook and (event!='PreToolUse' or hook['permissionDecision']!='deny'):
                raise ValueError('invalid_permission_decision')
            for key in ('additionalContext','permissionDecisionReason'):
                if key in hook and not isinstance(hook[key],str):
                    raise ValueError('invalid_hook_text')
        return payload
    except Exception:
        return blocked(event,'worker failure, deadline, or invalid output')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--event',required=True,choices=('SessionStart','UserPromptSubmit','PreToolUse','Stop','SubagentStop','ConfigChange'))
    args=parser.parse_args()
    raw=sys.stdin.buffer.read(4*1024*1024+1)
    event=args.event
    try:
        doc=json.loads(raw.decode('utf-8-sig'))
        if not isinstance(doc,dict) or doc.get('hook_event_name')!=event:
            raise ValueError('native_event_mismatch')
        if len(raw)>4*1024*1024:
            raise ValueError('oversized_input')
        manifest=verify_manifest(args.manifest,args.sha256)
        payload=supervise(raw,manifest)
    except Exception:
        payload=blocked(event,'missing or changed trusted dependency')
    print(json.dumps(payload,ensure_ascii=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
