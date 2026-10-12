#!/usr/bin/env python3
"""Deterministic, bounded local evidence excerpts; character metrics are not tokens.

Input: {"query": "terms", "evidence": [{"id": "unique", "path":
"absolute local UTF-8 file", "sha256": "64 hex digits"}]}.
Only manifest-listed files are opened. No network or model dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

MAX_MANIFEST_BYTES = 65536
MAX_ITEMS = 128
MAX_FILE_BYTES = 262144
MAX_TOTAL_BYTES = 1048576
MAX_EXCERPTS = 3
MAX_EXCERPT_CHARS = 600
MAX_PACKET_CHARS = 1600


class InvalidManifest(ValueError):
    pass


def read_manifest(path: Path) -> dict:
    try:
        if str(path).startswith(("\\\\", "//")):
            raise InvalidManifest("manifest must be a local file")
        path = path.resolve(strict=True)
        if str(path).startswith(("\\\\", "//")) or not path.is_file():
            raise InvalidManifest("manifest must be a local regular file")
        with path.open("rb") as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise InvalidManifest("manifest exceeds byte limit")
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidManifest("manifest is unavailable or invalid UTF-8 JSON") from exc
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict) or set(manifest) != {"query", "evidence"}:
        raise InvalidManifest("manifest requires only query and evidence")
    query = manifest["query"]
    if not isinstance(query, str) or not query.strip() or len(query) > 1024:
        raise InvalidManifest("query must be nonempty and at most 1024 characters")
    items = manifest["evidence"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise InvalidManifest("evidence must contain 1 to 128 items")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "path", "sha256"}:
            raise InvalidManifest("each evidence item requires only id, path, sha256")
        identity, path, digest = item["id"], item["path"], item["sha256"]
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", identity) or identity in seen:
            raise InvalidManifest("evidence IDs must be unique bounded identifiers")
        seen.add(identity)
        if not isinstance(path, str) or len(path) > 4096 or "\x00" in path or not Path(path).is_absolute() or path.startswith(("\\\\", "//")):
            raise InvalidManifest("evidence paths must be absolute local paths")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            raise InvalidManifest("sha256 must contain exactly 64 hexadecimal digits")


def build_packet(manifest: dict, max_excerpts: int = MAX_EXCERPTS,
                 char_budget: int = MAX_PACKET_CHARS) -> dict:
    validate_manifest(manifest)
    if not 1 <= max_excerpts <= MAX_EXCERPTS or not 1 <= char_budget <= MAX_PACKET_CHARS:
        raise InvalidManifest("requested excerpt limits exceed hard bounds")
    terms = sorted(set(manifest["query"].casefold().split()))
    records = []
    bytes_read = 0
    excerpt_chars = 0
    selected = 0
    source_chars = 0
    for item in manifest["evidence"]:
        record = dict(item, state="UNKNOWN", disposition="NO_EXCERPT", reason=None)
        records.append(record)
        path = Path(item["path"])
        if bytes_read >= MAX_TOTAL_BYTES:
            record["reason"] = "TOTAL_READ_LIMIT"
            continue
        try:
            # Reject a symlink escape to a remote filesystem on Windows as well.
            resolved = path.resolve(strict=True)
            if str(resolved).startswith(("\\\\", "//")) or not resolved.is_file():
                record["reason"] = "NOT_LOCAL_REGULAR_FILE"
                continue
            size = resolved.stat().st_size
            record["file_bytes"] = size
            if size > MAX_FILE_BYTES:
                record["reason"] = "FILE_READ_LIMIT"
                continue
            # The sentinel byte detects a file growing between stat and read.
            read_limit = min(MAX_FILE_BYTES + 1, MAX_TOTAL_BYTES - bytes_read)
            if size + 1 > read_limit:
                record["reason"] = "TOTAL_READ_LIMIT"
                continue
            with resolved.open("rb") as handle:
                raw = handle.read(read_limit)
            bytes_read += len(raw)
            if len(raw) > MAX_FILE_BYTES or len(raw) == read_limit:
                record["reason"] = "FILE_CHANGED_OR_READ_LIMIT"
                continue
        except (OSError, RuntimeError):
            record["reason"] = "FILE_UNAVAILABLE"
            continue
        observed = hashlib.sha256(raw).hexdigest()
        record["observed_sha256"] = observed
        if observed != item["sha256"].lower():
            record["reason"] = "HASH_MISMATCH"
            continue
        try:
            content = raw.decode("utf-8")
        except UnicodeError:
            record["reason"] = "INVALID_UTF8"
            continue
        record.update(state="VERIFIED", source_chars=len(content))
        source_chars += len(content)
        # Selection follows explicit manifest priority, then the first matching line.
        # Query matching is mechanical retrieval, never a relevance verdict.
        offset = 0
        match = None
        for line_number, line in enumerate(content.splitlines(keepends=True), 1):
            if any(term in line.casefold() for term in terms):
                match = (offset, line_number, line)
                break
            offset += len(line)
        if match is None:
            record.update(disposition="OMITTED", reason="NO_QUERY_MATCH")
            continue
        if selected >= max_excerpts:
            record.update(disposition="OMITTED", reason="EXCERPT_COUNT_LIMIT")
            continue
        allowance = min(MAX_EXCERPT_CHARS, char_budget - excerpt_chars)
        if allowance <= 0:
            record.update(disposition="OMITTED", reason="EXCERPT_CHAR_LIMIT")
            continue
        start, line_number, line = match
        # Keep a matched term visible even on a very long physical line.
        folded = line.casefold()
        match_index = min(folded.find(term) for term in terms if term in folded)
        # casefold can change string length: locate a matching prefix safely.
        physical_index = 0
        folded_length = 0
        while physical_index < len(line) and folded_length < match_index:
            folded_length += len(line[physical_index].casefold())
            physical_index += 1
        start += max(0, physical_index - min(80, allowance // 4))
        excerpt = content[start:start + allowance]
        record.update(disposition="SELECTED", reason=None, excerpt=excerpt,
                      excerpt_chars=len(excerpt), start_char=start,
                      end_char=start + len(excerpt), matched_line=line_number,
                      truncated=start > 0 or start + len(excerpt) < len(content))
        excerpt_chars += len(excerpt)
        selected += 1
    unknown = sum(record["state"] == "UNKNOWN" for record in records)
    omitted = sum(record["disposition"] == "OMITTED" for record in records)
    truncated = sum(record.get("truncated", False) for record in records)
    return {
        "schema": "fames.context-packet.v1",
        "state": "UNKNOWN" if unknown else "PARTIAL" if omitted or truncated else "VERIFIED",
        "query": manifest["query"], "model_calls": 0, "network_calls": 0,
        "limits": {"max_excerpts": max_excerpts, "excerpt_char_budget": char_budget,
                   "max_excerpt_chars": MAX_EXCERPT_CHARS, "max_file_bytes": MAX_FILE_BYTES,
                   "max_total_bytes": MAX_TOTAL_BYTES},
        "metrics": {"requested_items": len(records), "selected_items": selected,
                    "omitted_items": omitted, "unknown_items": unknown,
                    "truncated_items": truncated, "bytes_read": bytes_read,
                    "verified_source_chars": source_chars, "excerpt_chars": excerpt_chars,
                    "measurement_unit": "characters; no token or billing estimate"},
        "evidence": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-excerpts", type=int, default=MAX_EXCERPTS)
    parser.add_argument("--char-budget", type=int, default=MAX_PACKET_CHARS)
    args = parser.parse_args(argv)
    try:
        manifest = read_manifest(args.input)
        if str(args.out).startswith(("\\\\", "//")):
            raise InvalidManifest("receipt must be a local file")
        output_path = args.out.resolve()
        if str(output_path).startswith(("\\\\", "//")):
            raise InvalidManifest("receipt must be a local file")
        input_paths = [args.input.resolve()] + [Path(item["path"]).resolve() for item in manifest["evidence"]]
        if output_path in input_paths or (output_path.exists() and any(path.exists() and output_path.samefile(path) for path in input_paths)):
            raise InvalidManifest("receipt must not overwrite manifest or evidence")
        receipt = build_packet(manifest, args.max_excerpts, args.char_budget)
        status = 2 if receipt["state"] == "UNKNOWN" else 0
    except InvalidManifest as exc:
        # A malformed manifest never opens evidence files or writes an unsafe output.
        print(json.dumps({"state": "UNKNOWN", "reason": str(exc)}, sort_keys=True))
        return 2
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except OSError:
        print(json.dumps({"state": "UNKNOWN", "reason": "RECEIPT_WRITE_FAILED"}))
        return 2
    receipt_hash = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(json.dumps({"state": receipt["state"], "receipt_path": str(output_path),
                      "receipt_sha256": receipt_hash, "metrics": receipt["metrics"]}, sort_keys=True))
    return status


if __name__ == "__main__":
    sys.exit(main())
