from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collector import send_telegram


class TelegramDigestTests(unittest.TestCase):
    def write_day(
        self,
        root: Path,
        day: str,
        articles: list[dict[str, object]],
    ) -> None:
        year, month, date = day.split("-")
        path = root / year / month / date / "articles.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "date": day,
                    "articles": articles,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_keyword_boundary(self) -> None:
        self.assertTrue(send_telegram.keyword_matches("AI 시스템 구축", "AI"))
        self.assertFalse(send_telegram.keyword_matches("chairman", "AI"))
        self.assertTrue(send_telegram.keyword_matches("정보화 사업 개선", "정보화 사업"))

    def test_select_articles_only_includes_priority_levels(self) -> None:
        articles = [
            {"id": "1", "ip_relevance": {"level": "critical"}},
            {"id": "2", "ip_relevance": {"level": "important"}},
            {"id": "3", "ip_relevance": {"level": "normal"}},
            {"id": "4", "ip_relevance": {"level": "unrelated"}},
            {"id": "5", "ip_relevance": {"level": "unclassified"}},
        ]
        selected = send_telegram.select_articles(
            articles,
            max_critical=20,
            max_important=20,
            max_normal=5,
            max_unclassified=3,
            max_total=30,
        )
        self.assertEqual([item["id"] for item in selected], ["1", "2"])

    def test_build_digest_uses_priority_levels_without_keyword_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps({"default_keywords": ["AI"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            self.write_day(
                root,
                "2026-11-02",
                [
                    {
                        "id": "1",
                        "title": "공공부문 인공지능 공통기준",
                        "ip_relevance": {"level": "critical"},
                    },
                    {
                        "id": "2",
                        "title": "정부 공통 정보관리 개편",
                        "ip_relevance": {"level": "important"},
                    },
                    {
                        "id": "3",
                        "title": "AI 시범사업",
                        "ip_relevance": {"level": "normal"},
                    },
                    {
                        "id": "4",
                        "title": "일반 행사",
                        "ip_relevance": {"level": "unrelated"},
                    },
                ],
            )

            env = {
                "TELEGRAM_LEVELS": "critical,important",
                "TELEGRAM_KEYWORDS": "AI",
                "TELEGRAM_REQUIRE_KEYWORD_MATCH": "false",
            }
            with (
                patch.object(send_telegram, "DATA_DIR", root),
                patch.object(send_telegram, "CONFIG_PATH", config_path),
                patch.dict(os.environ, env, clear=False),
            ):
                result = send_telegram.build_digest("2026-11-02")

            self.assertEqual(
                [item["id"] for item in result.matched_articles],
                ["1", "2"],
            )
            self.assertEqual(
                [item["id"] for item in result.selected_articles],
                ["1", "2"],
            )
            self.assertEqual(result.counts["critical"], 1)
            self.assertEqual(result.counts["important"], 1)
            self.assertEqual(result.counts["normal"], 0)

    def test_keyword_filter_can_be_enabled_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps({"default_keywords": ["AI"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            self.write_day(
                root,
                "2026-11-02",
                [
                    {
                        "id": "1",
                        "title": "공공부문 인공지능 공통기준",
                        "ip_relevance": {"level": "critical"},
                    },
                    {
                        "id": "2",
                        "title": "AI 정부 공통 플랫폼",
                        "ip_relevance": {"level": "important"},
                    },
                ],
            )

            env = {
                "TELEGRAM_LEVELS": "critical,important",
                "TELEGRAM_KEYWORDS": "AI",
                "TELEGRAM_REQUIRE_KEYWORD_MATCH": "true",
            }
            with (
                patch.object(send_telegram, "DATA_DIR", root),
                patch.object(send_telegram, "CONFIG_PATH", config_path),
                patch.dict(os.environ, env, clear=False),
            ):
                result = send_telegram.build_digest("2026-11-02")

            self.assertEqual(
                [item["id"] for item in result.selected_articles],
                ["2"],
            )

    def test_build_message_chunks(self) -> None:
        result = send_telegram.DigestResult(
            report_date="2026-07-21",
            keywords=["AI"],
            articles=[{"id": "1"}],
            matched_articles=[{"id": "1"}],
            selected_articles=[
                {
                    "id": "1",
                    "title": "AI 규정 개정",
                    "summary": "전 부처 적용 기준",
                    "ministry": "과학기술정보통신부",
                    "original_url": "https://www.korea.kr/example",
                    "ip_relevance": {
                        "level": "critical",
                        "reason": "즉시 영향",
                    },
                    "_telegram_matched_keywords": ["AI"],
                }
            ],
            counts={
                "critical": 1,
                "important": 0,
                "normal": 0,
                "unrelated": 0,
                "unclassified": 0,
            },
            dashboard_url="https://example.github.io/dashboard/",
        )
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_LEVELS": "critical,important",
                "TELEGRAM_REQUIRE_KEYWORD_MATCH": "false",
            },
            clear=False,
        ):
            chunks = send_telegram.build_message_chunks(result)

        combined = "\n".join(chunks)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertIn("매우 중요", combined)
        self.assertIn("전송 기준", combined)
        self.assertNotIn("관계없음", combined)
        self.assertTrue(
            all(len(chunk) <= send_telegram.MAX_TELEGRAM_TEXT for chunk in chunks)
        )

    def test_empty_priority_digest_skips_send(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps({"default_keywords": ["AI"]}, ensure_ascii=False),
                encoding="utf-8",
            )
            self.write_day(
                root,
                "2026-11-02",
                [
                    {
                        "id": "1",
                        "title": "AI 시범사업",
                        "ip_relevance": {"level": "normal"},
                    }
                ],
            )

            env = {
                "TELEGRAM_LEVELS": "critical,important",
                "TELEGRAM_SKIP_EMPTY": "true",
                "TELEGRAM_BOT_TOKEN": "dummy",
                "TELEGRAM_CHAT_ID": "123",
            }
            with (
                patch.object(send_telegram, "DATA_DIR", root),
                patch.object(send_telegram, "CONFIG_PATH", config_path),
                patch.dict(os.environ, env, clear=False),
                patch.object(send_telegram, "send_message") as mocked_send,
            ):
                exit_code = send_telegram.main(
                    ["--date", "2026-11-02", "--require-config"]
                )

            self.assertEqual(exit_code, 0)
            mocked_send.assert_not_called()

    def test_require_config_argument_is_available(self) -> None:
        self.assertTrue(callable(send_telegram.main))


if __name__ == "__main__":
    unittest.main()
