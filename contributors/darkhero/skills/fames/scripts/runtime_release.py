"""Content-addressed, recoverable transport for explicit FAMES runtime sources.

CITE: _skill/technique_output/50-techniques/selective-codebase-migration.md
v1 (2026-06-04): transport functional sources, excluding secrets/environments.
CITE: _skill/technique_output/50-techniques/deploy-fames-cognitive-operators.md
v1 (2026-06-04): bind delivery to exact content identities and read-back.

Public API: build(workspace, package_root, source_paths), verify(package_root),
apply(workspace, package_root). No schedules, restarts, downloads, toolchain
installation, automatic rollback, or permanent deletion. Atomicity is per file.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import uuid

SCHEMA = 1
MAX_FILES = 512
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
_DENIED_PARTS = {
    '.git', '.ssh', '.aws', '.azure', '.config', '.claude', '.codex', '.cursor',
    '.venv', 'venv', 'node_modules', '__pycache__', '_secrets', 'secrets',
    'credentials', 'cookies', 'auth', 'authentication', 'settings', 'configs',
    'config', 'environments', 'logs', '_logs', 'runtime-state',
}
_DENIED_STEMS = {'settings', 'credentials', 'secrets', 'cookies', 'auth', 'authentication',
                 'config', 'models', 'model-config', 'model_config', 'hosts', 'known_hosts'}
_DENIED_SUFFIXES = {'.pfx', '.p12', '.pem', '.key', '.db', '.sqlite', '.sqlite3', '.log', '.pyc'}
_DEVICE = re.compile(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', re.I)


class ReleaseError(Exception):
    def __init__(self, code: str, relative: str | None = None):
        self.code = code
        self.relative = relative
        super().__init__(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _error(exc, state='UNKNOWN_INVALID_RELEASE') -> dict:
    result = {'ok': False, 'state': state, 'native_activation': 'UNKNOWN',
              'error': exc.code if isinstance(exc, ReleaseError) else type(exc).__name__}
    if isinstance(exc, ReleaseError) and exc.relative is not None:
        result['path'] = exc.relative
    return result


def _relative(value) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ReleaseError('invalid_relative_path')
    if '\\' in value or ':' in value or any(ord(char) < 32 for char in value):
        raise ReleaseError('invalid_relative_path')
    parts = value.split('/')
    if PurePosixPath(value).is_absolute() or any(part in ('', '.', '..') for part in parts):
        raise ReleaseError('path_traversal')
    for part in parts:
        if part.endswith((' ', '.')) or _DEVICE.match(part):
            raise ReleaseError('unsafe_portable_path')
        if part.casefold() in _DENIED_PARTS or part.casefold().startswith('.env'):
            raise ReleaseError('excluded_sensitive_or_environment_path')
    leaf = PurePosixPath(value)
    if leaf.stem.casefold() in _DENIED_STEMS or leaf.suffix.casefold() in _DENIED_SUFFIXES:
        raise ReleaseError('excluded_sensitive_or_environment_path')
    return value


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def _root(value) -> Path:
    path = Path(value).absolute()
    if _is_link(path):
        raise ReleaseError('root_is_link')
    return path.resolve()


def _beneath(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    target = root.joinpath(*parts)
    cursor = root
    for part in parts:
        cursor = cursor / part
        if _is_link(cursor):
            raise ReleaseError('symlink_or_junction_path', relative)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ReleaseError('path_escapes_root', relative)
    return target


def _read_file(path: Path) -> bytes:
    if not path.is_file():
        raise ReleaseError('missing_regular_file')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ReleaseError('file_size_limit')
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise ReleaseError('file_size_limit')
    return raw


def _write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != raw:
        raise ReleaseError('staged_readback_mismatch')


def _atomic_json(path: Path, doc: dict) -> None:
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.stage')
    _write_new(temporary, _json_bytes(doc) + b'\n')
    os.replace(temporary, path)


def _manifest_payload(manifest: dict) -> dict:
    if not isinstance(manifest, dict) or set(manifest) != {'schema', 'kind', 'generation', 'files', 'release_sha256'}:
        raise ReleaseError('invalid_manifest_fields')
    if manifest['schema'] != SCHEMA or manifest['kind'] != 'fames-runtime-release':
        raise ReleaseError('invalid_manifest_schema')
    if type(manifest['generation']) is not int or manifest['generation'] < 1:
        raise ReleaseError('invalid_generation')
    files = manifest['files']
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise ReleaseError('invalid_file_manifest')
    normalized = set()
    total = 0
    for relative, row in files.items():
        _relative(relative)
        if relative.casefold() in normalized:
            raise ReleaseError('case_colliding_path', relative)
        normalized.add(relative.casefold())
        if not isinstance(row, dict) or set(row) != {'sha256', 'bytes'}:
            raise ReleaseError('invalid_file_identity', relative)
        if not isinstance(row['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
            raise ReleaseError('invalid_file_hash', relative)
        if type(row['bytes']) is not int or not 0 <= row['bytes'] <= MAX_FILE_BYTES:
            raise ReleaseError('invalid_file_size', relative)
        total += row['bytes']
    if total > MAX_TOTAL_BYTES:
        raise ReleaseError('total_size_limit')
    payload = {key: manifest[key] for key in ('schema', 'kind', 'generation', 'files')}
    if manifest['release_sha256'] != _sha(_json_bytes(payload)):
        raise ReleaseError('manifest_hash_mismatch')
    return payload


def _verify_runtime(runtime: Path) -> dict:
    manifest_path = _beneath(runtime, 'manifest.json')
    manifest = json.loads(_read_file(manifest_path))
    _manifest_payload(manifest)
    files_root = _beneath(runtime, 'files')
    actual = set()
    if not files_root.is_dir():
        raise ReleaseError('missing_files_directory')
    for path in files_root.rglob('*'):
        relative = path.relative_to(files_root).as_posix()
        checked = _beneath(files_root, relative)
        if checked.is_file():
            actual.add(relative)
    if actual != set(manifest['files']):
        raise ReleaseError('declared_actual_file_set_mismatch')
    for relative, row in manifest['files'].items():
        raw = _read_file(_beneath(files_root, relative))
        if len(raw) != row['bytes'] or _sha(raw) != row['sha256']:
            raise ReleaseError('content_hash_mismatch', relative)
    return manifest


def verify(package_root) -> dict:
    """Verify exact declared bytes; no source execution, imports or target writes."""
    try:
        package = _root(package_root)
        manifest = _verify_runtime(_beneath(package, 'runtime'))
        return {'ok': True, 'state': 'VERIFIED', 'release_sha256': manifest['release_sha256'],
                'generation': manifest['generation'], 'manifest': manifest,
                'file_count': len(manifest['files']), 'native_activation': 'UNKNOWN'}
    except Exception as exc:
        return _error(exc)


def build(workspace, package_root, source_paths) -> dict:
    """Snapshot only explicit source paths, preserving any previous runtime tree."""
    stage = backup = None
    try:
        workspace, package = _root(workspace), _root(package_root)
        if isinstance(source_paths, (str, bytes)):
            raise ReleaseError('explicit_path_list_required')
        paths = list(source_paths)
        if not 1 <= len(paths) <= MAX_FILES:
            raise ReleaseError('invalid_source_count')
        paths = [_relative(path) for path in paths]
        if len({path.casefold() for path in paths}) != len(paths):
            raise ReleaseError('duplicate_source_path')
        raw_files = {relative: _read_file(_beneath(workspace, relative)) for relative in sorted(paths)}
        if sum(map(len, raw_files.values())) > MAX_TOTAL_BYTES:
            raise ReleaseError('total_size_limit')
        files = {relative: {'sha256': _sha(raw), 'bytes': len(raw)} for relative, raw in raw_files.items()}
        runtime = _beneath(package, 'runtime')
        previous = _verify_runtime(runtime) if runtime.exists() else None
        if previous and previous['files'] == files:
            return {'ok': True, 'state': 'UNCHANGED', 'release_sha256': previous['release_sha256'],
                    'generation': previous['generation'], 'file_count': len(files), 'native_activation': 'UNKNOWN'}
        payload = {'schema': SCHEMA, 'kind': 'fames-runtime-release',
                   'generation': previous['generation'] + 1 if previous else 1, 'files': files}
        manifest = {**payload, 'release_sha256': _sha(_json_bytes(payload))}
        stage = _beneath(package, 'runtime.stage-' + uuid.uuid4().hex)
        for relative, raw in raw_files.items():
            _write_new(_beneath(stage, 'files/' + relative), raw)
        _write_new(_beneath(stage, 'manifest.json'), _json_bytes(manifest) + b'\n')
        _verify_runtime(stage)
        for relative, row in files.items():
            if _sha(_read_file(_beneath(workspace, relative))) != row['sha256']:
                raise ReleaseError('source_changed_during_build', relative)
        if previous:
            backup = _beneath(workspace, '_registry/fames-runtime-build-backups/' + previous['release_sha256'] + '/' + uuid.uuid4().hex)
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(runtime, backup)
        os.replace(stage, runtime)
        final = verify(package)
        if not final['ok']:
            return {**final, 'state': 'UNKNOWN_BUILD_READBACK', 'retained_backup': str(backup) if backup else None}
        return {'ok': True, 'state': 'BUILT', 'release_sha256': manifest['release_sha256'],
                'generation': manifest['generation'], 'file_count': len(files),
                'retained_backup': str(backup) if backup else None, 'native_activation': 'UNKNOWN'}
    except Exception as exc:
        return {**_error(exc, 'UNKNOWN_BUILD'), 'retained_stage': str(stage) if stage else None,
                'retained_backup': str(backup) if backup else None}


@contextlib.contextmanager
def _apply_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ReleaseError('release_apply_busy') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _git(cwd: Path, *args: str):
    return subprocess.run(['git', '--no-optional-locks', '--literal-pathspecs',
                           '-c', 'core.fsmonitor=false', '-C', str(cwd), *args],
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def _clean_git_baseline(path: Path, raw: bytes) -> dict | None:
    """Clean HEAD/index baseline; only declared CRLF conversion is permitted.

    External filters and working-tree encodings are refused before any worktree
    diff can invoke conversion. Release payloads and backups remain raw bytes.
    """
    try:
        top = _git(path.parent, 'rev-parse', '--show-toplevel')
        if top.returncode:
            return None
        repo = Path(os.fsdecode(top.stdout.strip())).resolve()
        relative = path.relative_to(repo).as_posix()
        head = _git(repo, 'rev-parse', '--verify', 'HEAD')
        tree = _git(repo, 'ls-tree', '-z', 'HEAD', '--', relative)
        index = _git(repo, 'ls-files', '--stage', '-z', '--', relative)
        if any(item.returncode for item in (head, tree, index)):
            return None
        t = tree.stdout.split(b'\0')
        i = index.stdout.split(b'\0')
        if len(t) != 2 or len(i) != 2 or not t[0] or not i[0]:
            return None
        tree_meta, tree_path = t[0].split(b'\t', 1)
        index_meta, index_path = i[0].split(b'\t', 1)
        mode, kind, blob = tree_meta.split()
        index_mode, index_blob, stage = index_meta.split()
        if kind != b'blob' or mode not in (b'100644', b'100755') or stage != b'0':
            return None
        if mode != index_mode or blob != index_blob or tree_path != index_path:
            return None
        if os.fsdecode(tree_path) != relative:
            return None
        attrs = _git(repo, 'check-attr', '-z', 'filter', 'working-tree-encoding', 'text', 'eol', '--', relative)
        if attrs.returncode:
            return None
        fields = attrs.stdout.split(b'\0')
        if len(fields) != 13 or fields[-1] != b'':
            return None
        attributes = {}
        for offset in range(0, 12, 3):
            if os.fsdecode(fields[offset]) != relative:
                return None
            attributes[fields[offset + 1].decode('ascii')] = fields[offset + 2].decode('ascii')
        if any(attributes.get(name) not in ('unspecified', 'unset')
               for name in ('filter', 'working-tree-encoding')):
            return None
        algorithm = 'sha1' if len(blob) == 40 else 'sha256' if len(blob) == 64 else None
        if algorithm is None:
            return None
        def blob_hash(data):
            return hashlib.new(algorithm, b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        current_blob = blob_hash(raw)
        conversion = 'raw_identity'
        if current_blob != blob.decode('ascii'):
            setting = _git(repo, 'config', '--get', 'core.autocrlf')
            if setting.returncode not in (0, 1):
                return None
            autocrlf = setting.stdout.strip().lower() in (b'true', b'input')
            allows_crlf = attributes.get('text') != 'unset' and (
                attributes.get('text') in ('set', 'auto') or
                attributes.get('eol') in ('lf', 'crlf') or autocrlf)
            normalized = raw.replace(b'\r\n', b'\n')
            if not allows_crlf or b'\0' in raw or normalized == raw or blob_hash(normalized) != blob.decode('ascii'):
                return None
            current_blob = blob_hash(normalized)
            conversion = 'declared_crlf_to_lf'
        diff = _git(repo, 'diff', '--quiet', '--no-ext-diff', '--no-textconv', 'HEAD', '--', relative)
        if diff.returncode:
            return None
        commit = head.stdout.strip().decode('ascii')
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
            return None
        return {'baseline_kind': 'clean_tracked_git_HEAD', 'commit': commit,
                'blob_hash': current_blob, 'blob_algorithm': algorithm,
                'worktree_conversion': conversion, 'worktree_sha256': _sha(raw)}
    except (OSError, ValueError, subprocess.SubprocessError, UnicodeError):
        return None


def _previous(path: Path) -> dict | None:
    if not path.exists():
        return None
    doc = json.loads(_read_file(path))
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA or doc.get('kind') != 'fames-runtime-installation':
        raise ReleaseError('invalid_previous_receipt')
    if doc.get('installed_manifest') is not None:
        _manifest_payload(doc['installed_manifest'])
    if type(doc.get('highest_generation')) is not int or doc['highest_generation'] < 0:
        raise ReleaseError('invalid_previous_generation')
    if doc['highest_generation'] and not re.fullmatch(r'[0-9a-f]{64}', str(doc.get('highest_release_sha256', ''))):
        raise ReleaseError('invalid_previous_highest_identity')
    return doc


def _persist_receipt(workspace: Path, receipt: dict) -> None:
    path = _beneath(workspace, '_registry/fames-runtime-release.json')
    if path.exists():
        archive = _beneath(workspace, '_registry/fames-runtime-receipts/' + receipt['attempt_id'] + '.' + uuid.uuid4().hex + '.previous.json')
        _write_new(archive, _read_file(path))
    _atomic_json(path, receipt)
    if json.loads(path.read_bytes()) != receipt:
        raise ReleaseError('installation_receipt_readback_failed')


def _apply(workspace: Path, package: Path, checked: dict) -> dict:
    manifest = checked['manifest']
    release = manifest['release_sha256']
    receipt_path = _beneath(workspace, '_registry/fames-runtime-release.json')
    previous = _previous(receipt_path)
    installed = previous.get('installed_manifest') if previous else None
    old_files = installed['files'] if installed else {}
    highest = previous['highest_generation'] if previous else 0
    highest_release = previous.get('highest_release_sha256') if previous else None
    if manifest['generation'] < highest or (manifest['generation'] == highest and highest_release not in (None, release)):
        raise ReleaseError('rollback_or_same_generation_fork')
    receipt = {'schema': SCHEMA, 'kind': 'fames-runtime-installation', 'attempt_id': uuid.uuid4().hex,
               'observed_at': _now(), 'ok': False, 'state': 'PREFLIGHT', 'attempted_release_sha256': release,
               'release_sha256': release,
               'installed_release_sha256': installed['release_sha256'] if installed else None,
               'generation': manifest['generation'], 'highest_generation': highest,
               'highest_release_sha256': highest_release,
               'installed_manifest': installed, 'native_activation': 'UNKNOWN',
               'atomicity': 'PER_FILE_ONLY', 'files': [], 'errors': []}
    plan = []
    for relative, row in manifest['files'].items():
        destination = _beneath(workspace, relative)
        source = _beneath(package, 'runtime/files/' + relative)
        raw = _read_file(source)
        if _sha(raw) != row['sha256'] or len(raw) != row['bytes']:
            raise ReleaseError('source_changed_after_verify', relative)
        current = _read_file(destination) if destination.exists() else None
        current_hash = _sha(current) if current is not None else None
        baseline = {'baseline_kind': 'missing_destination'}
        if current_hash == row['sha256']:
            baseline = {'baseline_kind': 'already_new_hash'}
        elif current is not None:
            if relative in old_files and current_hash == old_files[relative]['sha256']:
                baseline = {'baseline_kind': 'previous_installed_manifest'}
            elif relative in old_files:
                baseline = None
            else:
                baseline = _clean_git_baseline(destination, current)
            if baseline is None:
                receipt.update(state='UNKNOWN_LOCAL_CHANGES')
                receipt['errors'].append({'code': 'unmanaged_or_modified_destination', 'path': relative,
                                          'current_sha256': current_hash, 'wanted_sha256': row['sha256']})
                continue
        record = {'path': relative, 'source_sha256': row['sha256'], 'before_sha256': current_hash,
                  'installed_sha256': None, **baseline}
        receipt['files'].append(record)
        plan.append((relative, raw, current, record))
    if receipt['errors']:
        _persist_receipt(workspace, receipt)
        return receipt
    receipt['highest_generation'] = max(highest, manifest['generation'])
    receipt['highest_release_sha256'] = release
    receipt['state'] = 'APPLYING'
    _persist_receipt(workspace, receipt)
    try:
        for relative, raw, before, record in plan:
            destination = _beneath(workspace, relative)
            current = _read_file(destination) if destination.exists() else None
            if current != before:
                raise ReleaseError('destination_changed_after_preflight', relative)
            if current != raw:
                if current is not None:
                    backup = _beneath(workspace, '_registry/fames-runtime-backups/' + release + '/' + relative)
                    if backup.exists():
                        if _read_file(backup) != current:
                            raise ReleaseError('backup_identity_conflict', relative)
                    else:
                        _write_new(backup, current)
                    record['backup_path'] = backup.relative_to(workspace).as_posix()
                    record['backup_sha256'] = _sha(_read_file(backup))
                stage = _beneath(workspace, '_registry/fames-runtime-staging/' + release + '/' + receipt['attempt_id'] + '/' + relative)
                _write_new(stage, raw)
                destination = _beneath(workspace, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if (_read_file(destination) if destination.exists() else None) != before:
                    raise ReleaseError('destination_changed_before_replace', relative)
                os.replace(stage, destination)
            actual = _sha(_read_file(_beneath(workspace, relative)))
            record['installed_sha256'] = actual
            if actual != record['source_sha256']:
                raise ReleaseError('destination_readback_mismatch', relative)
        for record in receipt['files']:
            if _sha(_read_file(_beneath(workspace, record['path']))) != record['source_sha256']:
                raise ReleaseError('final_destination_drift', record['path'])
        receipt.update(ok=True, state='INSTALLED', installed_manifest=manifest,
                       installed_release_sha256=release)
    except Exception as exc:
        receipt.update(ok=False, state='UNKNOWN_PARTIAL_APPLY')
        receipt['errors'].append(_error(exc))
    try:
        _persist_receipt(workspace, receipt)
    except Exception as exc:
        receipt.update(ok=False, state='UNKNOWN_RECEIPT_PERSISTENCE')
        receipt['errors'].append(_error(exc))
    return receipt


def apply(workspace, package_root) -> dict:
    """Preflight all paths, retain backups, replace/read back per file, never restart."""
    try:
        workspace, package = _root(workspace), _root(package_root)
        checked = verify(package)
        if not checked['ok']:
            return checked
        lock = _beneath(workspace, '_registry/fames-runtime-release.lock')
        with _apply_lock(lock):
            return _apply(workspace, package, checked)
    except Exception as exc:
        state = 'UNKNOWN_ROLLBACK' if isinstance(exc, ReleaseError) and exc.code == 'rollback_or_same_generation_fork' else 'UNKNOWN_APPLY'
        return _error(exc, state)
