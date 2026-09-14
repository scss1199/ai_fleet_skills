#!/usr/bin/env python3
"""Offline validator of a bounded mission/execution graph; no model/network calls.

Public API: validate_execution(document, root=None), defaulting root to the
current working directory at call time. See execution-interface.md (mission
evidence/mission-command-20260914) for the full schema. Document shape is
schema='fames.execution-evidence.v1': mission_id, contract={goal_id,
acceptance_id}, expected_tasks=[task_id,...], assignments={task_id:owner_id},
tasks=[task,...], coverage_receipt={path,sha256}, acceptance_receipt=
{path,sha256}.

Each task declares an expected owner/dependencies, an agent self_report, a
host_events log (format-selected adapter, analogous to work_efficiency's
usage adapters) and output_artifacts. TRUST BOUNDARY: hashes prove artifact
bytes are unchanged since they were recorded in a receipt or log; they do not
prove the log author, host hook, or agent was honest, or that a described
operation actually happened. A self_report of COMPLETED is never sufficient
by itself -- it must be corroborated by a host_events entry naming the same
task/owner and the same output artifact path, and closed by an independent
per-task acceptance receipt bound to this mission_id/task_id and to the exact
(path, sha256) set of the task's own output_artifacts. A task can only count
as accepted if every task it depends_on is itself already accepted
(dependency closure); an unfinished graph is state=INCOMPLETE, never PASS.

Output contains fixed diagnostic codes, identities and hashes only: no source
text, raw exceptions, or claims of semantic task success beyond what these
external receipts assert.
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
    MAX_COUNT,
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
HOST_OPS = {"file_write", "artifact_publish", "tool_call", "command_run"}
TASK_KEYS = {
    "task_id", "owner_id", "attempt_id", "parent_task_id", "depends_on",
    "retry_of", "hook_configured", "self_report", "format", "host_events",
    "output_artifacts", "task_acceptance_receipt",
}


def _host_event_log(raw_logs, task, shared):
    records = 0
    confirmed = set()
    for raw in raw_logs:
        for event in _events(raw):
            _keys(event, {"task_id", "owner_id", "op", "artifact_path"}, "host_event_invalid")
            _require(event["task_id"] == task["task_id"], "host_event_task_mismatch")
            _require(event["owner_id"] == task["owner_id"], "host_event_owner_mismatch")
            _require(event["op"] in HOST_OPS, "host_event_op_unknown")
            path = event["artifact_path"]
            _require(path is None or (isinstance(path, str) and IDENTITY.fullmatch(path)),
                     "host_event_artifact_path_invalid")
            if path is not None:
                confirmed.add(path)
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
    for name in ("task_id", "owner_id", "attempt_id"):
        _identity(task[name])
    for name in ("parent_task_id", "retry_of"):
        if task[name] is not None:
            _identity(task[name])
    depends_on = task["depends_on"]
    _require(isinstance(depends_on, list) and len(depends_on) <= MAX_TASKS, "depends_on_invalid")
    for identity in depends_on:
        _identity(identity)
    _require(len(set(depends_on)) == len(depends_on), "duplicate_dependency")
    _require(task["task_id"] not in depends_on, "self_dependency_invalid")
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


def _tasks(mission):
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
    for task in tasks:
        _task_shape(task)
        task_id = task["task_id"]
        _require(task_id not in roster, "duplicate_task")
        roster[task_id] = task
    _require(set(roster) == set(expected), "task_coverage_mismatch")
    for task_id, task in roster.items():
        _require(task["owner_id"] == assignments[task_id], "owner_assignment_mismatch")
    dependencies = {}
    for task_id, task in roster.items():
        edges = set(task["depends_on"])
        for field in ("parent_task_id", "retry_of"):
            target = task[field]
            if target is not None:
                edges.add(target)
        for target in edges:
            _require(target in roster, "task_reference_invalid")
        dependencies[task_id] = edges
    # Bounded topological elimination catches cycles across depends_on/retry/
    # parent edges without exponential traversal through shared ancestors.
    order = []
    remaining = dict(dependencies)
    while remaining:
        ready = sorted(key for key, parents in remaining.items() if not parents)
        _require(bool(ready), "task_dependency_cycle")
        order.extend(ready)
        remaining = {key: parents - set(ready) for key, parents in remaining.items() if key not in ready}
    return roster, order


def _bind_task_acceptance(receipt_doc, mission, task):
    _keys(receipt_doc, {"schema", "mission_id", "task_id", "state", "result_artifacts"},
          "task_acceptance_invalid")
    _require(receipt_doc["schema"] == "fames.execution-task-acceptance.v1", "task_acceptance_schema_unknown")
    _require(receipt_doc["mission_id"] == mission["mission_id"] and receipt_doc["task_id"] == task["task_id"],
             "stale_or_other_mission_receipt")
    _require(receipt_doc["state"] == "ACCEPTED", "task_not_accepted")
    results = receipt_doc["result_artifacts"]
    _require(isinstance(results, list) and 1 <= len(results) <= MAX_LOGS, "task_acceptance_results_missing")
    result_pairs = set()
    for record in results:
        _keys(record, {"path", "sha256"}, "artifact_record_invalid")
        result_pairs.add((record["path"], _hash(record["sha256"])))
    output_pairs = {(record["path"], record["sha256"]) for record in task["output_artifacts"]}
    _require(result_pairs == output_pairs, "task_acceptance_binding_mismatch")


def _validate_task(task, mission, artifacts, accepted):
    logs = [artifacts.read(record, log=True) for record in task["host_events"]]
    records, confirmed = ADAPTERS[task["format"]](logs, task, {})
    if task["hook_configured"]:
        _require(records > 0, "host_event_missing_despite_hook_configured")
    completed = task["self_report"]["state"] == "COMPLETED"
    outputs = task["output_artifacts"]
    receipt = task["task_acceptance_receipt"]
    if not completed:
        _require(not outputs and receipt is None, "incomplete_task_must_not_claim_artifacts_or_acceptance")
        return False
    _require(bool(outputs), "task_result_artifacts_missing")
    _require(records > 0, "self_report_not_host_corroborated")
    for record in outputs:
        artifacts.read(record, result=True)
        _require(record["path"] in confirmed, "output_artifact_not_host_observed")
    _require(receipt is not None, "task_acceptance_missing")
    _bind_task_acceptance(_json(artifacts.read(receipt)), mission, task)
    for dependency in task["depends_on"]:
        _require(accepted.get(dependency) is True, "dependency_not_accepted")
    return True


def _validate_mission(mission, artifacts):
    _keys(mission, {"mission_id", "contract", "expected_tasks", "assignments", "tasks",
                    "coverage_receipt", "acceptance_receipt"}, "mission_invalid")
    _identity(mission["mission_id"])
    _contract(mission["contract"])
    roster, order = _tasks(mission)
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
    _keys(acceptance, {"schema", "mission_id", "contract", "state", "coverage_sha256", "result_artifacts"},
          "acceptance_receipt_invalid")
    _require(acceptance["schema"] == "fames.execution-acceptance.v1" and acceptance["state"] == "ACCEPTED",
             "mission_not_accepted")
    _require(acceptance["mission_id"] == mission["mission_id"] and acceptance["contract"] == mission["contract"]
             and acceptance["coverage_sha256"] == mission["coverage_receipt"]["sha256"],
             "acceptance_binding_mismatch")
    results = acceptance["result_artifacts"]
    _require(isinstance(results, list) and 1 <= len(results) <= MAX_LOGS, "accepted_results_missing")
    for result in results:
        artifacts.read(result, result=True)
    accepted = {}
    for task_id in order:
        accepted[task_id] = _validate_task(roster[task_id], mission, artifacts, accepted)
    return roster, accepted


def validate_execution(document, root=None):
    """Return ok/state/reasons/normalized for a bounded mission execution graph.

    ok=True ONLY when every declared task is independently accepted with a
    host-observed operation for each output artifact and closed dependencies.
    state=INCOMPLETE is a valid, non-passing result (graph not yet finished);
    state=UNKNOWN means missing/invalid/tampered evidence. No returned string
    originates in raw logs.
    """
    output = {"schema": "fames.execution-evidence-result.v1", "ok": False,
              "state": "UNKNOWN", "reasons": [], "mission_id": None, "normalized": {"tasks": {}},
              "boundary": "hashes_prove_bytes_unchanged_since_recorded_observation_"
                           "not_observer_honesty_or_semantic_task_success"}
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
        roster, accepted = _validate_mission(mission, artifacts)
        output["mission_id"] = mission["mission_id"]
        output["normalized"]["tasks"] = {
            task_id: {"owner_id": roster[task_id]["owner_id"], "accepted": accepted[task_id]}
            for task_id in roster
        }
        if all(accepted.values()):
            output.update(ok=True, state="VERIFIED_EXECUTED")
        else:
            output.update(state="INCOMPLETE",
                          reasons=["mission_incomplete"])
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
