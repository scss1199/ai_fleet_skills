"""Runtime release tests; all fixture trees are retained for operator inspection.

No tempfile/TmpPath cleanup, no live workspace installs, no secret readers,
network calls, background services or global Git configuration changes.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

import pytest

SOURCE = Path(__file__).with_name('runtime_release.py')
spec = importlib.util.spec_from_file_location('runtime_release_under_test', SOURCE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
EVIDENCE = Path('C:/ai_workspace/ai_darkhero/evidence/fames-fleet-20260924/runtime-release-tests') if os.name == 'nt' else Path.cwd() / '.retained-runtime-release-tests'
PATH_A = '_harness/runtime/a.py'
PATH_B = '_lean/fames/Phase.lean'


@pytest.fixture
def lab():
    root = EVIDENCE / uuid.uuid4().hex
    source, package, target = (root / name for name in ('source', 'package', 'target'))
    for directory in (source, package, target):
        directory.mkdir(parents=True)
    put(source, PATH_A, b'old_a = 1\n')
    put(source, PATH_B, b'theorem simple : True := by trivial\n')
    return root, source, package, target


def put(root, relative, raw):
    path = root.joinpath(*relative.split('/'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def build(lab, paths=(PATH_A, PATH_B)):
    result = release.build(lab[1], lab[2], list(paths))
    assert result['ok'], result
    return result


def manifest(package):
    return json.loads((package / 'runtime/manifest.json').read_bytes())


def rewrite_manifest(package, doc):
    payload = {key: doc[key] for key in ('schema', 'kind', 'generation', 'files')}
    doc['release_sha256'] = release._sha(release._json_bytes(payload))
    (package / 'runtime/manifest.json').write_bytes(release._json_bytes(doc))


def test_explicit_build_verify_apply_and_idempotence(lab):
    _, source, package, target = lab
    built = build(lab)
    checked = release.verify(package)
    assert checked['ok'] and checked['release_sha256'] == built['release_sha256']
    result = release.apply(target, package)
    assert result['ok'] and result['state'] == 'INSTALLED'
    assert result['native_activation'] == 'UNKNOWN' and result['atomicity'] == 'PER_FILE_ONLY'
    assert result['installed_manifest'] == checked['manifest']
    for relative in (PATH_A, PATH_B):
        assert (target / relative).read_bytes() == (source / relative).read_bytes()
    repeated = release.apply(target, package)
    assert repeated['ok']
    assert all(row['baseline_kind'] == 'already_new_hash' for row in repeated['files'])
    assert release.build(source, package, [PATH_B, PATH_A])['state'] == 'UNCHANGED'


@pytest.mark.parametrize('path', ['../outside.py', '/absolute.py', 'C:/outside.py', 'safe/../outside.py',
                                 'safe\\outside.py', 'a//b.py', './a.py', 'a/CON.py', 'a/name. ',
                                 '_secrets/key.py', '.env', '_harness/configs/config.json',
                                 '_harness/runtime/settings.json', '.codex/config.toml',
                                 '_harness/runtime/token.pem'])
def test_build_rejects_unsafe_or_sensitive_paths(lab, path):
    result = release.build(lab[1], lab[2], [path])
    assert not result['ok'] and not (lab[2] / 'runtime').exists()


def test_missing_source_and_string_allowlist_fail_closed(lab):
    assert not release.build(lab[1], lab[2], ['_harness/runtime/missing.py'])['ok']
    assert not release.build(lab[1], lab[2], PATH_A)['ok']
    assert not release.build(lab[1], lab[2], [])['ok']


def test_case_colliding_source_paths_fail_closed(lab):
    assert not release.build(lab[1], lab[2], [PATH_A, PATH_A.upper()])['ok']


@pytest.mark.parametrize('mutation', ['content', 'missing', 'extra', 'manifest_hash', 'traversal'])
def test_corrupt_or_incomplete_package_fails_before_destination_write(lab, mutation):
    _, _, package, target = lab
    build(lab)
    if mutation == 'content':
        (package / 'runtime/files' / PATH_A).write_bytes(b'corruption')
    elif mutation == 'missing':
        # Retain the bytes; moving out of the declared tree simulates a missing file.
        (package / 'runtime/files' / PATH_A).rename(package / 'retained-missing-file.py')
    elif mutation == 'extra':
        put(package / 'runtime/files', '_harness/runtime/extra.py', b'extra')
    elif mutation == 'manifest_hash':
        doc = manifest(package)
        doc['release_sha256'] = '0' * 64
        (package / 'runtime/manifest.json').write_text(json.dumps(doc))
    else:
        doc = manifest(package)
        doc['files']['../escape.py'] = doc['files'].pop(PATH_A)
        rewrite_manifest(package, doc)
    assert not release.verify(package)['ok']
    assert not release.apply(target, package)['ok']
    assert not (target / PATH_A).exists()
    assert not (target / '_registry/fames-runtime-release.json').exists()


def test_existing_unmanaged_changes_block_whole_preflight(lab):
    _, _, package, target = lab
    build(lab)
    original = put(target, PATH_B, b'local custom theorem\n')
    result = release.apply(target, package)
    assert result['state'] == 'UNKNOWN_LOCAL_CHANGES'
    assert original.read_bytes() == b'local custom theorem\n'
    assert not (target / PATH_A).exists()


def test_managed_update_retains_exact_backups_and_build_tree(lab):
    _, source, package, target = lab
    first = build(lab)
    assert release.apply(target, package)['ok']
    old = (target / PATH_A).read_bytes()
    put(source, PATH_A, b'new_a = 2\n')
    second = build(lab)
    assert second['generation'] == first['generation'] + 1
    assert Path(second['retained_backup']).is_dir()
    result = release.apply(target, package)
    assert result['ok']
    row = next(row for row in result['files'] if row['path'] == PATH_A)
    assert row['baseline_kind'] == 'previous_installed_manifest'
    assert (target / row['backup_path']).read_bytes() == old
    assert row['backup_sha256'] == hashlib.sha256(old).hexdigest()


def test_changed_managed_file_is_never_overwritten(lab):
    _, source, package, target = lab
    build(lab)
    assert release.apply(target, package)['ok']
    put(target, PATH_A, b'operator customization\n')
    put(source, PATH_A, b'new release\n')
    build(lab)
    result = release.apply(target, package)
    assert result['state'] == 'UNKNOWN_LOCAL_CHANGES'
    assert (target / PATH_A).read_bytes() == b'operator customization\n'


def test_rollback_and_same_generation_fork_fail_closed(lab):
    root, source, package, target = lab
    first = build(lab)
    old_package = root / 'preserved-old-package'
    shutil.copytree(package, old_package)
    assert release.apply(target, package)['ok']
    put(source, PATH_A, b'new revision\n')
    build(lab)
    assert release.apply(target, package)['ok']
    assert release.apply(target, old_package)['state'] == 'UNKNOWN_ROLLBACK'
    assert (target / PATH_A).read_bytes() == b'new revision\n'
    fork = root / 'retained-fork'
    shutil.copytree(package, fork)
    doc = manifest(fork)
    raw = b'different same-generation content\n'
    (fork / 'runtime/files' / PATH_A).write_bytes(raw)
    doc['files'][PATH_A] = {'sha256': release._sha(raw), 'bytes': len(raw)}
    rewrite_manifest(fork, doc)
    assert release.verify(fork)['ok']
    assert release.apply(target, fork)['state'] == 'UNKNOWN_ROLLBACK'
    assert first['generation'] == 1


def test_partial_replace_failure_preserves_recoverability_and_retries(lab, monkeypatch):
    _, source, package, target = lab
    build(lab)
    assert release.apply(target, package)['ok']
    old_a = (target / PATH_A).read_bytes()
    old_b = (target / PATH_B).read_bytes()
    put(source, PATH_A, b'revision 2 a\n')
    put(source, PATH_B, b'revision 2 b\n')
    build(lab)
    real_replace = release.os.replace
    def interrupted(src, dst):
        if Path(dst) == target / PATH_B:
            raise OSError('synthetic second-file failure')
        return real_replace(src, dst)
    monkeypatch.setattr(release.os, 'replace', interrupted)
    result = release.apply(target, package)
    assert result['state'] == 'UNKNOWN_PARTIAL_APPLY' and not result['ok']
    assert (target / PATH_A).read_bytes() == b'revision 2 a\n'
    assert (target / PATH_B).read_bytes() == old_b
    backup_root = target / '_registry/fames-runtime-backups' / result['attempted_release_sha256']
    assert (backup_root / PATH_A).read_bytes() == old_a
    assert (backup_root / PATH_B).read_bytes() == old_b
    persisted = json.loads((target / '_registry/fames-runtime-release.json').read_bytes())
    assert persisted['state'] == 'UNKNOWN_PARTIAL_APPLY'
    monkeypatch.setattr(release.os, 'replace', real_replace)
    assert release.apply(target, package)['ok']


def test_source_drift_during_build_keeps_previous_release(lab, monkeypatch):
    _, source, package, _ = lab
    first = build(lab)
    put(source, PATH_A, b'revision 2\n')
    real_verify = release._verify_runtime
    def changing(stage):
        result = real_verify(stage)
        if 'runtime.stage-' in stage.name:
            put(source, PATH_A, b'concurrent edit\n')
        return result
    monkeypatch.setattr(release, '_verify_runtime', changing)
    result = release.build(source, package, [PATH_A, PATH_B])
    assert not result['ok'] and result['error'] == 'source_changed_during_build'
    assert manifest(package)['release_sha256'] == first['release_sha256']
    assert Path(result['retained_stage']).is_dir()


def test_bad_previous_receipt_is_preserved(lab):
    _, _, package, target = lab
    build(lab)
    receipt = put(target, '_registry/fames-runtime-release.json', b'{truncated')
    assert not release.apply(target, package)['ok']
    assert receipt.read_bytes() == b'{truncated'
    assert not (target / PATH_A).exists()


def test_destination_race_after_preflight_is_preserved(lab, monkeypatch):
    _, _, package, target = lab
    build(lab)
    real_persist = release._persist_receipt
    def racing(workspace, receipt):
        real_persist(workspace, receipt)
        if receipt['state'] == 'APPLYING':
            put(target, PATH_A, b'concurrent operator file\n')
    monkeypatch.setattr(release, '_persist_receipt', racing)
    result = release.apply(target, package)
    assert result['state'] == 'UNKNOWN_PARTIAL_APPLY'
    assert (target / PATH_A).read_bytes() == b'concurrent operator file\n'


@pytest.mark.parametrize('where', ['source', 'package', 'destination'])
def test_symlink_paths_fail_closed(lab, monkeypatch, where):
    _, source, package, target = lab
    if where != 'source':
        build(lab)
    guarded = (source / PATH_A) if where == 'source' else (package / 'runtime/files' / PATH_A) if where == 'package' else target / '_harness'
    real = release._is_link
    monkeypatch.setattr(release, '_is_link', lambda path: path == guarded or real(path))
    if where == 'source':
        result = release.build(source, package, [PATH_A])
    elif where == 'package':
        result = release.verify(package)
    else:
        result = release.apply(target, package)
    assert not result['ok'] and result['error'] == 'symlink_or_junction_path'


def git(repo, *args):
    result = subprocess.run(['git', '-c', 'user.name=Runtime Release Test',
                             '-c', 'user.email=runtime-release-test@invalid.local',
                             '-c', 'core.autocrlf=false', '-C', str(repo), *args],
                            capture_output=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    return result.stdout


@pytest.mark.parametrize('dirty', [None, 'worktree', 'index', 'untracked'])
def test_first_install_git_baseline_accepts_only_clean_tracked_file(lab, dirty):
    _, _, package, target = lab
    build(lab, [PATH_A])
    put(target, PATH_A, b'old tracked implementation\n')
    git(target, 'init', '-q')
    if dirty != 'untracked':
        git(target, 'add', '--', PATH_A)
        git(target, 'commit', '-q', '-m', 'Synthetic baseline')
    if dirty in ('worktree', 'index'):
        put(target, PATH_A, b'local modified implementation\n')
        if dirty == 'index':
            git(target, 'add', '--', PATH_A)
    before = (target / PATH_A).read_bytes()
    result = release.apply(target, package)
    if dirty is None:
        assert result['ok'], result
        row = result['files'][0]
        assert row['baseline_kind'] == 'clean_tracked_git_HEAD'
        assert len(row['commit']) == 40 and len(row['blob_hash']) == 40
        assert (target / row['backup_path']).read_bytes() == before
    else:
        assert result['state'] == 'UNKNOWN_LOCAL_CHANGES'
        assert (target / PATH_A).read_bytes() == before


def test_already_new_hash_initializes_management_without_git(lab):
    _, source, package, target = lab
    build(lab, [PATH_A])
    put(target, PATH_A, (source / PATH_A).read_bytes())
    result = release.apply(target, package)
    assert result['ok'] and result['files'][0]['baseline_kind'] == 'already_new_hash'


@pytest.mark.parametrize('mode', ['autocrlf', 'text_eol', 'disabled', 'binary', 'modified', 'staged'])
def test_first_git_migration_allows_only_declared_clean_crlf(lab, mode):
    _, _, package, target = lab
    build(lab, [PATH_A])
    baseline = b'old tracked implementation\n'
    put(target, PATH_A, baseline)
    git(target, 'init', '-q')
    git(target, 'config', 'core.autocrlf', 'true' if mode != 'disabled' else 'false')
    if mode == 'text_eol':
        put(target, '.gitattributes', b'*.py text eol=crlf\n')
    elif mode == 'binary':
        put(target, '.gitattributes', b'*.py -text\n')
    git(target, 'add', '--', PATH_A)
    git(target, 'commit', '-q', '-m', 'Synthetic LF baseline')
    if mode == 'staged':
        put(target, PATH_A, b'changed staged baseline\n')
        git(target, 'add', '--', PATH_A)
    before = baseline.replace(b'\n', b'\r\n')
    if mode == 'modified':
        before += b'local edit\r\n'
    put(target, PATH_A, before)
    result = release.apply(target, package)
    if mode in ('autocrlf', 'text_eol'):
        assert result['ok'], result
        row = result['files'][0]
        assert row['worktree_conversion'] == 'declared_crlf_to_lf'
        assert row['worktree_sha256'] == hashlib.sha256(before).hexdigest()
        assert (target / row['backup_path']).read_bytes() == before
    else:
        assert result['state'] == 'UNKNOWN_LOCAL_CHANGES', result
        assert (target / PATH_A).read_bytes() == before


@pytest.mark.parametrize('attribute', ['filter=untrusted', 'working-tree-encoding=UTF-8'])
def test_git_baseline_rejects_conversion_filters_before_diff(lab, monkeypatch, attribute):
    _, _, package, target = lab
    build(lab, [PATH_A])
    put(target, PATH_A, b'old tracked implementation\n')
    git(target, 'init', '-q')
    git(target, 'add', '--', PATH_A)
    git(target, 'commit', '-q', '-m', 'Synthetic baseline')
    put(target, '.gitattributes', ('*.py ' + attribute + '\n').encode())
    original = release._git
    calls = []
    def watched(cwd, *args):
        calls.append(args[0])
        return original(cwd, *args)
    monkeypatch.setattr(release, '_git', watched)
    result = release.apply(target, package)
    assert result['state'] == 'UNKNOWN_LOCAL_CHANGES'
    assert 'diff' not in calls and 'hash-object' not in calls


@pytest.mark.parametrize('where', ['source', 'package', 'destination'])
def test_real_link_escape_is_rejected_and_outside_bytes_remain(lab, where):
    root, source, package, target = lab
    outside = root / 'retained-outside'
    put(outside, 'runtime/a.py', b'outside must remain\n')
    if where != 'source':
        build(lab)
    if where == 'source':
        base = source
    elif where == 'package':
        base = package / 'runtime/files'
    else:
        base = target
    link = base / '_harness'
    if link.exists():
        link.rename(root / ('retained-original-' + where))
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str(outside), str(link))
    else:
        link.symlink_to(outside, target_is_directory=True)
    if where == 'source':
        result = release.build(source, package, [PATH_A])
    elif where == 'package':
        result = release.verify(package)
    else:
        result = release.apply(target, package)
    assert not result['ok'] and result['error'] == 'symlink_or_junction_path'
    assert (outside / 'runtime/a.py').read_bytes() == b'outside must remain\n'


def test_conflicting_existing_backup_is_preserved(lab):
    _, source, package, target = lab
    build(lab)
    assert release.apply(target, package)['ok']
    old = (target / PATH_A).read_bytes()
    put(source, PATH_A, b'new revision\n')
    built = build(lab)
    backup = put(target, '_registry/fames-runtime-backups/' + built['release_sha256'] + '/' + PATH_A,
                 b'preexisting backup is immutable\n')
    result = release.apply(target, package)
    assert result['state'] == 'UNKNOWN_PARTIAL_APPLY'
    assert (target / PATH_A).read_bytes() == old
    assert backup.read_bytes() == b'preexisting backup is immutable\n'


def test_failed_new_release_preflight_does_not_forbid_current_release(lab):
    root, source, package, target = lab
    build(lab)
    old_package = root / 'retained-current-package'
    shutil.copytree(package, old_package)
    assert release.apply(target, package)['ok']
    put(source, '_harness/runtime/new.py', b'new source\n')
    put(target, '_harness/runtime/new.py', b'local unrelated file\n')
    build(lab, [PATH_A, PATH_B, '_harness/runtime/new.py'])
    assert release.apply(target, package)['state'] == 'UNKNOWN_LOCAL_CHANGES'
    assert release.apply(target, old_package)['ok']
    assert (target / '_harness/runtime/new.py').read_bytes() == b'local unrelated file\n'


def test_failure_persisting_final_receipt_never_returns_success(lab, monkeypatch):
    _, _, package, target = lab
    build(lab)
    original = release._persist_receipt
    def failing(workspace, receipt):
        if receipt['state'] == 'INSTALLED':
            raise OSError('synthetic receipt fault')
        return original(workspace, receipt)
    monkeypatch.setattr(release, '_persist_receipt', failing)
    result = release.apply(target, package)
    assert not result['ok'] and result['state'] == 'UNKNOWN_RECEIPT_PERSISTENCE'
    pending = json.loads((target / '_registry/fames-runtime-release.json').read_bytes())
    assert pending['state'] == 'APPLYING' and pending['ok'] is False
    monkeypatch.setattr(release, '_persist_receipt', original)
    assert release.apply(target, package)['ok']


def test_final_readback_detects_first_file_drift(lab, monkeypatch):
    _, _, package, target = lab
    build(lab)
    original = release.os.replace
    def drifting(src, dst):
        result = original(src, dst)
        if Path(dst) == target / PATH_B:
            put(target, PATH_A, b'changed after initial readback\n')
        return result
    monkeypatch.setattr(release.os, 'replace', drifting)
    result = release.apply(target, package)
    assert result['state'] == 'UNKNOWN_PARTIAL_APPLY'
    assert not result['ok']
    assert any(error.get('error') == 'final_destination_drift' for error in result['errors'])
