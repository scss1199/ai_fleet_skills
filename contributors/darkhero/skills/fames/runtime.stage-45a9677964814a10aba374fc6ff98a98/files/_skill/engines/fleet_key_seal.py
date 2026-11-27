#!/usr/bin/env python3
"""fleet_key_seal.py - carry darkhero's free-pool API keys to the followers through the public carrier, sealed.

Operator 2026-11-18 chose option (a): encrypt to each follower's SSH public key and put the ciphertext in the
public ai_fleet_skills carrier, pulled at boot. No key value is ever printed, logged or put on a command line.

  follower: ensure_identity() keeps an ed25519 SSH key at ~/.ssh/f1s_fleet_ed25519 (made with `cryptography`,
            no subprocess, no window) and its public line goes into contributors/<host>/manifest.json.
  darkhero: seal_for_followers() reads each follower's published public key and writes
            contributors/darkhero/sealed/<host>.json = f1s-seal-v1(api-matrix free-pool rows).  The blob is only
            rewritten when the payload or the recipient key changes (digest kept in the local sync state).
  follower: apply_sealed() opens its own blob when the sealed_id changed and upserts the rows into its local
            _secrets/api-matrix.json; endpoints that are host-local (localhost / 127.*) are never carried.

f1s-seal-v1: ephemeral X25519 against the recipient's ed25519 key mapped to X25519, HKDF-SHA256
(salt = eph_pub || recipient_pub, info = b"f1s-seal-v1"), ChaCha20-Poly1305 with a random 12-byte nonce.

    python fleet_key_seal.py status        # names/counts only
    python fleet_key_seal.py selftest      # round-trip with a throwaway key, no real secret touched
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

SCHEME = "f1s-seal-v1"
IDENTITY = Path.home() / ".ssh" / "f1s_fleet_ed25519"
_P = 2 ** 255 - 19
_LOCAL_HOSTS = ("localhost", "127.", "0.0.0.0", "[::1]")
_ROW_FIELDS = ("provider", "account", "key", "status", "note")


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _ub64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _ed_pub_to_x(ed_pub: bytes) -> bytes:
    """Birational map Edwards y -> Montgomery u = (1 + y) / (1 - y) mod p (RFC 7748 section 4.1)."""
    y = int.from_bytes(ed_pub, "little") & ((1 << 255) - 1)
    u = (1 + y) * pow((1 - y) % _P, _P - 2, _P) % _P
    return u.to_bytes(32, "little")


def _ed_seed_to_x(seed: bytes) -> bytes:
    return hashlib.sha512(seed).digest()[:32]  # X25519 clamps on load


def _pub_from_line(line: str) -> bytes:
    from cryptography.hazmat.primitives.serialization import load_ssh_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    key = load_ssh_public_key(line.strip().encode("ascii"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("not an ssh-ed25519 key")
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def fingerprint(line: str) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(_pub_from_line(line)).digest()).decode().rstrip("=")


def _kdf(shared: bytes, eph_pub: bytes, rcpt_pub: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=eph_pub + rcpt_pub,
                info=SCHEME.encode()).derive(shared)


def seal(pub_line: str, plaintext: bytes) -> dict:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    rcpt = _ed_pub_to_x(_pub_from_line(pub_line))
    eph = X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key = _kdf(eph.exchange(X25519PublicKey.from_public_bytes(rcpt)), eph_pub, rcpt)
    nonce = os.urandom(12)
    ct = ChaCha20Poly1305(key).encrypt(nonce, plaintext, SCHEME.encode())
    return {"scheme": SCHEME, "recipient": fingerprint(pub_line), "eph": _b64(eph_pub),
            "nonce": _b64(nonce), "ct": _b64(ct), "sealed_id": hashlib.sha256(ct).hexdigest()[:16]}


def open_sealed(blob: dict, identity: Path = IDENTITY) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    from cryptography.hazmat.primitives.serialization import (Encoding, NoEncryption, PrivateFormat,
                                                              PublicFormat, load_ssh_private_key)
    if blob.get("scheme") != SCHEME:
        raise ValueError("unknown scheme")
    sk = load_ssh_private_key(identity.read_bytes(), password=None)
    if not isinstance(sk, Ed25519PrivateKey):
        raise ValueError("identity is not ed25519")
    seed = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    x = X25519PrivateKey.from_private_bytes(_ed_seed_to_x(seed))
    rcpt = x.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    eph_pub = _ub64(blob["eph"])
    key = _kdf(x.exchange(X25519PublicKey.from_public_bytes(eph_pub)), eph_pub, rcpt)
    return ChaCha20Poly1305(key).decrypt(_ub64(blob["nonce"]), _ub64(blob["ct"]), SCHEME.encode())


def ensure_identity(identity: Path = IDENTITY) -> str | None:
    """Public line of this host's fleet SSH key, creating it once. None when `cryptography` is missing."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (Encoding, NoEncryption, PrivateFormat,
                                                                  PublicFormat, load_ssh_private_key)
    except ImportError:
        return None
    if identity.is_file():
        sk = load_ssh_private_key(identity.read_bytes(), password=None)
    else:
        identity.parent.mkdir(parents=True, exist_ok=True)
        sk = Ed25519PrivateKey.generate()
        tmp = identity.with_name(identity.name + ".tmp")
        tmp.write_bytes(sk.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()))
        os.replace(tmp, identity)
    line = sk.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode("ascii")
    pub = identity.with_name(identity.name + ".pub")
    if not pub.is_file() or pub.read_text(encoding="ascii").split()[:2] != line.split()[:2]:
        pub.write_text(line + " f1s-fleet\n", encoding="ascii")
    return line


def _is_local(endpoint: dict) -> bool:
    url = str((endpoint or {}).get("url") or "").lower().split("//", 1)[-1]
    return url.startswith(_LOCAL_HOSTS)


def free_pool_payload(matrix: dict) -> dict:
    eps = {p: e for p, e in (matrix.get("endpoints") or {}).items() if isinstance(e, dict) and not _is_local(e)}
    rows = [{k: r.get(k) for k in _ROW_FIELDS if k in r} for r in matrix.get("keys") or []
            if isinstance(r, dict) and r.get("provider") in eps and r.get("key")]
    return {"endpoints": eps, "keys": rows}


def merge_payload(matrix: dict, payload: dict) -> dict:
    """Upsert carried rows by (provider, account); add carried endpoints the follower lacks; keep local ones."""
    eps = matrix.setdefault("endpoints", {})
    added_eps = 0
    for p, e in (payload.get("endpoints") or {}).items():
        if p not in eps:
            eps[p] = e
            added_eps += 1
    keys = matrix.setdefault("keys", [])
    index = {(r.get("provider"), r.get("account")): i for i, r in enumerate(keys) if isinstance(r, dict)}
    added = updated = 0
    for row in payload.get("keys") or []:
        at = index.get((row.get("provider"), row.get("account")))
        if at is None:
            keys.append(dict(row))
            added += 1
        elif keys[at].get("key") != row.get("key"):
            keys[at].update(row)
            updated += 1
    return {"endpoints_added": added_eps, "keys_added": added, "keys_updated": updated}


def _matrix_path() -> str:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _paths import API_MATRIX
    return API_MATRIX


def seal_for_followers(repo: str, own_slug: str, followers: list[str], state: dict) -> dict:
    """Upstream side. state is the caller's persisted dict; returns names/counts only."""
    out: dict = {}
    try:
        matrix = json.loads(Path(_matrix_path()).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"state": "UNKNOWN", "reason": "no_matrix"}
    payload = json.dumps(free_pool_payload(matrix), ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    seen = state.setdefault("key_seal", {})
    sealed_dir = Path(repo) / "contributors" / own_slug / "sealed"
    for slug in followers:
        try:
            man = json.loads((Path(repo) / "contributors" / slug / "manifest.json").read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            out[slug] = "no_manifest"
            continue
        line = (man.get("key_seal") or {}).get("ssh_pubkey")
        if not line:
            out[slug] = "no_pubkey"
            continue
        try:
            fpr = fingerprint(line)
        except Exception:  # noqa: BLE001 - malformed public key = skip, never guess
            out[slug] = "bad_pubkey"
            continue
        target = sealed_dir / f"{slug}.json"
        mark = f"{digest}:{fpr}"
        if seen.get(slug) == mark and target.is_file():
            out[slug] = "unchanged"
            continue
        blob = seal(line, payload)
        blob["sealed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sealed_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")
        seen[slug] = mark
        out[slug] = "sealed"
    return {"state": "MEASURED", "followers": out}


def apply_sealed(repo: str, upstream_slug: str, own_slug: str, state: dict) -> dict:
    """Follower side: open contributors/<upstream>/sealed/<own>.json once per sealed_id and merge it."""
    target = Path(repo) / "contributors" / upstream_slug / "sealed" / f"{own_slug}.json"
    if not target.is_file():
        return {"state": "NONE"}
    try:
        blob = json.loads(target.read_text(encoding="utf-8-sig"))
        if state.get("key_seal_applied") == blob.get("sealed_id"):
            return {"state": "UNCHANGED", "sealed_id": blob.get("sealed_id")}
        payload = json.loads(open_sealed(blob).decode("utf-8"))
        path = Path(_matrix_path())
        matrix = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {"version": 1}
        counts = merge_payload(matrix, payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001 - names only; the follower retries next tick
        return {"state": "FAILED", "reason": type(exc).__name__}
    state["key_seal_applied"] = blob.get("sealed_id")
    return {"state": "APPLIED", "sealed_id": blob.get("sealed_id"), **counts}


def _selftest() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ident = Path(d) / "id"
        line = ensure_identity(ident)
        assert line and ensure_identity(ident) == line
        msg = os.urandom(64)
        blob = seal(line, msg)
        assert open_sealed(blob, ident) == msg
        blob["ct"] = _b64(_ub64(blob["ct"])[:-1] + bytes([_ub64(blob["ct"])[-1] ^ 1]))
        try:
            open_sealed(blob, ident)
            return 1
        except Exception:  # noqa: BLE001 - tamper must fail
            pass
    m = {"endpoints": {"g": {"url": "https://x"}, "o": {"url": "http://127.0.0.1:1"}},
         "keys": [{"provider": "g", "account": "a", "key": "k1"}, {"provider": "o", "account": "a", "key": "k2"}]}
    p = free_pool_payload(m)
    assert list(p["endpoints"]) == ["g"] and len(p["keys"]) == 1
    local = {"endpoints": {"o": {"url": "http://127.0.0.1:2"}}, "keys": []}
    assert merge_payload(local, p) == {"endpoints_added": 1, "keys_added": 1, "keys_updated": 0}
    assert local["endpoints"]["o"]["url"].endswith(":2")
    print("selftest ok")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "selftest":
        sys.exit(_selftest())
    line = ensure_identity() if IDENTITY.is_file() else None
    print(json.dumps({"identity": str(IDENTITY), "present": IDENTITY.is_file(),
                      "fingerprint": fingerprint(line) if line else None}))
