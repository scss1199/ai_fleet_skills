#!/usr/bin/env python3
"""Install an official Lean 4 release under C:/ai_workspace/_lean.

No elan, no PATH edit, no environment variable change: the toolchain is a plain directory
and every caller reaches it through leanctl.py or an absolute path.

Steps (each one is detected and skipped when already done, so the script is re-runnable):
  1. read the release asset (name, size, sha256 digest) from the GitHub API
  2. download the Windows zip into downloads/ (resumes a partial file)
  3. verify sha256 against the digest GitHub publishes for that asset -- fail closed
  4. extract into toolchains/<name>/ through a .partial staging directory
  5. probe lean/lake --version and record state/install.json + state/current.json

No model calls, no visible windows, nothing is deleted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_VERSION = "v4.34.0"
RELEASE_API = "https://api.github.com/repos/leanprover/lean4/releases/tags/{tag}"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def log(msg: str) -> None:
    print(f"[install_lean] {msg}", flush=True)


def asset_name(tag: str) -> str:
    return f"lean-{tag.lstrip('v')}-windows.zip"


def release_asset(tag: str) -> dict:
    req = urllib.request.Request(
        RELEASE_API.format(tag=tag),
        headers={"Accept": "application/vnd.github+json", "User-Agent": "hub-lean-installer"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        release = json.load(resp)
    wanted = asset_name(tag)
    for asset in release.get("assets", []):
        if asset.get("name") == wanted:
            digest = str(asset.get("digest") or "")
            return {
                "tag": release.get("tag_name"),
                "name": wanted,
                "url": asset["browser_download_url"],
                "size": int(asset["size"]),
                "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
                "published_at": release.get("published_at"),
            }
    raise SystemExit(f"asset {wanted} not found in release {tag}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, size: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size == size:
        log(f"download: already complete ({size} bytes)")
        return
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise SystemExit("curl not found; it ships with Windows 10+ in System32")
    have = dest.stat().st_size if dest.is_file() else 0
    log(f"download: {url} -> {dest} (have {have} of {size} bytes)")
    cmd = [curl, "-L", "--fail", "--silent", "--show-error", "--retry", "8", "--retry-delay", "5",
           "--retry-all-errors", "-C", "-", "-o", str(dest), url]
    rc = subprocess.run(cmd, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    got = dest.stat().st_size if dest.is_file() else 0
    if rc != 0 or got != size:
        raise SystemExit(f"download incomplete: curl rc={rc}, {got} of {size} bytes (re-run to resume)")


def extract(zip_path: Path, final: Path) -> int:
    """Extract the release zip, dropping its single top-level folder, into `final`."""
    if (final / "bin" / "lean.exe").is_file():
        log(f"extract: {final} already present")
        return 0
    staging = final.with_name(final.name + ".partial")
    staging.mkdir(parents=True, exist_ok=True)
    base = staging.resolve()
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            parts = Path(info.filename).parts
            if len(parts) < 2:          # the top-level folder entry itself
                continue
            target = (staging.joinpath(*parts[1:])).resolve()
            if base not in target.parents and target != base:
                raise SystemExit(f"unsafe path in archive: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            count += 1
    os.replace(staging, final)
    log(f"extract: {count} files -> {final}")
    return count


def probe(exe: Path) -> str:
    out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=120,
                         stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    if out.returncode != 0:
        raise SystemExit(f"{exe.name} --version failed rc={out.returncode}: {out.stderr.strip()[:400]}")
    return out.stdout.strip()


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", default=DEFAULT_VERSION, help="Lean release tag, e.g. v4.34.0")
    ap.add_argument("--sha256", default="", help="expected zip sha256 (overrides the GitHub digest)")
    ap.add_argument("--no-current", action="store_true", help="install but keep state/current.json")
    args = ap.parse_args()

    started = time.time()
    asset = release_asset(args.version)
    expected = (args.sha256 or asset["sha256"]).lower()
    if len(expected) != 64:
        raise SystemExit("no sha256 digest available for the asset; pass --sha256 to proceed")
    log(f"release {asset['tag']} asset {asset['name']} size {asset['size']} sha256 {expected}")

    name = asset["name"][: -len(".zip")]
    final = ROOT / "toolchains" / name
    zip_path = ROOT / "downloads" / asset["name"]

    actual = ""
    if not (final / "bin" / "lean.exe").is_file():
        download(asset["url"], zip_path, asset["size"])
        actual = sha256_file(zip_path)
        if actual != expected:
            raise SystemExit(f"sha256 mismatch for {zip_path}: got {actual}, expected {expected}")
        log("sha256 verified against the published digest")
    files = extract(zip_path, final)

    lean_version = probe(final / "bin" / "lean.exe")
    lake_version = probe(final / "bin" / "lake.exe")
    log(lean_version)
    log(lake_version)

    record = {
        "schema": "hub-lean-install/1",
        "tag": asset["tag"],
        "asset": asset["name"],
        "source_url": asset["url"],
        "size": asset["size"],
        "sha256_expected": expected,
        "sha256_actual": actual or "(zip verified on an earlier run)",
        "toolchain": str(final),
        "files_extracted": files,
        "lean_version": lean_version,
        "lake_version": lake_version,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.time() - started, 1),
    }
    write_json(ROOT / "state" / f"install-{name}.json", record)
    if not args.no_current:
        write_json(ROOT / "state" / "current.json",
                   {"schema": "hub-lean-current/1", "toolchain": f"toolchains/{name}", "tag": asset["tag"]})
    log(f"done in {record['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
