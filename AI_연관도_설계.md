# 지식재산처 AI 연관도 기능

## 처리 흐름

```text
정책브리핑 보도자료 수집
→ 제목·요약·기관·본문 발췌 정규화
→ 명백한 무관 자료 규칙 사전판정
→ AI·정보화·지식재산 후보를 GitHub Models로 맥락 판정
→ 날짜별 articles.json에 ip_relevance 저장
→ 월별 색인에 단계별 건수 집계
→ 달력 색상 숫자 및 목록 배경 표시
```

## 저장 필드

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
    "method": "github-models",
    "model": "openai/gpt-4.1-mini",
    "prompt_version": "ip-office-relevance-v1.0",
    "classified_at": "2026-07-16T10:00:00+09:00",
    "source_hash": "..."
  }
}
```

## 캐시 및 재분석

본문의 `content_hash`, 판정 기준의 `prompt_version`, AI 모델명이 같으면 기존 판정을 재사용합니다. 보도자료 내용이 바뀌거나 기준·모델이 바뀌면 다시 분석합니다. `force_ai_reclassify` 입력으로 전체 재분석도 가능합니다.

## 실패 방지

AI 호출 실패는 수집·배포 실패로 처리하지 않습니다. 동일 기준의 규칙 판정을 저장하고 `method`를 `rules-fallback`으로 표시합니다. AI 접근이 복구되면 다음 실행에서 해당 자료만 다시 시도합니다.
