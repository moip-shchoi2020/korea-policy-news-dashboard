# 정부 보도자료 AI·정보화 동향 대시보드

대한민국 정책브리핑의 보도자료 목록·상세페이지를 정기 수집하고, 지식재산처와의 연관도를 4단계로 분석해 GitHub Pages와 Telegram으로 제공하는 프로젝트입니다.

기본 검색 키워드:

- `AI`
- `정보화 사업`
- `시스템`
- `AX`

## 주요 기능

- 정책브리핑 보도자료 HTML 수집
- `년/월/일` 폴더별 제목·요약·본문·원문 링크 저장
- 수정된 보도자료 이전 버전 보관
- 지식재산처 연관도 분석
  - 매우 중요
  - 중요
  - 보통
  - 관계없음
- 달력형 집계와 중요도별 색상 표시
- 키워드 편집 및 브라우저 즉시 재집계
- GitHub Pages 자동 배포
- 08시·16시 Telegram 브리핑
- GitHub 예약 지연에 대비한 슬롯 재시도 및 완료 상태 관리

## 화면 집계 기준

달력과 오른쪽 목록은 현재 입력된 키워드와 일치하는 보도자료를 표시합니다. 여러 키워드는 OR 조건입니다. 키워드를 모두 지우면 해당 월의 전체 보도자료를 표시합니다.

영문 키워드 `AI`, `AX`는 다른 영단어 내부 철자와 잘못 일치하지 않도록 영문·숫자 경계를 적용합니다.

수정 건수는 최초 수집 이후 제목·요약·본문 등의 변경을 발견한 자료 수입니다.

## 데이터 구조

```text
docs/data/
├── config.json
├── manifest.json
├── schedule_state.json          # 예약 슬롯 완료 상태
└── 2026/
    └── 07/
        ├── index.json            # 월간 색인
        └── 24/
            ├── articles.json     # 전체 본문·분석 결과
            ├── index.json        # 날짜별 목록 색인
            └── revisions/        # 수정 전 버전
```

보도자료에는 다음과 같은 정보가 저장됩니다.

```json
{
  "id": "기사 ID",
  "title": "제목",
  "summary": "요약",
  "ministry": "부처명",
  "publish_date": "2026-07-24",
  "original_url": "정책브리핑 원문",
  "content_html": "이미지와 위험 요소를 제거한 본문 HTML",
  "content_text": "검색용 본문",
  "is_modified": false,
  "ip_relevance": {
    "level": "important",
    "label": "중요",
    "reason": "판정 근거",
    "method": "github-models"
  }
}
```

# 설치

## 1. GitHub 저장소 만들기

1. GitHub에서 새 저장소를 만듭니다.
2. GitHub Pages를 무료로 단순하게 사용하려면 Public 저장소가 편리합니다.
3. 이 프로젝트의 파일을 저장소 루트에 업로드합니다.
4. 다음 구조가 있는지 확인합니다.

```text
.github/workflows/collect-and-deploy.yml
collector/
docs/
tests/
requirements.txt
```

## 2. Actions 쓰기 권한

다음 메뉴에서 저장소 쓰기 권한을 설정합니다.

```text
Settings
→ Actions
→ General
→ Workflow permissions
→ Read and write permissions
```

## 3. GitHub Pages

```text
Settings
→ Pages
→ Build and deployment
→ Source: GitHub Actions
```

## 4. Telegram 설정

Telegram에서 BotFather를 통해 Bot을 만든 뒤 다음 Repository secrets를 등록합니다.

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

경로:

```text
Settings
→ Secrets and variables
→ Actions
→ Secrets
```

선택적으로 다음 Repository variables를 등록할 수 있습니다.

```text
TELEGRAM_KEYWORDS=AI,정보화 사업,시스템,AX
DASHBOARD_URL=https://사용자명.github.io/저장소명/
TELEGRAM_MAX_CRITICAL=20
TELEGRAM_MAX_IMPORTANT=20
TELEGRAM_MAX_NORMAL=5
TELEGRAM_MAX_UNCLASSIFIED=3
TELEGRAM_MAX_ARTICLES=30
GITHUB_MODELS_MODEL=openai/gpt-4.1-mini
```

Telegram 시험 발송:

```text
저장소 상단 Actions
→ 보도자료 수집·AI 연관도 분석 및 대시보드 배포
→ Run workflow
→ send_telegram 체크
```

예약 발송에서는 Token 또는 Chat ID가 없으면 작업이 오류로 종료되므로, 설정 누락을 성공으로 오인하지 않습니다.

## 5. 첫 수집

```text
저장소 상단 Actions
→ 보도자료 수집·AI 연관도 분석 및 대시보드 배포
→ Run workflow
```

처음에는 1~3일을 지정해 시험하는 것이 좋습니다.

```text
start_date: 2026-07-24
end_date:   2026-07-24
```

# 자동 실행 일정

목표 슬롯은 한국시간 기준 다음과 같습니다.

| KST | 대시보드 | Telegram |
|---|---|---|
| 08:03 | 수집·AI 분석·배포 | 발송 |
| 11:03 | 수집·AI 분석·배포 | 발송 안 함 |
| 16:03 | 수집·AI 분석·배포 | 발송 |
| 19:03 | 수집·AI 분석·배포 | 발송 안 함 |

GitHub 예약 이벤트는 지연되거나 누락될 수 있으므로 한 번의 cron에만 의존하지 않습니다.

워크플로는 UTC 기준 다음 예약으로 재시도 이벤트를 발생시킵니다.

```yaml
schedule:
  - cron: "3,23,43 0,2,3,7,8,10,11,23 * * *"
```

이 시각은 KST로 다음과 같습니다.

```text
08:03 / 08:23 / 08:43
09:03 / 09:23 / 09:43
11:03 / 11:23 / 11:43
12:03 / 12:23 / 12:43
16:03 / 16:23 / 16:43
17:03 / 17:23 / 17:43
19:03 / 19:23 / 19:43
20:03 / 20:23 / 20:43
```

`collector/schedule_control.py`가 실제 한국시간과 `docs/data/schedule_state.json`을 확인하여 다음과 같이 처리합니다.

- 해당 슬롯이 아직 성공하지 않았으면 실행
- 이미 성공한 슬롯이면 즉시 건너뜀
- 실패한 슬롯은 같은 재시도 창에서 다시 시도
- 21시 이후에는 새 자동 작업을 시작하지 않음
- 08시·16시 슬롯이 성공한 경우에만 Telegram 발송

이 구조는 GitHub UI의 표시 시간이나 `timezone` 해석에 의존하지 않고 Python의 `Asia/Seoul` 시간대로 최종 판단합니다.

## 예약 상태 초기화

특정 날짜의 슬롯을 강제로 다시 실행해야 하는 경우 `docs/data/schedule_state.json`에서 해당 슬롯 항목을 삭제하고 커밋합니다.

예:

```json
"2026-07-30T08:03": { ... }
```

일반적인 수동 재실행은 상태 파일을 수정하지 않고 `Run workflow`를 사용하면 됩니다.

# 장애 확인

## 예약 실행이 10여 초 만에 끝난 경우

예약 점검에서 다음 중 하나로 판정된 것입니다.

- 현재 시각이 실행 창이 아님
- 해당 슬롯이 이미 성공함
- 심야 시간이어서 자동 실행하지 않음

`Actions → schedule_guard → 한국시간 예약 슬롯 판정` 로그와 Step summary를 확인합니다.

## Telegram이 오지 않는 경우

다음 순서로 확인합니다.

1. 실행 대상이 08시 또는 16시 슬롯인지 확인
2. `build`와 `deploy`가 성공했는지 확인
3. `notify_telegram` 작업이 생성됐는지 확인
4. `Telegram 설정 사전 점검`에서 Secret 누락이 없는지 확인
5. `텔레그램 브리핑 발송` 로그의 HTTP 오류 확인

19시 슬롯은 원래 Telegram 발송 대상이 아닙니다.

## 정책브리핑 연결 오류

수집기는 다음 설정을 사용합니다.

- 연결 제한 15초
- 읽기 제한 30초
- 연결 재시도 2회
- 지수 백오프
- `www.korea.kr` 실패 시 `m.korea.kr` 대체 접속
- 정기 실행 시 최근 3일 재확인

일부 날짜만 실패하면 다음 예약 또는 수동 실행에서 다시 확인합니다.

# 개발 및 검증

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
node --check docs/assets/app.js
python -m py_compile collector/*.py
```

Python 캐시 파일은 저장소에 포함하지 않습니다. `.gitignore`와 워크플로의 `PYTHONDONTWRITEBYTECODE=1` 설정이 `__pycache__`로 인한 작업트리 변경을 방지합니다.

# 주요 파일

| 파일 | 역할 |
|---|---|
| `.github/workflows/collect-and-deploy.yml` | 예약·수집·AI 분석·배포·Telegram 자동화 |
| `collector/schedule_control.py` | KST 슬롯 판정과 완료 상태 관리 |
| `collector/collect.py` | 정책브리핑 수집 |
| `collector/classify_relevance.py` | 지식재산처 연관도 분석 |
| `collector/build_indexes.py` | 날짜·월·전체 색인 생성 |
| `collector/send_telegram.py` | Telegram 브리핑 생성·발송 |
| `collector/relevance_policy.json` | 연관도 판단 기준 |
| `docs/assets/app.js` | 대시보드 화면 동작 |
| `docs/assets/style.css` | 화면 디자인 |
| `docs/data/config.json` | 공용 기본 키워드와 출처 설정 |

# 저작권 처리

- 목록에는 제목·요약·원문 링크를 표시합니다.
- 본문에서는 이미지·영상·iframe·script 등 비텍스트 요소를 제거합니다.
- 정책브리핑 원문 링크와 출처를 유지합니다.
- 개별 자료의 공공누리 표시 및 이용조건은 별도로 확인해야 합니다.
- 저장소의 MIT 라이선스는 프로그램 코드에만 적용되며 수집 콘텐츠에는 적용되지 않습니다.
