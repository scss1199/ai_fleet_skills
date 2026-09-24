#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# token-class: ZT
"""mtm-fleet-skill-github.py — MTM fleet skill federation via GitHub.

ai_darkhero (darkhero) = upstream: canonical → ai_fleet_skills/contributors/darkhero/ → git push.
ai_scar3 (scar3)       = downstream: pull darkhero contributor → deploy → push contributors/scar3/.

SSOT: _registry/fleet-skill-github.json

  python mtm-fleet-skill-github.py doctor [--node ai_darkhero]
  python mtm-fleet-skill-github.py export [--node ai_darkhero]
  python mtm-fleet-skill-github.py push [--node ai_darkhero]
  python mtm-fleet-skill-github.py pull [--from ai_darkhero] [--node ai_scar3]
  python mtm-fleet-skill-github.py sync [--node NODE]
  python mtm-fleet-skill-github.py tick [--node NODE]
  python mtm-fleet-skill-github.py receipt [--json]   # package_contract.receipt_rule, fleet-wide

CITE: fleet-skill-sync.py · git_smart.py · fleet-skill-github.json
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENG = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENG)
from _paths import COMMON as HUB, REGISTRY  # noqa: E402
import _projects as proj  # noqa: E402

PROTO_PATH = os.path.join(REGISTRY, "fleet-skill-github.json")
REG_SKILLS = os.path.join(REGISTRY, "fleet-skills.json")
CANON = os.path.join(HUB, "_skill", "fleet-skills")
SKILL_EXTRAS = ("reference.md", "oauth-verify-ledger.md")
FLAGS = 0x08000000 if os.name == "nt" else 0
TEXT_SUFFIXES = {".json", ".md", ".py", ".ps1", ".txt", ".yaml", ".yml"}


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_proto() -> dict:
    return json.loads(Path(PROTO_PATH).read_text(encoding="utf-8-sig"))


def _state_path(proto: dict) -> str:
    rel = proto.get("state") or "_registry/fleet-skill-github-state.json"
    return rel if os.path.isabs(rel) else os.path.join(HUB, rel.replace("/", os.sep))


def _load_state(proto: dict) -> dict:
    p = _state_path(proto)
    if os.path.isfile(p):
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    return {"schema": 1, "nodes": {}}


def _save_state(proto: dict, state: dict) -> str:
    p = _state_path(proto)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    Path(p).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _sha16_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _sha256_file(path: str) -> str:
    return _sha256_bytes(Path(path).read_bytes(), path)


def _sha256_bytes(data: bytes, path: str) -> str:
    if Path(path).suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _sha16_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _detect_node(proto: dict, explicit: str | None) -> tuple[str, dict]:
    if explicit and explicit in proto.get("nodes", {}):
        return explicit, proto["nodes"][explicit]
    # Hostname before cwd. Which machine this is cannot change under us; which seat a
    # path belongs to can, and at the hub root it is ambiguous by construction -- more
    # than one seat declares hub_root ".", so whoami() there returns whichever the
    # project matrix happens to list first. Trusting that made this box answer to a
    # peer's name and install that peer's canon over its own.
    host = os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "")).lower()
    for name, node in proto.get("nodes", {}).items():
        identities = {
            str(value).lower()
            for value in (
                name,
                node.get("machine"),
                node.get("seat"),
                node.get("contributor_slug"),
                *(node.get("hostnames") or []),
            )
            if value
        }
        if host in identities:
            return name, node
    if os.path.normcase(os.path.realpath(os.getcwd())) != os.path.normcase(os.path.realpath(HUB)):
        seat, _ = proj.whoami(os.getcwd())
        if seat in proto.get("nodes", {}):
            return seat, proto["nodes"][seat]
    return proto.get("default_upstream", "ai_darkhero"), proto["nodes"][proto["default_upstream"]]


def _contributor_slug(node: dict) -> str:
    return str(node.get("contributor_slug") or node.get("machine") or "unknown")


def _shared_repo(proto: dict) -> dict:
    return proto.get("shared_repo") or {}


def _repo_root(node: dict, proto: dict | None = None) -> str:
    if proto is None:
        proto = _load_proto()
    shared = _shared_repo(proto)
    rel = node.get("repo_path") or shared.get("repo_path") or "_skill/ai_fleet_skills"
    if os.path.isabs(rel):
        return os.path.normpath(rel)
    hub_root = node.get("hub_root")
    if hub_root == ".":
        return os.path.normpath(os.path.join(HUB, rel))
    return os.path.normpath(os.path.join(HUB, rel))


def _export_root(node: dict, proto: dict | None = None) -> str:
    if proto is None:
        proto = _load_proto()
    layout = proto.get("layout") or "contributors/{contributor}"
    sub = layout.replace("{contributor}", _contributor_slug(node))
    return os.path.join(_repo_root(node, proto), sub.replace("/", os.sep))


def _export_rel(node: dict, proto: dict | None = None) -> str:
    if proto is None:
        proto = _load_proto()
    layout = proto.get("layout") or "contributors/{contributor}"
    return layout.replace("{contributor}", _contributor_slug(node)).replace("\\", "/")


def _canonical_root(node: dict) -> str:
    rel = node.get("canonical_source", "_skill/fleet-skills")
    if os.path.isabs(rel):
        return os.path.normpath(rel)
    hub_root = node.get("hub_root")
    base = _repo_root(node) if hub_root == "." else HUB
    return os.path.normpath(os.path.join(base, rel.replace("/", os.sep)))


def _pkg_generation(pkg_root: str) -> tuple[int, ...] | None:
    """Version tuple from a package's own bundle-manifest; None when absent/unreadable."""
    try:
        raw = Path(os.path.join(pkg_root, "bundle-manifest.json")).read_text(encoding="utf-8-sig")
        parts = [p for p in str(json.loads(raw).get("version") or "").split(".") if p != ""]
        return tuple(int(p) for p in parts) if parts else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _gen_text(gen: tuple[int, ...] | None) -> str:
    return ".".join(str(p) for p in gen) if gen else "unversioned"


def _regression_note(name: str, dest_dir: str, src_dir: str) -> str:
    """Non-empty when writing src over dest would move a package backwards.

    The destination is read from disk at write time, so the check holds even when
    the incoming copy is exactly what upstream publishes: a stale published
    generation must never overwrite a newer installed one.
    """
    dest_gen = _pkg_generation(dest_dir)
    if dest_gen is None:
        return ""
    src_gen = _pkg_generation(src_dir)
    if src_gen is None:
        return f"{name}: incoming copy is unversioned, installed {_gen_text(dest_gen)}"
    if src_gen < dest_gen:
        return f"{name}: refusing to regress {_gen_text(dest_gen)} to {_gen_text(src_gen)}"
    return ""


def _load_registry() -> dict:
    if os.path.isfile(REG_SKILLS):
        return json.loads(Path(REG_SKILLS).read_text(encoding="utf-8-sig"))
    return {"canonical": [], "required": []}


def _skill_names(reg: dict) -> list[str]:
    names: list[str] = []
    for c in reg.get("canonical") or []:
        n = c.get("name")
        if n and n not in names:
            names.append(n)
    return names


def _copy_skill(src_name: str, src_base: str, dest_base: str) -> dict:
    src_dir = os.path.join(src_base, src_name)
    dest_dir = os.path.join(dest_base, "skills", src_name)
    src_md = os.path.join(src_dir, "SKILL.md")
    if not os.path.isfile(src_md):
        return {"name": src_name, "ok": False, "error": "missing SKILL.md"}
    os.makedirs(dest_dir, exist_ok=True)
    copied: list[str] = []
    files: dict[str, str] = {}
    for walk_root, dirs, filenames in os.walk(src_dir):
        dirs[:] = sorted(d for d in dirs if d not in {"__pycache__", ".git"})
        for filename in sorted(filenames):
            if filename.endswith((".pyc", ".pyo")):
                continue
            source = os.path.join(walk_root, filename)
            rel = os.path.relpath(source, src_dir).replace("\\", "/")
            target = os.path.join(dest_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
            copied.append(rel)
            files[rel] = _sha256_file(target)
    package_sha = hashlib.sha256(
        json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    bundle_manifest = os.path.join(dest_dir, "bundle-manifest.json")
    if os.path.isfile(bundle_manifest):
        try:
            bundle = json.loads(Path(bundle_manifest).read_text(encoding="utf-8-sig"))
            for rel, expected_sha in (bundle.get("files") or {}).items():
                if files.get(rel) != expected_sha:
                    raise ValueError(f"bundle hash mismatch: {rel}")
            if bundle.get("package_sha"):
                package_sha = str(bundle["package_sha"])
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return {"name": src_name, "ok": False, "error": str(exc)}
    return {
        "name": src_name,
        "ok": True,
        "sha": _sha16_file(os.path.join(dest_dir, "SKILL.md")),
        "package_sha": package_sha,
        "files": files,
        "copied": copied,
    }


def _mirror_skill_dir(src_skill_dir: str, dest_skill_dir: str) -> bool:
    src_md = os.path.join(src_skill_dir, "SKILL.md")
    if not os.path.isfile(src_md):
        return False
    os.makedirs(dest_skill_dir, exist_ok=True)
    for walk_root, dirs, filenames in os.walk(src_skill_dir):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git"}]
        rel_dir = os.path.relpath(walk_root, src_skill_dir)
        out_dir = dest_skill_dir if rel_dir == "." else os.path.join(dest_skill_dir, rel_dir)
        os.makedirs(out_dir, exist_ok=True)
        for filename in filenames:
            if filename.endswith((".pyc", ".pyo")):
                continue
            shutil.copy2(os.path.join(walk_root, filename), os.path.join(out_dir, filename))
    return True


def _finalize_manifest(manifest: dict) -> str:
    payload = {k: v for k, v in manifest.items() if k != "manifest_sha"}
    manifest["manifest_sha"] = _sha16_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return json.dumps(manifest, ensure_ascii=False, indent=2)


def cmd_export(node_name: str, node: dict, *, quiet: bool = False) -> dict:
    proto = _load_proto()
    reg = _load_registry()
    canon = _canonical_root(node)
    export = _export_root(node)
    # A draft canonical edit must never escape through the periodic publisher.
    # Existing followers create the same local receipts during converge/apply.
    try:
        package = Path(canon) / "fames"
        spec = importlib.util.spec_from_file_location("fames_export_gate", package / "scripts/fames_fleet.py")
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        verified = gate.verify_package(package)
        adoption = gate._runtime_adoption(Path(HUB), package, verified.get("package_sha"))
        ready = (verified.get("ok") is True and adoption.get("runtime_state") == "PASS"
                 and adoption.get("phase_proof_state") == "PASS" and adoption.get("base_proof_state") == "PASS")
        if not ready or gate.run_cases(Path(HUB), package).get("ok") is not True:
            return {"ok": False, "state": "UNKNOWN", "reason": "fames_release_verification_incomplete", "node": node_name}
    except Exception as exc:
        return {"ok": False, "state": "UNKNOWN", "reason": "fames_release_gate:" + type(exc).__name__, "node": node_name}
    previous_manifest: dict = {}
    previous_manifest_path = os.path.join(export, "manifest.json")
    if os.path.isfile(previous_manifest_path):
        try:
            previous_manifest = json.loads(
                Path(previous_manifest_path).read_text(encoding="utf-8-sig")
            )
        except (OSError, json.JSONDecodeError):
            previous_manifest = {}
    skills_dir = os.path.join(export, "skills")
    keep = None
    if os.path.isdir(skills_dir):
        keep = Path(HUB) / "_registry/fleet-skill-export-backups" / uuid.uuid4().hex / "skills"
        keep.parent.mkdir(parents=True, exist_ok=True)
        Path(skills_dir).rename(keep)
    os.makedirs(skills_dir, exist_ok=True)

    rows = []
    manifest_skills = []
    for name in _skill_names(reg):
        row = _copy_skill(name, canon, export)
        rows.append(row)
        if row.get("ok"):
            meta = next((c for c in reg.get("canonical", []) if c.get("name") == name), {})
            manifest_skills.append(
                {
                    "name": name,
                    "sha": row["sha"],
                    "required": name in (reg.get("required") or []) or bool(meta.get("required")),
                    "lane": (meta.get("fleet") or {}).get("lane", ""),
                    "package_sha": row["package_sha"],
                    "files": row["files"],
                }
            )

    failures = [row.get("name") for row in rows if row.get("ok") is not True]
    if failures:
        # Keep the previous manifest and all backups. A failed copy must never
        # publish a manifest that silently drops the FAMES/required skill.
        return {"ok": False, "state": "UNKNOWN", "reason": "skill_copy_verification_failed",
                "failed_skills": failures, "retained_previous_skills": str(keep) if keep else None,
                "retained_failed_stage": skills_dir, "node": node_name}

    digest_path = os.path.join(HUB, "ai_darkhero", "public", "fleet-skills-digest.json")
    digest = {}
    if os.path.isfile(digest_path):
        digest = json.loads(Path(digest_path).read_text(encoding="utf-8-sig"))

    manifest = {
        "schema": 2,
        "authority": node_name,
        "contributor": _contributor_slug(node),
        "role": node.get("role"),
        "machine": node.get("machine"),
        "repo": node.get("repo") or _shared_repo(proto).get("repo"),
        "generated_at": _iso(),
        "manifest_sha": "",
        "required": list(reg.get("required") or []),
        "skill_count": len(manifest_skills),
        "skills": manifest_skills,
    }
    same_generation = (
        previous_manifest.get("schema") == manifest["schema"]
        and previous_manifest.get("skills") == manifest_skills
        and previous_manifest.get("required") == manifest["required"]
        and previous_manifest.get("generated_at")
    )
    if same_generation:
        manifest["generated_at"] = previous_manifest["generated_at"]
    body = _finalize_manifest(manifest)
    os.makedirs(export, exist_ok=True)
    Path(os.path.join(export, "manifest.json")).write_text(body, encoding="utf-8")
    digest_out = os.path.join(export, "digest.json")
    if not (same_generation and os.path.isfile(digest_out)):
        Path(digest_out).write_text(
            json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    readme = "\n".join(
        [
            f"# Contributor `{_contributor_slug(node)}`",
            "",
            f"- **Seat:** `{node_name}`",
            f"- **Machine:** `{node.get('machine')}`",
            f"- **Generated:** {manifest['generated_at']}",
            f"- **Skills:** {manifest['skill_count']}",
            f"- **Manifest SHA:** `{manifest['manifest_sha']}`",
            "",
            "Shared repo layout: `contributors/darkhero/` · `contributors/scar3/` · `contributors/altos/`",
            "",
        ]
    )
    Path(os.path.join(export, "README.md")).write_text(readme, encoding="utf-8")

    report = {
        "ok": True,
        "node": node_name,
        "contributor": _contributor_slug(node),
        "export_root": export,
        "skill_count": len([r for r in rows if r.get("ok")]),
        "manifest_sha": manifest["manifest_sha"],
    }
    if not quiet:
        print(json.dumps(report, ensure_ascii=False))
    return report


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=FLAGS,
    )


def _fast_forward(repo: str) -> tuple[bool, str]:
    """Join the latest shared branch before writing one contributor directory."""
    fetch = _git(["fetch", "origin"], repo)
    if fetch.returncode != 0:
        return False, ((fetch.stderr or fetch.stdout) or "fetch failed")[-500:]
    branch = _git(["branch", "--show-current"], repo).stdout.strip() or "main"
    remote = f"origin/{branch}"
    if _git(["rev-parse", "--verify", remote], repo).returncode != 0:
        remote = "origin/main"
    merge = _git(["merge", "--ff-only", remote], repo)
    if merge.returncode != 0:
        return False, ((merge.stderr or merge.stdout) or "fast-forward failed")[-500:]
    return True, remote


def _skills_fingerprint(manifest_or_exp: dict) -> str:
    """Content-stable fingerprint (ignore generated_at noise)."""
    skills = manifest_or_exp.get("skills")
    if skills is None and manifest_or_exp.get("manifest_sha"):
        # export report may not embed skills — fall back to manifest file
        return str(manifest_or_exp.get("manifest_sha") or "")
    return _sha16_text(json.dumps(skills or [], ensure_ascii=False, sort_keys=True))


def cmd_push(node_name: str, node: dict, *, quiet: bool = False) -> dict:
    proto = _load_proto()
    repo = _repo_root(node, proto)
    synced, remote = _fast_forward(repo)
    if not synced:
        out = {"ok": False, "node": node_name, "error": remote}
        if not quiet:
            print(json.dumps(out, ensure_ascii=False))
        return out
    exp = cmd_export(node_name, node, quiet=True)
    if exp.get("ok") is not True:
        if not quiet:
            print(json.dumps(exp, ensure_ascii=False))
        return exp
    slug = _contributor_slug(node)
    export_rel = _export_rel(node, proto)
    # Economy: skip git when skill content unchanged (timestamp-only export churn)
    state0 = _load_state(proto)
    prev_fp = (state0.get("nodes") or {}).get(node_name, {}).get("skills_fingerprint")
    mpath = os.path.join(_export_root(node, proto), "manifest.json")
    try:
        man = json.loads(Path(mpath).read_text(encoding="utf-8-sig"))
        fp = _skills_fingerprint(man)
    except (OSError, json.JSONDecodeError):
        fp = exp.get("manifest_sha") or ""
    if prev_fp and fp and prev_fp == fp:
        out = {
            "ok": True,
            "node": node_name,
            "pushed": False,
            "committed": False,
            "skipped": "skills_fingerprint_unchanged",
            "skills_fingerprint": fp,
            "manifest_sha": exp.get("manifest_sha"),
        }
        if not quiet:
            print(json.dumps(out, ensure_ascii=False))
        return out
    st = _git(["status", "--porcelain", export_rel], repo)
    dirty = [ln for ln in (st.stdout or "").splitlines() if ln.strip()]
    if not dirty:
        out = {"ok": True, "node": node_name, "pushed": False, "reason": "clean", **exp}
        if not quiet:
            print(json.dumps(out, ensure_ascii=False))
        return out

    _git(["add", export_rel], repo)
    msg = "chore(skills/%s): export manifest %s (%d skills)" % (
        slug,
        exp.get("manifest_sha", "?")[:12],
        exp.get("skill_count", 0),
    )
    c = _git(["commit", "--only", "-m", msg, "--", export_rel], repo)
    pushed = False
    git_tail: list[str] = []
    if c.returncode == 0:
        p = _git(["push"], repo)
        if p.returncode != 0 and "no upstream" in (p.stderr or "").lower():
            p = _git(["push", "-u", "origin", "HEAD"], repo)
        if p.returncode != 0 and any(
            marker in ((p.stderr or "") + (p.stdout or "")).lower()
            for marker in ("fetch first", "non-fast-forward", "rejected")
        ):
            _git(["fetch", "origin"], repo)
            rebase = _git(["rebase", remote], repo)
            if rebase.returncode == 0:
                p = _git(["push"], repo)
        pushed = p.returncode == 0
        git_tail = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-3:]
    elif "nothing to commit" in (c.stdout or "") + (c.stderr or ""):
        pushed = False
    else:
        git_tail = ((c.stdout or "") + (c.stderr or "")).strip().splitlines()[-3:]
    proto = _load_proto()
    state = _load_state(proto)
    previous_node_state = (state.setdefault("nodes", {}).get(node_name) or {}).copy()
    state["nodes"][node_name] = {
        **previous_node_state,
        "last_push": _iso(),
        "manifest_sha": exp.get("manifest_sha"),
        "skills_fingerprint": fp,
        "repo": node.get("repo"),
    }
    _save_state(proto, state)

    out = {
        "ok": pushed or not dirty or "nothing to commit" in ((c.stdout or "") + (c.stderr or "")),
        "node": node_name,
        "pushed": pushed,
        "committed": c.returncode == 0,
        "dirty_files": len(dirty),
        "manifest_sha": exp.get("manifest_sha"),
        "skills_fingerprint": fp,
        "git_tail": git_tail,
    }
    if c.returncode == 0 and not pushed:
        sq = os.path.join(ENG, "ship-queue.py")
        if os.path.isfile(sq):
            subprocess.run(
                [sys.executable, sq, "request", repo],
                capture_output=True,
                text=True,
                creationflags=FLAGS,
                timeout=30,
            )
            out["ship_queue"] = True
    if not quiet:
        print(json.dumps(out, ensure_ascii=False))
    return out


def _fetch_url(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mtm-fleet-skill-github/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _upstream_node(proto: dict, upstream_name: str | None) -> tuple[str, dict]:
    name = upstream_name or proto.get("default_upstream", "ai_darkhero")
    node = proto.get("nodes", {}).get(name)
    if not node:
        raise RuntimeError(f"unknown upstream node: {name}")
    return name, node


def _local_upstream_manifest(up_node: dict) -> dict | None:
    path = os.path.join(_export_root(up_node), "manifest.json")
    if os.path.isfile(path):
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return None


def _commit_addressed_source(up_node: dict) -> tuple[str, str]:
    """Resolve one immutable GitHub tree so manifest and files cannot split on raw-main cache."""
    proto = _load_proto()
    repo = str(up_node.get("repo") or "").rstrip("/")
    branch = str(up_node.get("default_branch") or "main")
    probe = _git(
        ["ls-remote", repo, f"refs/heads/{branch}"],
        _repo_root(up_node, proto),
    )
    if probe.returncode != 0 or not probe.stdout.strip():
        raise RuntimeError(
            "cannot resolve commit-addressed authority ref: "
            + ((probe.stderr or probe.stdout) or "empty ls-remote")[-300:]
        )
    commit = probe.stdout.split()[0]
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise RuntimeError(f"authority ref returned invalid commit: {commit!r}")
    raw = str(up_node.get("raw_base") or "").rstrip("/")
    marker = f"/{branch}/"
    if raw and marker in raw:
        base = raw.replace(marker, f"/{commit}/", 1)
    else:
        slug = repo.removesuffix(".git").replace("https://github.com/", "")
        base = (
            f"https://raw.githubusercontent.com/{slug}/{commit}/contributors/"
            f"{_contributor_slug(up_node)}"
        )
    return base, commit


def _remote_manifest_snapshot(up_node: dict) -> tuple[dict, str, str]:
    base, commit = _commit_addressed_source(up_node)
    url = f"{base}/manifest.json"
    try:
        return json.loads(_fetch_url(url).decode("utf-8-sig")), base, commit
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise RuntimeError(f"fetch manifest failed: {url} ({exc})") from exc


def _remote_manifest(up_node: dict) -> dict:
    manifest, _, _ = _remote_manifest_snapshot(up_node)
    return manifest


def _download_skill(base: str, name: str, skill: dict, dest_dir: str) -> None:
    files = skill.get("files")
    if isinstance(files, dict) and files:
        for rel, expected_sha in files.items():
            rel_path = Path(rel)
            if rel_path.is_absolute() or ".." in rel_path.parts:
                raise RuntimeError(f"unsafe package path: {name}/{rel}")
            url = f"{base}/skills/{name}/{rel}"
            data = _fetch_url(url)
            actual_sha = _sha256_bytes(data, rel)
            if actual_sha != expected_sha:
                raise RuntimeError(f"download hash mismatch: {name}/{rel}")
            target = os.path.join(dest_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            Path(target).write_bytes(data)
        return

    md_url = f"{base}/skills/{name}/SKILL.md"
    text = _fetch_url(md_url).decode("utf-8")
    Path(os.path.join(dest_dir, "SKILL.md")).write_text(text, encoding="utf-8")
    for extra in SKILL_EXTRAS:
        try:
            ex_url = f"{base}/skills/{name}/{extra}"
            ex_text = _fetch_url(ex_url).decode("utf-8")
            Path(os.path.join(dest_dir, extra)).write_text(ex_text, encoding="utf-8")
        except urllib.error.HTTPError:
            pass


def cmd_pull(
    node_name: str,
    node: dict,
    *,
    upstream_name: str | None = None,
    quiet: bool = False,
) -> dict:
    proto = _load_proto()
    up_name, up_node = _upstream_node(proto, upstream_name or node.get("upstream"))
    remote, source_base, source_commit = _remote_manifest_snapshot(up_node)
    state = _load_state(proto)
    prev_sha = (state.get("nodes", {}).get(node_name) or {}).get("last_pull_manifest_sha")
    remote_sha = remote.get("manifest_sha", "")
    local_upstream = _local_upstream_manifest(up_node)
    local_upstream_current = bool(
        local_upstream and local_upstream.get("manifest_sha") == remote_sha
    )

    canon = _canonical_root(node)
    os.makedirs(canon, exist_ok=True)
    export = _export_root(node)
    upstream_mirror = os.path.join(export, "upstream")
    os.makedirs(upstream_mirror, exist_ok=True)
    Path(os.path.join(upstream_mirror, "manifest.json")).write_text(
        json.dumps(remote, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    updated: list[str] = []
    skipped: list[str] = []
    errors: list[dict] = []

    local_reg = _load_registry()
    local_shas = {c["name"]: c.get("sha") for c in local_reg.get("canonical", []) if c.get("name")}

    for sk in remote.get("skills") or []:
        name = sk.get("name")
        rsha = sk.get("sha")
        if not name:
            continue
        if prev_sha == remote_sha and local_shas.get(name) == rsha:
            skipped.append(name)
            continue

        src_dir = os.path.join(_export_root(up_node), "skills", name)
        if local_upstream_current and os.path.isdir(src_dir):
            mirror_dir = os.path.join(upstream_mirror, "skills", name)
            if _mirror_skill_dir(src_dir, mirror_dir):
                canon_dir = os.path.join(canon, name)
                note = _regression_note(name, canon_dir, src_dir)
                if note:
                    errors.append({"name": name, "error": note})
                elif _mirror_skill_dir(src_dir, canon_dir):
                    updated.append(name)
                else:
                    errors.append({"name": name, "error": "canonical install failed"})
            else:
                errors.append({"name": name, "error": "upstream mirror failed"})
            continue

        dest_dir = os.path.join(canon, name)
        os.makedirs(dest_dir, exist_ok=True)
        # Stage first: the incoming generation is only knowable after the download,
        # so the destination is never touched until the direction check has run.
        staging = dest_dir + ".incoming"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            _download_skill(source_base, name, sk, staging)
            note = _regression_note(name, dest_dir, staging)
            if note:
                errors.append({"name": name, "error": note})
            elif _mirror_skill_dir(staging, dest_dir):
                updated.append(name)
            else:
                errors.append({"name": name, "error": "canonical install failed"})
        except (urllib.error.URLError, OSError, RuntimeError) as exc:
            errors.append({"name": name, "error": str(exc)})
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    deploy_rc = 0
    if updated:
        fss = os.path.join(ENG, "fleet-skill-sync.py")
        if os.path.isfile(fss):
            dr = subprocess.run(
                [sys.executable, fss, "registry"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=FLAGS,
                timeout=120,
            )
            deploy_rc = dr.returncode
            if node.get("role") == "downstream_curator":
                subprocess.run(
                    [sys.executable, fss, "deploy", "--seats-only"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=FLAGS,
                    timeout=300,
                )

    previous_node_state = (state.setdefault("nodes", {}).get(node_name) or {}).copy()
    state["nodes"][node_name] = {
        **previous_node_state,
        "last_pull": _iso(),
        "last_pull_manifest_sha": remote_sha,
        "upstream": up_name,
        "source_commit": source_commit,
        "updated": updated,
        "packages": {
            sk.get("name"): sk.get("package_sha")
            for sk in (remote.get("skills") or [])
            if sk.get("name") and sk.get("package_sha")
        },
    }
    _save_state(proto, state)

    out = {
        "ok": not errors,
        "node": node_name,
        "upstream": up_name,
        "remote_manifest_sha": remote_sha,
        "source_commit": source_commit,
        "prev_manifest_sha": prev_sha,
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "updated": updated,
        "errors": errors,
        "registry_rc": deploy_rc,
    }
    if not quiet:
        print(json.dumps(out, ensure_ascii=False))
    return out


def _run_fames_follow(node_name: str, node: dict) -> dict:
    """Run the portable FAMES transition; old followers may not have it yet."""
    script = os.path.join(_canonical_root(node), "fames", "scripts", "fames_fleet.py")
    if not os.path.isfile(script):
        return {"ok": False, "bootstrap_needed": True, "error": "FAMES follow script missing"}
    # A node whose canonical root is not the hub's own runs a *different copy* of this
    # script. Its install targets are hub junctions, so an older copy silently rewrites
    # hub canon with its own generation. The direction check therefore has to happen
    # here, in the caller: a guard shipped inside the package cannot defend against an
    # older edition of that same package being the thing executed.
    script_pkg = os.path.dirname(os.path.dirname(script))
    hub_pkg = os.path.join(CANON, "fames")
    if os.path.normcase(os.path.realpath(script_pkg)) != os.path.normcase(os.path.realpath(hub_pkg)):
        script_gen = _pkg_generation(script_pkg)
        hub_gen = _pkg_generation(hub_pkg)
        if hub_gen is not None and (script_gen is None or script_gen < hub_gen):
            return {
                "ok": False,
                "refused": "older_follow_script",
                "error": (
                    f"{node_name}: follow script is {_gen_text(script_gen)}, "
                    f"hub canon is {_gen_text(hub_gen)}"
                ),
                "script": script,
            }
    result = subprocess.run(
        [sys.executable, script, "follow", "--workspace", HUB, "--host", node_name, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=FLAGS,
        timeout=120,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"ok": False, "error": (result.stderr or result.stdout)[-500:]}
    payload["returncode"] = result.returncode
    return payload


def cmd_sync(node_name: str, node: dict, *, quiet: bool = False) -> dict:
    role = node.get("role", "")
    if role == "upstream_curator":
        return cmd_push(node_name, node, quiet=quiet)
    if role in {"downstream_curator", "downstream_follower"}:
        before = _run_fames_follow(node_name, node)
        pull = cmd_pull(node_name, node, quiet=quiet)
        # A legacy follower may learn the follow command only through the pull above.
        after = before if before.get("ok") else _run_fames_follow(node_name, node)
        publish = (
            cmd_push(node_name, node, quiet=True)
            if node.get("also_push_local")
            else {"ok": True, "skipped": "publication_disabled"}
        )
        out = {
            **pull,
            "ok": bool(pull.get("ok") and after.get("ok") and publish.get("ok")),
            "fames": after,
            "publish": publish,
        }
        if not quiet:
            print(json.dumps(out, ensure_ascii=False))
        return out
    out = {"ok": False, "error": f"unknown role: {role}"}
    if not quiet:
        print(json.dumps(out, ensure_ascii=False))
    return out


def _package_sha_of_dir(skill_dir: str) -> tuple[str | None, str]:
    """(package_sha, note) over a skill tree, identical to the rule used by _copy_skill.

    A bundle-manifest.json in the tree overrides the walked sha, but only after every
    hash it declares matches the file on disk — same order as _copy_skill.
    """
    if not os.path.isdir(skill_dir):
        return None, "missing canonical source"
    files: dict[str, str] = {}
    for walk_root, dirs, filenames in os.walk(skill_dir):
        dirs[:] = sorted(d for d in dirs if d not in {"__pycache__", ".git"})
        for filename in sorted(filenames):
            if filename.endswith((".pyc", ".pyo")):
                continue
            source = os.path.join(walk_root, filename)
            rel = os.path.relpath(source, skill_dir).replace("\\", "/")
            files[rel] = _sha256_file(source)
    if not files:
        return None, "empty canonical source"
    package_sha = hashlib.sha256(
        json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    bundle_manifest = os.path.join(skill_dir, "bundle-manifest.json")
    if os.path.isfile(bundle_manifest):
        try:
            bundle = json.loads(Path(bundle_manifest).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"unreadable bundle-manifest: {exc}"
        for rel, expected_sha in (bundle.get("files") or {}).items():
            if files.get(rel) != expected_sha:
                return None, f"bundle hash mismatch: {rel}"
        if bundle.get("package_sha"):
            return str(bundle["package_sha"]), "bundle-manifest"
    return package_sha, "walked"


def _manifest_package_sha(node: dict, proto: dict, skill: str) -> tuple[str | None, str]:
    """(package_sha, reason) for one node's contributor manifest row."""
    manifest_path = os.path.join(_export_root(node, proto), "manifest.json")
    if not os.path.isfile(manifest_path):
        return None, "missing node manifest"
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return None, f"unreadable manifest: {exc}"
    for row in manifest.get("skills") or []:
        if row.get("name") == skill:
            sha = row.get("package_sha")
            return (sha, "") if sha else (None, f"{skill} row carries no package_sha")
    return None, f"missing {skill} row"


def _remote_package_sha(node: dict, skill: str) -> tuple[str | None, str]:
    try:
        manifest = _remote_manifest(node)
    except RuntimeError as exc:
        return None, str(exc)
    for row in manifest.get("skills") or []:
        if row.get("name") == skill:
            sha = row.get("package_sha")
            return (sha, "") if sha else (None, f"{skill} row carries no package_sha")
    return None, f"missing {skill} row"


def cmd_receipt(proto: dict, *, as_json: bool = False) -> int:
    """Mechanise package_contract.receipt_rule: PASS only on upstream package_sha."""
    contract = proto.get("package_contract") or {}
    skill = contract.get("required_portable_skill") or "fames"
    upstream_name = proto.get("default_upstream", "ai_darkhero")
    nodes = proto.get("nodes") or {}
    upstream = nodes.get(upstream_name)
    if not upstream:
        print(json.dumps({"ok": False, "error": f"default_upstream {upstream_name} not declared"},
                         ensure_ascii=False))
        return 1

    expected, expected_reason = _remote_package_sha(upstream, skill)
    source_sha, source_note = _package_sha_of_dir(os.path.join(_canonical_root(upstream), skill))
    # unknown_rule: a source manifest that no longer matches live canon is stale.
    source_state = "ok"
    if source_sha is None:
        source_state = source_note
    elif expected and source_sha != expected:
        source_state = "stale source manifest"

    rows = []
    for name, node in nodes.items():
        sha, reason = _remote_package_sha(node, skill)
        if expected is None:
            verdict, why = "UNKNOWN", expected_reason or "upstream package_sha unavailable"
        elif source_state != "ok":
            verdict, why = "UNKNOWN", source_state
        elif sha is None:
            verdict, why = "UNKNOWN", reason
        elif sha != expected:
            verdict, why = "UNKNOWN", "package_sha mismatch"
        else:
            verdict, why = "PASS", ""
        rows.append({
            "node": name,
            "contributor": _contributor_slug(node),
            "role": node.get("role"),
            "package_sha": sha,
            "verdict": verdict,
            "reason": why,
        })

    ok = bool(rows) and all(r["verdict"] == "PASS" for r in rows)
    out = {
        "ok": ok,
        "skill": skill,
        "upstream": upstream_name,
        "expected_package_sha": expected,
        "source_package_sha": source_sha,
        "source_state": source_state,
        "source_sha_from": source_note,
        "declared_nodes": len(rows),
        "nodes": rows,
        "rule": contract.get("receipt_rule"),
    }
    if as_json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"receipt {skill} · upstream {upstream_name} · source {source_state}")
        print(f"expected package_sha: {expected}")
        for r in rows:
            tail = f"  ({r['reason']})" if r["reason"] else ""
            print(f"  {r['verdict']:8} {r['node']:12} {r['package_sha'] or '-'}{tail}")
        print(f"ok={ok} ({sum(1 for r in rows if r['verdict'] == 'PASS')}/{len(rows)} PASS)")
    return 0 if ok else 1


def cmd_doctor(node_name: str, node: dict) -> int:
    proto = _load_proto()
    reg = _load_registry()
    print(json.dumps({
        "node": node_name,
        "contributor": _contributor_slug(node),
        "role": node.get("role"),
        "machine": node.get("machine"),
        "repo_root": _repo_root(node, proto),
        "export_root": _export_root(node, proto),
        "export_rel": _export_rel(node, proto),
        "canonical_root": _canonical_root(node),
        "canonical_skills": len(_skill_names(reg)),
        "upstream": node.get("upstream"),
        "repo_remote": node.get("repo") or _shared_repo(proto).get("repo"),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_tick(node_name: str, node: dict) -> int:
    out = cmd_sync(node_name, node, quiet=True)
    brief = {
        "ok": out.get("ok", False),
        "node": node_name,
        "role": node.get("role"),
        "action": "push" if node.get("role") == "upstream_curator" else "follow-pull-publish",
        "pushed": out.get("pushed"),
        "committed": out.get("committed"),
        "skipped": out.get("skipped") or out.get("reason"),
        "updated_count": out.get("updated_count", 0),
        "manifest_sha": out.get("manifest_sha") or out.get("remote_manifest_sha"),
        "skills_fingerprint": out.get("skills_fingerprint"),
    }
    print(json.dumps(brief, ensure_ascii=False))
    return 0 if brief["ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="MTM fleet skill GitHub federation")
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--node", help="ai_darkhero | ai_scar3")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", parents=[parent])
    sub.add_parser("export", parents=[parent])
    sub.add_parser("push", parents=[parent])
    p_pull = sub.add_parser("pull", parents=[parent])
    p_pull.add_argument("--from", dest="upstream", default=None, help="upstream node id")
    sub.add_parser("sync", parents=[parent])
    sub.add_parser("tick", parents=[parent])
    p_receipt = sub.add_parser("receipt", parents=[parent])
    p_receipt.add_argument("--json", dest="as_json", action="store_true")

    args = ap.parse_args()
    proto = _load_proto()
    # receipt judges every declared node, so it must not depend on local detection.
    if args.cmd == "receipt":
        return cmd_receipt(proto, as_json=args.as_json)
    node_name, node = _detect_node(proto, args.node)

    if args.cmd == "doctor":
        return cmd_doctor(node_name, node)
    if args.cmd == "export":
        return 0 if cmd_export(node_name, node).get("ok") else 1
    if args.cmd == "push":
        return 0 if cmd_push(node_name, node).get("ok") else 1
    if args.cmd == "pull":
        return 0 if cmd_pull(node_name, node, upstream_name=args.upstream).get("ok") else 1
    if args.cmd == "sync":
        return 0 if cmd_sync(node_name, node).get("ok") else 1
    if args.cmd == "tick":
        return cmd_tick(node_name, node)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
