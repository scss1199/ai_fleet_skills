"""Offline regression fixtures; synthetic usage is test evidence, not savings."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import work_efficiency as efficiency


class EfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def artifact(self, name, value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
        (self.root / name).write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}

    def claude(self, session, message, ordinary=50, creation=10, cached=20, output=30, thinking=5):
        return {"type": "assistant", "sessionId": session,
                "message": {"id": message, "model": "test-model", "content": [{"text": "SECRET_PROMPT_SENTINEL"}],
                            "usage": {"input_tokens": ordinary, "cache_creation_input_tokens": creation,
                                      "cache_read_input_tokens": cached, "output_tokens": output,
                                      "thinking_tokens": thinking,
                                      "cache_creation": {"ephemeral_5m_input_tokens": creation,
                                                         "ephemeral_1h_input_tokens": 0}}}}

    def codex(self, session, input_tokens=120, cached=70, output=50, reasoning=30):
        usage = {"input_tokens": input_tokens, "cached_input_tokens": cached,
                 "output_tokens": output, "reasoning_output_tokens": reasoning,
                 "total_tokens": input_tokens + output}
        event = {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": usage}}}
        return [{"type": "session_meta", "payload": {"id": session}},
                {"type": "turn_context", "payload": {"model": "test-model"}}, event]

    def actor(self, run_id, actor_id="parent", parent=None, events=None, format="claude_jsonl_v1", retry_of=None):
        session = run_id + "-" + actor_id
        if events is None:
            events = [self.claude(session, session + "-message")]
        log = self.artifact(session + ".jsonl", b"\n".join(json.dumps(item).encode("utf-8") for item in events) + b"\n")
        return {"actor_id": actor_id, "parent_actor_id": parent, "attempt_id": "attempt-1",
                "retry_of": retry_of, "session_id": session, "format": format, "logs": [log]}

    def seal(self, run):
        coverage = {"schema": "fames.work-coverage.v1", "state": "COMPLETE", "all_usage_included": True,
                    "omitted_actors": [], "omitted_retries": []}
        coverage.update({key: deepcopy(run[key]) for key in ("run_id", "contract", "scope", "actors")})
        run["coverage_receipt"] = self.artifact(run["run_id"] + "-coverage.json", coverage)
        acceptance = {"schema": "fames.work-acceptance.v1", "state": "ACCEPTED", "run_id": run["run_id"],
                      "contract": run["contract"], "coverage_sha256": run["coverage_receipt"]["sha256"],
                      "result_artifacts": [self.artifact(run["run_id"] + "-result.txt", b"accepted final result\n")]}
        run["acceptance_receipt"] = self.artifact(run["run_id"] + "-acceptance.json", acceptance)
        return run

    def run_record(self, run_id, actors=None):
        actors = actors or [self.actor(run_id)]
        return self.seal({"run_id": run_id,
                          "contract": {"goal_id": "same-goal", "model_id": "test-model",
                                       "config_id": "same-config", "acceptance_id": "same-criteria"},
                          "scope": deepcopy(efficiency.SCOPE), "expected_actors": [a["actor_id"] for a in actors],
                          "actors": actors})

    def document(self):
        baseline = self.run_record("baseline")
        candidate = self.run_record("candidate", [self.actor("candidate", events=[
            self.claude("candidate-parent", "candidate-message", ordinary=20, creation=5, cached=10, output=20)])])
        return {"schema": "fames.work-efficiency.v1", "baseline": baseline, "candidate": candidate}

    def replace_log(self, run, events, actor_index=0):
        actor = run["actors"][actor_index]
        actor["logs"] = [self.artifact(actor["session_id"] + ".jsonl",
                                       b"\n".join(json.dumps(item).encode("utf-8") for item in events) + b"\n")]
        self.seal(run)

    def assert_unknown(self, document, reason=None):
        result = efficiency.validate_efficiency(document, root=self.root)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["state"], "UNKNOWN", result)
        self.assertFalse(result["token_savings_verified"])
        self.assertIsNone(result["token_reduction_percent"])
        self.assertEqual(result["normalized"], {})
        if reason:
            self.assertIn(reason, result["reasons"])
        self.assertNotIn("SECRET_PROMPT_SENTINEL", json.dumps(result))
        return result

    def test_measured_reduction_matching_contract(self):
        result = efficiency.validate_efficiency(self.document(), root=self.root)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["state"], "VERIFIED_REDUCTION_CONDITIONAL")
        self.assertTrue(result["token_savings_verified"])
        self.assertEqual(result["token_reduction_percent"], 50.0)
        self.assertEqual(result["metrics"]["baseline"]["total_tokens"], 110)
        self.assertEqual(result["metrics"]["candidate"]["total_tokens"], 55)
        self.assertEqual(result["token_comparison"]["reduction_tokens"], 55)
        self.assertEqual(result["cost"]["state"], "UNKNOWN")
        self.assertEqual(result["latency"]["state"], "UNKNOWN")
        self.assertNotIn("SECRET_PROMPT_SENTINEL", json.dumps(result))

    def test_shared_message_deduplicated_across_parent_child_and_blocks(self):
        doc = self.document()
        message = self.claude("baseline-parent", "shared")
        repeated = deepcopy(message)
        repeated["message"]["content"] = [{"text": "different content block"}]
        parent = self.actor("baseline", events=[message, repeated])
        shared = deepcopy(message)
        shared["sessionId"] = "baseline-child"
        own = self.claude("baseline-child", "child-own", ordinary=5, creation=0, cached=0, output=5, thinking=0)
        child = self.actor("baseline", actor_id="child", parent="parent", events=[shared, own])
        doc["baseline"] = self.run_record("baseline", [parent, child])
        result = efficiency.validate_efficiency(doc, root=self.root)
        self.assertTrue(result["ok"], result)
        base = result["normalized"]["baseline"]
        self.assertEqual(base["total_tokens"], 120)
        self.assertEqual(base["raw_usage_records"], 4)
        self.assertEqual(base["unique_usage_units"], 2)
        self.assertEqual(base["actor_attempts"], 2)

    def test_conflicting_shared_message_usage_is_unknown(self):
        doc = self.document()
        first = self.claude("baseline-parent", "same-message")
        second = deepcopy(first)
        second["message"]["usage"]["output_tokens"] += 1
        self.replace_log(doc["baseline"], [first, second])
        self.assert_unknown(doc, "duplicate_message_usage_conflict")

    def test_thinking_and_cache_breakdown_are_not_added_twice(self):
        result = efficiency.validate_efficiency(self.document(), root=self.root)
        base = result["normalized"]["baseline"]
        self.assertEqual({key: base[key] for key in efficiency.MEASURES},
                         {"ordinary_input": 50, "cache_creation": 10, "cache_read": 20, "output": 30})
        self.assertEqual(base["thinking"], 5)
        self.assertEqual(base["total_tokens"], 110)

    def test_missing_thinking_is_unknown_subset_but_not_missing_output(self):
        doc = self.document()
        event = self.claude("baseline-parent", "baseline-message")
        del event["message"]["usage"]["thinking_tokens"]
        self.replace_log(doc["baseline"], [event])
        result = efficiency.validate_efficiency(doc, root=self.root)
        self.assertTrue(result["ok"], result)
        self.assertIsNone(result["normalized"]["baseline"]["thinking"])
        self.assertEqual(result["normalized"]["baseline"]["thinking_state"], "UNKNOWN")

    def test_codex_uses_final_cumulative_usage_and_subsets(self):
        doc = self.document()
        events = self.codex("baseline-parent", input_tokens=70, cached=40, output=20, reasoning=10)
        terminal = self.codex("baseline-parent")[-1]
        events.extend([terminal, deepcopy(terminal)])
        actor = self.actor("baseline", events=events, format="codex_jsonl_v1")
        doc["baseline"] = self.run_record("baseline", [actor])
        result = efficiency.validate_efficiency(doc, root=self.root)
        self.assertTrue(result["ok"], result)
        base = result["normalized"]["baseline"]
        self.assertEqual(base["total_tokens"], 170)
        self.assertEqual(base["ordinary_input"], 50)
        self.assertEqual(base["cache_read"], 70)
        self.assertEqual(base["thinking"], 30)
        self.assertEqual(base["output"], 50)
        self.assertEqual(base["raw_usage_records"], 3)
        self.assertEqual(base["unique_usage_units"], 1)

    def test_codex_parent_and_child_totals_are_aggregated(self):
        doc = self.document()
        parent = self.actor("baseline", events=self.codex("baseline-parent"), format="codex_jsonl_v1")
        child = self.actor("baseline", actor_id="child", parent="parent", format="codex_jsonl_v1",
                           events=self.codex("baseline-child", input_tokens=30, cached=0, output=10, reasoning=2))
        doc["baseline"] = self.run_record("baseline", [parent, child])
        result = efficiency.validate_efficiency(doc, root=self.root)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["normalized"]["baseline"]["total_tokens"], 210)

    def test_missing_child_is_unknown(self):
        doc = self.document()
        doc["baseline"]["expected_actors"].append("missing-child")
        self.assert_unknown(doc, "actor_coverage_mismatch")

    def test_omitted_retry_is_unknown(self):
        doc = self.document()
        run = doc["baseline"]
        coverage_path = run["coverage_receipt"]["path"]
        coverage = json.loads((self.root / coverage_path).read_text())
        coverage["omitted_retries"] = ["retry-2"]
        run["coverage_receipt"] = self.artifact(coverage_path, coverage)
        self.assert_unknown(doc, "coverage_not_complete")

    def test_retry_is_counted_as_own_actor_attempt(self):
        doc = self.document()
        retry = self.actor("baseline", actor_id="retry", parent="parent", retry_of="parent")
        doc["baseline"]["actors"].append(retry)
        doc["baseline"]["expected_actors"].append("retry")
        self.seal(doc["baseline"])
        result = efficiency.validate_efficiency(doc, root=self.root)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["normalized"]["baseline"]["total_tokens"], 220)

    def test_contract_mismatch_fails_for_each_identity(self):
        for key in efficiency.CONTRACT_KEYS:
            with self.subTest(key=key):
                doc = self.document()
                doc["candidate"]["contract"][key] = "different"
                self.assert_unknown(doc, "comparison_contract_mismatch")

    def test_raw_model_mismatch_is_unknown(self):
        doc = self.document()
        event = self.claude("candidate-parent", "candidate-message")
        event["message"]["model"] = "other-model"
        self.replace_log(doc["candidate"], [event])
        self.assert_unknown(doc, "log_model_mismatch")

    def test_tampered_logs_fail_hash_check(self):
        doc = self.document()
        path = self.root / doc["baseline"]["actors"][0]["logs"][0]["path"]
        path.write_bytes(path.read_bytes() + b" ")
        self.assert_unknown(doc, "artifact_hash_mismatch")

    def test_tampered_result_fails_hash_check(self):
        doc = self.document()
        (self.root / "candidate-result.txt").write_bytes(b"changed result")
        self.assert_unknown(doc, "artifact_hash_mismatch")

    def test_missing_result_acceptance_is_unknown(self):
        doc = self.document()
        run = doc["candidate"]
        path = run["acceptance_receipt"]["path"]
        receipt = json.loads((self.root / path).read_text())
        receipt["state"] = "UNKNOWN"
        run["acceptance_receipt"] = self.artifact(path, receipt)
        self.assert_unknown(doc, "result_not_accepted")

    def test_acceptance_coverage_binding_is_required(self):
        doc = self.document()
        run = doc["candidate"]
        path = run["acceptance_receipt"]["path"]
        receipt = json.loads((self.root / path).read_text())
        receipt["coverage_sha256"] = "0" * 64
        run["acceptance_receipt"] = self.artifact(path, receipt)
        self.assert_unknown(doc, "acceptance_binding_mismatch")

    def test_malformed_counts_fail_closed(self):
        for bad in (-1, True, 1.0, None, "2", float("nan"), float("inf"), efficiency.MAX_COUNT + 1):
            with self.subTest(bad=repr(bad)):
                doc = self.document()
                event = self.claude("candidate-parent", "candidate-message")
                event["message"]["usage"]["output_tokens"] = bad
                self.replace_log(doc["candidate"], [event])
                self.assert_unknown(doc)

    def test_missing_primary_count_is_unknown(self):
        doc = self.document()
        event = self.claude("candidate-parent", "candidate-message")
        del event["message"]["usage"]["cache_read_input_tokens"]
        self.replace_log(doc["candidate"], [event])
        self.assert_unknown(doc, "claude_usage_fields_missing")

    def test_thinking_cannot_exceed_output(self):
        doc = self.document()
        event = self.claude("candidate-parent", "candidate-message", thinking=31)
        self.replace_log(doc["candidate"], [event])
        self.assert_unknown(doc, "thinking_exceeds_output")

    def test_unchanged_or_increased_does_not_claim_reduction(self):
        for ordinary, state in ((50, "UNCHANGED"), (70, "INCREASED")):
            with self.subTest(state=state):
                doc = self.document()
                self.replace_log(doc["candidate"], [self.claude("candidate-parent", "candidate-message", ordinary=ordinary)])
                result = efficiency.validate_efficiency(doc, root=self.root)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["state"], "NOT_REDUCED")
                self.assertFalse(result["token_savings_verified"])
                self.assertIsNone(result["token_reduction_percent"])
                self.assertEqual(result["token_comparison"]["state"], state)
                self.assertIsNone(result["token_comparison"]["reduction_tokens"])

    def test_partial_or_missing_scope_is_unknown(self):
        for scope in ({"kind": "task_slice", "complete": True}, {"kind": "whole_session_single_task", "complete": False}, {}, None):
            with self.subTest(scope=scope):
                doc = self.document()
                doc["candidate"]["scope"] = scope
                self.assert_unknown(doc, "whole_session_single_task_scope_required")

    def test_unknown_adapter_is_unknown(self):
        doc = self.document()
        doc["candidate"]["actors"][0]["format"] = "future_format_without_adapter"
        self.assert_unknown(doc, "usage_adapter_unknown")

    def test_duplicate_log_path_is_rejected(self):
        doc = self.document()
        actor = doc["baseline"]["actors"][0]
        actor["logs"].append(deepcopy(actor["logs"][0]))
        self.seal(doc["baseline"])
        self.assert_unknown(doc, "duplicate_artifact_path")

    def test_duplicate_log_hash_under_new_path_is_rejected(self):
        doc = self.document()
        actor = doc["baseline"]["actors"][0]
        raw = (self.root / actor["logs"][0]["path"]).read_bytes()
        actor["logs"].append(self.artifact("copied-log.jsonl", raw))
        self.seal(doc["baseline"])
        self.assert_unknown(doc, "duplicate_log_hash")

    def test_duplicate_session_across_actors_is_rejected(self):
        doc = self.document()
        child = self.actor("baseline", actor_id="child", parent="parent")
        child["session_id"] = "baseline-parent"
        doc["baseline"]["actors"].append(child)
        doc["baseline"]["expected_actors"].append("child")
        self.seal(doc["baseline"])
        self.assert_unknown(doc, "duplicate_actor_session")

    def test_cross_run_message_overlap_is_rejected(self):
        doc = self.document()
        self.replace_log(doc["candidate"], [self.claude("candidate-parent", "baseline-parent-message")])
        self.assert_unknown(doc, "cross_run_usage_overlap")

    def test_raw_session_mismatch_is_unknown(self):
        doc = self.document()
        self.replace_log(doc["candidate"], [self.claude("wrong-session", "candidate-message")])
        self.assert_unknown(doc, "log_session_mismatch")

    def test_codex_reset_missing_metadata_and_invalid_subsets_are_unknown(self):
        cases = []
        decreasing = self.codex("candidate-parent")
        decreasing.append(self.codex("candidate-parent", input_tokens=50, cached=20, output=10, reasoning=5)[-1])
        cases.append((decreasing, "codex_counter_reset_or_reorder"))
        cases.append((self.codex("candidate-parent")[2:], "codex_metadata_before_usage_required"))
        cases.append((self.codex("candidate-parent", input_tokens=10, cached=11), "cached_exceeds_input"))
        cases.append((self.codex("candidate-parent", output=10, reasoning=11), "thinking_exceeds_output"))
        wrong_total = self.codex("candidate-parent")
        wrong_total[-1]["payload"]["info"]["total_token_usage"]["total_tokens"] += 1
        cases.append((wrong_total, "codex_total_mismatch"))
        for events, reason in cases:
            with self.subTest(reason=reason):
                doc = self.document()
                doc["candidate"] = self.run_record("candidate", [self.actor("candidate", events=events, format="codex_jsonl_v1")])
                self.assert_unknown(doc, reason)

    def test_cyclic_actor_dependencies_are_unknown(self):
        doc = self.document()
        child = self.actor("baseline", actor_id="child", parent="parent")
        doc["baseline"]["actors"][0]["retry_of"] = "child"
        doc["baseline"]["actors"].append(child)
        doc["baseline"]["expected_actors"].append("child")
        self.seal(doc["baseline"])
        self.assert_unknown(doc, "actor_dependency_cycle")

    def test_path_escape_is_unknown(self):
        doc = self.document()
        doc["candidate"]["actors"][0]["logs"][0]["path"] = "../outside.jsonl"
        self.seal(doc["candidate"])
        self.assert_unknown(doc)

    def test_manifest_nan_and_unknown_keys_are_unknown(self):
        doc = self.document()
        doc["summary_tokens"] = float("nan")
        self.assert_unknown(doc, "manifest_not_json_or_nonfinite")
        doc["summary_tokens"] = 1
        self.assert_unknown(doc, "manifest_invalid")

    def test_duplicate_json_keys_are_unknown(self):
        doc = self.document()
        actor = doc["candidate"]["actors"][0]
        actor["logs"] = [self.artifact("duplicate-key.jsonl", b'{"type":"assistant","type":"user"}\n')]
        self.seal(doc["candidate"])
        self.assert_unknown(doc, "duplicate_json_key")

    def test_public_api_default_root_is_resolved_at_call_time(self):
        doc = self.document()
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            self.assertTrue(efficiency.validate_efficiency(doc)["ok"])
        finally:
            os.chdir(previous)

    def test_zero_usage_cannot_be_wrapper_savings(self):
        doc = self.document()
        self.replace_log(doc["candidate"], [self.claude("candidate-parent", "candidate-message", ordinary=0,
                                                       creation=0, cached=0, output=0, thinking=0)])
        self.assert_unknown(doc, "positive_measured_usage_required")


if __name__ == "__main__":
    unittest.main()
