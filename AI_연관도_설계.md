# 지식재산처 AI 연관도 기능

## 기준

- 정상 기준일: 2026-07-29
- 정책 버전: `ip-office-relevance-v1.0`
- 기본 모델: `gpt-4.1-mini`
- 현재 AI 공급자: OpenAI API

2026년 7월 29일까지 사용한 판정 정책·프롬프트·규칙 사전판정은 변경하지 않습니다. 당시 사용하던 GitHub Models 추론 서비스가 2026년 7월 30일 종료되어, 같은 판단 기준을 OpenAI API로 호출하도록 전송 계층만 교체했습니다.

## 처리 흐름

```text
정책브리핑 보도자료 수집
→ 제목·요약·기관·본문 발췌 정규화
→ 명백한 자료 규칙 사전판정
→ AI·정보화·지식재산 후보를 OpenAI API로 맥락 판정
→ 날짜별 articles.json에 ip_relevance 저장
→ 월별 색인에 단계별 건수 집계
→ 달력 색상 숫자 및 목록 배경 표시
```

## 저장 필드

신규 AI 판정:

```json
{
  "ip_relevance": {
    "level": "critical",
    "label": "매우 중요",
    "score": 4,
    "confidence": 0.96,
    "reason": "전 부처에 즉시 적용되는 AI 관련 규정 개정입니다.",
    "signals": ["인공지능 기본법", "전 부처", "규정 개정"],
    "recommended_action": "즉시 검토",
    "method": "openai-api",
    "model": "openai/gpt-4.1-mini",
    "prompt_version": "ip-office-relevance-v1.0",
    "classified_at": "2026-10-28T23:00:00+09:00",
    "source_hash": "..."
  }
}
```

과거 정상 판정은 다음 형식으로 그대로 보존합니다.

```json
{
  "method": "github-models",
  "model": "openai/gpt-4.1-mini",
  "prompt_version": "ip-office-relevance-v1.0"
}
```

AI 호출 실패 또는 키 미등록 시:

```json
{
  "method": "rules-fallback",
  "model": null
}
```

AI 검토가 불필요한 명백한 자료의 규칙 판정:

```json
{
  "method": "rules",
  "model": null
}
```

## 캐시 및 재분석

다음 값이 같으면 기존 판정을 재사용합니다.

- 본문의 `content_hash`
- 판정 기준의 `prompt_version`
- 모델명

따라서 기존 `github-models` 방식으로 정상 판정된 `openai/gpt-4.1-mini` 결과는 공급자 전환 후에도 유지합니다.

다음 경우 다시 분석합니다.

- 보도자료 내용이 변경됨
- 판정 정책 버전이 변경됨
- `force_ai_reclassify=true`로 수동 실행함
- `rules-fallback` 저장 후 재시도 유예기간이 지남

과거 정상 판정을 유지하려면 `force_ai_reclassify`를 사용하지 않습니다.

## 실패 처리

기본 동작에서는 AI 장애가 수집·배포 전체를 막지 않도록 동일 기준의 규칙 판정을 저장하고 `method`를 `rules-fallback`으로 표시합니다.

다만 AI 장애를 워크플로 성공으로 처리하지 않아야 하는 검증 실행에서는 다음 입력을 사용합니다.

```text
require_ai=true
```

이 경우 다음 중 하나가 발생하면 워크플로가 실패합니다.

- `OPENAI_API_KEY` 미등록
- OpenAI API 호출 실패
- 응답에서 유효한 판정 결과를 받지 못함

## 운영 설정

Repository secret:

```text
OPENAI_API_KEY
```

선택 Repository variable:

```text
OPENAI_MODEL=gpt-4.1-mini
```

## 구현 파일

| 파일 | 역할 |
|---|---|
| `collector/relevance_policy.json` | 4단계 판단 기준과 정책 용어 |
| `collector/classify_relevance.py` | 공통 규칙·프롬프트·캐시·저장 처리 |
| `collector/classify_relevance_openai.py` | OpenAI API 호출과 공급자별 기록 처리 |
| `tests/test_relevance.py` | 공통 판정 규칙 테스트 |
| `tests/test_openai_relevance.py` | OpenAI 요청·응답 변환 테스트 |
