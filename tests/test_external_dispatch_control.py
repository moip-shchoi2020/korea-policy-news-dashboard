from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from collector.external_dispatch_control import decide, load_state, mark_completed

KST = ZoneInfo("Asia/Seoul")


class ExternalDispatchControlTests(unittest.TestCase):
    def test_empty_slot_is_allowed_for_manual_run(self) -> None:
        allowed, reason = decide("", {"completed_slots": {}})
        self.assertTrue(allowed)
        self.assertIn("일반 수동 실행", reason)

    def test_unseen_slot_is_allowed(self) -> None:
        allowed, _ = decide("2026-07-31T16:03+09:00", {"completed_slots": {}})
        self.assertTrue(allowed)

    def test_completed_slot_is_rejected(self) -> None:
        state = {
            "completed_slots": {
                "2026-07-31T16:03+09:00": {"completed_at": "2026-07-31T16:20:00+09:00"}
            }
        }
        allowed, reason = decide("2026-07-31T16:03+09:00", state)
        self.assertFalse(allowed)
        self.assertIn("이미 완료", reason)

    def test_mark_completed_persists_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            mark_completed(
                "2026-07-31T08:03+09:00",
                slot_label="08:03 대시보드 갱신 + Telegram",
                source="cloudflare-workers",
                state_path=path,
                now=datetime(2026, 7, 31, 8, 30, tzinfo=KST),
                run_id="123",
            )
            payload = load_state(path)
            entry = payload["completed_slots"]["2026-07-31T08:03+09:00"]
            self.assertEqual(entry["source"], "cloudflare-workers")
            self.assertEqual(entry["run_id"], "123")
            with path.open("r", encoding="utf-8") as handle:
                json.load(handle)


if __name__ == "__main__":
    unittest.main()
