#!/usr/bin/env python3
"""Offline validator of a bounded mission/execution graph; no model/network calls.

Public API: validate_execution(document, root=None), defaulting root to the
current working directory at call time. No model API is called; no source
text, raw exceptions, or path/credential contents are ever returned. Reuses
work_efficiency.Artifacts and its bounded JSON/identity/hash primitives.

Document is schema='fames.execution-evidence.v1':
  mission_id, contract={goal_id, acceptance_id},
  expected_tasks=[logical_task_id, ...], assignments={logical_task_id: owner_id},
  tasks=[attempt, ...], coverage_receipt={path, sha256}, acceptance_receipt={path, sha256}.

Each entry in `tasks` is one ATTEMPT at a logical task (the same relationship
actor_id has to a retried session in work_efficiency.py). attempt:
  task_id (unique per attempt), logical_task_id (must be in expected_tasks),
  owner_id (must equal assignments[logical_task_id]), attempt_id,
  parent_task_id, depends_on=[logical_task_id, ...] (identical across every
  attempt of the same logical_task_id), retry_of=task_id|null,
  hook_configured, self_report={state}, format, host_events=[{path,sha256}],
  output_artifacts=[{path,sha256}], task_acceptance_receipt={path,sha256}|null.

TRUST BOUNDARY: a sha256 proves the referenced file's bytes, at the moment
they are read here, equal the digest recorded in a receipt or host-event
log line. It proves nothing about who wrote that line, whether a host hook
actually fired, or whether a described operation actually happened -- an
adversary who controls the log/receipt files can fabricate any of that.
This validator only narrows what a fabricator would have to fake:
  - Every host_events line must name THIS mission_id and THIS attempt_id
    (host_event_mission_mismatch / host_event_attempt_mismatch), so a log
    line copied verbatim from a different mission or attempt is rejected
    even when task_id/owner_id/path happen to match.
  - Only op in {file_write, artifact_publish} with result=="success" can
    corroborate output production; a bare tool_call/command_run, or a
    failed write, never corroborates (self_report of COMPLETED plus only
    such evidence is self_report_not_host_corroborated /
    output_artifact_not_host_observed).
  - Corroboration binds to the (path, sha256) pair actually re-hashed from
    disk right now, not merely the path string, so a host event cannot be
    replayed against a mutated file.
  - A per-task acceptance receipt must be bound to this mission_id/task_id
    and must carry a verifier_id distinct from the attempt's own owner_id
    (acceptance_not_independent_of_owner) -- an owner cannot accept its own
    output. verifier_id is an unauthenticated identity string, like every
    other identity here: it narrows who MUST be named, not who is telling
    the truth.
  - A logical task resolves once ANY of its attempts is independently
    accepted; failed attempts stay visible in the roster (never deleted,
    never silently treated as successful) and a retry_of must reference an
    earlier attempt of the SAME logical_task_id whose self_report is FAILED
    (retry_logical_task_mismatch / retry_of_target_not_failed rejects a
    claimed retry of an unrelated or non-failed task). "Earlier" is the
    attempt's position in the manifest's own `tasks` list, strictly before
    the retrying attempt (retry_of_not_earlier_in_roster) -- this rejects
    both a forward reference to an attempt not yet recorded and any
    retry_of cycle, since a cycle cannot have every edge point to a
    strictly-earlier position.
  - A task can only be resolved once every logical task in its depends_on
    is itself already resolved (dependency_not_accepted); an unfinished
    graph (any expected logical task with zero accepted attempts) is
    state=INCOMPLETE, never a pass. Planning, dispatch, or an agent's own
    self_report is never sufficient by itself.
  - The mission-level acceptance receipt's own result_artifacts must each
    equal, by exact (path, sha256) pair, an output_artifacts entry of some
    independently-accepted attempt (mission_result_not_bound_to_accepted_output);
    naming a file no accepted attempt ever produced is rejected even when
    the acceptance receipt is otherwise well-formed and its own bytes
    hash-verify -- a final result must be traceable to real, corroborated
    task output, not merely to some file that happens to exist.

Output contains fixed diagnostic codes, identities and hashes only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from work_efficiency import (
    Artifacts,
    EvidenceError,
    HASH,
    IDENTITY,
    MAX_FILE_BYTES,
    MAX_LOGS,
    _events,
    _hash,
    _identity,
    _json,
    _keys,
    _require,
)

MAX_TASKS = 64
CONTRACT_KEYS = {"goal_id", "acceptance_id"}
SELF_REPORT_STATES = {"COMPLETED", "IN_PROGRESS", "FAILED", "BLOCKED"}
WRITE_OPS = {"file_write", "artifact_publish"}
CALL_OPS = {"tool_call", "command_run"}
HOST_OPS = WRITE_OPS | CALL_OPS
HOST_RESULTS = {"success", "failed"}
TASK_KEYS = {
    "task_id", "logical_task_id", "owner_id", "attempt_id", "parent_task_id",
    "depends_on", "retry_of", "hook_configured", "self_report", "format",
    "host_events", "output_artifacts", "task_acceptance_receipt",
}


def _host_event_log(raw_logs, task, mission_id):
    records = 0
    confirmed = set()
    for raw in raw_logs:
        for event in _events(raw):
            _keys(event, {"mission_id", "attempt_id", "task_id", "owner_id", "op",
                         "result", "artifact_path", "artifact_sha256"}, "host_event_invalid")
            _require(event["mission_id"] == mission_id, "host_event_mission_mismatch")
            _require(event["attempt_id"] == task["attempt_id"], "host_event_attempt_mismatch")
            _require(event["task_id"] == task["task_id"], "host_event_task_mismatch")
            _require(event["owner_id"] == task["owner_id"], "host_event_owner_mismatch")
            _require(event["op"] in HOST_OPS, "host_event_op_unknown")
            _require(event["result"] in HOST_RESULTS, "host_event_result_invalid")
            path, digest = event["artifact_path"], event["artifact_sha256"]
            if event["op"] in CALL_OPS:
                # A call alone -- successful or not -- never claims artifact production.
                _require(path is None and digest is None, "host_event_call_op_must_not_claim_artifact")
            else:
                _require(isinstance(path, str) and IDENTITY.fullmatch(path), "host_event_artifact_path_invalid")
                if event["result"] == "success":
                    _require(isinstance(digest, str) and HASH.fullmatch(digest), "host_event_artifact_digest_invalid")
                    confirmed.add((path, digest))
                else:
                    _require(digest is None, "host_event_failed_write_must_not_claim_digest")
            records += 1
    return records, confirmed


# Adapter registry is an implementation boundary; extend for another explicit
# host-observation schema (Codex/DSH own runtime adapters and protocol).
ADAPTERS = {"host_event_log_v1": _host_event_log}


def _contract(value):
    _keys(value, CONTRACT_KEYS, "contract_invalid")
    for identity in value.values():
        _identity(identity)


def _task_shape(task):
    _keys(task, TASK_KEYS, "task_invalid")
    for name in ("task_id", "logical_task_id", "owner_id", "attempt_id"):
        _identity(task[name])
    for name in ("parent_task_id", "retry_of"):
        if task[name] is not None:
            _identity(task[name])
    depends_on = task["depends_on"]
    _require(isinstance(depends_on, list) and len(depends_on) <= MAX_TASKS, "depends_on_invalid")
    for identity in depends_on:
        _identity(identity)
    _require(len(set(depends_on)) == len(depends_on), "duplicate_dependency")
    _require(task["logical_task_id"] not in depends_on, "self_dependency_invalid")
    _require(type(task["hook_configured"]) is bool, "hook_configured_invalid")
    _keys(task["self_report"], {"state"}, "self_report_invalid")
    _require(task["self_report"]["state"] in SELF_REPORT_STATES, "self_report_invalid")
    _require(task["format"] in ADAPTERS, "host_event_adapter_unknown")
    logs = task["host_events"]
    _require(isinstance(logs, list) and len(logs) <= MAX_LOGS, "host_events_invalid")
    outputs = task["output_artifacts"]
    _require(isinstance(outputs, list) and len(outputs) <= MAX_LOGS, "output_artifacts_invalid")
    receipt = task["task_acceptance_receipt"]
    _require(receipt is None or (isinstance(receipt, dict) and set(receipt) == {"path", "sha256"}),
             "task_acceptance_receipt_invalid")


def _attempts(mission):
    tasks = mission["tasks"]
    expected = mission["expected_tasks"]
    assignments = mission["assignments"]
    _require(isinstance(tasks, list) and 1 <= len(tasks) <= MAX_TASKS, "tasks_missing_or_exceeded")
    _require(isinstance(expected, list) and 1 <= len(expected) <= MAX_TASKS, "expected_tasks_missing")
    for identity in expected:
        _identity(identity)
    _require(len(set(expected)) == len(expected), "duplicate_expected_task")
    _require(isinstance(assignments, dict) and set(assignments) == set(expected), "assignment_coverage_mismatch")
    for identity in assignments.values():
        _identity(identity)
    roster = {}
    logical = {}
    index_of = {}
    for index, task in enumerate(tasks):
        _task_shape(task)
        task_id = task["task_id"]
        _require(task_id not in roster, "duplicate_task")
        roster[task_id] = task
        index_of[task_id] = index
        logical.setdefault(task["logical_task_id"], []).append(task_id)
    _require(set(logical) == set(expected), "task_coverage_mismatch")
    depends_map = {}
    for logical_id, attempt_ids in logical.items():
        depends_sets = {frozenset(roster[tid]["depends_on"]) for tid in attempt_ids}
        _require(len(depends_sets) == 1, "logical_task_dependency_inconsistent")
        deps = next(iter(depends_sets))
        for dep in deps:
            _require(dep in expected, "task_reference_invalid")
        depends_map[logical_id] = deps
        for tid in attempt_ids:
            _require(roster[tid]["owner_id"] == assignments[logical_id], "owner_assignment_mismatch")
    for task_id, task in roster.items():
        parent = task["parent_task_id"]
        if parent is not None:
            _require(parent in roster and parent != task_id, "task_reference_invalid")
        retry_of = task["retry_of"]
        if retry_of is not None:
            _require(retry_of in roster and retry_of != task_id, "retry_reference_invalid")
            target = roster[retry_of]
            _require(target["logical_task_id"] == task["logical_task_id"], "retry_logical_task_mismatch")
            _require(target["self_report"]["state"] == "FAILED", "retry_of_target_not_failed")
            # Strict roster-position ordering forbids both a forward reference
            # to an attempt not yet recorded and any retry_of cycle: a cycle
            # would require every edge to point strictly earlier, which no
            # finite loop of edges can satisfy back to its own start.
            _require(index_of[retry_of] < index_of[task_id], "retry_of_not_earlier_in_roster")
    # Bounded topological elimination over the logical dependency graph
    # catches cycles without exponential traversal through shared ancestors.
    order = []
    remaining = {key: set(deps) for key, deps in depends_map.items()}
    while remaining:
        ready = sorted(key for key, parents in remaining.items() if not parents)
        _require(bool(ready), "task_dependency_cycle")
        order.extend(ready)
        remaining = {key: parents - set(ready) for key, parents in remaining.items() if key not in ready}
    return roster, logical, depends_map, order


def _bind_task_acceptance(receipt_doc, mission, task):
    _keys(receipt_doc, {"schema", "mission_id", "task_id", "verifier_id", "state", "result_artifacts"},
          "task_acceptance_invalid")
    _require(receipt_doc["schema"] == "fames.execution-task-acceptance.v1", "task_acceptance_schema_unknown")
    _require(receipt_doc["mission_id"] == mission["mission_id"] and receipt_doc["task_id"] == task["task_id"],
             "stale_or_other_mission_receipt")
    _identity(receipt_doc["verifier_id"])
    _require(receipt_doc["verifier_id"] != task["owner_id"], "acceptance_not_independent_of_owner")
    _require(receipt_doc["state"] == "ACCEPTED", "task_not_accepted")
    results = receipt_doc["result_artifacts"]
    _require(isinstance(results, list) and 1 <= len(results) <= MAX_LOGS, "task_acceptance_results_missing")
    result_pairs = set()
    for record in results:
        _keys(record, {"path", "sha256"}, "artifact_record_invalid")
        result_pairs.add((record["path"], _hash(record["sha256"])))
    output_pairs = {(record["path"], record["sha256"]) for record in task["output_artifacts"]}
    _require(result_pairs == output_pairs, "task_acceptance_binding_mismatch")


def _validate_attempt(task, mission, artifacts):
    logs = [artifacts.read(record, log=True) for record in task["host_events"]]
    records, confirmed = ADAPTERS[task["format"]](logs, task, mission["mission_id"])
    if task["hook_configured"]:
        _require(records > 0, "host_event_missing_despite_hook_configured")
    completed = task["self_report"]["state"] == "COMPLETED"
    outputs = task["output_artifacts"]
    receipt = task["task_acceptance_receipt"]
    if not completed:
        # A failed/in-progress/blocked attempt stays visible in the roster;
        # it must never smuggle in an output or acceptance of its own.
        _require(not outputs and receipt is None, "incomplete_task_must_not_claim_artifacts_or_acceptance")
        return False
    _require(bool(outputs), "task_result_artifacts_missing")
    _require(records > 0, "self_report_not_host_corroborated")
    for record in outputs:
        artifacts.read(record, result=True)
        _require((record["path"], record["sha256"]) in confirmed, "output_artifact_not_host_observed")
    _require(receipt is not None, "task_acceptance_missing")
    _bind_task_acceptance(_json(artifacts.read(receipt)), mission, task)
    return True


def _validate_mission(mission, artifacts):
    _keys(mission, {"mission_id", "contract", "expected_tasks", "assignments", "tasks",
                    "coverage_receipt", "acceptance_receipt"}, "mission_invalid")
    _identity(mission["mission_id"])
    _contract(mission["contract"])
    roster, logical, depends_map, order = _attempts(mission)
    coverage = _json(artifacts.read(mission["coverage_receipt"]))
    _keys(coverage, {"schema", "mission_id", "contract", "expected_tasks", "assignments", "tasks",
                     "state", "all_tasks_included", "omitted_tasks", "omitted_retries"},
          "coverage_receipt_invalid")
    _require(coverage["schema"] == "fames.execution-coverage.v1" and coverage["state"] == "COMPLETE"
             and coverage["all_tasks_included"] is True and coverage["omitted_tasks"] == []
             and coverage["omitted_retries"] == [], "coverage_not_complete")
    for field in ("mission_id", "contract", "expected_tasks", "assignments", "tasks"):
        _require(coverage[field] == mission[field], "coverage_binding_mismatch")
    acceptance = _json(artifacts.read(mission["acceptance_receipt"]))
    _keys(acceptance, {"schema", "mission_id", "contract", "state", "coverage_sha256",
                       "result_artifacts", "verifier_id"}, "acceptance_receipt_invalid")
    _require(acceptance["schema"] == "fames.execution-acceptance.v1" and acceptance["state"] == "ACCEPTED",
             "mission_not_accepted")
    _identity(acceptance["verifier_id"])
    _require(acceptance["mission_id"] == mission["mission_id"] and acceptance["contract"] == mission["contract"]
             and acceptance["coverage_sha256"] == mission["coverage_receipt"]["sha256"],
             "acceptance_binding_mismatch")
    results = acceptance["result_artifacts"]
    _require(isinstance(results, list) and 1 <= len(results) <= MAX_LOGS, "accepted_results_missing")
    for result in results:
        _keys(result, {"path", "sha256"}, "artifact_record_invalid")
    resolved = {}
    attempt_accepted = {}
    # Every result claimed as a final mission output must equal, by exact
    # (path, sha256), an output of some attempt this same pass independently
    # accepts -- that attempt's own output_artifacts were already re-hashed
    # from disk in _validate_attempt, so re-reading the identical file here
    # would only collide with Artifacts' duplicate-read guard; the binding
    # is a set-membership check, not a second read.
    accepted_outputs = set()
    for logical_id in order:
        for dependency in depends_map[logical_id]:
            _require(resolved.get(dependency) is True, "dependency_not_accepted")
        any_ok = False
        for task_id in sorted(logical[logical_id]):
            ok = _validate_attempt(roster[task_id], mission, artifacts)
            attempt_accepted[task_id] = ok
            any_ok = any_ok or ok
            if ok:
                accepted_outputs.update(
                    (record["path"], record["sha256"]) for record in roster[task_id]["output_artifacts"]
                )
        resolved[logical_id] = any_ok
    for result in results:
        _require((result["path"], result["sha256"]) in accepted_outputs,
                 "mission_result_not_bound_to_accepted_output")
    return roster, attempt_accepted, resolved


def validate_execution(document, root=None):
    """Return ok/state/reasons/normalized for a bounded mission execution graph.

    ok=True ONLY when every expected logical task has at least one attempt
    independently accepted, with a host-observed successful write for each
    of its output artifacts, and closed dependencies. state=INCOMPLETE is a
    valid, non-passing result (graph not yet finished, e.g. a retry still
    pending); state=UNKNOWN means missing/invalid/tampered/unfalsifiable
    evidence. No returned string originates in raw logs.
    """
    output = {"schema": "fames.execution-evidence-result.v1", "ok": False,
              "state": "UNKNOWN", "reasons": [], "mission_id": None,
              "normalized": {"tasks": {}, "logical_tasks": {}},
              "boundary": "sha256_proves_bytes_read_now_match_a_recorded_digest_"
                           "not_observer_or_verifier_honesty_or_semantic_task_success"}
    try:
        try:
            encoded = json.dumps(document, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            raise EvidenceError("manifest_not_json_or_nonfinite") from None
        _require(len(encoded) <= MAX_FILE_BYTES, "manifest_size_exceeded")
        _keys(document, {"schema", "mission_id", "contract", "expected_tasks", "assignments",
                         "tasks", "coverage_receipt", "acceptance_receipt"}, "manifest_invalid")
        _require(document["schema"] == "fames.execution-evidence.v1", "manifest_schema_unknown")
        mission = {key: value for key, value in document.items() if key != "schema"}
        artifacts = Artifacts(Path.cwd() if root is None else root)
        roster, attempt_accepted, resolved = _validate_mission(mission, artifacts)
        output["mission_id"] = mission["mission_id"]
        output["normalized"]["tasks"] = {
            task_id: {"owner_id": roster[task_id]["owner_id"],
                     "logical_task_id": roster[task_id]["logical_task_id"],
                     "accepted": attempt_accepted[task_id]}
            for task_id in roster
        }
        output["normalized"]["logical_tasks"] = dict(resolved)
        if all(resolved.values()):
            output.update(ok=True, state="VERIFIED_EXECUTED")
        else:
            output.update(state="INCOMPLETE", reasons=["mission_incomplete"])
    except EvidenceError as exc:
        output["reasons"].append(str(exc))
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        output["reasons"].append("artifact_unavailable_or_invalid")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate a bounded offline mission execution graph")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    try:
        _require(not str(args.input).startswith(("\\\\", "//")), "manifest_not_local")
        input_path = args.input.resolve(strict=True)
        _require(not str(input_path).startswith(("\\\\", "//")), "manifest_not_local")
        with input_path.open("rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
        _require(len(raw) <= MAX_FILE_BYTES, "manifest_size_exceeded")
        result = validate_execution(_json(raw), root=args.root or input_path.parent)
    except (EvidenceError, OSError, RuntimeError):
        result = {"ok": False, "state": "UNKNOWN", "reasons": ["manifest_unavailable_or_invalid"], "normalized": {}}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
