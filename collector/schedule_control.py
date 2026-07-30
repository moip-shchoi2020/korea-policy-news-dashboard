from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
DEFAULT_STATE_PATH = Path("docs/data/schedule_state.json")
STATE_SCHEMA_VERSION = 1
STATE_RETENTION_DAYS = 45


@dataclass(frozen=True)
class ScheduleSlot:
    slot_id: str
    start: time
    end: time
    label: str
    telegram_required: bool
    telegram_title: str = ""


# GitHub 예약 이벤트는 지연되거나 누락될 수 있으므로 각 슬롯에 약 2시간의
# 재시도 창을 둔다. 21시 이후에는 자동 작업을 시작하지 않아 심야 실행을 막는다.
SLOTS: tuple[ScheduleSlot, ...] = (
    ScheduleSlot(
        slot_id="08:03",
        start=time(8, 3),
        end=time(10, 0),
        label="08:03 대시보드 갱신 + Telegram",
        telegram_required=True,
        telegram_title="08시 브리핑",
    ),
    ScheduleSlot(
        slot_id="11:03",
        start=time(11, 3),
        end=time(13, 0),
        label="11:03 대시보드 갱신",
        telegram_required=False,
    ),
    ScheduleSlot(
        slot_id="16:03",
        start=time(16, 3),
        end=time(18, 0),
        label="16:03 대시보드 갱신 + Telegram",
        telegram_required=True,
        telegram_title="16시 브리핑",
    ),
    ScheduleSlot(
        slot_id="19:03",
        start=time(19, 3),
        end=time(21, 0),
        label="19:03 대시보드 갱신",
        telegram_required=False,
    ),
)


@dataclass(frozen=True)
class ScheduleDecision:
    allowed: bool
    reason: str
    slot_key: str = ""
    slot_date: str = ""
    slot_label: str = ""
    telegram_required: bool = False
    telegram_title: str = ""


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "updated_at": None,
        "completed_slots": {},
    }


def load_state(path: Path | str = DEFAULT_STATE_PATH) -> dict[str, Any]:
    state_path = Path(path)
    try:
        with state_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty_state()

    if not isinstance(payload, dict):
        return _empty_state()
    completed = payload.get("completed_slots")
    if not isinstance(completed, dict):
        completed = {}
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "updated_at": payload.get("updated_at"),
        "completed_slots": completed,
    }


def write_state(path: Path | str, payload: dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=state_path.parent,
        prefix=f".{state_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(state_path)


def parse_now(value: str | None = None) -> datetime:
    if not value:
        return datetime.now(KST)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def _slot_key(day: date, slot: ScheduleSlot) -> str:
    return f"{day.isoformat()}T{slot.slot_id}"


def _slot_bounds(day: date, slot: ScheduleSlot) -> tuple[datetime, datetime]:
    return (
        datetime.combine(day, slot.start, tzinfo=KST),
        datetime.combine(day, slot.end, tzinfo=KST),
    )


def decide_schedule(
    now: datetime | None = None,
    state: dict[str, Any] | None = None,
) -> ScheduleDecision:
    current = (now or datetime.now(KST)).astimezone(KST)
    current_state = state or _empty_state()
    completed = current_state.get("completed_slots", {})
    if not isinstance(completed, dict):
        completed = {}

    for slot in SLOTS:
        start_at, end_at = _slot_bounds(current.date(), slot)
        if not (start_at <= current < end_at):
            continue

        key = _slot_key(current.date(), slot)
        if key in completed:
            completed_at = ""
            entry = completed.get(key)
            if isinstance(entry, dict):
                completed_at = str(entry.get("completed_at") or "")
            detail = f" ({completed_at})" if completed_at else ""
            return ScheduleDecision(
                allowed=False,
                reason=f"{slot.label} 슬롯은 이미 완료되었습니다{detail}.",
                slot_key=key,
                slot_date=current.date().isoformat(),
                slot_label=slot.label,
                telegram_required=slot.telegram_required,
                telegram_title=slot.telegram_title,
            )

        age_minutes = int((current - start_at).total_seconds() // 60)
        return ScheduleDecision(
            allowed=True,
            reason=f"{slot.label} 슬롯 실행 대상입니다. 예정 시각 대비 {age_minutes}분 경과했습니다.",
            slot_key=key,
            slot_date=current.date().isoformat(),
            slot_label=slot.label,
            telegram_required=slot.telegram_required,
            telegram_title=slot.telegram_title,
        )

    upcoming = next(
        (
            slot
            for slot in SLOTS
            if current < datetime.combine(current.date(), slot.start, tzinfo=KST)
        ),
        None,
    )
    if upcoming:
        reason = f"현재 한국시간은 예약 실행 창이 아닙니다. 다음 슬롯은 {upcoming.label}입니다."
    else:
        reason = "오늘의 마지막 예약 실행 창이 종료되었습니다. 심야 자동 실행은 하지 않습니다."
    return ScheduleDecision(allowed=False, reason=reason)


def _clean_old_entries(completed: dict[str, Any], now: datetime) -> dict[str, Any]:
    threshold = now.date() - timedelta(days=STATE_RETENTION_DAYS)
    cleaned: dict[str, Any] = {}
    for key, value in completed.items():
        try:
            key_date = date.fromisoformat(str(key)[:10])
        except ValueError:
            continue
        if key_date >= threshold:
            cleaned[str(key)] = value
    return cleaned


def mark_completed(
    slot_key: str,
    *,
    slot_label: str,
    telegram_required: bool,
    state_path: Path | str = DEFAULT_STATE_PATH,
    now: datetime | None = None,
    run_id: str = "",
    run_url: str = "",
) -> dict[str, Any]:
    if not slot_key:
        raise ValueError("slot_key가 비어 있습니다.")

    current = (now or datetime.now(KST)).astimezone(KST)
    state = load_state(state_path)
    completed = state.get("completed_slots", {})
    if not isinstance(completed, dict):
        completed = {}
    completed = _clean_old_entries(completed, current)
    completed[slot_key] = {
        "slot_label": slot_label,
        "telegram_required": bool(telegram_required),
        "completed_at": current.replace(microsecond=0).isoformat(),
        "run_id": str(run_id or "") or None,
        "run_url": str(run_url or "") or None,
    }
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "updated_at": current.replace(microsecond=0).isoformat(),
        "completed_slots": dict(sorted(completed.items())),
    }
    write_state(state_path, payload)
    return payload


def _write_github_output(path: str, decision: ScheduleDecision) -> None:
    if not path:
        return
    outputs = {
        "allowed": "true" if decision.allowed else "false",
        "reason": decision.reason,
        "slot_key": decision.slot_key,
        "slot_date": decision.slot_date,
        "slot_label": decision.slot_label,
        "telegram_required": "true" if decision.telegram_required else "false",
        "telegram_title": decision.telegram_title,
    }
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            safe_value = str(value).replace("\r", " ").replace("\n", " ")
            handle.write(f"{key}={safe_value}\n")


def _append_summary(path: str, decision: ScheduleDecision, now: datetime) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n### 한국시간 예약 슬롯 판정\n")
        handle.write(f"- 현재 KST: `{now.strftime('%Y-%m-%d %H:%M:%S %Z')}`\n")
        handle.write(f"- 실행 여부: `{'실행' if decision.allowed else '건너뜀'}`\n")
        if decision.slot_key:
            handle.write(f"- 슬롯: `{decision.slot_key}`\n")
        handle.write(f"- 사유: {decision.reason}\n")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KST 기준 대시보드 예약 슬롯을 판정·기록합니다.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    decide_parser = subparsers.add_parser("decide", help="현재 실행할 KST 슬롯을 판정")
    decide_parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    decide_parser.add_argument("--now", help="테스트용 ISO 시각")
    decide_parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    decide_parser.add_argument("--github-summary", default=os.getenv("GITHUB_STEP_SUMMARY", ""))

    mark_parser = subparsers.add_parser("mark", help="슬롯 완료 상태 기록")
    mark_parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    mark_parser.add_argument("--slot-key", required=True)
    mark_parser.add_argument("--slot-label", required=True)
    mark_parser.add_argument("--telegram-required", choices=("true", "false"), required=True)
    mark_parser.add_argument("--now", help="테스트용 ISO 시각")
    mark_parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    mark_parser.add_argument("--run-url", default="")

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "decide":
        current = parse_now(args.now)
        decision = decide_schedule(current, load_state(args.state_path))
        print(f"KST now: {current.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"allowed: {decision.allowed}")
        print(f"reason: {decision.reason}")
        if decision.slot_key:
            print(f"slot: {decision.slot_key} / {decision.slot_label}")
        _write_github_output(args.github_output, decision)
        _append_summary(args.github_summary, decision, current)
        return 0

    current = parse_now(args.now)
    run_url = args.run_url
    if not run_url:
        server = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        repository = os.getenv("GITHUB_REPOSITORY", "").strip()
        run_id = args.run_id or os.getenv("GITHUB_RUN_ID", "")
        if repository and run_id:
            run_url = f"{server}/{repository}/actions/runs/{run_id}"
    payload = mark_completed(
        args.slot_key,
        slot_label=args.slot_label,
        telegram_required=args.telegram_required == "true",
        state_path=args.state_path,
        now=current,
        run_id=args.run_id,
        run_url=run_url,
    )
    print(f"예약 슬롯 완료 기록: {args.slot_key}")
    print(f"상태 파일: {args.state_path}")
    print(f"완료 슬롯 수: {len(payload['completed_slots'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
