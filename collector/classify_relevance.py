from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import requests

from collector.common import normalize_plain_text, now_iso, read_json, write_json

DEFAULT_POLICY_PATH = Path(__file__).with_name("relevance_policy.json")
DEFAULT_ENDPOINT = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4.1-mini"
VALID_LEVELS = {"critical", "important", "normal", "unrelated"}
LEVEL_LABELS = {
    "critical": "매우 중요",
    "important": "중요",
    "normal": "보통",
    "unrelated": "관계없음",
    "unclassified": "미분류",
}
LEVEL_SCORES = {
    "critical": 4,
    "important": 3,
    "normal": 2,
    "unrelated": 1,
    "unclassified": 0,
}
LEVEL_ACTIONS = {
    "critical": "즉시 검토",
    "important": "동향 추적",
    "normal": "참고",
    "unrelated": "제외",
    "unclassified": "검토 필요",
}


@dataclass(frozen=True)
class PendingArticle:
    path: Path
    article: dict[str, Any]
    source_hash: str
    rule_result: dict[str, Any]
    needs_model: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="저장된 보도자료를 지식재산처 연관도 기준으로 AI 분류합니다."
    )
    parser.add_argument("--data-dir", default="docs/data")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--endpoint", default=os.getenv("GITHUB_MODELS_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--model", default=os.getenv("GITHUB_MODELS_MODEL", DEFAULT_MODEL))
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--max-articles", type=int, default=300)
    parser.add_argument("--request-delay", type=float, default=4.1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--rules-only", action="store_true")
    return parser.parse_args()


def load_policy(path: Path) -> dict[str, Any]:
    policy = read_json(path, {})
    if not isinstance(policy, dict) or not policy.get("prompt_version"):
        raise RuntimeError(f"판정 기준 파일을 읽지 못했습니다: {path}")
    return policy


def normalize_for_match(value: Any) -> str:
    return normalize_plain_text(str(value or "")).casefold()


def article_source_hash(article: dict[str, Any]) -> str:
    existing = normalize_plain_text(str(article.get("content_hash", "")))
    if existing:
        return existing
    text = "\n".join(
        normalize_plain_text(str(article.get(key, "")))
        for key in ("id", "title", "summary", "ministry", "content_text")
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def contains_any(text: str, terms: Iterable[str]) -> list[str]:
    found: list[str] = []
    for term in terms:
        normalized = normalize_for_match(term)
        if not normalized:
            continue
        if re.fullmatch(r"[a-z0-9+#._ -]+", normalized, flags=re.IGNORECASE):
            pattern = rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])"
            matched = re.search(pattern, text, flags=re.IGNORECASE) is not None
        else:
            matched = normalized in text
        if matched:
            found.append(str(term))
    return found


def _iter_term_spans(text: str, terms: Iterable[str]) -> list[tuple[int, int, str]]:
    """문자열에서 용어별 위치를 반환합니다."""

    spans: list[tuple[int, int, str]] = []
    for term in terms:
        original = str(term)
        normalized = normalize_for_match(original)
        if not normalized:
            continue
        if re.fullmatch(r"[a-z0-9+#._ -]+", normalized, flags=re.IGNORECASE):
            pattern = rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])"
            spans.extend(
                (match.start(), match.end(), original)
                for match in re.finditer(pattern, text, flags=re.IGNORECASE)
            )
            continue

        start = 0
        while True:
            index = text.find(normalized, start)
            if index < 0:
                break
            spans.append((index, index + len(normalized), original))
            start = index + max(1, len(normalized))
    return sorted(spans, key=lambda item: (item[0], item[1], item[2]))


def linked_term_evidence(
    text: str,
    target_terms: Iterable[str],
    action_terms: Iterable[str],
    *,
    max_distance: int,
) -> tuple[list[str], list[str]]:
    """AI·정보화·보안 대상과 행동어가 같은 문맥에 연결됐는지 확인합니다.

    문장 경계를 넘지 않고 두 표현 사이가 ``max_distance``자 이내인 경우만
    연결된 근거로 인정합니다. 문서 다른 부분에 각각 존재하는 것만으로는
    B 조건을 충족하지 않습니다.
    """

    normalized_text = normalize_for_match(text)
    targets = _iter_term_spans(normalized_text, target_terms)
    actions = _iter_term_spans(normalized_text, action_terms)
    linked_targets: list[str] = []
    linked_actions: list[str] = []

    for target_start, target_end, target in targets:
        for action_start, action_end, action in actions:
            if target_end <= action_start:
                gap = action_start - target_end
                bridge = normalized_text[target_end:action_start]
            elif action_end <= target_start:
                gap = target_start - action_end
                bridge = normalized_text[action_end:target_start]
            else:
                gap = 0
                bridge = ""

            if gap > max_distance:
                continue
            if re.search(r"[.!?。！？;]", bridge):
                continue
            linked_targets.append(target)
            linked_actions.append(action)

    return (
        list(dict.fromkeys(linked_targets)),
        list(dict.fromkeys(linked_actions)),
    )


def make_rule_record(
    level: str,
    reason: str,
    signals: Iterable[str],
    confidence: float,
    *,
    method: str = "rules",
) -> dict[str, Any]:
    level = level if level in VALID_LEVELS else "unrelated"
    return {
        "level": level,
        "label": LEVEL_LABELS[level],
        "score": LEVEL_SCORES[level],
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "reason": normalize_plain_text(reason)[:220],
        "signals": list(dict.fromkeys(normalize_plain_text(item) for item in signals if item))[:5],
        "recommended_action": LEVEL_ACTIONS[level],
        "method": method,
    }


def classification_evidence(
    article: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    """A/B 조건과 강화된 행사 상한을 판단하기 위한 근거를 계산합니다.

    A: 지식재산처 직접 연결. 지식재산·특허행정 직접 언급 또는
       전 부처 준수 의무·공통 기준이 명시된 경우입니다.
    B: AI·정보화·보안 대상에 직접 연결된 구체적 조치입니다.
       행동어가 문서 다른 부분에 따로 존재하는 것만으로는 인정하지 않습니다.
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

    action_targets = policy.get("action_target_terms", policy.get("ai_it_terms", []))
    body_distance = int(policy.get("action_link_max_chars", 140))
    title_distance = int(policy.get("title_summary_link_max_chars", 260))
    title_targets, title_actions = linked_term_evidence(
        title_summary,
        action_targets,
        policy.get("strong_action_terms", []),
        max_distance=title_distance,
    )
    body_targets, body_actions = linked_term_evidence(
        content,
        action_targets,
        policy.get("strong_action_terms", []),
        max_distance=body_distance,
    )
    targeted_action_targets = list(dict.fromkeys(title_targets + body_targets))
    targeted_actions = list(dict.fromkeys(title_actions + body_actions))

    override_title_targets, override_title_actions = linked_term_evidence(
        title_summary,
        action_targets,
        policy.get("event_override_action_terms", []),
        max_distance=title_distance,
    )
    override_body_targets, override_body_actions = linked_term_evidence(
        content,
        action_targets,
        policy.get("event_override_action_terms", []),
        max_distance=body_distance,
    )
    event_override_targets = list(
        dict.fromkeys(override_title_targets + override_body_targets)
    )
    event_override_actions = list(
        dict.fromkeys(override_title_actions + override_body_actions)
    )

    condition_a = bool(ai_it) and (bool(direct_ip) or bool(broad and mandatory))
    condition_b = bool(targeted_action_targets) and bool(targeted_actions)
    event_override_b = bool(event_override_targets) and bool(event_override_actions)

    # 행사·설명회·포럼 형식은 실제 개통·발주·공모·예산확정·시행 등
    # 예외조치가 확인되지 않으면 중요 이상으로 올리지 않습니다.
    event_capped_normal = (
        bool(ai_it)
        and bool(event)
        and not event_override_b
        and bool(condition_b or case_reference)
        and not bool(discussion and not condition_b)
    )
    event_discussion_only = bool(ai_it) and (
        (bool(event) and not event_override_b and not event_capped_normal)
        or (bool(discussion) and not condition_b and not case_reference)
    )
    case_reference_only = (
        bool(ai_it)
        and bool(case_reference)
        and not condition_b
        and not event_discussion_only
        and not event_capped_normal
    )

    signals = (
        direct_ip
        + ai_it
        + targeted_action_targets
        + targeted_actions
        + event_override_actions
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
        "targeted_action_targets": targeted_action_targets,
        "targeted_actions": targeted_actions,
        "event_override_targets": event_override_targets,
        "event_override_actions": event_override_actions,
        "condition_a": condition_a,
        "condition_b": condition_b,
        "event_override_b": event_override_b,
        "event_capped_normal": event_capped_normal,
        "event_discussion_only": event_discussion_only,
        "case_reference_only": case_reference_only,
        "signals": signals,
    }


def _guard_reason(target_level: str, evidence: dict[str, Any]) -> str:
    if evidence["event_discussion_only"]:
        return "실제 개통·발주·공모·예산확정·시행 없이 회의·행사·논의 중심이므로 관계없음으로 조정했습니다."
    if evidence["event_capped_normal"]:
        return "행사·설명회 형식이며 실제 개통·발주·공모·예산확정·시행 등 예외조치가 없어 보통으로 제한했습니다."
    if target_level == "important":
        return "AI·정보화·보안 대상에 직접 연결된 구체적 조치(B)는 확인되지만 지식재산처 직접 연결(A)이 없어 중요으로 조정했습니다."
    if target_level == "normal":
        if evidence["strong"] and not evidence["condition_b"]:
            return "강한 행동어는 있으나 그 대상이 AI·정보화·보안으로 직접 연결되지 않아 보통으로 조정했습니다."
        return "AI·정보화·보안 대상에 직접 연결된 구체적 조치(B)가 확인되지 않아 보통으로 조정했습니다."
    return "AI·정보화 관련성과 대상에 연결된 구체적 조치가 확인되지 않아 관계없음으로 조정했습니다."


def constrain_model_result(
    article: dict[str, Any],
    model_result: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """모델 결과가 대상연결 B 조건과 강화된 행사 상한을 넘지 못하게 강제합니다."""

    result = dict(model_result)
    original_level = str(result.get("level") or "unrelated")
    if original_level not in VALID_LEVELS:
        original_level = "unrelated"
    target_level = original_level
    evidence = classification_evidence(article, policy)

    if evidence["event_discussion_only"]:
        target_level = "unrelated"
    elif evidence["event_capped_normal"] and original_level in {"critical", "important"}:
        target_level = "normal"
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
    """대상연결 B 조건과 강화된 행사 상한에 따른 규칙 사전판정을 반환합니다."""

    evidence = classification_evidence(article, policy)
    signals = evidence["signals"]

    if evidence["event_discussion_only"]:
        return (
            make_rule_record(
                "unrelated",
                "실제 개통·발주·공모·예산확정·시행 없이 회의·포럼·페스티벌·논의·미래상 소개에 그치는 자료입니다.",
                signals,
                0.94,
            ),
            False,
        )

    if evidence["event_capped_normal"]:
        return (
            make_rule_record(
                "normal",
                "AI·정보화 관련 사업을 다루지만 행사·설명회 형식이며 실제 개통·발주·공모·예산확정·시행은 확인되지 않아 보통으로 제한합니다.",
                signals,
                0.88,
            ),
            True,
        )

    if evidence["condition_a"] and evidence["condition_b"]:
        return (
            make_rule_record(
                "critical",
                "지식재산처 직접 연결(A)과 AI·정보화·보안 대상에 직접 연결된 구체적 실행조치(B)를 모두 충족해 즉시 검토가 필요합니다.",
                signals,
                0.94,
            ),
            True,
        )

    if evidence["condition_b"]:
        return (
            make_rule_record(
                "important",
                "AI·정보화·보안 대상에 직접 연결된 구체적 시행·도입·구축·대응조치(B)가 확인되어 동향 추적이 필요합니다.",
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
        reason = (
            "강한 행동어가 있으나 그 대상이 AI·정보화·보안으로 직접 연결되지 않았습니다."
            if evidence["strong"]
            else "AI·정보화 관련성은 있으나 대상에 직접 연결된 구체적 시행·도입·의무 조치(B)는 확인되지 않았습니다."
        )
        return (
            make_rule_record(
                "normal",
                reason,
                signals,
                0.8,
            ),
            True,
        )

    return (
        make_rule_record(
            "unrelated",
            "AI·정보화·보안 또는 지식재산처 업무와 연결되는 실질적 신호가 확인되지 않았습니다.",
            signals,
            0.91,
        ),
        False,
    )

def classification_is_current(
    article: dict[str, Any], policy: dict[str, Any], model: str, token_available: bool
) -> bool:
    current = article.get("ip_relevance")
    if not isinstance(current, dict):
        return False
    if current.get("source_hash") != article_source_hash(article):
        return False
    if current.get("prompt_version") != policy.get("prompt_version"):
        return False
    method = str(current.get("method") or "")
    if method == "github-models" and current.get("model") != model:
        return False
    if method == "rules-fallback" and token_available:
        # GitHub Models가 일시적으로 제한되더라도 같은 자료를 매 실행마다
        # 재호출하지 않는다. 24시간이 지난 뒤에만 다시 시도한다.
        classified_at = str(current.get("classified_at") or "")
        try:
            classified_time = datetime.fromisoformat(classified_at)
            now = datetime.now(classified_time.tzinfo) if classified_time.tzinfo else datetime.now()
            if (now - classified_time).total_seconds() < 24 * 60 * 60:
                return str(current.get("level")) in VALID_LEVELS
        except ValueError:
            pass
        return False
    return str(current.get("level")) in VALID_LEVELS


def article_excerpt(article: dict[str, Any], max_chars: int = 1800) -> str:
    title = normalize_plain_text(str(article.get("title", "")))
    summary = normalize_plain_text(str(article.get("summary", "")))
    content = normalize_plain_text(str(article.get("content_text", "")))
    header = f"제목: {title}\n요약: {summary}\n"
    remaining = max(max_chars - len(header), 300)
    if len(content) <= remaining:
        body = content
    else:
        head_size = int(remaining * 0.78)
        tail_size = remaining - head_size
        body = f"{content[:head_size]} … [중략] … {content[-tail_size:]}"
    return f"{header}본문 발췌: {body}"[:max_chars]


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
            "3. B는 AI·정보화·보안 대상에 직접 연결된 구체적 조치입니다. 실행 동사의 직접 대상이 AI 모델·정보시스템·데이터 플랫폼·클라우드·소프트웨어·정보보호·보안사고 등이어야 합니다.",
            "4. AI·정보화 용어와 착수·점검·지원 같은 행동어가 문서의 서로 다른 부분에 따로 존재하는 것만으로는 B가 아닙니다. 같은 문장 또는 가까운 문맥에서 대상과 행동이 연결되어야 합니다.",
            "5. 공항 개발 착수, 건설현장 안전점검, 외국인 사업장 점검 등 AI·정보화·보안이 아닌 대상에 대한 행동은 B로 인정하지 않습니다.",
            "6. 품질경영시스템·안전관리시스템 등 일반 관리체계의 '시스템'은 정보시스템으로 해석하지 않습니다.",
            "7. critical은 A와 B를 모두 충족할 때만 선택합니다.",
            "8. important는 대상연결 B를 충족하면 선택할 수 있으며 A는 필수조건이 아닙니다. B가 없으면 critical 또는 important를 선택하지 않습니다.",
            "9. 회의·포럼·학술대회·페스티벌·박람회·설명회 등 행사 형식은 실제 시스템 개통, 사업 발주·공모, 예산 확정, 법령·지침 시행, 서비스 운영 개시, 신규 플랫폼 도입이 명확할 때만 important 이상이 가능합니다.",
            "10. 행사가 단순 사례 발표·체험·강연·활용방안 논의·미래상 소개에 그치면 unrelated로, 독립적인 참고사례가 있더라도 최대 normal로 판정합니다.",
            "11. 행정안전부·과학기술정보통신부 등 우선기관 자료라는 이유만으로 등급을 높이지 않습니다.",
            "12. 제정·개정·시행·도입·구축·착수 등 강한 조치와 논의·모색·소개·공유·전망 등 약한 표현을 구분합니다.",
            "13. 추측을 최소화하고 원문에서 확인 가능한 대상과 구체적 행동을 판정 이유에 명시합니다.",
            "출력은 요청된 JSON 스키마만 따릅니다.",
        ]
    )

def response_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "ip_relevance_batch",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string"},
                                "level": {
                                    "type": "string",
                                    "enum": ["critical", "important", "normal", "unrelated"],
                                },
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "reason": {"type": "string", "maxLength": 220},
                                "signals": {
                                    "type": "array",
                                    "maxItems": 5,
                                    "items": {"type": "string", "maxLength": 60},
                                },
                            },
                            "required": ["id", "level", "confidence", "reason", "signals"],
                        },
                    }
                },
                "required": ["results"],
            },
        },
    }


def parse_model_content(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("AI 응답에 choices가 없습니다.")
    content = choices[0].get("message", {}).get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        content = "".join(text_parts)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("AI 응답 본문이 비어 있습니다.")
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        preview = normalize_plain_text(cleaned)[:300]
        raise RuntimeError(f"AI JSON 응답을 해석하지 못했습니다: {preview}") from exc


def call_github_models(
    batch: list[PendingArticle],
    *,
    policy: dict[str, Any],
    endpoint: str,
    model: str,
    token: str,
    session: requests.Session,
) -> dict[str, dict[str, Any]]:
    article_payload = [
        {
            "id": str(item.article.get("id", "")),
            "ministry": normalize_plain_text(str(item.article.get("ministry", "기관 미상"))),
            "rule_hint": item.rule_result.get("level"),
            "document": article_excerpt(item.article),
        }
        for item in batch
    ]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": build_system_prompt(policy)},
            {
                "role": "user",
                "content": (
                    "다음 보도자료를 각각 판정하십시오. 반환 형식은 "
                    '{"results":[{"id":"문서 ID","level":"critical|important|normal|unrelated",'
                    '"confidence":0.0,"reason":"근거","signals":["신호"]}]} 입니다.\n'
                    + json.dumps(article_payload, ensure_ascii=False)
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 1800,
        "response_format": response_schema(),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2026-03-10",
    }

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.post(endpoint, headers=headers, json=body, timeout=(10, 90))
            if response.status_code == 429 and attempt < 2:
                retry_after = float(response.headers.get("Retry-After", "8"))
                time.sleep(max(retry_after, 4.0))
                continue
            if response.status_code == 422 and body.get("response_format", {}).get("type") == "json_schema":
                # 일부 모델 배포가 JSON Schema를 일시적으로 지원하지 않으면
                # JSON object 모드로 한 번 더 요청한다.
                body["response_format"] = {"type": "json_object"}
                continue
            if response.status_code >= 400:
                preview = normalize_plain_text(response.text)[:500]
                raise RuntimeError(f"GitHub Models HTTP {response.status_code}: {preview}")
            parsed = parse_model_content(response.json())
            results = parsed.get("results")
            if not isinstance(results, list):
                raise RuntimeError("AI JSON 응답에 results 배열이 없습니다.")
            mapped: dict[str, dict[str, Any]] = {}
            for result in results:
                if not isinstance(result, dict):
                    continue
                article_id = str(result.get("id", ""))
                level = str(result.get("level", ""))
                if article_id and level in VALID_LEVELS:
                    mapped[article_id] = result
            return mapped
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(str(last_error or "GitHub Models 요청 실패"))


def finalize_record(
    base: dict[str, Any],
    *,
    source_hash: str,
    policy: dict[str, Any],
    model: str,
    method: str,
) -> dict[str, Any]:
    level = str(base.get("level", "unrelated"))
    if level not in VALID_LEVELS:
        level = "unrelated"
    try:
        confidence = float(base.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    record = {
        "level": level,
        "label": LEVEL_LABELS[level],
        "score": LEVEL_SCORES[level],
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "reason": normalize_plain_text(str(base.get("reason", "")))[:220]
        or "판정 근거가 제공되지 않았습니다.",
        "signals": [
            normalize_plain_text(str(item))[:60]
            for item in (base.get("signals") or [])
            if normalize_plain_text(str(item))
        ][:5],
        "recommended_action": LEVEL_ACTIONS[level],
        "method": method,
        "model": model if method == "github-models" else None,
        "prompt_version": policy["prompt_version"],
        "classified_at": now_iso(),
        "source_hash": source_hash,
    }
    return record


def iter_article_files(data_dir: Path) -> Iterable[Path]:
    yield from sorted(
        data_dir.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/articles.json")
    )


def collect_pending(
    data_dir: Path,
    policy: dict[str, Any],
    model: str,
    token_available: bool,
    force: bool,
    max_articles: int,
) -> tuple[list[PendingArticle], Counter[str]]:
    pending: list[PendingArticle] = []
    stats: Counter[str] = Counter()
    for path in iter_article_files(data_dir):
        payload = read_json(path, {})
        articles = payload.get("articles")
        if not isinstance(articles, list):
            continue
        for article in articles:
            if not isinstance(article, dict):
                continue
            stats["scanned"] += 1
            if not force and classification_is_current(article, policy, model, token_available):
                stats["cached"] += 1
                continue
            rule_result, needs_model = rule_classify(article, policy)
            pending.append(
                PendingArticle(
                    path=path,
                    article=article,
                    source_hash=article_source_hash(article),
                    rule_result=rule_result,
                    needs_model=needs_model,
                )
            )
            if len(pending) >= max_articles:
                stats["limited"] += 1
                return pending, stats
    return pending, stats


def save_records(records: list[tuple[PendingArticle, dict[str, Any]]]) -> Counter[str]:
    by_path: dict[Path, dict[str, dict[str, Any]]] = {}
    result_counts: Counter[str] = Counter()
    for pending, record in records:
        by_path.setdefault(pending.path, {})[str(pending.article.get("id", ""))] = record
        result_counts[str(record.get("level", "unclassified"))] += 1

    for path, records_by_id in by_path.items():
        payload = read_json(path, {})
        articles = payload.get("articles")
        if not isinstance(articles, list):
            continue
        changed = False
        for article in articles:
            if not isinstance(article, dict):
                continue
            article_id = str(article.get("id", ""))
            record = records_by_id.get(article_id)
            if record is None:
                continue
            article["ip_relevance"] = record
            changed = True
        if changed:
            payload["classification_prompt_version"] = next(
                iter(records_by_id.values()), {}
            ).get("prompt_version")
            payload["classification_updated_at"] = now_iso()
            payload["relevance_counts"] = dict(
                Counter(
                    str(article.get("ip_relevance", {}).get("level", "unclassified"))
                    for article in articles
                    if isinstance(article, dict)
                )
            )
            write_json(path, payload)
    return result_counts


def chunks(values: list[PendingArticle], size: int) -> Iterable[list[PendingArticle]]:
    size = max(1, size)
    for index in range(0, len(values), size):
        yield values[index : index + size]


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    policy = load_policy(Path(args.policy))
    token = os.getenv("GITHUB_TOKEN", "").strip()
    token_available = bool(token) and not args.rules_only

    print(f"지식재산처 연관도 분석 기준: {policy['prompt_version']}", flush=True)
    print(f"AI 모델: {args.model}", flush=True)
    print(
        "분석 방식: "
        + ("GitHub Models + 규칙 사전판정" if token_available else "규칙 기반(모델 토큰 없음 또는 rules-only)"),
        flush=True,
    )

    pending, scan_stats = collect_pending(
        data_dir,
        policy,
        args.model,
        token_available,
        args.force,
        max(1, args.max_articles),
    )
    print(
        f"검사 {scan_stats['scanned']}건 / 캐시 재사용 {scan_stats['cached']}건 / "
        f"이번 분석 대상 {len(pending)}건",
        flush=True,
    )
    if not pending:
        print("새로 판정할 보도자료가 없습니다.", flush=True)
        return 0

    records: list[tuple[PendingArticle, dict[str, Any]]] = []
    model_candidates: list[PendingArticle] = []
    for item in pending:
        if item.needs_model and token_available:
            model_candidates.append(item)
        else:
            fallback_method = "rules-fallback" if item.needs_model and not token_available else "rules"
            records.append(
                (
                    item,
                    finalize_record(
                        item.rule_result,
                        source_hash=item.source_hash,
                        policy=policy,
                        model=args.model,
                        method=fallback_method,
                    ),
                )
            )

    if model_candidates:
        session = requests.Session()
        batches = list(chunks(model_candidates, max(1, args.batch_size)))
        for batch_index, batch in enumerate(batches, start=1):
            ids = [str(item.article.get("id", "")) for item in batch]
            print(
                f"AI 분석 {batch_index}/{len(batches)}: {len(batch)}건 ({', '.join(ids)})",
                flush=True,
            )
            try:
                model_results = call_github_models(
                    batch,
                    policy=policy,
                    endpoint=args.endpoint,
                    model=args.model,
                    token=token,
                    session=session,
                )
            except Exception as exc:  # 모델 장애가 대시보드 전체 배포를 막지 않게 한다.
                print(
                    f"::warning title=AI 판정 대체::{exc}. 이 묶음은 규칙 판정으로 저장합니다.",
                    file=sys.stderr,
                    flush=True,
                )
                model_results = {}

            for item in batch:
                article_id = str(item.article.get("id", ""))
                model_record = model_results.get(article_id)
                if model_record is None:
                    base = dict(item.rule_result)
                    method = "rules-fallback"
                else:
                    base = constrain_model_result(item.article, model_record, policy)
                    method = "github-models"
                records.append(
                    (
                        item,
                        finalize_record(
                            base,
                            source_hash=item.source_hash,
                            policy=policy,
                            model=args.model,
                            method=method,
                        ),
                    )
                )
            if batch_index < len(batches):
                time.sleep(max(0.0, args.request_delay))

    counts = save_records(records)
    labels = [
        f"{LEVEL_LABELS[level]} {counts[level]}건"
        for level in ("critical", "important", "normal", "unrelated")
    ]
    fallback_count = sum(
        1 for _, record in records if record.get("method") == "rules-fallback"
    )
    ai_count = sum(1 for _, record in records if record.get("method") == "github-models")
    rule_count = len(records) - ai_count - fallback_count
    print(
        "연관도 분석 완료: "
        + " / ".join(labels)
        + f" · AI {ai_count}건 · 규칙 {rule_count}건 · AI 실패 대체 {fallback_count}건",
        flush=True,
    )
    if scan_stats["limited"]:
        print(
            f"::warning title=분석 건수 제한::한 번에 {args.max_articles}건까지만 처리했습니다. "
            "다음 실행에서 남은 자료를 이어서 분석합니다.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
