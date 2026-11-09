from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from collector.build_indexes import build_indexes
from collector.classify_relevance import (
    classification_evidence,
    constrain_model_result,
    load_policy,
    rule_classify,
)
from collector.common import read_json, write_json


class RelevanceRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy(Path("collector/relevance_policy.json"))

    def article(self, title: str, content: str, ministry: str = "기관") -> dict[str, str]:
        return {
            "id": title,
            "title": title,
            "summary": content[:160],
            "content_text": content,
            "ministry": ministry,
        }

    def test_foundational_ai_law_is_critical_when_a_and_b_pass(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "인공지능 기본법 시행령 개정안 발표",
                "전 부처가 준수할 인공지능 안전·투명성 정부 공통 기준을 개정하고 즉시 시행한다.",
                "과학기술정보통신부",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "critical")
        self.assertTrue(needs_model)

    def test_government_wide_ai_lab_is_important_with_b_only(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "전 부처 대상 AI 실험실 시범사업 추진",
                "행정안전부가 중앙부처 공통 생성형 AI 실험실 구축을 추진한다.",
                "행정안전부",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "important")
        self.assertTrue(needs_model)

    def test_agency_specific_ai_deployment_is_important_with_b(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "민원 상담 AI 챗봇 도입 추진",
                "해당 기관이 자체 민원 상담 업무에 AI 챗봇을 도입한다.",
                "해양수산부",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "important")
        self.assertTrue(needs_model)

    def test_event_only_ai_hearing_is_unrelated(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "AI 정책 공청회 개최",
                "전문가와 국민 의견을 듣기 위한 공청회를 개최하고 미래 방향을 논의했다.",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "unrelated")
        self.assertFalse(needs_model)

    def test_record_management_conference_is_unrelated(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "동아시아 기록관리 전문가, 한 자리에 모여 기록관리의 미래를 논하다",
                "국가기록원이 국제 협의회에서 인공지능 네이티브 기록관 미래상과 전자기록 통합 관리 체계를 소개하고 논의한다.",
                "행정안전부",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "unrelated")
        self.assertFalse(needs_model)

    def test_priority_ministry_does_not_raise_discussion(self) -> None:
        result, _ = rule_classify(
            self.article(
                "공공 AI 미래 포럼 개최",
                "공공부문 인공지능의 미래상을 논의하고 해외 사례를 공유한다.",
                "행정안전부",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "unrelated")

    def test_case_introduction_is_at_most_normal(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "생성형 AI 업무자동화 사례 소개",
                "한 공공기관이 생성형 AI 업무자동화 사례와 기술동향을 소개한다.",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "normal")
        self.assertTrue(needs_model)

    def test_unrelated_action_does_not_satisfy_b(self) -> None:
        article = self.article(
            "경기남부 민간공항 개발계획 수립 및 실시설계 착수",
            "공항 개발 사업 착수와 실시설계를 추진한다. 이용객 안내 시스템 연계는 장기적으로 검토한다.",
            "국토교통부",
        )
        evidence = classification_evidence(article, self.policy)
        result, _ = rule_classify(article, self.policy)
        self.assertFalse(evidence["condition_b"])
        self.assertNotIn(result["level"], {"critical", "important"})

    def test_generic_management_system_is_not_targeted_b(self) -> None:
        article = self.article(
            "산림치유프로그램 인증제로 품질관리 본격화",
            "ISO 13485 품질경영시스템 인증제를 시행한다.",
            "산림청",
        )
        evidence = classification_evidence(article, self.policy)
        result, _ = rule_classify(article, self.policy)
        self.assertFalse(evidence["condition_b"])
        self.assertNotIn(result["level"], {"critical", "important"})

    def test_general_safety_inspection_is_not_targeted_b(self) -> None:
        article = self.article(
            "5천여 개 사업장 안전분야 이행실태 불시 점검",
            "건설현장과 제조업 사업장의 안전관리 이행실태를 점검 실시한다. 점검 결과는 데이터로 관리한다.",
            "고용노동부",
        )
        evidence = classification_evidence(article, self.policy)
        result, _ = rule_classify(article, self.policy)
        self.assertFalse(evidence["condition_b"])
        self.assertNotIn(result["level"], {"critical", "important"})

    def test_targeted_security_action_is_important(self) -> None:
        article = self.article(
            "공공 정보시스템 보안 취약점 긴급 점검",
            "공공 정보시스템의 보안 취약점을 점검 실시하고 보안 패치를 배포한다.",
            "행정안전부",
        )
        evidence = classification_evidence(article, self.policy)
        result, needs_model = rule_classify(article, self.policy)
        self.assertTrue(evidence["condition_b"])
        self.assertEqual(result["level"], "important")
        self.assertTrue(needs_model)

    def test_ai_festival_without_actual_action_is_unrelated(self) -> None:
        result, needs_model = rule_classify(
            self.article(
                "AI 콘텐츠 페스티벌 개최",
                "인공지능 콘텐츠 전시와 체험, 전문가 강연을 열고 미래 활용방안을 논의한다.",
            ),
            self.policy,
        )
        self.assertEqual(result["level"], "unrelated")
        self.assertFalse(needs_model)

    def test_project_briefing_without_override_is_capped_at_normal(self) -> None:
        article = self.article(
            "차세대 지방행정공통시스템 구축 사업설명회 개최",
            "AI 기반 공통 정보시스템 구축 추진 계획과 사업 범위를 설명한다.",
            "행정안전부",
        )
        evidence = classification_evidence(article, self.policy)
        result, needs_model = rule_classify(article, self.policy)
        self.assertTrue(evidence["condition_b"])
        self.assertTrue(evidence["event_capped_normal"])
        self.assertEqual(result["level"], "normal")
        self.assertTrue(needs_model)

    def test_event_with_actual_ai_service_launch_can_be_important(self) -> None:
        article = self.article(
            "행정 AI 플랫폼 개통 설명회",
            "행정기관용 생성형 AI 플랫폼을 개통하고 서비스 운영을 개시한다.",
            "행정안전부",
        )
        evidence = classification_evidence(article, self.policy)
        result, needs_model = rule_classify(article, self.policy)
        self.assertTrue(evidence["condition_b"])
        self.assertTrue(evidence["event_override_b"])
        self.assertEqual(result["level"], "important")
        self.assertTrue(needs_model)

    def test_model_event_without_override_is_demoted_to_normal(self) -> None:
        article = self.article(
            "차세대 공통시스템 구축 사업설명회",
            "AI 기반 공통 정보시스템 구축을 추진하며 사업 계획을 설명한다.",
            "행정안전부",
        )
        result = constrain_model_result(
            article,
            {"level": "important", "confidence": 0.92, "reason": "구축 사업", "signals": ["AI"]},
            self.policy,
        )
        self.assertEqual(result["level"], "normal")


def test_briefing_title_with_targeted_build_is_capped_at_normal(self) -> None:
    article = self.article(
        "차세대 지방행정공통시스템 구축 통합사업 설명회 개최",
        "사업 범위와 추진 일정을 설명한다.",
        "행정안전부",
    )
    evidence = classification_evidence(article, self.policy)
    result, needs_model = rule_classify(article, self.policy)
    self.assertTrue(evidence["condition_b"])
    self.assertTrue(evidence["event_capped_normal"])
    self.assertEqual(result["level"], "normal")
    self.assertTrue(needs_model)

def test_academic_congress_without_actual_action_is_unrelated(self) -> None:
    result, needs_model = rule_classify(
        self.article(
            "AI 활용 해양 국제범죄 대응 학술의회 개최",
            "인공지능 활용사례를 공유하고 국제협력 방향을 논의한다.",
            "해양경찰청",
        ),
        self.policy,
    )
    self.assertEqual(result["level"], "unrelated")
    self.assertFalse(needs_model)

def test_digital_transition_center_opening_is_important(self) -> None:
    article = self.article(
        "해양정보 디지털 전환 인프라센터 대한민국에 문 연다",
        "디지털 전환 인프라센터가 대한민국에 문을 연다.",
        "해양수산부",
    )
    evidence = classification_evidence(article, self.policy)
    result, needs_model = rule_classify(article, self.policy)
    self.assertTrue(evidence["condition_b"])
    self.assertEqual(result["level"], "important")
    self.assertTrue(needs_model)

def test_ai_infrastructure_link_without_action_is_not_important(self) -> None:
    article = self.article(
        "국산 NPU, 엔비디아 시스템과 연계해 글로벌 AI 인프라 시장 진출 길 연다",
        "관련 보도자료의 자세한 내용은 첨부파일을 참고한다.",
        "과학기술정보통신부",
    )
    evidence = classification_evidence(article, self.policy)
    result, _ = rule_classify(article, self.policy)
    self.assertFalse(evidence["condition_b"])
    self.assertNotIn(result["level"], {"critical", "important"})

    def test_model_critical_without_a_is_demoted_to_important(self) -> None:
        article = self.article(
            "AI 민원시스템 구축 추진",
            "개별 기관이 AI 민원시스템 구축을 추진한다.",
            "해양수산부",
        )
        result = constrain_model_result(
            article,
            {"level": "critical", "confidence": 0.96, "reason": "중요 사업", "signals": ["AI"]},
            self.policy,
        )
        self.assertEqual(result["level"], "important")

    def test_model_important_without_b_is_demoted(self) -> None:
        article = self.article(
            "AI 정책 미래상 논의",
            "행정안전부가 인공지능 정책의 미래상을 포럼에서 논의한다.",
            "행정안전부",
        )
        result = constrain_model_result(
            article,
            {"level": "important", "confidence": 0.9, "reason": "향후 영향", "signals": ["AI"]},
            self.policy,
        )
        self.assertEqual(result["level"], "unrelated")


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
                        "method": "gemini-api",
                        "model": "google/gemini-3.1-flash-lite",
                        "prompt_version": "ip-office-relevance-v1.2",
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
                        "prompt_version": "ip-office-relevance-v1.2",
                    },
                },
            ]
            write_json(article_path, {"schema_version": 2, "date": "2026-07-14", "articles": articles})
            manifest = build_indexes(data_dir)
            self.assertEqual(manifest["relevance_counts"]["critical"], 1)
            self.assertEqual(manifest["relevance_counts"]["unrelated"], 1)
            self.assertEqual(manifest["classified_count"], 2)
            month_index = read_json(data_dir / "2026" / "07" / "index.json")
            self.assertEqual(month_index["relevance_counts"]["critical"], 1)
            self.assertEqual(month_index["articles"][0]["ip_relevance"]["level"], "critical")


if __name__ == "__main__":
    unittest.main()
