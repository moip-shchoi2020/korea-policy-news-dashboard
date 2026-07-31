# 변경 내용

## GitHub Actions

- GitHub 자체 `schedule`/cron 제거
- Cloudflare가 호출할 `workflow_dispatch` 입력 추가
- `external_slot` 기준 중복 실행 방지
- 08시·16시 호출에서만 Telegram 발송
- 성공 슬롯을 `docs/data/external_schedule_state.json`에 기록
- 기존 수동 실행과 코드 변경 Pages 배포 유지

## Cloudflare Worker

- KST 08:03·11:03·16:03·19:03 슬롯 계산
- 슬롯별 20분 간격 재시도
- GitHub REST API `workflow_dispatch` 호출
- GitHub API 실패 시 최대 3회 재시도
- `/health` 상태 확인
- 브라우저 기반 수동 시험 화면
- GitHub Token과 수동 시험키를 Cloudflare Secret으로 사용
