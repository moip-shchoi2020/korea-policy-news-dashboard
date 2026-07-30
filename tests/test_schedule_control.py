from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from collector.schedule_control import decide_schedule, load_state, mark_completed

KST = ZoneInfo("Asia/Seoul")


class ScheduleControlTests(unittest.TestCase):
    def test_morning_slot_requires_telegram(self) -> None:
        decision = decide_schedule(datetime(2026, 7, 30, 8, 3, tzinfo=KST), {})
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.slot_key, "2026-07-30T08:03")
        self.assertTrue(decision.telegram_required)
        self.assertEqual(decision.telegram_title, "08시 브리핑")

    def test_completed_slot_is_not_repeated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "schedule_state.json"
            mark_completed(
                "2026-07-30T08:03",
                slot_label="08:03 대시보드 갱신 + Telegram",
                telegram_required=True,
                state_path=state_path,
                now=datetime(2026, 7, 30, 8, 20, tzinfo=KST),
            )
            decision = decide_schedule(
                datetime(2026, 7, 30, 8, 43, tzinfo=KST),
                load_state(state_path),
            )
            self.assertFalse(decision.allowed)
            self.assertIn("이미 완료", decision.reason)

    def test_midnight_delayed_run_is_blocked(self) -> None:
        decision = decide_schedule(datetime(2026, 7, 31, 0, 58, tzinfo=KST), {})
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.slot_key, "")

    def test_evening_slot_does_not_require_telegram(self) -> None:
        decision = decide_schedule(datetime(2026, 7, 30, 19, 23, tzinfo=KST), {})
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.slot_key, "2026-07-30T19:03")
        self.assertFalse(decision.telegram_required)

    def test_slot_window_expires_before_night(self) -> None:
        decision = decide_schedule(datetime(2026, 7, 30, 21, 1, tzinfo=KST), {})
        self.assertFalse(decision.allowed)
        self.assertIn("마지막 예약 실행 창", decision.reason)

    def test_state_file_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "schedule_state.json"
            payload = mark_completed(
                "2026-07-30T16:03",
                slot_label="16:03 대시보드 갱신 + Telegram",
                telegram_required=True,
                state_path=state_path,
                now=datetime(2026, 7, 30, 16, 30, tzinfo=KST),
                run_id="123",
                run_url="https://github.com/example/repo/actions/runs/123",
            )
            with state_path.open("r", encoding="utf-8") as handle:
                disk_payload = json.load(handle)
            self.assertEqual(payload, disk_payload)
            self.assertIn("2026-07-30T16:03", disk_payload["completed_slots"])


if __name__ == "__main__":
    unittest.main()
