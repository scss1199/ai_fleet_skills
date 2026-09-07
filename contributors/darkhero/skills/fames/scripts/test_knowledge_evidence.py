"""Portable offline evidence-contract tests; no source or model network calls."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from knowledge_evidence import _sha, main, validate_knowledge


class KnowledgeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.url = "https://example.org/PRIVATE_SOURCE_ID"
        self.full = b"PRIVATE_SOURCE_TEXT A full extracted source that remains untrusted."
        self.digest = b"An extractive digest; source truth is not verified."
        (self.root / "full.txt").write_bytes(self.full)
        (self.root / "digest.md").write_bytes(self.digest)
        self.source = {"schema": 1, "source_url": self.url, "final_url": self.url, "source_kind": "public_page_text",
                       "full_sha256": _sha(self.full), "digest_sha256": _sha(self.digest), "raw_sha256": _sha(self.full),
                       "model_calls": 0, "model_api_calls": 0, "model_calls_scope": "remote_model_APIs",
                       "local_asr_runs": 0, "trust": "UNVALIDATED_SOURCE", "promoted": False,
                       "completeness": "entire_extracted_page_text; embedded_or_linked_media_excluded"}
        self.record = {"state": "VERIFIED", "source_url": self.url, "full_path": "full.txt", "digest_path": "digest.md",
                       "full_sha256": _sha(self.full), "digest_sha256": _sha(self.digest),
                       "model_api_calls": 0, "local_asr_runs": 0, "truth_status": "UNVALIDATED_SOURCE"}
        self.persist()

    def tearDown(self):
        self.temp.cleanup()

    def persist(self):
        (self.root / "source.json").write_text(json.dumps(self.source), encoding="utf-8")

    def validate(self):
        return validate_knowledge(self.record, self.root)

    def bind_full(self, text):
        self.full = text.encode("utf-8")
        (self.root / "full.txt").write_bytes(self.full)
        self.record["full_sha256"] = self.source["full_sha256"] = _sha(self.full)

    def speech_fixture(self, cached=False):
        self.bind_full("A machine transcript containing only speech, with visual information excluded.\n" * 4)
        media, transcript = self.root / "speech-source.m4a", self.root / "speech-transcript.txt"
        media.write_bytes(b"fixture local media")
        transcript.write_bytes(self.full + b"\n")
        self.source["source_kind"] = "cached_public_media_local_whisper" if cached else "public_media_local_whisper"
        self.record["local_asr_runs"] = self.source["local_asr_runs"] = 0 if cached else 1
        provenance = {"source_url": self.url, "source_kind": "public_media_local_whisper",
                      "media_path": str(media), "media_sha256": _sha(media.read_bytes()),
                      "transcript_path": str(transcript), "transcript_sha256": _sha(transcript.read_bytes()),
                      "duration_seconds": 31.5, "device": "cpu", "threads": 2, "model_api_calls": 0,
                      "local_asr_runs": 1, "promoted": False, "trust": "machine_transcript_unreviewed",
                      "speech_segments": 2, "source_segments": 2}
        (self.root / "speech-source.json").write_text(json.dumps(provenance))
        self.persist()
        return provenance

    def test_valid_current_receipt_passes_acquisition_only(self):
        result = self.validate()
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["acquisition_state"], "VERIFIED")
        self.assertEqual(result["truth_state"], "UNKNOWN")
        self.assertEqual(result["source_origin_state"], "UNKNOWN")
        self.assertEqual(result["canon_state"], "NOT_PROMOTED")
        self.assertEqual(result["remote_model_api_calls"], 0)
        for private in ("PRIVATE_SOURCE_ID", "PRIVATE_SOURCE_TEXT", str(self.root)):
            self.assertNotIn(private, json.dumps(result))

    def test_full_or_digest_tamper_fails_closed(self):
        for name, original in (("full", self.full), ("digest", self.digest)):
            path = self.root / ("full.txt" if name == "full" else "digest.md")
            with self.subTest(name=name):
                path.write_bytes(b"changed PRIVATE_CONTENT")
                result = self.validate()
                self.assertEqual(result["state"], "UNKNOWN")
                self.assertIn(name + "_hash_mismatch", result["errors"])
                path.write_bytes(original)

    def test_matching_receipt_and_content_cannot_override_source_hash(self):
        self.record["full_sha256"] = _sha(b"tampered")
        (self.root / "full.txt").write_bytes(b"tampered")
        self.assertIn("full_hash_mismatch", self.validate()["errors"])

    def test_bool_and_negative_counters_are_rejected(self):
        for name, bad in (("model_api_calls", False), ("model_calls", False), ("local_asr_runs", True),
                          ("local_asr_runs", -1), ("local_asr_runs", "0")):
            with self.subTest(name=name, bad=bad):
                original = self.source[name]
                self.source[name] = bad
                self.persist()
                self.assertIn("counter_type_or_range_invalid", self.validate()["errors"])
                self.source[name] = original
        self.persist()
        self.record["model_api_calls"] = False
        self.assertIn("counter_type_or_range_invalid", self.validate()["errors"])

    def test_counter_alias_scope_and_conflicts_fail_closed(self):
        self.source["remote_model_api_calls"] = 1
        self.persist()
        self.assertIn("remote_model_counters_conflict", self.validate()["errors"])
        self.source.pop("remote_model_api_calls")
        self.source.pop("model_calls_scope")
        self.persist()
        self.assertIn("legacy_model_counter_scope_missing", self.validate()["errors"])

    def test_missing_explicit_counter_is_unknown(self):
        self.source.pop("local_asr_runs")
        self.persist()
        self.assertEqual(self.validate()["state"], "UNKNOWN")

    def test_source_url_identity_mismatch(self):
        self.record["source_url"] = "https://example.org/different"
        self.assertIn("source_identity_mismatch", self.validate()["errors"])

    def test_missing_and_malformed_provenance_fail_closed(self):
        path = self.root / "source.json"
        path.unlink()
        self.assertIn("artifact_missing", self.validate()["errors"])
        for raw in (b'{"PRIVATE":', b'[]', b'{"schema":1,"schema":2}', b'{"schema":NaN}'):
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                result = self.validate()
                self.assertEqual(result["state"], "UNKNOWN")
                self.assertNotIn("PRIVATE", json.dumps(result))

    def test_parent_path_escape_is_rejected(self):
        self.record["full_path"] = "../outside.txt"
        self.assertIn("artifact_path_escape", self.validate()["errors"])

    def test_artifact_roles_cannot_alias(self):
        self.record["digest_path"] = "full.txt"
        self.assertIn("artifact_directory_or_role_mismatch", self.validate()["errors"])

    def test_input_or_source_tombstones_block_even_with_valid_artifacts(self):
        for flag in ({"state": "TOMBSTONED"}, {"deleted": True}, {"tombstone": 1}):
            result = validate_knowledge({**self.record, **flag}, self.root)
            self.assertEqual(result["state"], "BLOCKED")
        self.source["tombstoned"] = True
        self.persist()
        self.assertEqual(self.validate()["state"], "BLOCKED")

    def test_truth_and_promotion_cannot_be_laundered(self):
        self.record["truth_status"] = "VERIFIED"
        self.assertIn("unsupported_truth_claim", self.validate()["errors"])
        self.record["truth_status"] = "UNKNOWN"
        self.source["promoted"] = True
        self.persist()
        self.assertEqual(self.validate()["state"], "BLOCKED")
        self.source["promoted"] = 0
        self.persist()
        self.assertEqual(self.validate()["state"], "UNKNOWN")

    def test_asr_validates_media_and_transcript_provenance(self):
        self.speech_fixture()
        result = self.validate()
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["source_class"], "LOCAL_SPEECH_TRANSCRIPT")
        self.assertEqual(result["local_asr_runs"], 1)
        self.assertEqual(result["remote_model_api_calls"], 0)
        self.assertEqual(result["visual_understanding_state"], "UNKNOWN")
        (self.root / "speech-source.m4a").write_bytes(b"changed media")
        self.assertIn("media_hash_mismatch", self.validate()["errors"])

    def test_cached_asr_distinguishes_historical_from_current_runs(self):
        self.speech_fixture(cached=True)
        result = self.validate()
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["local_asr_runs"], 0)
        self.assertEqual(result["historical_local_asr_runs"], 1)

    def test_windows_newlines_do_not_break_hash_bound_transcript_identity(self):
        provenance = self.speech_fixture()
        transcript = Path(provenance["transcript_path"])
        transcript.write_bytes(self.full.replace(b"\n", b"\r\n") + b"\r\n")
        provenance["transcript_sha256"] = _sha(transcript.read_bytes())
        (self.root / "speech-source.json").write_text(json.dumps(provenance))
        self.assertEqual(self.validate()["state"], "PASS")
        transcript.write_bytes(transcript.read_bytes().replace(b"speech", b"edited"))
        self.assertIn("media_hash_mismatch", self.validate()["errors"])

    def test_binary_empty_text_and_contradictory_source_states_fail_closed(self):
        for raw in (b"\xff\x00", b"  \r\n"):
            self.record["full_sha256"] = self.source["full_sha256"] = _sha(raw)
            (self.root / "full.txt").write_bytes(raw)
            self.persist()
            self.assertEqual(self.validate()["state"], "UNKNOWN")
        self.bind_full("A restored source statement.")
        self.source["state"] = "UNKNOWN"
        self.persist()
        self.assertIn("source_acquisition_not_verified", self.validate()["errors"])

    def test_media_duration_and_bool_provenance_fail_closed(self):
        provenance = self.speech_fixture()
        for field, value in (("duration_seconds", True), ("duration_seconds", 901), ("threads", True),
                             ("local_asr_runs", True), ("speech_segments", True), ("source_url", "https://wrong.example/")):
            with self.subTest(field=field):
                altered = {**provenance, field: value}
                (self.root / "speech-source.json").write_text(json.dumps(altered))
                self.assertEqual(self.validate()["state"], "UNKNOWN")

    def test_full_transcript_requires_bound_local_provenance(self):
        self.speech_fixture()
        (self.root / "speech-source.json").unlink()
        self.assertEqual(self.validate()["state"], "UNKNOWN")
        self.source["source_kind"] = "cached_full_speech:" + "a" * 64
        self.persist()
        self.assertIn("legacy_transcript_provenance_missing", self.validate()["errors"])

    def test_captions_are_classified_separately_from_speech_and_visuals(self):
        caption = b"WEBVTT\n\n00:00:00.000 --> 00:00:04.000\nA caption line without visual interpretation.\n"
        directory = self.root / "captions"
        directory.mkdir()
        path = directory / "source.en.vtt"
        path.write_bytes(caption)
        self.bind_full("A caption line without visual interpretation.")
        self.source["source_kind"] = "public_vtt:" + _sha(caption)
        self.persist()
        result = self.validate()
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["source_class"], "CAPTIONS")
        self.assertEqual(result["coverage"], "available_caption_text_only")
        self.assertEqual(result["visual_understanding_state"], "UNKNOWN")
        path.unlink()
        self.assertEqual(self.validate()["state"], "UNKNOWN")

    def test_raw_source_receipt_requires_verified_state_and_identity(self):
        raw = copy.deepcopy(self.source)
        self.assertEqual(validate_knowledge(raw, self.root)["state"], "UNKNOWN")
        raw["state"] = "VERIFIED"
        self.assertEqual(validate_knowledge(raw, self.root)["state"], "PASS")
        self.record.pop("source_url")
        self.assertEqual(self.validate()["state"], "UNKNOWN")

    def test_cli_outputs_only_sanitized_evidence_and_correct_exit_status(self):
        path = self.root / "receipt.json"
        path.write_text(json.dumps(self.record))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            status = main(["--input", str(path), "--root", str(self.root), "--json"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["state"], "PASS")
        self.assertNotIn("PRIVATE", output.getvalue())
        path.write_text("PRIVATE_INVALID_JSON")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            status = main(["--input", str(path), "--root", str(self.root), "--json"])
        self.assertEqual(status, 2)
        self.assertNotIn("PRIVATE", output.getvalue())


if __name__ == "__main__":
    unittest.main()
