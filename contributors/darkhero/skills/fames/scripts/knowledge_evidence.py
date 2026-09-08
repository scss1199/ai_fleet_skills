"""Read-only validation of persisted knowledge artifacts, not source truth.

validate_knowledge(record, root) accepts a VERIFIED acquisition receipt with
source_url (or url), full_path/digest_path, and their SHA-256 values. Paths may be
relative to root. source_path defaults to source.json beside full.txt. The
current producer's model_api_calls/model_calls aliases are accepted only with
consistent, non-boolean integer counters. An input source.json can be adapted
by adding state='VERIFIED'; absent paths default to root/full.txt and digest.md.

Output contains classifications, counters and hashes only: no source text,
URLs, raw exception strings, paths, credentials, or claims of verified truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import urllib.parse

MAX_JSON = 65536
MAX_TEXT = 8 * 1024 * 1024
MAX_MEDIA = 32 * 1024 * 1024
HASH = re.compile(r"[a-f0-9]{64}")


class EvidenceError(Exception):
    """Fixed diagnostic codes only."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("duplicate_json_key")
        result[key] = value
    return result


def _json(data: bytes):
    try:
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(EvidenceError("nonfinite_json_number")))
    except (ValueError, UnicodeError):
        raise EvidenceError("malformed_json") from None
    if not isinstance(value, dict):
        raise EvidenceError("json_object_required")
    return value


def _path(value, root: Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise EvidenceError("artifact_path_missing")
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise EvidenceError("artifact_path_escape")
    return path


def _read(path: Path, limit: int) -> bytes:
    if not path.is_file():
        raise EvidenceError("artifact_missing")
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise EvidenceError("artifact_size_exceeded")
    if not data:
        raise EvidenceError("artifact_empty")
    return data


def _hash(value) -> str:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise EvidenceError("sha256_invalid")
    return value


def _text(data: bytes) -> str:
    try:
        value = data.decode("utf-8-sig").replace("\r\n", "\n").strip()
    except UnicodeError:
        raise EvidenceError("artifact_text_encoding_invalid") from None
    if not value:
        raise EvidenceError("artifact_text_empty")
    return value


def _counter(value) -> int:
    if type(value) is not int or value < 0:
        raise EvidenceError("counter_type_or_range_invalid")
    return value


def _remote(document: dict):
    counters = []
    for name in ("remote_model_api_calls", "model_api_calls"):
        if name in document:
            counters.append(_counter(document[name]))
    if "model_calls" in document:
        legacy = _counter(document["model_calls"])
        if document.get("model_calls_scope") != "remote_model_APIs":
            raise EvidenceError("legacy_model_counter_scope_missing")
        counters.append(legacy)
    if not counters:
        raise EvidenceError("remote_model_counter_missing")
    if len(set(counters)) != 1:
        raise EvidenceError("remote_model_counters_conflict")
    return counters[0]


def _identity(value) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise EvidenceError("source_identity_missing_or_invalid")
    try:
        url = urllib.parse.urlsplit(value)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise EvidenceError("source_identity_missing_or_invalid")
    except ValueError:
        raise EvidenceError("source_identity_missing_or_invalid") from None
    return value


def _tombstoned(doc: dict) -> bool:
    if doc.get("state") in ("TOMBSTONED", "DELETED"):
        return True
    for name in ("deleted", "tombstoned", "tombstone"):
        if name not in doc:
            continue
        value = doc[name]
        if type(value) is bool:
            if value:
                return True
        elif name == "tombstone" and type(value) is int and value in (0, 1):
            if value:
                return True
        else:
            raise EvidenceError("deletion_flag_invalid")
    return False


def _truth_guard(doc: dict):
    for name in ("truth_state", "truth_status"):
        if name in doc and doc[name] not in ("UNKNOWN", "UNVALIDATED_SOURCE", "UNVERIFIED"):
            raise EvidenceError("unsupported_truth_claim")


def _caption_body(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise EvidenceError("caption_encoding_invalid") from None
    lines = []
    for line in text.splitlines():
        if not line.strip() or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:")) or line.strip().isdigit():
            continue
        value = re.sub(r"<[^>]*>", "", line).strip()
        if value and (not lines or value != lines[-1]):
            lines.append(value)
    return "\n".join(lines).strip()


def _speech(source, full: bytes, directory: Path, root: Path, url: str, current_runs: int) -> dict:
    provenance = _json(_read(_path(directory / "speech-source.json", root), MAX_JSON))
    if _tombstoned(provenance):
        raise EvidenceError("media_tombstoned")
    _truth_guard(provenance)
    if provenance.get("promoted") is not False:
        raise EvidenceError("media_promotion_not_false")
    if provenance.get("source_url") != url:
        raise EvidenceError("media_source_identity_mismatch")
    historical = _counter(provenance.get("local_asr_runs"))
    if historical < 1:
        raise EvidenceError("media_asr_evidence_missing")
    remote = _remote(provenance)
    if remote != 0:
        raise EvidenceError("local_asr_remote_model_conflict")
    if source["source_kind"] == "public_media_local_whisper" and current_runs < 1:
        raise EvidenceError("fresh_asr_counter_missing")
    duration = provenance.get("duration_seconds")
    if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 900:
        raise EvidenceError("media_duration_invalid")
    if provenance.get("device") != "cpu" or _counter(provenance.get("threads")) > 2 or provenance["threads"] < 1:
        raise EvidenceError("local_asr_compute_provenance_invalid")
    media = _path(provenance.get("media_path"), root)
    transcript = _path(provenance.get("transcript_path"), root)
    if media.parent != directory or transcript.parent != directory:
        raise EvidenceError("media_artifact_directory_mismatch")
    media_bytes, text = _read(media, MAX_MEDIA), _read(transcript, MAX_TEXT)
    if _sha(media_bytes) != _hash(provenance.get("media_sha256")) or _sha(text) != _hash(provenance.get("transcript_sha256")):
        raise EvidenceError("media_hash_mismatch")
    if _text(text) != _text(full):
        raise EvidenceError("transcript_full_text_mismatch")
    for name in ("speech_segments", "source_segments"):
        if name in provenance:
            _counter(provenance[name])
    if "speech_segments" in provenance and "source_segments" in provenance:
        if provenance["speech_segments"] < 1 or provenance["speech_segments"] > provenance["source_segments"]:
            raise EvidenceError("media_segment_counts_invalid")
    return {"source_class": "LOCAL_SPEECH_TRANSCRIPT", "coverage": "machine_transcribed_speech_only",
            "historical_local_asr_runs": historical, "media_duration_seconds": duration,
            "media_sha256": _sha(media_bytes), "transcript_sha256": _sha(text)}


def validate_knowledge(record, root: Path) -> dict:
    """Validate local receipt integrity. PASS never asserts truth or canon authority."""
    output = {"schema_version": 1, "state": "UNKNOWN", "acquisition_state": "UNKNOWN",
              "truth_state": "UNKNOWN", "canon_state": "UNKNOWN", "source_class": "UNKNOWN",
              "coverage": "UNKNOWN", "source_origin_state": "UNKNOWN", "visual_understanding_state": "UNKNOWN",
              "remote_model_api_calls": None, "local_asr_runs": None, "hashes": {}, "errors": []}
    try:
        if not isinstance(record, dict):
            raise EvidenceError("receipt_object_required")
        if _tombstoned(record):
            output["state"] = "BLOCKED"
            raise EvidenceError("input_tombstoned")
        if "promoted" in record and record["promoted"] is not False:
            output["state"] = "BLOCKED" if record["promoted"] is True else "UNKNOWN"
            raise EvidenceError("canon_promotion_not_false")
        _truth_guard(record)
        if record.get("state") != "VERIFIED":
            raise EvidenceError("acquisition_not_verified")
        root = Path(root).resolve()
        if not root.is_dir():
            raise EvidenceError("artifact_root_missing")
        url = _identity(record.get("source_url", record.get("url")))
        if "source_url" in record and "url" in record and record["source_url"] != record["url"]:
            raise EvidenceError("source_identity_conflict")
        full_path = _path(record.get("full_path", "full.txt"), root)
        digest_path = _path(record.get("digest_path", "digest.md"), root)
        source_path = _path(record.get("source_path", full_path.parent / "source.json"), root)
        if len({full_path, digest_path, source_path}) != 3 or digest_path.parent != full_path.parent or source_path.parent != full_path.parent:
            raise EvidenceError("artifact_directory_or_role_mismatch")
        source = _json(_read(source_path, MAX_JSON))
        if type(source.get("schema")) is not int or source["schema"] != 1:
            raise EvidenceError("source_schema_invalid")
        if _tombstoned(source):
            output["state"] = "BLOCKED"
            raise EvidenceError("source_tombstoned")
        if "state" in source and source["state"] != "VERIFIED":
            raise EvidenceError("source_acquisition_not_verified")
        _truth_guard(source)
        if source.get("promoted") is not False:
            output["state"] = "BLOCKED" if source.get("promoted") is True else "UNKNOWN"
            raise EvidenceError("canon_promotion_not_false")
        output["canon_state"] = "NOT_PROMOTED"
        if source.get("source_url") != url:
            raise EvidenceError("source_identity_mismatch")
        full, digest = _read(full_path, MAX_TEXT), _read(digest_path, MAX_TEXT)
        _text(full)
        _text(digest)
        for name, data in (("full", full), ("digest", digest)):
            actual = _sha(data)
            if actual != _hash(record.get(name + "_sha256")) or actual != _hash(source.get(name + "_sha256")):
                raise EvidenceError(name + "_hash_mismatch")
            output["hashes"][name + "_sha256"] = actual
        remote, runs = _remote(source), _counter(source.get("local_asr_runs"))
        if any(name in record for name in ("remote_model_api_calls", "model_api_calls", "model_calls")) and _remote(record) != remote:
            raise EvidenceError("receipt_remote_counter_mismatch")
        if "local_asr_runs" in record and _counter(record["local_asr_runs"]) != runs:
            raise EvidenceError("receipt_local_asr_counter_mismatch")
        output.update(remote_model_api_calls=remote, local_asr_runs=runs)
        kind = source.get("source_kind")
        if not isinstance(kind, str) or not kind:
            raise EvidenceError("source_kind_missing")
        if "source_kind" in record and record["source_kind"] != kind:
            raise EvidenceError("receipt_source_kind_mismatch")
        if kind in ("public_media_local_whisper", "cached_public_media_local_whisper"):
            media = _speech(source, full, full_path.parent, root, url, runs)
            output["hashes"].update({key: media.pop(key) for key in ("media_sha256", "transcript_sha256")})
            output.update(media)
        elif kind.startswith("public_vtt:"):
            expected = _hash(kind.partition(":")[2])
            candidates = list((full_path.parent / "captions").glob("source*.vtt"))
            if not candidates or len(candidates) > 16:
                raise EvidenceError("caption_source_missing_or_unbounded")
            matching = None
            for candidate in candidates:
                raw = _read(_path(candidate, root), MAX_TEXT)
                if _sha(raw) == expected:
                    matching = raw
                    break
            if matching is None:
                raise EvidenceError("caption_source_hash_mismatch")
            if _caption_body(matching) != _text(full):
                raise EvidenceError("caption_full_text_mismatch")
            output.update(source_class="CAPTIONS", coverage="available_caption_text_only")
            output["hashes"]["caption_sha256"] = expected
        elif kind.startswith("cached_full_speech:"):
            raise EvidenceError("legacy_transcript_provenance_missing")
        else:
            if any(word in kind.lower() for word in ("transcript", "speech", "caption", "whisper", "video", "audio")):
                raise EvidenceError("media_provenance_contract_unknown")
            if (full_path.parent / "speech-source.json").exists() or any(
                    name in source for name in ("duration_seconds", "media_path", "transcript_path")):
                raise EvidenceError("media_provenance_kind_conflict")
            output.update(source_class="PAGE_TEXT" if kind == "public_page_text" else "SOURCE_TEXT",
                          coverage="persisted_extracted_text_only")
        output["hashes"]["source_identity_sha256"] = _sha(url.encode("utf-8"))
        output.update(state="PASS", acquisition_state="VERIFIED")
    except EvidenceError as exc:
        output["errors"].append(str(exc))
    except Exception:
        output["errors"].append("evidence_read_or_shape_error")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        record = _json(_read(args.input, MAX_JSON))
        result = validate_knowledge(record, args.root)
    except Exception:
        result = {"schema_version": 1, "state": "UNKNOWN", "acquisition_state": "UNKNOWN",
                  "truth_state": "UNKNOWN", "canon_state": "UNKNOWN", "errors": ["input_receipt_unreadable"]}
    if args.json:
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    else:
        print("state=" + result["state"] + " acquisition=" + result["acquisition_state"] + " truth=UNKNOWN errors=" + ",".join(result["errors"]))
    return 0 if result["state"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
