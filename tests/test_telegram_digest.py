from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collector import send_telegram


class TelegramDigestTests(unittest.TestCase):
    def test_keyword_boundary(self) -> None:
        self.assertTrue(send_telegram.keyword_matches("AI 시스템 구축", "AI"))
        self.assertFalse(send_telegram.keyword_matches("chairman", "AI"))
        self.assertTrue(send_telegram.keyword_matches("정보화 사업 개선", "정보화 사업"))

    def test_select_articles_excludes_unrelated_details(self) -> None:
        articles = [
            {"id": "1", "ip_relevance": {"level": "critical"}},
            {"id": "2", "ip_relevance": {"level": "important"}},
            {"id": "3", "ip_relevance": {"level": "normal"}},
            {"id": "4", "ip_relevance": {"level": "unrelated"}},
        ]
        selected = send_telegram.select_articles(
            articles,
            max_critical=20,
            max_important=20,
            max_normal=5,
            max_unclassified=3,
            max_total=30,
        )
        self.assertEqual([item["id"] for item in selected], ["1", "2", "3"])

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
        chunks = send_telegram.build_message_chunks(result)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertIn("매우 중요", "\n".join(chunks))
        self.assertTrue(all(len(chunk) <= send_telegram.MAX_TELEGRAM_TEXT for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
