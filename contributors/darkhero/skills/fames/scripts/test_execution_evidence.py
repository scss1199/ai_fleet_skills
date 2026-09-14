"""Offline regression fixtures for execution_evidence; no host/model dependency."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import execution_evidence as evidence


class ExecutionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def artifact(self, name, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
        (self.root / name).write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}

    def host_log(self, name, events):
        raw = b"\n".join(json.dumps(event).encode("utf-8") for event in events) + b"\n"
        return self.artifact(name, raw)

    def make_task(self, task_id, owner_id="owner-1", depends_on=None, parent=None, retry_of=None,
                  hook_configured=True, state="COMPLETED", output_names=None, host_ops="auto",
                  accept=True, mission_id="mission-1"):
        depends_on = depends_on or []
        if output_names is None:
            output_names = [task_id + "-out.txt"] if state == "COMPLETED" else []
        outputs = [self.artifact(name, ("result for " + task_id).encode("utf-8")) for name in output_names]
        if host_ops == "auto":
            host_ops = [{"task_id": task_id, "owner_id": owner_id, "op": "file_write", "artifact_path": name}
                        for name in output_names]
        logs = [self.host_log(task_id + "-hostlog.jsonl", host_ops)] if host_ops else []
        receipt = None
        if state == "COMPLETED" and accept:
            receipt_doc = {"schema": "fames.execution-task-acceptance.v1", "mission_id": mission_id,
                           "task_id": task_id, "state": "ACCEPTED", "result_artifacts": deepcopy(outputs)}
            receipt = self.artifact(task_id + "-task-acceptance.json", receipt_doc)
        return {"task_id": task_id, "owner_id": owner_id, "attempt_id": "attempt-1",
                "parent_task_id": parent, "depends_on": depends_on, "retry_of": retry_of,
                "hook_configured": hook_configured, "self_report": {"state": state},
                "format": "host_event_log_v1", "host_events": logs, "output_artifacts": outputs,
                "task_acceptance_receipt": receipt}

    def seal(self, mission):
        coverage = {"schema": "fames.execution-coverage.v1", "state": "COMPLETE",
                    "all_tasks_included": True, "omitted_tasks": [], "omitted_retries": []}
        coverage.update({key: deepcopy(mission[key]) for key in
                         ("mission_id", "contract", "expected_tasks", "assignments", "tasks")})
        mission["coverage_receipt"] = self.artifact(mission["mission_id"] + "-coverage.json", coverage)
        acceptance = {"schema": "fames.execution-acceptance.v1", "mission_id": mission["mission_id"],
                      "contract": mission["contract"], "state": "ACCEPTED",
                      "coverage_sha256": mission["coverage_receipt"]["sha256"],
                      "result_artifacts": [self.artifact(mission["mission_id"] + "-result.txt",
                                                          b"mission accepted\n")]}
        mission["acceptance_receipt"] = self.artifact(mission["mission_id"] + "-acceptance.json", acceptance)
        return mission

    def build_mission(self, tasks, mission_id="mission-1"):
        mission = {"mission_id": mission_id, "contract": {"goal_id": "goal-1", "acceptance_id": "accept-1"},
                   "expected_tasks": [task["task_id"] for task in tasks],
                   "assignments": {task["task_id"]: task["owner_id"] for task in tasks}, "tasks": tasks}
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

    def test_positive_control_single_task(self):
        mission = self.build_mission([self.make_task("t1")])
        result = evidence.validate_execution(self.document(mission), root=self.root)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "VERIFIED_EXECUTED")
        self.assertEqual(result["mission_id"], "mission-1")
        self.assertEqual(result["normalized"]["tasks"], {"t1": {"owner_id": "owner-1", "accepted": True}})

    def test_dependency_closure_passes_when_both_accepted(self):
        parent = self.make_task("parent")
        child = self.make_task("child", depends_on=["parent"], parent="parent")
        mission = self.build_mission([parent, child])
        result = evidence.validate_execution(self.document(mission), root=self.root)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["normalized"]["tasks"]["child"]["accepted"])

    def test_dependency_not_accepted_when_parent_incomplete(self):
        parent = self.make_task("parent", state="IN_PROGRESS", hook_configured=False)
        child = self.make_task("child", depends_on=["parent"], parent="parent")
        mission = self.build_mission([parent, child])
        self.assert_unknown(self.document(mission), "dependency_not_accepted")

    def test_missing_child_result_artifact_is_unknown(self):
        task = self.make_task("t1", output_names=[], host_ops=[], hook_configured=False)
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

    def test_stale_or_other_mission_receipt(self):
        task = self.make_task("t1")
        stale_doc = {"schema": "fames.execution-task-acceptance.v1", "mission_id": "other-mission",
                    "task_id": "t1", "state": "ACCEPTED", "result_artifacts": deepcopy(task["output_artifacts"])}
        task["task_acceptance_receipt"] = self.artifact("t1-task-acceptance.json", stale_doc)
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "stale_or_other_mission_receipt")

    def test_omitted_retry_is_unknown(self):
        parent = self.make_task("parent")
        retry = self.make_task("retry", retry_of="parent")
        mission = self.build_mission([parent, retry])
        coverage_path = mission["coverage_receipt"]["path"]
        coverage = json.loads((self.root / coverage_path).read_text())
        coverage["omitted_retries"] = ["retry"]
        mission["coverage_receipt"] = self.artifact(coverage_path, coverage)
        self.assert_unknown(self.document(mission), "coverage_not_complete")

    def test_host_event_missing_despite_hook_configured(self):
        task = self.make_task("t1", hook_configured=True, host_ops=[])
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "host_event_missing_despite_hook_configured")

    def test_false_agent_completion_without_host_observed_output(self):
        misdirected = [{"task_id": "t1", "owner_id": "owner-1", "op": "file_write",
                        "artifact_path": "unrelated-file.txt"}]
        task = self.make_task("t1", host_ops=misdirected)
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "output_artifact_not_host_observed")

    def test_incomplete_task_may_not_claim_artifacts_or_acceptance(self):
        task = self.make_task("t1", state="IN_PROGRESS", hook_configured=False,
                              output_names=["should-not-exist.txt"], host_ops=[])
        mission = self.build_mission([task])
        self.assert_unknown(self.document(mission), "incomplete_task_must_not_claim_artifacts_or_acceptance")

    def test_unfinished_graph_is_incomplete_not_pass(self):
        done = self.make_task("done")
        pending = self.make_task("pending", state="IN_PROGRESS", hook_configured=False)
        mission = self.build_mission([done, pending])
        result = evidence.validate_execution(self.document(mission), root=self.root)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["state"], "INCOMPLETE")
        self.assertIn("mission_incomplete", result["reasons"])
        self.assertTrue(result["normalized"]["tasks"]["done"]["accepted"])
        self.assertFalse(result["normalized"]["tasks"]["pending"]["accepted"])

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


if __name__ == "__main__":
    unittest.main()
