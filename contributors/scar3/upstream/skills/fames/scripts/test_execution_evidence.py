"""Offline regression fixtures for execution_evidence; no host/model dependency."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import execution_evidence as evidence

MISSION_ID = "mission-1"


class ExecutionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def artifact(self, name, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
        (self.root / name).write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}

    def event(self, task, op="file_write", result="success", artifact=None, mission_id=MISSION_ID):
        ev = {"mission_id": mission_id, "attempt_id": task["attempt_id"], "task_id": task["task_id"],
              "owner_id": task["owner_id"], "op": op, "result": result,
              "artifact_path": None, "artifact_sha256": None}
        if op in evidence.WRITE_OPS and result == "success":
            ev["artifact_path"] = artifact["path"]
            ev["artifact_sha256"] = artifact["sha256"]
        elif op in evidence.WRITE_OPS:
            ev["artifact_path"] = artifact["path"] if artifact else "unwritten.txt"
        return ev

    def host_log(self, name, events):
        raw = b"\n".join(json.dumps(e).encode("utf-8") for e in events) + b"\n"
        return self.artifact(name, raw)

    def make_task(self, task_id, logical_task_id=None, owner_id="owner-1", depends_on=None,
                 parent=None, retry_of=None, hook_configured=True, state="COMPLETED",
                 output_names=None, events="auto", accept=True, verifier_id="verifier-1",
                 mission_id=MISSION_ID):
        logical_task_id = logical_task_id or task_id
        depends_on = depends_on or []
        if output_names is None:
            output_names = [task_id + "-out.txt"] if state == "COMPLETED" else []
        outputs = [self.artifact(name, ("result for " + task_id).encode("utf-8")) for name in output_names]
        task = {"task_id": task_id, "logical_task_id": logical_task_id, "owner_id": owner_id,
                "attempt_id": task_id + "-attempt", "parent_task_id": parent, "depends_on": depends_on,
                "retry_of": retry_of, "hook_configured": hook_configured,
                "self_report": {"state": state}, "format": "host_event_log_v1",
                "host_events": [], "output_artifacts": outputs, "task_acceptance_receipt": None}
        if events == "auto":
            events = [self.event(task, artifact=out, mission_id=mission_id) for out in outputs]
        task["host_events"] = [self.host_log(task_id + "-hostlog.jsonl", events)] if events else []
        if state == "COMPLETED" and accept:
            receipt_doc = {"schema": "fames.execution-task-acceptance.v1", "mission_id": mission_id,
                           "task_id": task_id, "verifier_id": verifier_id, "state": "ACCEPTED",
                           "result_artifacts": deepcopy(outputs)}
            task["task_acceptance_receipt"] = self.artifact(task_id + "-task-acceptance.json", receipt_doc)
        return task

    def seal(self, mission, result_artifacts=None):
        coverage = {"schema": "fames.execution-coverage.v1", "state": "COMPLETE",
                    "all_tasks_included": True, "omitted_tasks": [], "omitted_retries": []}
        coverage.update({key: deepcopy(mission[key]) for key in
                         ("mission_id", "contract", "expected_tasks", "assignments", "tasks")})
        mission["coverage_receipt"] = self.artifact(mission["mission_id"] + "-coverage.json", coverage)
        if result_artifacts is None:
            # Default final result is bound to a real, completed attempt's own
            # output -- an arbitrary unrelated file is only ever used when no
            # task has one (a test exercising an earlier, unrelated failure).
            result_artifacts = [deepcopy(output) for task in mission["tasks"]
                                if task["self_report"]["state"] == "COMPLETED"
                                for output in task["output_artifacts"]]
            if not result_artifacts:
                result_artifacts = [self.artifact(mission["mission_id"] + "-result.txt",
                                                   b"mission accepted\n")]
        acceptance = {"schema": "fames.execution-acceptance.v1", "mission_id": mission["mission_id"],
                      "contract": mission["contract"], "state": "ACCEPTED", "verifier_id": "mission-verifier",
                      "coverage_sha256": mission["coverage_receipt"]["sha256"],
                      "result_artifacts": result_artifacts}
        mission["acceptance_receipt"] = self.artifact(mission["mission_id"] + "-acceptance.json", acceptance)
        return mission

    def build_mission(self, tasks, mission_id=MISSION_ID):
        expected = sorted({task["logical_task_id"] for task in tasks})
        assignments = {}
        for task in tasks:
            assignments.setdefault(task["logical_task_id"], task["owner_id"])
        mission = {"mission_id": mission_id, "contract": {"goal_id": "goal-1", "acceptance_id": "accept-1"},
                   "expected_tasks": expected, "assignments": assignments, "tasks": tasks}
        return self.seal(mission)

    def document(self, mission):
        return {"schema": "fames.execution-evidence.v1", **mission}

    def assert_unknown(self, document, reason=None):
        result = evidence.validate_execution(document, root=self.root)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["state"], "UNKNOWN", result)
        if reason:
            self.assertIn(reason, result["reasons"])
        return result

    # --- positive control -------------------------------------------------

    def test_positive_control_single_task(self):
        mission = self.build_mission([self.make_task("t1")])
        result = evidence.validate_execution(self.document(mission), root=self.root)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "VERIFIED_EXECUTED")
        self.assertEqual(result["mission_id"], MISSION_ID)
        self.assertTrue(result["normalized"]["logical_tasks"]["t1"])
        self.assertEqual(result["normalized"]["tasks"]["t1"]["accepted"], True)

    def test_dependency_closure_passes_when_both_accepted(self):
        parent = self.make_task("parent")
        child = self.make_task("child", depends_on=["parent"], parent="parent")
        mission = self.build_mission([parent, child])
        result = evidence.validate_execution(self.document(mission), root=self.root)
        self.assertTrue(result["ok"], result)

    # --- structural / coverage faults -------------------------------------

    def test_dependency_not_accepted_when_parent_incomplete(self):
        parent = self.make_task("parent", state="IN_PROGRESS", hook_configured=False, events=[])
        child = self.make_task("child", depends_on=["parent"], parent="parent")
        mission = self.build_mission([parent, child])
        self.assert_unknown(self.document(mission), "dependency_not_accepted")

    def test_missing_child_result_artifact_is_unknown(self):
        task = self.make_task("t1", output_names=[], events=[], hook_configured=False)
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "task_result_artifacts_missing")

    def test_task_coverage_mismatch_for_undeclared_task(self):
        mission = self.build_mission([self.make_task("t1")])
        mission["expected_tasks"].append("ghost")
        mission["assignments"]["ghost"] = "owner-1"
        self.seal(mission)
        self.assert_unknown(self.document(mission), "task_coverage_mismatch")

    def test_owner_assignment_mismatch(self):
        mission = self.build_mission([self.make_task("t1")])
        mission["assignments"]["t1"] = "someone-else"
        self.seal(mission)
        self.assert_unknown(self.document(mission), "owner_assignment_mismatch")

    def test_dependency_cycle_is_unknown(self):
        a = self.make_task("a", depends_on=["b"])
        b = self.make_task("b", depends_on=["a"])
        mission = self.build_mission([a, b])
        self.assert_unknown(self.document(mission), "task_dependency_cycle")

    def test_mutated_output_fails_hash_check(self):
        mission = self.build_mission([self.make_task("t1")])
        path = self.root / mission["tasks"][0]["output_artifacts"][0]["path"]
        path.write_bytes(path.read_bytes() + b" tampered")
        self.assert_unknown(self.document(mission), "artifact_hash_mismatch")

    def test_unfinished_graph_is_incomplete_not_pass(self):
        done = self.make_task("done")
        pending = self.make_task("pending", state="IN_PROGRESS", hook_configured=False, events=[])
        mission = self.build_mission([done, pending])
        result = evidence.validate_execution(self.document(mission), root=self.root)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["state"], "INCOMPLETE")
        self.assertIn("mission_incomplete", result["reasons"])
        self.assertTrue(result["normalized"]["logical_tasks"]["done"])
        self.assertFalse(result["normalized"]["logical_tasks"]["pending"])

    def test_incomplete_task_may_not_claim_artifacts_or_acceptance(self):
        task = self.make_task("t1", state="IN_PROGRESS", hook_configured=False,
                              output_names=["should-not-exist.txt"], events=[])
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "incomplete_task_must_not_claim_artifacts_or_acceptance")

    def test_omitted_retry_is_unknown(self):
        failed = self.make_task("failed-attempt", state="FAILED", hook_configured=False, events=[])
        retry = self.make_task("retry", logical_task_id="failed-attempt", retry_of="failed-attempt")
        mission = self.build_mission([failed, retry])
        coverage_path = mission["coverage_receipt"]["path"]
        coverage = json.loads((self.root / coverage_path).read_text())
        coverage["omitted_retries"] = ["retry"]
        mission["coverage_receipt"] = self.artifact(coverage_path, coverage)
        self.assert_unknown(self.document(mission), "coverage_not_complete")

    def test_host_event_missing_despite_hook_configured(self):
        task = self.make_task("t1", hook_configured=True, events=[])
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "host_event_missing_despite_hook_configured")

    def test_task_acceptance_missing_when_completed(self):
        task = self.make_task("t1", accept=False)
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "task_acceptance_missing")

    def test_mission_not_accepted_when_receipt_state_wrong(self):
        mission = self.build_mission([self.make_task("t1")])
        path = mission["acceptance_receipt"]["path"]
        receipt = json.loads((self.root / path).read_text())
        receipt["state"] = "UNKNOWN"
        mission["acceptance_receipt"] = self.artifact(path, receipt)
        self.assert_unknown(self.document(mission), "mission_not_accepted")

    def test_manifest_schema_and_shape_are_unknown(self):
        mission = self.build_mission([self.make_task("t1")])
        doc = self.document(mission)
        doc["schema"] = "wrong-schema"
        self.assert_unknown(doc, "manifest_schema_unknown")
        doc["schema"] = "fames.execution-evidence.v1"
        doc["extra_key"] = 1
        self.assert_unknown(doc, "manifest_invalid")

    # --- Codex review round: cross-mission/attempt replay -----------------

    def test_host_event_from_another_mission_is_rejected(self):
        task = self.make_task("t1", events=[])
        replayed = [self.event(task, artifact=task["output_artifacts"][0], mission_id="other-mission")]
        task["host_events"] = [self.host_log("t1-hostlog.jsonl", replayed)]
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "host_event_mission_mismatch")

    def test_host_event_from_another_attempt_is_rejected(self):
        task = self.make_task("t1", events=[])
        stolen = self.event(task, artifact=task["output_artifacts"][0])
        stolen["attempt_id"] = "some-other-attempt"
        task["host_events"] = [self.host_log("t1-hostlog.jsonl", [stolen])]
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "host_event_attempt_mismatch")

    def test_host_event_with_stale_digest_does_not_corroborate_current_bytes(self):
        # Same mission/attempt/task/owner/path, but the digest was recorded
        # for different bytes than the ones now on disk -- a rewrapped event
        # must not corroborate the current output.
        task = self.make_task("t1", events=[])
        stale = self.event(task, artifact=task["output_artifacts"][0])
        stale["artifact_sha256"] = hashlib.sha256(b"different content entirely").hexdigest()
        task["host_events"] = [self.host_log("t1-hostlog.jsonl", [stale])]
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "output_artifact_not_host_observed")

    # --- Codex review round: only successful writes corroborate -----------

    def test_tool_call_alone_does_not_corroborate_output(self):
        task = self.make_task("t1", events=[])
        calls = [self.event(task, op="tool_call", result="success")]
        task["host_events"] = [self.host_log("t1-hostlog.jsonl", calls)]
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "output_artifact_not_host_observed")

    def test_failed_write_does_not_corroborate_output(self):
        task = self.make_task("t1", events=[])
        failed_write = self.event(task, op="file_write", result="failed",
                                  artifact=task["output_artifacts"][0])
        task["host_events"] = [self.host_log("t1-hostlog.jsonl", [failed_write])]
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "output_artifact_not_host_observed")

    def test_call_op_may_not_claim_an_artifact(self):
        task = self.make_task("t1", events=[])
        bad = self.event(task, op="tool_call", result="success")
        bad["artifact_path"] = task["output_artifacts"][0]["path"]
        task["host_events"] = [self.host_log("t1-hostlog.jsonl", [bad])]
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "host_event_call_op_must_not_claim_artifact")

    # --- Codex review round: retry recovery of a logical task --------------

    def test_successful_retry_resolves_logical_task_after_earlier_failure(self):
        failed = self.make_task("t1-try1", logical_task_id="t1", state="FAILED",
                                hook_configured=False, events=[])
        retry = self.make_task("t1-try2", logical_task_id="t1", retry_of="t1-try1")
        mission = self.build_mission([failed, retry])
        result = evidence.validate_execution(self.document(mission), root=self.root)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["normalized"]["logical_tasks"]["t1"])
        self.assertFalse(result["normalized"]["tasks"]["t1-try1"]["accepted"])
        self.assertTrue(result["normalized"]["tasks"]["t1-try2"]["accepted"])

    def test_retry_of_unrelated_logical_task_is_rejected(self):
        failed = self.make_task("t1-try1", logical_task_id="t1", state="FAILED",
                                hook_configured=False, events=[])
        other = self.make_task("t2", logical_task_id="t2")
        claimed = self.make_task("t1-try2", logical_task_id="t1", retry_of="t2")
        mission = self.build_mission([failed, other, claimed])
        self.assert_unknown(self.document(mission), "retry_logical_task_mismatch")

    def test_retry_of_non_failed_target_is_rejected(self):
        succeeded = self.make_task("t1-try1", logical_task_id="t1")
        claimed_retry = self.make_task("t1-try2", logical_task_id="t1", retry_of="t1-try1")
        mission = self.build_mission([succeeded, claimed_retry])
        self.assert_unknown(self.document(mission), "retry_of_target_not_failed")

    # --- Codex review round: acceptance independence -----------------------

    def test_owner_cannot_accept_own_output(self):
        task = self.make_task("t1", owner_id="owner-1", verifier_id="owner-1")
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "acceptance_not_independent_of_owner")

    def test_stale_or_other_mission_receipt(self):
        task = self.make_task("t1")
        stale_doc = {"schema": "fames.execution-task-acceptance.v1", "mission_id": "other-mission",
                    "task_id": "t1", "verifier_id": "verifier-1", "state": "ACCEPTED",
                    "result_artifacts": deepcopy(task["output_artifacts"])}
        task["task_acceptance_receipt"] = self.artifact("t1-task-acceptance.json", stale_doc)
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "stale_or_other_mission_receipt")

    # --- independent review round: unobserved final result / retry roster --

    def test_mission_result_naming_unproduced_file_is_rejected(self):
        # Reproduces the reported fail-open: an accepted mission's own final
        # result_artifacts pointed at a file no task ever produced or had
        # accepted, and the validator wrongly returned VERIFIED_EXECUTED.
        mission = self.build_mission([self.make_task("t1")])
        unrelated = self.artifact("unrelated-result.txt", b"never produced by any task")
        acceptance_path = mission["acceptance_receipt"]["path"]
        acceptance = json.loads((self.root / acceptance_path).read_text())
        acceptance["result_artifacts"] = [unrelated]
        mission["acceptance_receipt"] = self.artifact(acceptance_path, acceptance)
        self.assert_unknown(self.document(mission), "mission_result_not_bound_to_accepted_output")

    def test_mission_result_bound_to_accepted_output_still_passes(self):
        # Positive control for the fix above: the final result is exactly
        # the accepted task's own output, and must still verify.
        mission = self.build_mission([self.make_task("t1")])
        result = evidence.validate_execution(self.document(mission), root=self.root)
        self.assertTrue(result["ok"], result)
        acceptance_path = mission["acceptance_receipt"]["path"]
        acceptance = json.loads((self.root / acceptance_path).read_text())
        self.assertEqual(acceptance["result_artifacts"], mission["tasks"][0]["output_artifacts"])

    def test_retry_of_cycle_is_rejected(self):
        # Reproduces the reported fail-open: two FAILED attempts pointing
        # retry_of at each other (a cycle), with a third successful attempt
        # retrying one of them, previously passed as VERIFIED_EXECUTED.
        a = self.make_task("a", logical_task_id="work", state="FAILED",
                           hook_configured=False, events=[], retry_of="b")
        b = self.make_task("b", logical_task_id="work", state="FAILED",
                           hook_configured=False, events=[], retry_of="a")
        c = self.make_task("c", logical_task_id="work", retry_of="b")
        mission = self.build_mission([a, b, c])
        self.assert_unknown(self.document(mission), "retry_of_not_earlier_in_roster")

    def test_retry_of_forward_reference_is_rejected(self):
        forward = self.make_task("t1-try1", logical_task_id="t1", retry_of="t1-try2")
        target = self.make_task("t1-try2", logical_task_id="t1", state="FAILED",
                                hook_configured=False, events=[])
        mission = self.build_mission([forward, target])
        self.assert_unknown(self.document(mission), "retry_of_not_earlier_in_roster")

    def test_retry_recovery_with_earlier_failure_still_passes(self):
        # Positive control for the roster-order fix: a real failed-then-
        # successful-retry history (earlier attempt strictly before its
        # retry) must keep resolving the logical task.
        failed = self.make_task("t1-try1", logical_task_id="t1", state="FAILED",
                                hook_configured=False, events=[])
        retry = self.make_task("t1-try2", logical_task_id="t1", retry_of="t1-try1")
        mission = self.build_mission([failed, retry])
        result = evidence.validate_execution(self.document(mission), root=self.root)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["normalized"]["logical_tasks"]["t1"])
        self.assertFalse(result["normalized"]["tasks"]["t1-try1"]["accepted"])
        self.assertTrue(result["normalized"]["tasks"]["t1-try2"]["accepted"])


if __name__ == "__main__":
    unittest.main()
