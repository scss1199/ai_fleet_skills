from __future__ import annotations

import argparse
import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("inspect_line_inbox.py")
SPEC = importlib.util.spec_from_file_location("inspect_line_inbox", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class InspectLineInboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.group = {
            "ts": "2026-08-10T10:00:00+08:00",
            "source_type": "group",
            "group_name": "凱羅實驗室",
            "channel_label": "群組 · 凱羅實驗室",
            "display_name": "Private Sender",
            "uid": "U-secret",
            "group_id": "C-secret",
            "message_id": "m1",
            "text": "AI note https://example.com/a",
        }
        self.user = {
            "ts": "2026-08-09T10:00:00+08:00",
            "source_type": "user",
            "display_name": "Direct Sender",
            "uid": "U-private",
            "message_id": "m2",
            "text": "private text",
        }

    def args(self, **overrides):
        values = {
            "group_name": "",
            "source_type": "",
            "include_sender": False,
            "include_text": False,
            "include_urls": False,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_safe_row_redacts_identifiers_and_content_by_default(self):
        row = MOD.safe_row(self.group, self.args())
        self.assertNotIn("uid", row)
        self.assertNotIn("group_id", row)
        self.assertNotIn("message_id", row)
        self.assertNotIn("display_name", row)
        self.assertNotIn("text", row)

    def test_exact_group_filter_and_requested_content(self):
        args = self.args(group_name="凱羅實驗室", include_text=True, include_urls=True)
        self.assertTrue(MOD.matches(self.group, args, None))
        self.assertFalse(MOD.matches(self.user, args, None))
        row = MOD.safe_row(self.group, args)
        self.assertEqual(row["urls"], ["https://example.com/a"])
        self.assertEqual(row["text"], self.group["text"])

    def test_summary_separates_group_and_direct_events(self):
        summary = MOD.summarize([self.group, self.user])
        self.assertEqual(summary["source_types"], {"group": 1, "user": 1})
        self.assertEqual(summary["groups"], {"凱羅實驗室": 1})

    def test_dedupe_prefers_message_id(self):
        self.assertEqual(len(MOD.dedupe([self.group, dict(self.group)])), 1)


if __name__ == "__main__":
    unittest.main()
