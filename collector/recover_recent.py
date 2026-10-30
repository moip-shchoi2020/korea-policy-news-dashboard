from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from collector.build_indexes import build_indexes
from collector.collect import (
    DEFAULT_LIST_URL,
    create_session,
    fetch_detail_article,
    parse_list_page,
    request_page,
    upsert_article,
)
from collector.common import now_iso, write_json

SEOUL = ZoneInfo("Asia/Seoul")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="정책브리핑 날짜 검색이 오작동할 때 일반 목록을 역추적해 최근 날짜 자료를 복구합니다."
    )
    parser.add_argument("--start-date", help="복구 시작일 YYYY-MM-DD")
    parser.add_argument("--end-date", help="복구 종료일 YYYY-MM-DD")
    parser.add_argument("--lookback-days", type=int, default=4)
    parser.add_argument("--data-dir", default="docs/data")
    parser.add_argument("--list-url", default=DEFAULT_LIST_URL)
    parser.add_argument("--max-pages", type=int, default=120)
    parser.add_argument("--detail-workers", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=0.2)
    return parser.parse_args()


def resolve_range(args: argparse.Namespace) -> tuple[date, date]:
    if bool(args.start_date) != bool(args.end_date):
        raise ValueError("start-date와 end-date는 함께 지정해야 합니다.")
    if args.start_date and args.end_date:
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
    else:
        if args.lookback_days < 1:
            raise ValueError("lookback-days는 1 이상이어야 합니다.")
        end = datetime.now(SEOUL).date()
        start = end - timedelta(days=args.lookback_days - 1)
    if start > end:
        raise ValueError("start-date는 end-date보다 늦을 수 없습니다.")
    if args.max_pages < 1:
        raise ValueError("max-pages는 1 이상이어야 합니다.")
    if args.detail_workers < 1 or args.detail_workers > 4:
        raise ValueError("detail-workers는 1 이상 4 이하여야 합니다.")
    return start, end


def iter_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def ensure_empty_file(data_dir: Path, day: date) -> None:
    path = data_dir / f"{day:%Y/%m/%d}" / "articles.json"
    if path.exists():
        return
    write_json(
        path,
        {
            "schema_version": 2,
            "date": day.isoformat(),
            "source": "대한민국 정책브리핑 보도자료 HTML",
            "generated_at": now_iso(),
            "article_count": 0,
            "modified_count": 0,
            "articles": [],
        },
    )


def main() -> int:
    args = parse_args()
    start, end = resolve_range(args)
    target_days = iter_days(start, end)
    target_set = set(target_days)
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"일반 목록 역추적 범위: {start.isoformat()} ~ {end.isoformat()}", flush=True)
    session = create_session()
    entries_by_id = {}
    passed_start = False

    for page_no in range(1, args.max_pages + 1):
        print(f"일반 목록 페이지 {page_no}/{args.max_pages} 확인 중", flush=True)
        content = request_page(
            session,
            args.list_url,
            params={
                "pageIndex": str(page_no),
                "period": "",
                "srchWord": "",
                "repCode": "",
                "repCodeType": "",
            },
        )

        dates_seen: set[date] = set()
        candidate_count = 0
        for target_day in target_days:
            parsed = parse_list_page(content, target_day)
            candidate_count = max(candidate_count, parsed.candidate_count)
            dates_seen.update(date.fromisoformat(value) for value in parsed.dates_seen)
            for entry in parsed.entries:
                entries_by_id[entry.article_id] = entry

        if candidate_count == 0 and not dates_seen:
            raise RuntimeError("일반 목록에서 보도자료 항목과 날짜를 찾지 못했습니다.")

        if dates_seen:
            print(
                "  화면 날짜: " + ", ".join(value.isoformat() for value in sorted(dates_seen)),
                flush=True,
            )
            if min(dates_seen) < start:
                passed_start = True
                break

        if args.request_delay > 0:
            time.sleep(args.request_delay)

    if not passed_start:
        raise RuntimeError(
            f"{start.isoformat()}보다 과거 자료까지 도달하지 못했습니다. max-pages를 늘려야 합니다."
        )

    entries = [entry for entry in entries_by_id.values() if entry.publish_date in target_set]
    entries.sort(key=lambda item: (item.publish_date, item.article_id), reverse=True)
    print(f"복구 대상 목록: {len(entries)}건", flush=True)

    outcomes = {"created": 0, "updated": 0, "normalized": 0, "unchanged": 0}
    failures = 0
    if entries:
        with ThreadPoolExecutor(max_workers=min(args.detail_workers, len(entries))) as executor:
            futures = {
                executor.submit(
                    fetch_detail_article,
                    entry,
                    request_delay=0.15,
                ): entry
                for entry in entries
            }
            completed = 0
            for future in as_completed(futures):
                article, failed = future.result()
                outcome = upsert_article(data_dir, article, save_history=True)
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
                failures += int(failed)
                completed += 1
                if completed == 1 or completed % 10 == 0 or completed == len(entries):
                    print(f"본문 진행 {completed}/{len(entries)} (실패 {failures})", flush=True)

    for target_day in target_days:
        ensure_empty_file(data_dir, target_day)

    build_indexes(data_dir)
    print(f"복구 완료: {outcomes}, 본문 실패 {failures}건", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
