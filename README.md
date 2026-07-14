# 정부 보도자료 AI·정보화 동향 대시보드

대한민국 정책브리핑 OpenAPI에서 **보도자료(`GroupingCode=brief`)**를 정기 수집하고, GitHub Pages에 달력형 대시보드로 자동 배포하는 시작용 프로젝트입니다.

기본 키워드는 다음과 같습니다.

- `AI`
- `정보화 사업`
- `시스템`
- `AX`

대시보드에서 키워드를 수정한 뒤 **재집계**를 누르면 현재 월의 제목·요약·본문을 브라우저에서 다시 검색합니다. 키워드는 브라우저의 `localStorage`에 저장되므로 다음 방문에도 유지됩니다.

## 1. 구현된 요구사항

- `년/월/일` 폴더 구조로 본문과 메타데이터 저장
- 제목·요약 목록 제공
- 목록 선택 시 제목 → 요약·실제 원문 링크 → 본문 순서로 상세 표시
- 기본 키워드 `AI`, `정보화 사업`, `시스템`, `AX`
- 키워드 편집·초기화·브라우저 내 즉시 재집계
- 메인 상단 월간 달력
- 오늘 날짜 하이라이트
- 날짜별 키워드 일치 건수 표시
- 날짜 선택 시 하단 목록 표시
- 수정본이 있을 때 `5건 (2건)` 형식으로 표시
- 이미지·영상·스크립트·임베드 요소 제거
- 원문과 정책브리핑 저작권 정책 링크 표시
- GitHub Actions를 이용한 정기 수집과 GitHub Pages 자동 배포

## 2. 화면에서 건수를 계산하는 기준

`5건 (2건)`은 다음 의미입니다.

- `5건`: 선택한 키워드가 제목·요약·본문 중 하나 이상에 포함된 고유 보도자료 수
- `(2건)`: 위 5건 중 API의 `ContentsStatus=U` 또는 `ModifyId>1`인 수정본 수

달력 날짜는 **최초 승인일(`ApproveDate`)** 기준입니다. 수정본도 최초 게시일 칸에 유지됩니다.

영문 키워드 `AI`, `AX`는 다른 영단어 내부의 철자와 잘못 일치하지 않도록 영문·숫자 경계를 적용합니다. 한글 문구는 부분 문자열 방식으로 일치시킵니다. 여러 키워드는 OR 조건입니다. 키워드를 모두 지우면 해당 월의 전체 보도자료가 표시됩니다.

## 3. 데이터 저장 구조

```text
docs/data/
├── config.json
├── manifest.json
└── 2026/
    └── 07/
        ├── index.json                # 2026년 7월 재집계용 월 색인
        └── 14/
            ├── index.json            # 2026-07-14 목록용 색인
            ├── articles.json         # 제목·요약·본문 등 전체 데이터
            └── revisions/            # 수정 전 버전을 실제로 발견한 경우 보관
                └── 156000001/
                    └── modify-1_....json
```

`articles.json`에는 다음 항목이 저장됩니다.

```json
{
  "id": "기사 ID",
  "title": "제목",
  "summary": "부제목 또는 본문 앞부분",
  "ministry": "부처명",
  "approved_at": "최초 승인 시각",
  "modified_at": "최종 변경 시각",
  "contents_status": "I 또는 U",
  "modify_id": 2,
  "is_modified": true,
  "original_url": "정책브리핑 원문",
  "content_html": "이미지와 위험 요소를 제거한 본문 HTML",
  "content_text": "검색용 본문 텍스트"
}
```

월 색인에는 재집계에 필요한 `search_text`가 들어갑니다. 상세 본문은 날짜 폴더의 `articles.json`을 선택 시점에 불러옵니다.

---

# 처음부터 설치하기

아래 절차는 Git과 명령어를 사용하지 않고 **GitHub 웹 화면만으로 설치하는 방식**입니다.

## 4. GitHub 계정 만들기

1. `https://github.com/`에 접속합니다.
2. **Sign up**을 선택합니다.
3. 이메일, 비밀번호, 사용자 이름을 입력합니다.
4. 이메일 인증을 완료합니다.
5. 가능하면 계정의 2단계 인증도 설정합니다.

GitHub에서 저장소를 만들려면 이메일 인증이 완료되어 있어야 합니다.

## 5. 공공데이터포털 API 키 받기

1. `https://www.data.go.kr/`에서 회원가입·로그인합니다.
2. 다음 데이터 페이지를 엽니다.
   - `https://www.data.go.kr/data/15095335/openapi.do`
3. **활용신청**을 선택합니다.
4. 사용 목적에는 `정책브리핑 보도자료 AI·정보화 동향 모니터링`처럼 입력합니다.
5. 승인이 완료되면 마이페이지에서 인증키를 확인합니다.
6. 가능하면 **일반 인증키(Decoding)** 값을 복사합니다.

인증키는 공개 파일에 직접 적지 않습니다. 다음 단계에서 GitHub Secret으로 저장합니다.

## 6. 새 GitHub 저장소 만들기

1. GitHub 오른쪽 위의 `+` 메뉴를 선택합니다.
2. **New repository**를 선택합니다.
3. Repository name에 다음과 같이 입력합니다.

```text
korea-policy-dashboard
```

4. Public을 선택합니다. GitHub Free에서 Pages를 가장 단순하게 사용하기 위한 설정입니다.
5. `Add a README`, `.gitignore`, `license`는 선택하지 않습니다. 이 프로젝트에 이미 포함되어 있습니다.
6. **Create repository**를 선택합니다.

## 7. 프로젝트 파일 업로드하기

1. 이 시작용 패키지 ZIP을 컴퓨터에 압축 해제합니다.
2. 새 저장소의 초기 화면에서 **uploading an existing file**을 선택합니다.
   - 저장소에 파일이 이미 있다면 `Add file` → `Upload files`를 선택합니다.
3. 압축을 푼 폴더 **자체가 아니라 폴더 안의 모든 파일과 폴더**를 업로드 영역으로 끌어 놓습니다.
   - macOS에서 `.github` 폴더가 보이지 않으면 Finder에서 `Command + Shift + .`을 눌러 숨김 파일을 표시합니다.
   - 업로드 후 `.github/workflows/collect-and-deploy.yml`이 반드시 존재하는지 확인합니다.
4. 하단 Commit changes 제목은 다음처럼 입력합니다.

```text
Initial dashboard setup
```

5. **Commit changes**를 선택합니다.

업로드 후 저장소 최상단에 `.github`, `collector`, `docs`, `tests`, `README.md`, `requirements.txt`가 보여야 합니다.

파일 업로드 직후에는 Pages와 Secret 설정이 끝나기 전에 첫 워크플로가 실행되어 빨간 실패 표시가 나타날 수 있습니다. 아래 8~10단계를 완료한 뒤 Actions에서 다시 실행하면 됩니다.

## 8. API 키를 GitHub Secret으로 등록하기

1. 저장소 상단의 **Settings**를 선택합니다.
2. 왼쪽에서 **Secrets and variables** → **Actions**를 선택합니다.
3. **New repository secret**을 선택합니다.
4. Name에 정확히 다음을 입력합니다.

```text
DATA_GO_KR_SERVICE_KEY
```

5. Secret에 공공데이터포털 인증키를 붙여 넣습니다.
6. **Add secret**을 선택합니다.

인증키는 Actions 실행 중 환경변수로만 전달되며, 소스코드와 공개 대시보드에는 포함되지 않습니다.

## 9. GitHub Actions 쓰기 권한 확인하기

자동 수집 결과를 저장소에 커밋하려면 쓰기 권한이 필요합니다.

1. 저장소 **Settings**를 선택합니다.
2. **Actions** → **General**을 선택합니다.
3. 아래쪽 `Workflow permissions`에서 **Read and write permissions**를 선택합니다.
4. **Save**를 선택합니다.

조직 정책으로 이 선택이 잠겨 있으면 조직 관리자 권한이 필요합니다. 개인 저장소에서는 보통 직접 설정할 수 있습니다.

## 10. GitHub Pages 켜기

1. 저장소 **Settings**를 선택합니다.
2. 왼쪽에서 **Pages**를 선택합니다.
3. `Build and deployment`의 Source를 **GitHub Actions**로 설정합니다.

워크플로 파일에는 공식 Pages 배포 액션이 이미 들어 있습니다.

## 11. 첫 수집 실행하기

처음에는 최근 14일만 시험 수집하는 것이 안전합니다.

1. 저장소 상단의 **Actions**를 선택합니다.
2. 왼쪽에서 **보도자료 수집 및 대시보드 배포**를 선택합니다.
3. **Run workflow**를 선택합니다.
4. 시작일과 종료일은 비워 둡니다.
5. `lookback_days`는 `14`로 둡니다.
6. 초록색 **Run workflow**를 선택합니다.

실행 항목을 선택하면 단계별 로그를 볼 수 있습니다. 모든 단계가 초록색이면 완료입니다.

첫 실행 후 다음 파일들이 자동으로 생깁니다.

```text
docs/data/YYYY/MM/DD/articles.json
docs/data/YYYY/MM/DD/index.json
docs/data/YYYY/MM/index.json
docs/data/manifest.json
```

## 12. 대시보드 주소 확인하기

1. 저장소 **Settings** → **Pages**로 이동합니다.
2. 상단에 표시되는 사이트 주소를 엽니다.

일반적으로 주소 형식은 다음과 같습니다.

```text
https://사용자이름.github.io/korea-policy-dashboard/
```

## 13. 과거 데이터 추가 수집하기

Actions의 **Run workflow**에서 시작일과 종료일을 입력합니다.

예시:

```text
start_date: 2026-01-01
end_date:   2026-06-30
```

수집기는 API를 하루 단위로 호출합니다. 개발계정 기본 한도는 일 1,000회이므로 한 번의 실행 범위는 최대 900일로 제한했습니다. 기간이 더 길면 여러 번 나누어 실행합니다.

권장 순서:

1. 최근 14일 시험
2. 최근 3개월
3. 최근 1년
4. 필요 시 이전 연도를 연도별로 추가

## 14. 자동 실행 시간

기본 설정은 한국시간 기준 매일 다음 시각에 실행합니다.

```text
00:23
06:23
12:23
18:23
```

각 실행은 최근 14일을 다시 확인합니다. 이 방식으로 최근 게시물의 수정 여부도 갱신합니다. 실행 시각을 바꾸려면 다음 파일을 수정합니다.

```text
.github/workflows/collect-and-deploy.yml
```

해당 부분:

```yaml
schedule:
  - cron: "23 0,6,12,18 * * *"
    timezone: "Asia/Seoul"
```

## 15. 공용 기본 키워드 변경하기

대시보드 화면에서 바꾼 키워드는 현재 브라우저에만 저장됩니다. 모든 이용자에게 보이는 공용 기본값을 변경하려면 GitHub에서 다음 파일을 엽니다.

```text
docs/data/config.json
```

오른쪽 위 연필 아이콘을 눌러 다음 배열을 수정합니다.

```json
"default_keywords": [
  "AI",
  "인공지능",
  "정보화 사업",
  "시스템",
  "AX",
  "디지털 전환"
]
```

수정 후 **Commit changes**를 선택하면 Pages가 다시 배포됩니다.

## 16. 저작권 처리 방식과 주의점

이 프로젝트는 다음 방식으로 처리합니다.

- 목록: 제목과 요약만 표시
- 상세: 제목 → 요약 → 원문 링크 → 본문 순서
- 모든 상세 화면에 `대한민국 정책브리핑 및 해당 부처` 출처 표시
- 정책브리핑 원문과 저작권 정책으로 연결
- 이미지·사진·영상·iframe·첨부파일은 저장·재게시하지 않음
- 본문 HTML에서 스크립트와 위험 요소 제거

다만 화면 구성과 출처 표시는 저작권 적법성을 자동으로 보장하는 장치가 아닙니다. 정책브리핑 정책에 따르면 공공누리 제1유형 표시가 있는 텍스트는 출처 표시 조건으로 이용할 수 있지만, 공공누리가 없는 자료와 사진·이미지 등은 별도 확인이 필요할 수 있습니다. 운영 전 각 자료의 이용조건과 기관 내부 기준을 확인하십시오.

수집된 콘텐츠에는 이 저장소의 MIT 라이선스가 적용되지 않습니다. MIT 라이선스는 프로그램 코드에만 적용됩니다.

## 17. 수정본 보관 방식

같은 기사 ID의 본문 또는 수정 정보가 달라진 것을 수집기가 확인하면 기존 버전을 다음 위치에 보관한 뒤 최신 버전으로 갱신합니다.

```text
docs/data/YYYY/MM/DD/revisions/기사ID/
```

수정 이력 저장을 끄려면 Actions 환경변수 `SAVE_REVISION_HISTORY=false`를 추가할 수 있습니다. 기본값은 `true`입니다.

## 18. 장애 확인

### `DATA_GO_KR_SERVICE_KEY가 비어 있습니다`

Secret 이름이 정확히 `DATA_GO_KR_SERVICE_KEY`인지 확인합니다. Actions에서 Secret 값 자체는 보이지 않는 것이 정상입니다.

### `API 오류` 또는 `HTTP 4xx`

- 활용신청 승인이 완료됐는지 확인합니다.
- 인증키에 앞뒤 공백이 없는지 확인합니다.
- 공공데이터포털 장애 공지를 확인합니다.
- Encoding 키를 사용해도 수집기가 한 번 디코딩하지만, 가능하면 Decoding 키를 사용합니다.

### 자동 커밋 단계에서 권한 오류

Settings → Actions → General → Workflow permissions를 `Read and write permissions`로 바꿉니다.

### Pages는 열리지만 데이터가 0건

- Actions의 첫 수집이 성공했는지 확인합니다.
- `docs/data/YYYY/MM/index.json` 파일이 생성됐는지 확인합니다.
- 현재 달이 아닌 과거 기간만 수집했다면 달력의 이전 달 버튼을 사용합니다.
- 키워드를 모두 지우고 재집계해 전체 자료가 있는지 확인합니다.

### 브라우저에서 HTML 파일을 직접 열었더니 데이터가 안 보임

`file://` 방식은 JSON 요청이 차단될 수 있습니다. GitHub Pages 주소로 열거나 아래의 로컬 서버를 사용합니다.

## 19. 선택 사항: 컴퓨터에서 미리 실행하기

Python이 설치돼 있다면 다음 명령을 프로젝트 최상단에서 실행합니다.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATA_GO_KR_SERVICE_KEY="발급받은_인증키"
python -m collector.collect --lookback-days 14
python -m http.server 8000 --directory docs
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
export DATA_GO_KR_SERVICE_KEY="발급받은_인증키"
python -m collector.collect --lookback-days 14
python -m http.server 8000 --directory docs
```

브라우저에서 다음 주소를 엽니다.

```text
http://localhost:8000
```

테스트만 실행하려면:

```bash
python -m unittest discover -s tests -v
```

## 20. 주요 파일

| 파일 | 역할 |
|---|---|
| `collector/collect.py` | OpenAPI 일자별 호출, 보도자료 필터, 본문 정제, 날짜 폴더 저장 |
| `collector/build_indexes.py` | 일·월 색인과 전체 manifest 생성 |
| `docs/index.html` | 대시보드 구조 |
| `docs/assets/app.js` | 달력, 키워드 재집계, 목록·상세 표시 |
| `docs/assets/style.css` | 반응형 화면 디자인 |
| `docs/data/config.json` | 공용 기본 키워드와 출처 설정 |
| `.github/workflows/collect-and-deploy.yml` | 정기 수집, 자동 커밋, Pages 배포 |

## 21. 데이터 증가 시 운영 원칙

전체 보도자료를 장기간 본문까지 저장하면 저장소 크기와 Pages 배포 용량이 계속 증가합니다. 초기 운영은 최근 1년부터 시작하고, 장기간 축적 후에는 다음 중 하나를 검토하는 것이 좋습니다.

- 오래된 연도 데이터를 별도 아카이브 저장소로 분리
- 본문은 외부 객체 저장소에 두고 GitHub에는 색인만 유지
- 최근 2~3년만 Pages에서 제공하고 이전 자료는 원문 링크만 유지

현재 구조는 연·월 단위로 분리되어 있어 이후 이전·분리가 가능합니다.
