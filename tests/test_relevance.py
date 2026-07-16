from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from collector.build_indexes import build_indexes
from collector.classify_relevance import load_policy, rule_classify
from collector.common import read_json, write_json


class RelevanceRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy(Path("collector/relevance_policy.json"))

    def article(self, title: str, content: str, ministry: str = "기관") -> dict[str, str]:
        return {
            "id": title,
            "title": title,
            "summary": content[:120],
            "content_text": content,
            "ministry": ministry,
        }

    def test_foundational_ai_law_is_critical(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "인공지능 기본법 시행령 개정안 발표",
                "전 부처가 준수할 인공지능 안전·투명성 기준을 개정하고 즉시 시행한다.",
                "과학기술정보통신부",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "critical")
        self.assertTrue(needs_model)

    def test_government_wide_ai_lab_is_important(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "전 부처 대상 AI 실험실 시범사업 추진",
                "행정안전부가 중앙부처 공통 생성형 AI 실험실을 내부 테스트 단계로 구축한다.",
                "행정안전부",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "important")
        self.assertTrue(needs_model)

    def test_agency_specific_ai_project_is_normal(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "민원 상담 AI 챗봇 구축",
                "해당 기관이 자체 민원 상담 업무를 자동화하기 위한 AI 챗봇을 도입한다.",
                "해양수산부",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "normal")
        self.assertTrue(needs_model)

    def test_event_only_ai_hearing_is_unrelated(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "AI 정책 공청회 개최",
                "전문가와 국민 의견을 듣기 위한 공청회를 개최했다.",
                "기관",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "unrelated")
        self.assertTrue(needs_model)


class RelevanceIndexTests(unittest.TestCase):
    def test_build_indexes_contains_relevance_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            article_path = data_dir / "2026" / "07" / "14" / "articles.json"
            articles = [
                {
                    "id": "1",
                    "title": "AI 기본법 개정",
                    "summary": "정부 공통 규정",
                    "ministry": "과학기술정보통신부",
                    "approved_at": "2026-07-14T09:00:00+09:00",
                    "publish_date": "2026-07-14",
                    "is_modified": False,
                    "original_url": "https://example.com/1",
                    "content_text": "전 부처 적용",
                    "collected_at": "2026-07-14T10:00:00+09:00",
                    "ip_relevance": {
                        "level": "critical",
                        "label": "매우 중요",
                        "score": 4,
                        "confidence": 0.95,
                        "reason": "즉시 영향",
                        "signals": ["AI 기본법"],
                        "recommended_action": "즉시 검토",
                        "method": "github-models",
                        "model": "openai/gpt-4.1-mini",
                        "prompt_version": "ip-office-relevance-v1.0",
                    },
                },
                {
                    "id": "2",
                    "title": "일반 간담회",
                    "summary": "행사",
                    "ministry": "기관",
                    "approved_at": "2026-07-14T08:00:00+09:00",
                    "publish_date": "2026-07-14",
                    "is_modified": False,
                    "original_url": "https://example.com/2",
                    "content_text": "간담회 개최",
                    "collected_at": "2026-07-14T10:00:00+09:00",
                    "ip_relevance": {
                        "level": "unrelated",
                        "label": "관계없음",
                        "score": 1,
                        "confidence": 0.9,
                        "reason": "행사성",
                        "signals": ["간담회"],
                        "recommended_action": "제외",
                        "method": "rules",
                        "prompt_version": "ip-office-relevance-v1.0",
                    },
                },
            ]
            write_json(
                article_path,
                {
                    "schema_version": 2,
                    "date": "2026-07-14",
                    "articles": articles,
                },
            )

            manifest = build_indexes(data_dir)
            self.assertEqual(manifest["relevance_counts"]["critical"], 1)
            self.assertEqual(manifest["relevance_counts"]["unrelated"], 1)
            self.assertEqual(manifest["classified_count"], 2)

            month_index = read_json(data_dir / "2026" / "07" / "index.json")
            self.assertEqual(month_index["relevance_counts"]["critical"], 1)
            self.assertEqual(month_index["articles"][0]["ip_relevance"]["level"], "critical")


if __name__ == "__main__":
    unittest.main()
