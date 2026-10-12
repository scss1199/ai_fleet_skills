#!/usr/bin/env python3
"""Offline whole-task token comparison; no model, network, prices or prompt output.

Public API: validate_efficiency(document, root=None), defaulting to the current
working directory at call time. The JSON manifest is
schema='fames.work-efficiency.v1', with baseline/candidate run objects:
  run_id, contract={goal_id, model_id, config_id, acceptance_id},
  scope={kind: 'whole_session_single_task', complete: true},
  expected_actors=[actor_id, ...], actors=[{actor_id, parent_actor_id,
  attempt_id, retry_of, session_id, format, logs:[{path, sha256}]}],
  coverage_receipt={path, sha256}, acceptance_receipt={path, sha256}.

Every actor entry represents one session/attempt; children and retries need
their own entries. Exactly one parent is null. A retry names its earlier actor
in retry_of (otherwise null). Session IDs and actor IDs are unique within a
run. Supported raw adapters are selected by format, not by a policy allowlist
of providers. Extend ADAPTERS to support another explicit measurement schema.

The coverage JSON uses schema='fames.work-coverage.v1', run_id, contract, scope,
actors (exact manifest roster including logs), state='COMPLETE',
all_usage_included=true, omitted_actors=[], omitted_retries=[]. The acceptance
JSON uses schema='fames.work-acceptance.v1', run_id, contract, state='ACCEPTED',
coverage_sha256, and nonempty result_artifacts=[{path, sha256}]. These receipts
are EXTERNAL ASSERTIONS of completeness/acceptance, not independent proof of
semantic task success, unlogged calls, model settings or billing. Result bytes
and all receipts/logs are rehashed. A pass is conditional on these assertions.

Scope deliberately excludes arbitrary turn slices, mixed-model sessions,
unattributed API activity, reset Codex counters and conflicting Claude usage
revisions. Claude requires all four input/cache/output counts; input_tokens
excludes cache, output_tokens includes thinking. Optional thinking_tokens is
only a subset. Codex requires session_meta and turn_context model evidence;
token_count.info.total_token_usage is cumulative, input includes cache and
output includes reasoning. No cumulative snapshots or thinking subsets are
added twice. Duplicate Claude message IDs across actors count once, with
conflicting values failing closed. Cross-run usage overlap is rejected.

Paths are local files below root, bounded and manifest-listed. Log aliases,
duplicate paths/hashes and reused sessions across runs are rejected. Output
contains fixed diagnostic codes and aggregate measurements only. Latency and
cost always remain UNKNOWN: this adapter has no clock/billing evidence path.
Token reduction is reported only for a strictly smaller measured total.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

MAX_MANIFEST_BYTES = 256 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ACTORS = 64
MAX_LOGS = 128
MAX_LINES = 100000
MAX_COUNT = 2**53 - 1
HASH = re.compile(r"[a-f0-9]{64}")
IDENTITY = re.compile(r"[A-Za-z0-9_.:@/+\-]{1,160}")
CONTRACT_KEYS = {"goal_id", "model_id", "config_id", "acceptance_id"}
SCOPE = {"kind": "whole_session_single_task", "complete": True}
MEASURES = ("ordinary_input", "cache_creation", "cache_read", "output")


class EvidenceError(ValueError):
    """Fixed diagnostic codes; never include source contents or exceptions."""


def _require(condition, reason):
    if not condition:
        raise EvidenceError(reason)


def _keys(value, keys, reason):
    _require(isinstance(value, dict) and set(value) == set(keys), reason)


def _identity(value):
    _require(isinstance(value, str) and IDENTITY.fullmatch(value), "identity_invalid")
    return value


def _hash(value):
    _require(isinstance(value, str) and HASH.fullmatch(value), "sha256_invalid")
    return value


def _count(value):
    _require(type(value) is int and 0 <= value <= MAX_COUNT, "usage_count_invalid")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_):
    raise EvidenceError("nonfinite_json_number")


def _json(raw):
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs,
                           parse_constant=_nonfinite)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("malformed_json") from None
    _require(isinstance(value, dict), "json_object_required")
    return value


class Artifacts:
    def __init__(self, root):
        _require(not str(root).startswith(("\\\\", "//")), "root_not_local")
        self.root = Path(root).resolve(strict=True)
        _require(self.root.is_dir() and not str(self.root).startswith(("\\\\", "//")), "root_not_local")
        self.paths = set()
        self.file_ids = set()
        self.log_hashes = set()
        self.bytes_read = 0
        self.log_count = 0

    def read(self, record, *, log=False, result=False):
        _keys(record, {"path", "sha256"}, "artifact_record_invalid")
        value = record["path"]
        _require(isinstance(value, str) and 0 < len(value) <= 4096
                 and not value.startswith(("\\\\", "//")) and "\x00" not in value,
                 "artifact_path_invalid")
        path = Path(value)
        # A colon is only allowed in the Windows drive; reject alternate streams.
        _require(":" not in value[len(path.drive):], "artifact_path_invalid")
        path = (path if path.is_absolute() else self.root / path).resolve(strict=True)
        _require(path.is_relative_to(self.root) and not str(path).startswith(("\\\\", "//")),
                 "artifact_path_escape")
        _require(path.is_file(), "artifact_not_regular_file")
        _require(path not in self.paths, "duplicate_artifact_path")
        stat = path.stat()
        file_id = (stat.st_dev, stat.st_ino)
        _require(file_id not in self.file_ids, "duplicate_artifact_file")
        digest = _hash(record["sha256"])
        if log:
            self.log_count += 1
            _require(self.log_count <= MAX_LOGS, "log_count_exceeded")
            _require(digest not in self.log_hashes, "duplicate_log_hash")
        limit = MAX_FILE_BYTES if log or result else MAX_MANIFEST_BYTES
        _require(0 < stat.st_size <= limit, "artifact_size_invalid")
        _require(self.bytes_read + stat.st_size <= MAX_TOTAL_BYTES, "total_read_limit")
        with path.open("rb") as handle:
            raw = handle.read(min(limit, MAX_TOTAL_BYTES - self.bytes_read) + 1)
        _require(0 < len(raw) <= limit and self.bytes_read + len(raw) <= MAX_TOTAL_BYTES,
                 "artifact_changed_or_read_limit")
        self.bytes_read += len(raw)
        _require(hashlib.sha256(raw).hexdigest() == digest, "artifact_hash_mismatch")
        self.paths.add(path)
        self.file_ids.add(file_id)
        if log:
            self.log_hashes.add(digest)
        return raw


def _events(raw):
    lines = raw.splitlines()
    _require(len(lines) <= MAX_LINES, "log_line_limit")
    for line in lines:
        if line.strip():
            yield _json(line)


def _metric(ordinary, creation, read, output, thinking):
    counts = [_count(value) for value in (ordinary, creation, read, output)]
    _require(sum(counts) <= MAX_COUNT, "usage_count_overflow")
    if thinking is not None:
        _require(_count(thinking) <= output, "thinking_exceeds_output")
    return dict(zip(MEASURES, counts), thinking=thinking, total_tokens=sum(counts))


def _claude_usage(usage):
    _require(isinstance(usage, dict), "claude_usage_missing")
    fields = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
    _require(all(name in usage for name in fields), "claude_usage_fields_missing")
    thinking = usage.get("thinking_tokens")
    if "thinking_tokens" in usage:
        _count(thinking)
    metric = _metric(*[_count(usage[name]) for name in fields], thinking)
    if "cache_creation" in usage:
        detail = usage["cache_creation"]
        _require(isinstance(detail, dict), "cache_creation_detail_invalid")
        # Detailed cache lifetimes partition, rather than add to, creation usage.
        _require(set(detail) <= {"ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"},
                 "cache_creation_detail_unknown")
        _require(sum(_count(count) for count in detail.values()) == metric["cache_creation"],
                 "cache_creation_detail_mismatch")
    return metric


def _claude(raw_logs, actor, contract, shared):
    records = 0
    new_metrics = []
    for raw in raw_logs:
        for event in _events(raw):
            if event.get("type") != "assistant":
                continue
            message = event.get("message")
            _require(isinstance(message, dict), "claude_message_missing")
            # An assistant record without usage cannot establish complete usage.
            _require(event.get("sessionId") == actor["session_id"], "log_session_mismatch")
            _require(message.get("model") == contract["model_id"], "log_model_mismatch")
            message_id = _identity(message.get("id"))
            metric = _claude_usage(message.get("usage"))
            key = ("claude_message", message_id)
            if key in shared:
                _require(shared[key] == metric, "duplicate_message_usage_conflict")
            else:
                shared[key] = metric
                new_metrics.append(metric)
            records += 1
    _require(records > 0, "usage_records_missing")
    return new_metrics, records


def _codex_usage(usage):
    _require(isinstance(usage, dict), "codex_usage_missing")
    fields = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
    _require(all(name in usage for name in fields), "codex_usage_fields_missing")
    input_tokens, cached, output, reasoning, total = [_count(usage[name]) for name in fields]
    _require(cached <= input_tokens, "cached_exceeds_input")
    metric = _metric(input_tokens - cached, 0, cached, output, reasoning)
    _require(total == metric["total_tokens"], "codex_total_mismatch")
    return metric


def _codex(raw_logs, actor, contract, shared):
    previous = None
    records = 0
    session_seen = False
    model_seen = False
    for raw in raw_logs:
        for event in _events(raw):
            kind, payload = event.get("type"), event.get("payload")
            if kind == "session_meta":
                _require(isinstance(payload, dict) and payload.get("id") == actor["session_id"],
                         "log_session_mismatch")
                session_seen = True
            elif kind == "turn_context":
                _require(isinstance(payload, dict) and payload.get("model") == contract["model_id"],
                         "log_model_mismatch")
                model_seen = True
            elif kind == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
                info = payload.get("info")
                # Initial Codex rate-limit events may carry no usage yet.
                if info is None:
                    continue
                _require(isinstance(info, dict), "codex_usage_missing")
                usage = info.get("total_token_usage")
                if usage is None:
                    continue
                _require(session_seen and model_seen, "codex_metadata_before_usage_required")
                current = _codex_usage(usage)
                if previous is not None:
                    # Cumulative ordinary input may decrease as cached tokens get
                    # attributed; the raw input/cache/output/reasoning must not.
                    pairs = [(current["ordinary_input"] + current["cache_read"],
                              previous["ordinary_input"] + previous["cache_read"])]
                    pairs += [(current[key], previous[key]) for key in ("cache_read", "output", "thinking", "total_tokens")]
                    _require(all(now >= before for now, before in pairs), "codex_counter_reset_or_reorder")
                previous = current
                records += 1
    _require(session_seen and model_seen and previous is not None, "codex_complete_usage_missing")
    key = ("codex_session", actor["session_id"])
    _require(key not in shared, "duplicate_usage_session")
    shared[key] = previous
    return [previous], records


# This adapter registry is an implementation boundary, not a provider policy.
ADAPTERS = {"claude_jsonl_v1": _claude, "codex_jsonl_v1": _codex}


def _contract(value):
    _keys(value, CONTRACT_KEYS, "contract_invalid")
    for identity in value.values():
        _identity(identity)


def _actors(run):
    actors = run["actors"]
    expected = run["expected_actors"]
    _require(isinstance(actors, list) and 1 <= len(actors) <= MAX_ACTORS, "actors_missing_or_exceeded")
    _require(isinstance(expected, list) and 1 <= len(expected) <= MAX_ACTORS, "expected_actors_missing")
    for identity in expected:
        _identity(identity)
    _require(len(set(expected)) == len(expected), "duplicate_expected_actor")
    roster = {}
    sessions = set()
    for actor in actors:
        _keys(actor, {"actor_id", "parent_actor_id", "attempt_id", "retry_of", "session_id", "format", "logs"}, "actor_invalid")
        for name in ("actor_id", "attempt_id", "session_id", "format"):
            _identity(actor[name])
        actor_id = actor["actor_id"]
        _require(actor_id not in roster, "duplicate_actor")
        _require(actor["session_id"] not in sessions, "duplicate_actor_session")
        _require(actor["format"] in ADAPTERS, "usage_adapter_unknown")
        _require(isinstance(actor["logs"], list) and 1 <= len(actor["logs"]) <= MAX_LOGS, "actor_logs_missing")
        roster[actor_id] = actor
        sessions.add(actor["session_id"])
    _require(set(roster) == set(expected), "actor_coverage_mismatch")
    _require(sum(actor["parent_actor_id"] is None for actor in actors) == 1, "actor_root_invalid")
    dependencies = {}
    for actor in actors:
        dependencies[actor["actor_id"]] = set()
        for field in ("parent_actor_id", "retry_of"):
            target = actor[field]
            if target is not None:
                _identity(target)
                _require(target in roster and target != actor["actor_id"], "actor_reference_invalid")
                dependencies[actor["actor_id"]].add(target)
    # Bounded topological elimination also catches cycles across parent/retry
    # edges, without exponential traversal through shared ancestors.
    while dependencies:
        ready = {key for key, parents in dependencies.items() if not parents}
        _require(bool(ready), "actor_dependency_cycle")
        dependencies = {key: parents - ready for key, parents in dependencies.items() if key not in ready}
    return sessions


def _validate_run(run, artifacts):
    _keys(run, {"run_id", "contract", "scope", "expected_actors", "actors", "coverage_receipt", "acceptance_receipt"}, "run_invalid")
    _identity(run["run_id"])
    _contract(run["contract"])
    _require(run["scope"] == SCOPE and type(run["scope"].get("complete")) is bool,
             "whole_session_single_task_scope_required")
    sessions = _actors(run)
    coverage = _json(artifacts.read(run["coverage_receipt"]))
    _keys(coverage, {"schema", "run_id", "contract", "scope", "actors", "state", "all_usage_included", "omitted_actors", "omitted_retries"}, "coverage_receipt_invalid")
    _require(coverage["schema"] == "fames.work-coverage.v1" and coverage["state"] == "COMPLETE"
             and coverage["all_usage_included"] is True and coverage["omitted_actors"] == []
             and coverage["omitted_retries"] == [], "coverage_not_complete")
    for field in ("run_id", "contract", "scope", "actors"):
        _require(coverage[field] == run[field], "coverage_binding_mismatch")
    acceptance = _json(artifacts.read(run["acceptance_receipt"]))
    _keys(acceptance, {"schema", "run_id", "contract", "state", "coverage_sha256", "result_artifacts"}, "acceptance_receipt_invalid")
    _require(acceptance["schema"] == "fames.work-acceptance.v1" and acceptance["state"] == "ACCEPTED",
             "result_not_accepted")
    _require(acceptance["run_id"] == run["run_id"] and acceptance["contract"] == run["contract"]
             and acceptance["coverage_sha256"] == run["coverage_receipt"]["sha256"], "acceptance_binding_mismatch")
    results = acceptance["result_artifacts"]
    _require(isinstance(results, list) and 1 <= len(results) <= MAX_LOGS, "accepted_results_missing")
    for result in results:
        artifacts.read(result, result=True)
    metrics = []
    shared = {}
    observed = 0
    for actor in run["actors"]:
        logs = [artifacts.read(record, log=True) for record in actor["logs"]]
        actor_metrics, records = ADAPTERS[actor["format"]](logs, actor, run["contract"], shared)
        metrics.extend(actor_metrics)
        observed += records
    totals = {name: sum(item[name] for item in metrics) for name in MEASURES}
    thinking = (sum(item["thinking"] for item in metrics)
                if all(item["thinking"] is not None for item in metrics) else None)
    normalized = _metric(*(totals[name] for name in MEASURES), thinking)
    _require(normalized["total_tokens"] > 0, "positive_measured_usage_required")
    normalized.update(state="VERIFIED_FROM_LOGS", actor_attempts=len(run["actors"]),
                      raw_usage_records=observed, unique_usage_units=len(metrics),
                      thinking_state="UNKNOWN" if thinking is None else "MEASURED_SUBSET_OF_OUTPUT",
                      acceptance_state="EXTERNAL_ACCEPTANCE_RECEIPT_BOUND",
                      coverage_state="EXTERNAL_COMPLETE_SCOPE_RECEIPT_BOUND")
    return normalized, set(shared), sessions


def validate_efficiency(document, root=None):
    """Return ok/state/reasons/normalized; a pass is conditional on receipts.

    ok=True ONLY for measured token reduction under the same bound contract.
    UNKNOWN means missing/invalid evidence; NOT_REDUCED is a valid comparison
    with equal or increased usage. No returned string originates in raw logs.
    """
    output = {"schema": "fames.work-efficiency-result.v1", "ok": False,
              "state": "UNKNOWN", "reasons": [], "normalized": {}, "metrics": {},
              "token_savings_verified": False, "token_reduction_percent": None,
              "token_comparison": {"state": "UNKNOWN", "delta_tokens": None,
                                   "reduction_tokens": None, "reduction_percent": None},
              "latency": {"state": "UNKNOWN", "reason": "no_clock_measurement_adapter"},
              "cost": {"state": "UNKNOWN", "reason": "no_billing_measurement_adapter"},
              "boundary": "measurement_is_conditional_on_external_scope_and_acceptance_receipts"}
    try:
        # Bound public-API documents too, and reject NaN before opening artifacts.
        try:
            encoded = json.dumps(document, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            raise EvidenceError("manifest_not_json_or_nonfinite") from None
        _require(len(encoded) <= MAX_MANIFEST_BYTES, "manifest_size_exceeded")
        _keys(document, {"schema", "baseline", "candidate"}, "manifest_invalid")
        _require(document["schema"] == "fames.work-efficiency.v1", "manifest_schema_unknown")
        baseline, candidate = document["baseline"], document["candidate"]
        _require(isinstance(baseline, dict) and isinstance(candidate, dict), "run_invalid")
        _require(baseline.get("run_id") != candidate.get("run_id"), "distinct_runs_required")
        _contract(baseline.get("contract"))
        _contract(candidate.get("contract"))
        _require(baseline["contract"] == candidate["contract"], "comparison_contract_mismatch")
        artifacts = Artifacts(Path.cwd() if root is None else root)
        base, base_units, base_sessions = _validate_run(baseline, artifacts)
        cand, cand_units, cand_sessions = _validate_run(candidate, artifacts)
        _require(not (base_units & cand_units or base_sessions & cand_sessions), "cross_run_usage_overlap")
        output["normalized"] = {"baseline": base, "candidate": cand}
        output["metrics"] = output["normalized"]
        delta = cand["total_tokens"] - base["total_tokens"]
        output["token_comparison"]["delta_tokens"] = delta
        if delta < 0:
            output.update(ok=True, state="VERIFIED_REDUCTION_CONDITIONAL")
            output["token_comparison"].update(state="MEASURED_REDUCTION", reduction_tokens=-delta,
                                               reduction_percent=100.0 * (-delta) / base["total_tokens"])
            output.update(token_savings_verified=True,
                          token_reduction_percent=output["token_comparison"]["reduction_percent"])
        else:
            output.update(state="NOT_REDUCED", reasons=["measured_tokens_not_lower"])
            output["token_comparison"]["state"] = "UNCHANGED" if delta == 0 else "INCREASED"
    except EvidenceError as exc:
        output["reasons"].append(str(exc))
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        output["reasons"].append("artifact_unavailable_or_invalid")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate bounded offline whole-task token evidence")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    try:
        _require(not str(args.input).startswith(("\\\\", "//")), "manifest_not_local")
        input_path = args.input.resolve(strict=True)
        _require(not str(input_path).startswith(("\\\\", "//")), "manifest_not_local")
        with input_path.open("rb") as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
        _require(len(raw) <= MAX_MANIFEST_BYTES, "manifest_size_exceeded")
        result = validate_efficiency(_json(raw), root=args.root or input_path.parent)
    except (EvidenceError, OSError, RuntimeError):
        result = {"ok": False, "state": "UNKNOWN", "reasons": ["manifest_unavailable_or_invalid"], "normalized": {}}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
