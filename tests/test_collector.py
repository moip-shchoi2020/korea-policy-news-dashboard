from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from collector.build_indexes import build_indexes
from collector.collect import parse_response, upsert_article
from collector.common import read_json


class CollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "sample.xml"
        self.xml = fixture.read_text(encoding="utf-8")

    def test_parses_only_press_release_and_removes_images_and_scripts(self) -> None:
        articles = parse_response(self.xml, date(2026, 7, 14))
        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article["id"], "156000001")
        self.assertTrue(article["is_modified"])
        self.assertEqual(article["modify_id"], 2)
        self.assertEqual(article["publish_date"], "2026-07-14")
        self.assertNotIn("<img", article["content_html"])
        self.assertNotIn("<script", article["content_html"])
        self.assertIn("AI 시스템", article["content_text"])
        self.assertEqual(article["summary_source"], "subtitle")

    def test_writes_daily_data_and_month_index(self) -> None:
        articles = parse_response(self.xml, date(2026, 7, 14))
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            result = upsert_article(data_dir, articles[0])
            self.assertEqual(result, "created")
            unchanged = upsert_article(data_dir, articles[0])
            self.assertEqual(unchanged, "unchanged")

            manifest = build_indexes(data_dir)
            self.assertEqual(manifest["article_count"], 1)
            self.assertEqual(manifest["modified_count"], 1)
            month_index = read_json(data_dir / "2026" / "07" / "index.json")
            self.assertEqual(month_index["articles"][0]["id"], "156000001")
            self.assertIn("AI 시스템", month_index["articles"][0]["search_text"])


if __name__ == "__main__":
    unittest.main()
