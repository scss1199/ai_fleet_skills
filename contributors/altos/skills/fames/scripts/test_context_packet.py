import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import context_packet as packet


class ContextPacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def item(self, identity, content):
        path = self.root / (identity + ".txt")
        raw = content.encode("utf-8")
        path.write_bytes(raw)
        return {"id": identity, "path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}

    def test_hash_mismatch_is_preserved_without_excerpt(self):
        item = self.item("changed", "needle confidential stale")
        item["sha256"] = "0" * 64
        result = packet.build_packet({"query": "needle", "evidence": [item]})
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["evidence"][0]["reason"], "HASH_MISMATCH")
        self.assertNotIn("excerpt", result["evidence"][0])

    def test_caps_and_all_omissions_are_visible(self):
        items = [self.item(str(i), "needle " + "x" * 4000) for i in range(5)]
        result = packet.build_packet({"query": "needle", "evidence": items})
        self.assertEqual(result["metrics"]["excerpt_chars"], 1600)
        self.assertEqual(result["metrics"]["selected_items"], 3)
        self.assertEqual(result["metrics"]["omitted_items"], 2)
        self.assertEqual(len(result["evidence"]), 5)
        self.assertTrue(all(r["truncated"] for r in result["evidence"][:3]))
        self.assertEqual(result["state"], "PARTIAL")

    def test_missing_and_unmatched_evidence_not_silently_dropped(self):
        missing = self.item("missing", "needle")
        Path(missing["path"]).unlink()
        other = self.item("other", "unrelated")
        result = packet.build_packet({"query": "needle", "evidence": [missing, other]})
        self.assertEqual([r["reason"] for r in result["evidence"]], ["FILE_UNAVAILABLE", "NO_QUERY_MATCH"])
        self.assertEqual(result["metrics"]["unknown_items"], 1)
        self.assertEqual(result["metrics"]["omitted_items"], 1)

    def test_oversized_file_has_no_excerpt_and_no_read(self):
        item = self.item("huge", "needle" + "x" * packet.MAX_FILE_BYTES)
        result = packet.build_packet({"query": "needle", "evidence": [item]})
        self.assertEqual(result["evidence"][0]["reason"], "FILE_READ_LIMIT")
        self.assertEqual(result["metrics"]["bytes_read"], 0)

    def test_total_read_bound_preserves_unread_items(self):
        items = [self.item(str(i), "needle" + "x" * 250000) for i in range(6)]
        result = packet.build_packet({"query": "needle", "evidence": items})
        self.assertLessEqual(result["metrics"]["bytes_read"], packet.MAX_TOTAL_BYTES)
        self.assertEqual(len(result["evidence"]), 6)
        self.assertEqual(result["evidence"][-1]["reason"], "TOTAL_READ_LIMIT")

    def test_malformed_input_is_unknown_and_does_not_write(self):
        input_path, output_path = self.root / "manifest.json", self.root / "receipt.json"
        for malformed in ('{"evidence": []}', '{invalid', '[]'):
            input_path.write_text(malformed, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                status = packet.main(["--input", str(input_path), "--out", str(output_path)])
            self.assertEqual(status, 2)
            self.assertEqual(json.loads(stdout.getvalue())["state"], "UNKNOWN")
            self.assertFalse(output_path.exists())

    def test_receipt_is_deterministic_and_stdout_compact(self):
        item = self.item("good", "needle proof")
        manifest = {"query": "needle", "evidence": [item]}
        input_path, output_path = self.root / "manifest.json", self.root / "receipt.json"
        input_path.write_text(json.dumps(manifest), encoding="utf-8")
        snapshots = []
        for _ in range(2):
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                status = packet.main(["--input", str(input_path), "--out", str(output_path)])
            self.assertEqual(status, 0)
            summary = json.loads(stdout.getvalue())
            self.assertNotIn("needle proof", stdout.getvalue())
            self.assertNotIn("evidence", summary)
            snapshots.append(output_path.read_bytes())
        self.assertEqual(snapshots[0], snapshots[1])
        result = json.loads(snapshots[0])
        self.assertEqual(result["metrics"]["measurement_unit"], "characters; no token or billing estimate")
        self.assertFalse(any("saving" in key or "tokens" in key for key in result["metrics"]))

    def test_output_cannot_overwrite_evidence(self):
        item = self.item("good", "needle proof")
        input_path = self.root / "manifest.json"
        input_path.write_text(json.dumps({"query": "needle", "evidence": [item]}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            status = packet.main(["--input", str(input_path), "--out", item["path"]])
        self.assertEqual(status, 2)
        self.assertEqual(Path(item["path"]).read_text(), "needle proof")

    def test_match_on_long_line_is_visible(self):
        item = self.item("long", "x" * 2000 + " needle " + "y" * 2000)
        result = packet.build_packet({"query": "needle", "evidence": [item]}, char_budget=100)
        self.assertIn("needle", result["evidence"][0]["excerpt"])
        self.assertEqual(result["metrics"]["excerpt_chars"], 100)

    def test_remote_paths_and_duplicate_ids_rejected(self):
        item = self.item("good", "needle")
        for items in ([item, item], [dict(item, path="https://example.test/a")], [dict(item, path="\\\\server\\share\\a")]):
            with self.assertRaises(packet.InvalidManifest):
                packet.build_packet({"query": "needle", "evidence": items})

    def test_hard_limits_cannot_be_raised(self):
        manifest = {"query": "needle", "evidence": [self.item("good", "needle")]}
        for count, budget in ((4, 1600), (3, 1601), (0, 10), (1, 0)):
            with self.assertRaises(packet.InvalidManifest):
                packet.build_packet(manifest, count, budget)

    def test_unicode_and_casefold_matching_is_deterministic(self):
        item = self.item("unicode", "ß" * 500 + " needle 中文證據")
        result = packet.build_packet({"query": "needle", "evidence": [item]}, char_budget=60)
        self.assertIn("needle 中文證據", result["evidence"][0]["excerpt"])


if __name__ == "__main__":
    unittest.main()
