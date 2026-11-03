from __future__ import annotations

import json
import textwrap
from pathlib import Path


def update_policy() -> None:
    path = Path("collector/relevance_policy.json")
    policy = json.loads(path.read_text(encoding="utf-8"))
    policy["schema_version"] = 2
    policy["prompt_version"] = "ip-office-relevance-v1.1"
    policy["description"] = (
        "정부 보도자료가 지식재산처의 AI·정보화·시스템 업무에 미치는 영향을 "
        "A(직접 연결)와 B(구체적 조치) 조건으로 분류한다."
    )

    levels = {item["key"]: item for item in policy.get("levels", [])}
    levels["critical"]["definition"] = (
        "A(지식재산처 직접 연결)와 B(구체적 시행·도입·의무 조치)를 모두 충족하는 사안"
    )
    levels["critical"]["examples"] = [
        "지식재산처·특허행정에 직접 적용되는 AI 법령·공통기준의 제정·개정·시행",
        "전 부처 준수 의무가 있는 AI·데이터·보안 기준의 시행 또는 의무화",
        "지식재산처 업무·시스템에 직접 영향을 주는 보안사고와 구체적 대응조치",
    ]
    levels["important"]["definition"] = (
        "AI·정보화 맥락에서 B(구체적 시행·도입·구축·사업 조치)를 충족하는 사안. "
        "A(지식재산처 직접 연결)는 필수조건이 아니다."
    )
    levels["important"]["examples"] = [
        "AI·정보시스템의 구축·도입·개통·사업 착수·공모·발주",
        "전 부처 또는 개별 기관의 구체적 AI 시범사업·실증·운영 개시",
        "AI·정보보호 사고에 대한 점검·복구·대응조치",
    ]
    levels["normal"]["definition"] = (
        "AI·정보화 관련성이 있으나 B에 해당하는 구체적 조치가 없고, "
        "사례 소개·기술동향 공유 등 참고 가치만 있는 사안"
    )
    levels["unrelated"]["definition"] = (
        "AI·정보화 관련성이 없거나, 구체적 조치 없이 회의·포럼·논의·모색·미래상 소개에 그치는 사안"
    )

    policy["mandatory_application_terms"] = [
        "전 부처가 준수",
        "전부처가 준수",
        "전 부처 적용",
        "전부처 적용",
        "모든 부처 적용",
        "각 부처 적용",
        "전 기관 적용",
        "전기관 적용",
        "행정기관 공통",
        "정부 공통 기준",
        "공통 준수기준",
        "준수 의무",
        "적용 의무",
        "의무화",
        "즉시 적용",
    ]
    policy["strong_action_terms"] = [
        "제정",
        "개정",
        "공포",
        "시행한다",
        "시행 예정",
        "시행에 들어간",
        "입법예고",
        "행정예고",
        "의무화",
        "준수 의무",
        "적용 의무",
        "도입한다",
        "도입 추진",
        "구축한다",
        "구축 착수",
        "구축 추진",
        "개통",
        "운영 개시",
        "서비스 개시",
        "사업 착수",
        "사업을 추진",
        "시범사업 추진",
        "실증 착수",
        "예산 확정",
        "예산 편성",
        "발주",
        "입찰",
        "계약 체결",
        "공모",
        "복구",
        "점검 실시",
        "대응 조치",
        "대응대책 시행",
    ]
    policy["weak_action_terms"] = [
        "논의",
        "모색",
        "소개",
        "공유",
        "전망",
        "미래상",
        "발표",
        "협력 강화",
        "의견수렴",
        "참석",
        "방문",
        "교류",
        "홍보",
    ]
    policy["discussion_terms"] = [
        "논의",
        "모색",
        "전망",
        "미래상",
        "의견수렴",
        "회의",
        "포럼",
        "컨퍼런스",
        "콘퍼런스",
        "세미나",
        "워크숍",
        "간담회",
        "설명회",
        "공청회",
        "토론회",
        "협의회",
        "집행이사회",
    ]
    policy["case_reference_terms"] = [
        "사례 소개",
        "사례 발표",
        "사례 공유",
        "성과 공유",
        "체계 소개",
        "기술동향",
        "기술 동향",
        "제품 소개",
        "서비스 소개",
        "전시회",
        "박람회",
    ]
    policy.pop("substantive_action_terms", None)
    path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_classifier() -> None:
    path = Path("collector/classify_relevance.py")
    text = path.read_text(encoding="utf-8")
    start = text.index("def rule_classify(")
    end = text.index("\ndef classification_is_current(", start)
    new_rules = textwrap.dedent(
        '''
        def classification_evidence(
            article: dict[str, Any], policy: dict[str, Any]
        ) -> dict[str, Any]:
            """A/B 조건과 행사·논의 상한을 판단하기 위한 근거를 계산합니다.

            A: 지식재산처 직접 연결. 지식재산·특허행정 직접 언급 또는
               전 부처 준수 의무·공통 기준이 명시된 경우입니다.
            B: 구체적 조치. 제정·개정·시행·의무화·도입·구축·착수·개통·
               발주·공모·점검·복구 등 실행 조치가 원문에 명시된 경우입니다.
            """

            title = normalize_for_match(article.get("title"))
            summary = normalize_for_match(article.get("summary"))
            ministry = normalize_for_match(article.get("ministry"))
            content = normalize_for_match(article.get("content_text"))
            text = " ".join([title, summary, ministry, content])
            title_summary = " ".join([title, summary])

            direct_ip = contains_any(text, policy.get("direct_ip_terms", []))
            ai_it = contains_any(text, policy.get("ai_it_terms", []))
            broad = contains_any(text, policy.get("government_wide_terms", []))
            foundational = contains_any(text, policy.get("foundational_regulation_terms", []))
            regulatory = contains_any(text, policy.get("regulatory_terms", []))
            incident = contains_any(text, policy.get("security_incident_terms", []))
            mandatory = contains_any(text, policy.get("mandatory_application_terms", []))
            strong = contains_any(text, policy.get("strong_action_terms", []))
            weak = contains_any(text, policy.get("weak_action_terms", []))
            event = contains_any(title_summary, policy.get("event_terms", []))
            discussion = contains_any(text, policy.get("discussion_terms", []))
            case_reference = contains_any(text, policy.get("case_reference_terms", []))
            priority_ministry = contains_any(ministry, policy.get("priority_ministries", []))

            condition_a = bool(ai_it) and (bool(direct_ip) or bool(broad and mandatory))
            condition_b = bool(ai_it) and bool(strong or incident)
            event_discussion_only = bool(ai_it) and bool(event or discussion) and not condition_b
            case_reference_only = (
                bool(ai_it)
                and bool(case_reference)
                and not condition_b
                and not event_discussion_only
            )

            signals = (
                direct_ip
                + ai_it
                + broad
                + foundational
                + regulatory
                + incident
                + mandatory
                + strong
                + weak
                + event
                + discussion
                + case_reference
            )
            return {
                "direct_ip": direct_ip,
                "ai_it": ai_it,
                "broad": broad,
                "foundational": foundational,
                "regulatory": regulatory,
                "incident": incident,
                "mandatory": mandatory,
                "strong": strong,
                "weak": weak,
                "event": event,
                "discussion": discussion,
                "case_reference": case_reference,
                "priority_ministry": priority_ministry,
                "condition_a": condition_a,
                "condition_b": condition_b,
                "event_discussion_only": event_discussion_only,
                "case_reference_only": case_reference_only,
                "signals": signals,
            }


        def _guard_reason(target_level: str, evidence: dict[str, Any]) -> str:
            if evidence["event_discussion_only"]:
                return "구체적 시행·도입 조치 없이 회의·논의·미래상 소개 중심이므로 관계없음으로 조정했습니다."
            if target_level == "important":
                return "구체적 조치(B)는 확인되지만 지식재산처 직접 연결(A)이 없어 중요으로 조정했습니다."
            if target_level == "normal":
                return "구체적 시행·도입·의무 조치(B)가 확인되지 않아 보통으로 조정했습니다."
            return "AI·정보화 관련성과 구체적 조치가 확인되지 않아 관계없음으로 조정했습니다."


        def constrain_model_result(
            article: dict[str, Any],
            model_result: dict[str, Any],
            policy: dict[str, Any],
        ) -> dict[str, Any]:
            """모델 결과가 A/B 조건과 행사·논의 상한을 넘지 못하게 강제합니다."""

            result = dict(model_result)
            original_level = str(result.get("level") or "unrelated")
            if original_level not in VALID_LEVELS:
                original_level = "unrelated"
            target_level = original_level
            evidence = classification_evidence(article, policy)

            if evidence["event_discussion_only"]:
                target_level = "unrelated"
            elif evidence["case_reference_only"] and original_level in {"critical", "important"}:
                target_level = "normal"
            elif original_level == "critical" and not (
                evidence["condition_a"] and evidence["condition_b"]
            ):
                if evidence["condition_b"]:
                    target_level = "important"
                elif evidence["ai_it"]:
                    target_level = "normal"
                else:
                    target_level = "unrelated"
            elif original_level == "important" and not evidence["condition_b"]:
                target_level = "normal" if evidence["ai_it"] else "unrelated"

            if target_level != original_level:
                original_reason = normalize_plain_text(str(result.get("reason") or ""))
                reason = _guard_reason(target_level, evidence)
                if original_reason:
                    reason = f"{reason} 원 모델 근거: {original_reason}"
                result["reason"] = reason[:220]
                try:
                    result["confidence"] = min(float(result.get("confidence", 0.8)), 0.9)
                except (TypeError, ValueError):
                    result["confidence"] = 0.8
            result["level"] = target_level
            return result


        def rule_classify(article: dict[str, Any], policy: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            """A/B 조건과 행사·논의 상한에 따른 규칙 사전판정을 반환합니다."""

            evidence = classification_evidence(article, policy)
            signals = evidence["signals"]

            if evidence["event_discussion_only"]:
                return (
                    make_rule_record(
                        "unrelated",
                        "구체적인 시행·도입·의무 조치 없이 회의·포럼·논의·미래상 소개에 그치는 자료입니다.",
                        signals,
                        0.94,
                    ),
                    False,
                )

            if evidence["condition_a"] and evidence["condition_b"]:
                return (
                    make_rule_record(
                        "critical",
                        "지식재산처 직접 연결(A)과 구체적 실행조치(B)를 모두 충족해 즉시 검토가 필요합니다.",
                        signals,
                        0.94,
                    ),
                    True,
                )

            if evidence["condition_b"]:
                return (
                    make_rule_record(
                        "important",
                        "AI·정보화 분야의 구체적 시행·도입·구축·대응조치(B)가 확인되어 동향 추적이 필요합니다.",
                        signals,
                        0.88,
                    ),
                    True,
                )

            if evidence["case_reference_only"]:
                return (
                    make_rule_record(
                        "normal",
                        "구체적 조치 없이 사례·체계·기술동향을 소개하는 자료로 참고 가치가 있습니다.",
                        signals,
                        0.84,
                    ),
                    True,
                )

            if evidence["ai_it"]:
                return (
                    make_rule_record(
                        "normal",
                        "AI·정보화 관련성은 있으나 구체적 시행·도입·의무 조치(B)는 확인되지 않았습니다.",
                        signals,
                        0.8,
                    ),
                    True,
                )

            return (
                make_rule_record(
                    "unrelated",
                    "AI·정보화·시스템 또는 지식재산처 업무와 연결되는 실질적 신호가 확인되지 않았습니다.",
                    signals,
                    0.91,
                ),
                False,
            )
        '''
    ).lstrip()
    text = text[:start] + new_rules + text[end:]

    prompt_start = text.index("def build_system_prompt(")
    prompt_end = text.index("\ndef response_schema(", prompt_start)
    new_prompt = textwrap.dedent(
        '''
        def build_system_prompt(policy: dict[str, Any]) -> str:
            level_lines = []
            for level in policy.get("levels", []):
                examples = "; ".join(level.get("examples", []))
                level_lines.append(
                    f"- {level['key']} / {level['label']}: {level['definition']} 예: {examples}"
                )
            return "\n".join(
                [
                    "당신은 대한민국 지식재산처의 AI·정보화 정책 모니터링 담당 분석가입니다.",
                    "정부 보도자료가 지식재산처의 법령, 업무, 정보시스템, 데이터, 보안, AI 사업에 미칠 영향을 판정하십시오.",
                    "다음 네 단계 중 반드시 하나만 선택하십시오.",
                    *level_lines,
                    "판정 원칙:",
                    "1. 제목의 단어만 보지 말고 기관·요약·본문 발췌의 실질적 조치와 적용 범위를 함께 판단합니다.",
                    "2. A는 지식재산처 직접 연결입니다. 지식재산·특허행정 직접 언급 또는 전 부처 준수 의무·공통기준의 명시가 필요합니다.",
                    "3. B는 구체적 조치입니다. 제정·개정·시행·의무화·도입·구축·착수·개통·발주·공모·점검·복구 등 실행이 원문에 명시되어야 합니다.",
                    "4. critical은 A와 B를 모두 충족할 때만 선택합니다.",
                    "5. important는 AI·정보화 맥락에서 B를 충족하면 선택할 수 있으며 A는 필수조건이 아닙니다.",
                    "6. B가 없으면 critical 또는 important를 선택하지 않습니다.",
                    "7. 회의·포럼·국제행사·논의·모색·미래상 소개만 있고 B가 없으면 unrelated로 판정합니다.",
                    "8. 사례·체계·기술동향 소개만 있고 B가 없으면 최대 normal입니다.",
                    "9. 행정안전부·과학기술정보통신부 등 우선기관 자료라는 이유만으로 등급을 높이지 않습니다.",
                    "10. 제정·개정·시행·도입·구축·착수 등 강한 조치와 논의·모색·소개·공유·전망 등 약한 표현을 구분합니다.",
                    "11. 행사 형식이라도 실제 제도 개정·사업 도입·사고 대응이 명시되면 B 충족 여부에 따라 판정합니다.",
                    "12. 추측을 최소화하고 원문에서 확인 가능한 내용만 근거로 1~2문장 이유를 작성합니다.",
                    "출력은 요청된 JSON 스키마만 따릅니다.",
                ]
            )
        '''
    ).lstrip()
    text = text[:prompt_start] + new_prompt + text[prompt_end:]

    old = '                else:\n                    base = model_record\n                    method = "github-models"\n'
    new = '                else:\n                    base = constrain_model_result(item.article, model_record, policy)\n                    method = "github-models"\n'
    if old not in text:
        raise RuntimeError("GitHub Models 결과 처리 위치를 찾지 못했습니다.")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def update_gemini() -> None:
    path = Path("collector/classify_relevance_gemini.py")
    text = path.read_text(encoding="utf-8")
    marker = "    classification_is_current,\n"
    if "    constrain_model_result,\n" not in text:
        text = text.replace(marker, marker + "    constrain_model_result,\n", 1)
    old = '                else:\n                    base_record = model_record\n                    method = "gemini-api"\n'
    new = '                else:\n                    base_record = constrain_model_result(item.article, model_record, policy)\n                    method = "gemini-api"\n'
    if old not in text:
        raise RuntimeError("Gemini 결과 처리 위치를 찾지 못했습니다.")
    text = text.replace(old, new, 1)
    text = text.replace(
        "2026-07-29 기준으로 Gemini API를 이용해 분류합니다.",
        "A/B 정책 기준으로 Gemini API를 이용해 분류합니다.",
    )
    path.write_text(text, encoding="utf-8")


def update_tests() -> None:
    Path("tests/test_relevance.py").write_text(
        '''from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from collector.build_indexes import build_indexes
from collector.classify_relevance import constrain_model_result, load_policy, rule_classify
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
                        "prompt_version": "ip-office-relevance-v1.1",
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
                        "prompt_version": "ip-office-relevance-v1.1",
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
''',
        encoding="utf-8",
    )


def main() -> None:
    update_policy()
    update_classifier()
    update_gemini()
    update_tests()


if __name__ == "__main__":
    main()
