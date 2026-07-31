# Cloudflare Workers 전환 적용 가이드

대상 저장소: `moip-shchoi2020/korea-policy-news-dashboard`

## 최종 구조

```text
Cloudflare Cron Trigger
  ├─ 08:03 KST → GitHub Actions → 대시보드 + Telegram
  ├─ 11:03 KST → GitHub Actions → 대시보드
  ├─ 16:03 KST → GitHub Actions → 대시보드 + Telegram
  └─ 19:03 KST → GitHub Actions → 대시보드
```

각 슬롯은 23분과 43분에도 같은 슬롯 ID로 다시 호출합니다. 첫 실행이 성공하면 GitHub의 `docs/data/external_schedule_state.json`에 완료 기록이 남고, 이후 재시도는 짧게 종료됩니다.

---

## 1. GitHub 파일 적용

### 1-1. 새 Python 파일 추가

저장소 상단에서:

```text
Code → Add file → Create new file
```

파일 이름:

```text
collector/external_dispatch_control.py
```

패치의 같은 파일 내용을 붙여넣고 커밋합니다.

### 1-2. 새 테스트 파일 추가

```text
Code → Add file → Create new file
```

파일 이름:

```text
tests/test_external_dispatch_control.py
```

패치의 같은 파일 내용을 붙여넣고 커밋합니다.

### 1-3. GitHub Actions 파일 교체

```text
Code
→ .github
→ workflows
→ collect-and-deploy.yml
→ Edit this file
```

패치의 `.github/workflows/collect-and-deploy.yml` 전체 내용으로 교체합니다.

커밋 메시지 예시:

```text
Replace GitHub cron with Cloudflare scheduler dispatch
```

이 파일에는 `schedule:`이 없습니다. 기존 GitHub cron은 이 교체로 완전히 제거됩니다.

### 1-4. 자동 배포 확인

파일 커밋 후 Actions에서 다음 실행이 발생합니다.

```text
코드 변경 배포(수집·AI 분석 없음)
```

`build`와 `deploy`가 모두 성공하는지 확인합니다.

---

## 2. GitHub fine-grained PAT 생성

GitHub 우측 상단 프로필 사진에서:

```text
Settings
→ Developer settings
→ Personal access tokens
→ Fine-grained tokens
→ Generate new token
```

권장 설정:

```text
Token name:
korea-policy-cloudflare-scheduler

Expiration:
90 days 또는 기관 보안정책에 맞는 기간

Resource owner:
moip-shchoi2020

Repository access:
Only select repositories
→ korea-policy-news-dashboard

Repository permissions:
Actions → Read and write
```

토큰을 생성하면 한 번만 표시되므로 안전한 곳에 복사합니다.

주의:

- 이 토큰은 GitHub 저장소 파일에 넣지 않습니다.
- Cloudflare Secret으로만 저장합니다.
- 만료일 전에 교체해야 합니다.

---

## 3. Cloudflare Worker 배포

### 3-1. 준비

- Cloudflare 계정 생성
- Windows 11 환경에 Node.js와 npm 설치
- 패치 ZIP의 `cloudflare-worker` 폴더를 로컬 PC에 압축 해제

PowerShell에서 폴더로 이동합니다.

```powershell
cd C:\경로\cloudflare-worker
```

### 3-2. 패키지 설치 및 테스트

```powershell
npm install
npm test
```

정상 결과:

```text
4 tests
4 pass
0 fail
```

### 3-3. Cloudflare 로그인

```powershell
npx wrangler login
```

브라우저가 열리면 Cloudflare 로그인을 승인합니다.

### 3-4. Worker 최초 배포

```powershell
npm run deploy
```

정상적으로 배포되면 다음과 유사한 주소가 표시됩니다.

```text
https://korea-policy-dashboard-scheduler.<계정>.workers.dev
```

### 3-5. GitHub Token을 Secret으로 등록

```powershell
npx wrangler secret put GITHUB_TOKEN
```

입력 요청이 나오면 2단계에서 만든 fine-grained PAT를 붙여넣습니다.

### 3-6. 수동 시험용 비밀키 등록

임의의 긴 문자열을 준비합니다. 예:

```text
kpd-2026-<충분히 긴 임의 문자열>
```

등록:

```powershell
npx wrangler secret put MANUAL_TRIGGER_KEY
```

이 값은 Worker 웹 화면에서 시험 실행할 때 사용합니다.

---

## 4. 즉시 시험 실행

Worker 주소를 브라우저로 엽니다.

```text
https://korea-policy-dashboard-scheduler.<계정>.workers.dev/
```

화면에서:

1. `수동 시험 키`에 `MANUAL_TRIGGER_KEY` 입력
2. `Telegram도 발송` 체크 유지
3. `GitHub Actions 시험 실행` 클릭

정상이라면 화면에 GitHub Actions 실행 URL이 표시됩니다.

GitHub에서 확인:

```text
저장소 상단 Actions
→ 보도자료 수집·AI 연관도 분석 및 대시보드 배포
→ Cloudflare 외부 예약 실행
```

작업 순서:

```text
dispatch_guard
→ build
→ deploy
→ notify_telegram
→ finalize_external_slot
```

Telegram 시험 메시지가 도착해야 합니다.

---

## 5. 예약 일정 확인

Cloudflare Cron은 UTC 기준입니다. `wrangler.jsonc`에는 다음 한 줄이 들어 있습니다.

```text
3,23,43 23,2,7,10 * * *
```

한국시간 변환:

| UTC | KST | 의미 |
|---|---|---|
| 23:03·23·43 | 다음 날 08:03·23·43 | 08시 슬롯, Telegram |
| 02:03·23·43 | 11:03·23·43 | 11시 슬롯 |
| 07:03·23·43 | 16:03·23·43 | 16시 슬롯, Telegram |
| 10:03·23·43 | 19:03·23·43 | 19시 슬롯 |

Cloudflare Cron Trigger 변경은 전 세계에 반영되는 데 최대 약 15분이 걸릴 수 있습니다.

확인 위치:

```text
Cloudflare Dashboard
→ Workers & Pages
→ korea-policy-dashboard-scheduler
→ Settings
→ Trigger Events
```

---

## 6. 중복 실행 방지 원리

Cloudflare는 각 목표 시각마다 3회 호출합니다.

```text
08:03 → 08:23 → 08:43
11:03 → 11:23 → 11:43
16:03 → 16:23 → 16:43
19:03 → 19:23 → 19:43
```

세 호출은 같은 `external_slot`을 전달합니다.

예:

```text
2026-08-01T16:03+09:00
```

첫 실행이 성공하면 다음 파일에 완료 기록이 저장됩니다.

```text
docs/data/external_schedule_state.json
```

23분·43분 재시도는 이미 완료된 슬롯을 확인하고 수집·Telegram을 다시 수행하지 않습니다.

첫 실행이 실패하면 완료 기록이 없으므로 다음 재시도가 다시 실행합니다.

---

## 7. 기존 GitHub cron 정리 확인

최종 `.github/workflows/collect-and-deploy.yml`에는 다음 항목이 없어야 합니다.

```yaml
schedule:
  - cron: ...
```

다음 항목만 남아야 합니다.

```yaml
on:
  push:
  workflow_dispatch:
```

`collector/schedule_control.py`와 `docs/data/schedule_state.json`은 남아 있어도 실행되지 않습니다. 정리하려면 나중에 삭제해도 됩니다.

---

## 8. 장애 확인 방법

### Worker 자체 상태

```text
Worker URL/health
```

정상 예:

```json
{
  "ok": true,
  "tokenConfigured": true,
  "manualKeyConfigured": true
}
```

### GitHub Token 오류

Cloudflare 로그에 다음이 나타납니다.

```text
HTTP 401 또는 HTTP 403
```

원인:

- PAT 만료
- 잘못된 토큰
- Actions write 권한 미부여
- 다른 저장소만 선택

### Workflow 파일 오류

```text
HTTP 404
```

확인:

```text
GH_OWNER=moip-shchoi2020
GH_REPO=korea-policy-news-dashboard
GH_WORKFLOW=collect-and-deploy.yml
GH_REF=main
```

### Telegram 미발송

GitHub Actions에서 `notify_telegram` 단계가 생성됐는지 확인합니다.

- 08시·16시 슬롯: 생성되어야 함
- 11시·19시 슬롯: 생성되지 않는 것이 정상

---

## 9. 운영 전 최종 점검표

- [ ] GitHub YML에서 `schedule:` 제거
- [ ] `collector/external_dispatch_control.py` 추가
- [ ] `tests/test_external_dispatch_control.py` 추가
- [ ] GitHub 코드 변경 배포 성공
- [ ] fine-grained PAT에 해당 저장소만 선택
- [ ] PAT에 Actions Read and write 부여
- [ ] Cloudflare Worker 배포
- [ ] `GITHUB_TOKEN` Secret 등록
- [ ] `MANUAL_TRIGGER_KEY` Secret 등록
- [ ] Worker `/health`에서 두 Secret이 `true`
- [ ] 브라우저 수동 시험 성공
- [ ] Telegram 시험 발송 성공
- [ ] 다음 예약 시각에 `workflow_dispatch` 실행 확인
