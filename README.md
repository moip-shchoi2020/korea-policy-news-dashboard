# 정부 보도자료 AI·정보화 동향 대시보드

대한민국 정책브리핑 보도자료를 정기 수집하고, 지식재산처와의 연관도를 4단계로 분석하여 GitHub Pages와 Telegram으로 제공하는 프로젝트입니다.

기본 검색 키워드:

- `AI`
- `정보화 사업`
- `시스템`
- `AX`

## 주요 기능

- 정책브리핑 보도자료 목록·상세페이지 수집
- `년/월/일` 폴더별 제목·요약·본문·원문 링크 저장
- 수정된 보도자료의 이전 버전 보관
- 지식재산처 연관도 4단계 분석
  - 매우 중요
  - 중요
  - 보통
  - 관계없음
- 달력형 집계와 중요도별 표시
- 키워드 편집 및 브라우저 즉시 재집계
- GitHub Pages 자동 배포
- 08시·16시 Telegram 브리핑
- GitHub Actions 자체 예약으로 하루 4회 실행

## 2026-07-29 기준 복원과 Gemini 전환

2026년 7월 29일까지 사용하던 연관도 정책·프롬프트·규칙 사전판정은 그대로 유지합니다.

```text
정책 버전: ip-office-relevance-v1.0
현재 모델: gemini-3.1-flash-lite
현재 공급자: Google Gemini API
```

기존 GitHub Models 서비스는 2026년 7월 30일 종료되었습니다. 이후 공급자만 Google Gemini API로 교체했으며, 과거 `github-models` 방식으로 정상 저장된 판정은 재분류하지 않고 그대로 보존합니다. 신규 AI 판정은 `gemini-api` 방식으로 기록합니다.

복원 원인과 변경 내역은 다음 문서를 참고합니다.

```text
RECOVERY_2026-07-29.md
```

## 화면 집계 기준

달력과 오른쪽 목록은 현재 입력된 키워드와 일치하는 보도자료를 표시합니다. 여러 키워드는 OR 조건입니다. 키워드를 모두 지우면 해당 월의 전체 보도자료를 표시합니다.

영문 키워드 `AI`, `AX`는 다른 영단어 내부 철자와 잘못 일치하지 않도록 영문·숫자 경계를 적용합니다.

수정 건수는 최초 수집 이후 제목·요약·본문 등의 변경을 발견한 자료 수입니다.

## 데이터 구조

```text
docs/data/
├── config.json
├── manifest.json
└── 2026/
    └── 07/
        ├── index.json            # 월간 색인
        └── 29/
            ├── articles.json     # 전체 본문·분석 결과
            ├── index.json        # 날짜별 목록 색인
            └── revisions/        # 수정 전 버전
```

신규 Gemini 판정 예시:

```json
{
  "ip_relevance": {
    "level": "important",
    "label": "중요",
    "reason": "판정 근거",
    "method": "gemini-api",
    "model": "google/gemini-3.1-flash-lite",
    "prompt_version": "ip-office-relevance-v1.0"
  }
}
```

기존 정상 판정은 다음과 같이 남아 있을 수 있습니다.

```json
{
  "method": "github-models",
  "model": "openai/gpt-4.1-mini"
}
```

API 키가 없거나 호출이 실패한 모델 검토 대상은 다음처럼 표시됩니다.

```json
{
  "method": "rules-fallback"
}
```

# 설치 및 운영 설정

## 1. GitHub Actions 쓰기 권한

```text
Settings
→ Actions
→ General
→ Workflow permissions
→ Read and write permissions
```

수집된 `docs/data`를 워크플로가 `main` 브랜치에 다시 저장하기 위해 필요합니다.

## 2. GitHub Pages

```text
Settings
→ Pages
→ Build and deployment
→ Source: GitHub Actions
```

## 3. Gemini API 설정

Google AI Studio에서 Gemini API 키를 발급한 뒤 다음 Repository secret을 등록합니다.

```text
GEMINI_API_KEY
```

경로:

```text
Settings
→ Secrets and variables
→ Actions
→ Secrets
→ New repository secret
```

선택적으로 다음 Repository variable을 등록할 수 있습니다.

```text
GEMINI_MODEL=gemini-3.1-flash-lite
```

기본 호출 주소는 다음 OpenAI 호환 엔드포인트입니다.

```text
https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
```

특수한 환경에서만 다음 변수로 주소를 덮어씁니다.

```text
GEMINI_API_ENDPOINT
```

`GEMINI_API_KEY`가 없어도 보도자료 수집과 규칙 판정은 계속되지만, AI 검토가 필요한 자료는 `rules-fallback`으로 저장됩니다.

AI 호출 실패를 성공으로 오인하지 않으려면 수동 실행 시 다음을 사용합니다.

```text
require_ai=true
```

이 경우 키가 없거나 AI 호출이 실패하면 워크플로가 실패로 종료됩니다.

### 무료 티어 사용 시 주의

Gemini 무료 티어에서는 입력·출력 토큰을 무료로 사용할 수 있지만, 전송한 콘텐츠가 Google 제품 개선에 사용될 수 있습니다. 이 프로젝트는 공개 보도자료만 전송하도록 유지하고, 내부 문서·개인정보·비공개 판단자료는 프롬프트에 포함하지 않습니다.

## 4. Telegram 설정

다음 Repository secrets를 등록합니다.

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

선택 Repository variables:

```text
TELEGRAM_KEYWORDS=AI,정보화 사업,시스템,AX
DASHBOARD_URL=https://사용자명.github.io/저장소명/
TELEGRAM_MAX_CRITICAL=20
TELEGRAM_MAX_IMPORTANT=20
TELEGRAM_MAX_NORMAL=5
TELEGRAM_MAX_UNCLASSIFIED=3
TELEGRAM_MAX_ARTICLES=30
```

Telegram 시험 발송:

```text
저장소 상단 Actions
→ 보도자료 수집·AI 연관도 분석 및 대시보드 배포
→ Run workflow
→ send_telegram 체크
```

## 5. 첫 Gemini 시험

먼저 하루 범위로 시험합니다.

```text
start_date: 2026-07-30
end_date:   2026-07-30
require_ai: true
force_ai_reclassify: false
```

정상 실행 시 Actions 요약에서 다음 항목을 확인합니다.

- `gemini-api`: 실제 Gemini 판정 건수
- `github-models`: 과거 정상 AI 판정 캐시 건수
- `rules`: 명백한 자료의 규칙 판정 건수
- `rules-fallback`: Gemini 호출 실패 또는 키 미등록 건수

# 자동 실행 일정

한국시간 기준 다음 시각에 GitHub Actions가 직접 실행됩니다.

| KST | 대시보드 | Telegram |
|---|---|---|
| 08:03 | 수집·AI 분석·배포 | 발송 |
| 11:03 | 수집·AI 분석·배포 | 발송 안 함 |
| 16:03 | 수집·AI 분석·배포 | 발송 |
| 19:03 | 수집·AI 분석·배포 | 발송 안 함 |

워크플로 정의:

```yaml
schedule:
  - cron: "3 8 * * *"
    timezone: "Asia/Seoul"
  - cron: "3 11 * * *"
    timezone: "Asia/Seoul"
  - cron: "3 16 * * *"
    timezone: "Asia/Seoul"
  - cron: "3 19 * * *"
    timezone: "Asia/Seoul"
```

정기 실행은 한국시간 기준 오늘과 전날을 다시 확인합니다.

```text
lookback_days=2
```

따라서 일시적인 접속 실패나 늦게 게시된 보도자료는 다음 실행에서 다시 수집할 수 있습니다.

# 누락 기간 복구

긴 기간은 7~14일 단위로 나누어 수동 실행하는 것이 안전합니다.

예시:

```text
start_date: 2026-08-07
end_date:   2026-08-17
require_ai: true
force_ai_reclassify: false
```

기존 정상 AI 판정을 유지하려면 `force_ai_reclassify`를 체크하지 않습니다. 과거 `rules-fallback` 자료는 Gemini 키가 등록된 상태에서 재시도 유예시간이 지나면 자동으로 다시 판정됩니다.

# 장애 확인

## 수집은 성공했지만 Gemini 판정이 없는 경우

Actions의 `지식재산처 AI 연관도 분석` 로그에서 다음을 확인합니다.

1. `GEMINI_API_KEY` 등록 여부
2. `GEMINI_MODEL` 값
3. Google AI Studio의 활성 프로젝트와 사용 한도
4. GitHub-hosted runner의 Gemini API 접속 가능 여부
5. 결과의 `method`가 `gemini-api`인지 `rules-fallback`인지

수동 검증에서는 `require_ai=true`를 사용해야 AI 장애가 워크플로 성공으로 숨지 않습니다.

## 예약 실행이 누락되는 경우

다음 순서로 확인합니다.

1. `.github/workflows/collect-and-deploy.yml`에 `schedule:`이 있는지 확인
2. Actions에서 워크플로가 비활성화되지 않았는지 확인
3. `schedule_guard`가 지연 실행을 차단했는지 확인
4. 최근 수동 실행이 같은 concurrency 그룹의 정기 실행을 취소했는지 확인
5. `manifest.json`의 `last_date`와 실제 날짜 폴더를 비교

## 정책브리핑 연결 오류

수집기는 다음 설정을 사용합니다.

- 연결 제한 15초
- 읽기 제한 30초
- 연결 재시도 2회
- 지수 백오프
- `www.korea.kr` 실패 시 `m.korea.kr` 대체 접속
- 정기 실행 시 최근 2일 재확인

일부 날짜만 실패하면 다음 예약 또는 수동 실행에서 다시 확인합니다.

# 개발 및 검증

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
node --check docs/assets/app.js
python -m py_compile collector/*.py
```

# 주요 파일

| 파일 | 역할 |
|---|---|
| `.github/workflows/collect-and-deploy.yml` | 예약·수집·AI 분석·배포·Telegram 자동화 |
| `collector/collect.py` | 정책브리핑 수집 |
| `collector/classify_relevance.py` | 2026-07-29 기준 공통 판정 규칙·프롬프트·저장 처리 |
| `collector/classify_relevance_gemini.py` | Gemini API 호출·캐시 호환·공급자별 기록 처리 |
| `collector/relevance_policy.json` | 연관도 판단 기준 |
| `collector/build_indexes.py` | 날짜·월·전체 색인 생성 |
| `collector/send_telegram.py` | Telegram 브리핑 생성·발송 |
| `tests/test_gemini_relevance.py` | Gemini 요청·응답·캐시 호환 단위 테스트 |
| `docs/assets/app.js` | 대시보드 화면 동작 |
| `docs/assets/style.css` | 화면 디자인 |
| `docs/data/config.json` | 공용 기본 키워드와 출처 설정 |

# 저작권 처리

- 목록에는 제목·요약·원문 링크를 표시합니다.
- 본문에서는 이미지·영상·iframe·script 등 비텍스트 요소를 제거합니다.
- 정책브리핑 원문 링크와 출처를 유지합니다.
- 개별 자료의 공공누리 표시 및 이용조건은 별도로 확인해야 합니다.
- 저장소의 MIT 라이선스는 프로그램 코드에만 적용되며 수집 콘텐츠에는 적용되지 않습니다.
