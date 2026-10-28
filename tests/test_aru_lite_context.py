import datetime as dt
import json
import os
import tempfile
import unittest
from unittest import mock

import aru_lite_context as alc


class LiteContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "state.json")
        self.patcher = mock.patch.object(alc, "PATH", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_plan_does_not_become_completed(self):
        item = alc.set_item("dinner", "cook noodles", state="planned", scope="today")
        active = alc.get_active()
        self.assertEqual(item["state"], "planned")
        self.assertEqual(active[0]["state"], "planned")

    def test_completed_becomes_tombstone_not_active(self):
        alc.set_item("delivery", "paper-wrapped chicken ordered", state="in_progress", scope="today")
        alc.set_item("delivery", "paper-wrapped chicken arrived", state="completed", scope="today")
        self.assertEqual(alc.get_active(), [])
        reasons = [x["reason"] for x in alc.get_tombstones(key="delivery")]
        self.assertIn("superseded", reasons)
        self.assertIn("completed", reasons)

    def test_drop_prevents_active_resurrection(self):
        alc.set_item("visitor", "family member is staying", state="in_progress", scope="current", ttl_hours=48)
        self.assertEqual(alc.drop_item("visitor", reason="went_home"), 1)
        self.assertEqual(alc.get_active(), [])
        self.assertEqual(alc.get_tombstones(key="visitor")[-1]["reason"], "went_home")

    def test_current_requires_expiry(self):
        with self.assertRaises(ValueError):
            alc.set_item("project", "temporary work", scope="current", state="in_progress")

    def test_render_keeps_evidence_state_visible(self):
        alc.set_item("meal", "chicken ordered", scope="today", state="in_progress", evidence="user_stated")
        block = alc.render_context()
        self.assertIn('state="in_progress"', block)
        self.assertIn("plans are not completed facts", block)


if __name__ == "__main__":
    unittest.main()
