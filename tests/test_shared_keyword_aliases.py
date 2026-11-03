from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collector
from collector import send_telegram


class SharedKeywordAliasTests(unittest.TestCase):
    def test_ai_group_expands_requested_terms(self) -> None:
        config = collector.load_keyword_config(
            Path(__file__).resolve().parents[1] / "docs" / "data" / "config.json"
        )
        expanded = collector.expand_keyword_aliases(
            ["AI"],
            config.get("keyword_aliases"),
        )

        self.assertIn("AI", expanded)
        self.assertIn("인공지능", expanded)
        self.assertIn("LLM", expanded)
        self.assertIn("생성형 인공지능", expanded)
        self.assertEqual(len(expanded), len({item.casefold() for item in expanded}))

    def test_alias_input_resolves_to_same_group(self) -> None:
        aliases = {
            "AI": ["인공지능", "LLM", "생성형 인공지능"],
        }
        self.assertEqual(
            collector.expand_keyword_aliases(["LLM"], aliases),
            ["AI", "인공지능", "LLM", "생성형 인공지능"],
        )

    def test_telegram_environment_uses_shared_defaults_and_requires_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "default_keywords": ["AI"],
                        "keyword_aliases": {
                            "AI": ["인공지능", "LLM", "생성형 인공지능"]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "TELEGRAM_KEYWORDS": "AI",
                    "TELEGRAM_REQUIRE_KEYWORD_MATCH": "",
                },
                clear=False,
            ):
                os.environ.pop("TELEGRAM_REQUIRE_KEYWORD_MATCH", None)
                expanded = collector.configure_telegram_keyword_environment(config_path)
                configured = send_telegram.parse_keywords(os.environ["TELEGRAM_KEYWORDS"])
                require_match = os.environ["TELEGRAM_REQUIRE_KEYWORD_MATCH"]

            self.assertEqual(expanded, ["AI", "인공지능", "LLM", "생성형 인공지능"])
            self.assertEqual(configured, expanded)
            self.assertEqual(require_match, "true")

    def test_telegram_filters_priority_articles_by_expanded_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            config = {
                "default_keywords": ["AI"],
                "keyword_aliases": {
                    "AI": ["인공지능", "LLM", "생성형 인공지능"]
                },
            }
            config_path.write_text(
                json.dumps(config, ensure_ascii=False),
                encoding="utf-8",
            )

            day_path = root / "2026" / "11" / "03" / "articles.json"
            day_path.parent.mkdir(parents=True, exist_ok=True)
            day_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "date": "2026-11-03",
                        "articles": [
                            {
                                "id": "1",
                                "title": "생성형 인공지능 공통 기준 시행",
                                "ip_relevance": {"level": "critical"},
                            },
                            {
                                "id": "2",
                                "title": "정부 공통 기록관리 체계 개편",
                                "ip_relevance": {"level": "important"},
                            },
                            {
                                "id": "3",
                                "title": "LLM 기반 상담 시범사업",
                                "ip_relevance": {"level": "normal"},
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            expanded = collector.expand_keyword_aliases(
                config["default_keywords"],
                config["keyword_aliases"],
            )
            env = {
                "TELEGRAM_LEVELS": "critical,important",
                "TELEGRAM_KEYWORDS": ",".join(expanded),
                "TELEGRAM_REQUIRE_KEYWORD_MATCH": "true",
            }
            with (
                patch.object(send_telegram, "DATA_DIR", root),
                patch.object(send_telegram, "CONFIG_PATH", config_path),
                patch.dict(os.environ, env, clear=False),
            ):
                result = send_telegram.build_digest("2026-11-03")

            self.assertEqual(
                [article["id"] for article in result.matched_articles],
                ["1"],
            )
            self.assertEqual(
                [article["id"] for article in result.selected_articles],
                ["1"],
            )
            self.assertEqual(result.counts["critical"], 1)
            self.assertEqual(result.counts["important"], 0)


if __name__ == "__main__":
    unittest.main()
