import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_latest
from price_check import URL


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.history = self.root / "history.jsonl"
        self.history.write_text(json.dumps({
            "queried_at": "2026-10-21T09:00:00+08:00", "url": URL,
            "verified": True, "price_cny": 17499,
        }) + "\n", encoding="utf-8")
        self.history_patch = patch.object(publish_latest, "HISTORY", self.history)
        self.history_patch.start()
        self.addCleanup(self.history_patch.stop)
        self.output = self.root / "latest-price.json"

    def test_failed_check_keeps_history_price_separate(self):
        result_path = self.root / "result.json"
        result_path.write_text(json.dumps({
            "queried_at": "2026-10-22T09:00:00+08:00", "verified": False,
            "browser_started": True, "price_cny": None,
        }), encoding="utf-8")
        latest = publish_latest.build(result_path, self.output)
        self.assertFalse(latest["verified"])
        self.assertIsNone(latest["price_cny"])
        self.assertEqual(latest["previous_verified_price_cny"], 17499)
        self.assertIsNone(latest["price_change_cny"])
        self.assertEqual(latest["checked_at"], "2026-10-22T09:00:00+08:00")
        self.assertEqual(len(publish_latest.read_history()), 1)

    def test_missing_run_publishes_failure_status(self):
        latest = publish_latest.build(None, self.output)
        self.assertFalse(latest["verified"])
        self.assertIsNone(latest["price_cny"])
        self.assertEqual(latest["previous_verified_price_cny"], 17499)
        self.assertEqual(latest["error"], "query_did_not_run")

    def test_claimed_success_without_browser_evidence_is_not_published(self):
        result_path = self.root / "result.json"
        result_path.write_text(json.dumps({
            "queried_at": "2026-10-22T09:00:00+08:00", "url": URL,
            "verified": True, "price_cny": 99999,
        }), encoding="utf-8")
        latest = publish_latest.build(result_path, self.output)
        self.assertFalse(latest["verified"])
        self.assertIsNone(latest["price_cny"])
        self.assertEqual(latest["previous_verified_price_cny"], 17499)
        self.assertEqual(latest["error"], "evidence_validation_failed")
        self.assertEqual(len(publish_latest.read_history()), 1)


if __name__ == "__main__":
    unittest.main()
