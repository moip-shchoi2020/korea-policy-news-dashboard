from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
DEFAULT_STATE_PATH = Path("docs/data/external_schedule_state.json")
STATE_SCHEMA_VERSION = 1
STATE_RETENTION_DAYS = 45


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


def _entry_date(slot_key: str, entry: Any) -> date | None:
    candidates = [str(slot_key)[:10]]
    if isinstance(entry, dict):
        completed_at = str(entry.get("completed_at") or "")[:10]
        if completed_at:
            candidates.append(completed_at)
    for candidate in candidates:
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _clean_old_entries(completed: dict[str, Any], now: datetime) -> dict[str, Any]:
    threshold = now.date() - timedelta(days=STATE_RETENTION_DAYS)
    cleaned: dict[str, Any] = {}
    for key, value in completed.items():
        item_date = _entry_date(str(key), value)
        if item_date is None or item_date >= threshold:
            cleaned[str(key)] = value
    return cleaned


def decide(slot_key: str, state: dict[str, Any]) -> tuple[bool, str]:
    normalized = str(slot_key or "").strip()
    if not normalized:
        return True, "외부 슬롯 식별자가 없어 일반 수동 실행으로 처리합니다."
    completed = state.get("completed_slots", {})
    if isinstance(completed, dict) and normalized in completed:
        entry = completed.get(normalized)
        completed_at = entry.get("completed_at") if isinstance(entry, dict) else None
        detail = f" ({completed_at})" if completed_at else ""
        return False, f"외부 예약 슬롯 {normalized}은 이미 완료되었습니다{detail}."
    return True, f"외부 예약 슬롯 {normalized}은 실행 대상입니다."


def mark_completed(
    slot_key: str,
    *,
    slot_label: str,
    source: str,
    state_path: Path | str = DEFAULT_STATE_PATH,
    now: datetime | None = None,
    run_id: str = "",
    run_url: str = "",
) -> dict[str, Any]:
    normalized = str(slot_key or "").strip()
    if not normalized:
        raise ValueError("slot_key가 비어 있습니다.")

    current = (now or datetime.now(KST)).astimezone(KST)
    state = load_state(state_path)
    completed = state.get("completed_slots", {})
    if not isinstance(completed, dict):
        completed = {}
    completed = _clean_old_entries(completed, current)
    completed[normalized] = {
        "slot_label": str(slot_label or normalized),
        "source": str(source or "external"),
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


def _write_output(path: str, *, allowed: bool, reason: str) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"allowed={'true' if allowed else 'false'}\n")
        handle.write(f"reason={reason.replace(chr(10), ' ').replace(chr(13), ' ')}\n")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="외부 스케줄러 슬롯의 중복 실행을 제어합니다.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    decide_parser = subparsers.add_parser("decide")
    decide_parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    decide_parser.add_argument("--slot-key", default="")
    decide_parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))

    mark_parser = subparsers.add_parser("mark")
    mark_parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    mark_parser.add_argument("--slot-key", required=True)
    mark_parser.add_argument("--slot-label", default="")
    mark_parser.add_argument("--source", default="external")
    mark_parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    mark_parser.add_argument("--run-url", default="")

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "decide":
        allowed, reason = decide(args.slot_key, load_state(args.state_path))
        print(f"allowed: {allowed}")
        print(f"reason: {reason}")
        _write_output(args.github_output, allowed=allowed, reason=reason)
        return 0

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
        source=args.source,
        state_path=args.state_path,
        run_id=args.run_id,
        run_url=run_url,
    )
    print(f"외부 예약 슬롯 완료 기록: {args.slot_key}")
    print(f"완료 슬롯 수: {len(payload['completed_slots'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
