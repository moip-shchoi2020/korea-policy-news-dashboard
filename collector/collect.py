from __future__ import annotations

import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from collector.build_indexes import build_indexes
from collector.common import (
    collapse_whitespace,
    content_hash,
    local_name,
    now_iso,
    read_json,
    sanitize_body_html,
    truncate,
    write_json,
)

SEOUL = ZoneInfo("Asia/Seoul")
DEFAULT_API_URL = "https://apis.data.go.kr/1371000/policyNewsService/policyNewsList"


@dataclass(frozen=True)
class CollectRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def iter_days(self) -> Iterable[date]:
        current = self.start
        while current <= self.end:
            yield current
            current += timedelta(days=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="대한민국 정책브리핑 OpenAPI에서 보도자료를 날짜별로 수집합니다."
    )
    parser.add_argument("--start-date", help="수집 시작일(YYYY-MM-DD)")
    parser.add_argument("--end-date", help="수집 종료일(YYYY-MM-DD)")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=int(os.getenv("LOOKBACK_DAYS", "14")),
        help="날짜 미지정 시 오늘을 포함해 다시 확인할 일수(기본 14일)",
    )
    parser.add_argument(
        "--max-days",
        type=int,
        default=int(os.getenv("MAX_RANGE_DAYS", "900")),
        help="한 번에 요청할 수 있는 최대 일수(기본 900일)",
    )
    parser.add_argument(
        "--data-dir",
        default=os.getenv("DATA_DIR", "docs/data"),
        help="데이터 저장 경로",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("POLICY_NEWS_API_URL", DEFAULT_API_URL),
        help="정책브리핑 OpenAPI 요청 URL",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=float(os.getenv("REQUEST_DELAY_SECONDS", "0.15")),
        help="일자별 요청 사이의 대기 시간(초)",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="일부 날짜 요청 실패 시 나머지 날짜를 계속 수집",
    )
    parser.add_argument(
        "--require-records",
        action="store_true",
        help="전체 수집 결과가 0건이면 오류로 종료",
    )
    return parser.parse_args()


def parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name}은 YYYY-MM-DD 형식이어야 합니다: {value}") from exc


def resolve_range(args: argparse.Namespace) -> CollectRange:
    if bool(args.start_date) != bool(args.end_date):
        raise ValueError("start-date와 end-date는 함께 지정해야 합니다.")

    if args.start_date and args.end_date:
        start = parse_iso_date(args.start_date, "start-date")
        end = parse_iso_date(args.end_date, "end-date")
    else:
        if args.lookback_days < 1:
            raise ValueError("lookback-days는 1 이상이어야 합니다.")
        end = datetime.now(SEOUL).date()
        start = end - timedelta(days=args.lookback_days - 1)

    if start > end:
        raise ValueError("start-date는 end-date보다 늦을 수 없습니다.")

    result = CollectRange(start=start, end=end)
    if result.days > args.max_days:
        raise ValueError(
            f"요청 범위가 {result.days}일로 최대 {args.max_days}일을 초과합니다. "
            "기간을 나누어 실행하세요."
        )
    return result


def normalize_service_key(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("DATA_GO_KR_SERVICE_KEY가 비어 있습니다.")
    # 공공데이터포털의 Encoding 키를 붙여 넣은 경우 requests가 다시 인코딩할 수 있도록 복원한다.
    return unquote(value) if "%" in value else value


def create_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "korea-policy-dashboard/1.0 (+https://github.com/)",
            "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
        }
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def node_text(parent: ET.Element, field_name: str) -> str:
    for node in parent.iter():
        if local_name(node.tag).lower() == field_name.lower():
            if len(node) == 0:
                return collapse_whitespace(node.text)
            fragments = [node.text or ""]
            for child in node:
                fragments.append(ET.tostring(child, encoding="unicode", method="html"))
            return "".join(fragments).strip()
    return ""


def find_records(root: ET.Element) -> list[ET.Element]:
    records: list[ET.Element] = []
    for element in root.iter():
        child_names = {local_name(child.tag).lower() for child in list(element)}
        if "newsitemid" in child_names:
            records.append(element)
    return records


def parse_datetime(value: str) -> datetime | None:
    value = collapse_whitespace(value)
    if not value:
        return None

    formats = (
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d%H%M%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=SEOUL)
            return parsed.astimezone(SEOUL)
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SEOUL)
        return parsed.astimezone(SEOUL)
    except ValueError:
        return None


def parse_int(value: str, default: int = 0) -> int:
    match = re.search(r"-?\d+", value or "")
    return int(match.group()) if match else default


def make_summary(subtitles: list[str], body_text: str) -> tuple[str, str]:
    subtitle = " · ".join(dict.fromkeys(filter(None, (collapse_whitespace(v) for v in subtitles))))
    if subtitle:
        return truncate(subtitle, 240), "subtitle"
    return truncate(body_text, 240), "body_excerpt"


def parse_response(xml_text: str, query_day: date) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        preview = collapse_whitespace(xml_text)[:300]
        raise RuntimeError(f"API 응답을 XML로 해석하지 못했습니다: {preview}") from exc

    # 공공데이터포털은 정상 응답과 인증/서비스 오류 응답의 XML 구조가 다르다.
    # 오류 응답(returnAuthMsg 등)을 빈 검색 결과로 오인하지 않도록 모든 상태 필드를 먼저 확인한다.
    response_fields: dict[str, str] = {}
    for node in root.iter():
        name = local_name(node.tag).lower()
        value = collapse_whitespace(node.text)
        if value and name not in response_fields:
            response_fields[name] = value

    result_code = response_fields.get("resultcode", "")
    result_message = (
        response_fields.get("resultmsg")
        or response_fields.get("resultmessage")
        or ""
    )
    portal_error = (
        response_fields.get("returnauthmsg")
        or response_fields.get("errmsg")
        or ""
    )
    portal_reason = response_fields.get("returnreasoncode", "")

    if portal_error:
        reason_suffix = f" (코드 {portal_reason})" if portal_reason else ""
        raise RuntimeError(
            f"공공데이터포털 인증/서비스 오류: {portal_error}{reason_suffix}. "
            "Repository secret DATA_GO_KR_SERVICE_KEY와 API 활용승인 상태를 확인하세요."
        )

    if result_code and result_code not in {"0", "00"}:
        raise RuntimeError(f"API 오류 {result_code}: {result_message or '메시지 없음'}")

    records = find_records(root)
    if not result_code and not records:
        preview = collapse_whitespace(xml_text)[:300]
        raise RuntimeError(f"예상하지 못한 API 응답입니다: {preview}")

    collected_at = now_iso()
    articles: list[dict] = []

    for record in records:
        grouping_code = node_text(record, "GroupingCode")
        if grouping_code.lower() != "brief":
            continue

        article_id = node_text(record, "NewsItemId")
        title = node_text(record, "Title")
        if not article_id or not title:
            continue

        original_url = node_text(record, "OriginalUrl") or (
            f"https://www.korea.kr/briefing/pressReleaseView.do?newsId={article_id}"
        )
        raw_body = node_text(record, "DataContents")
        content_html, content_text = sanitize_body_html(raw_body, original_url)

        approved = parse_datetime(node_text(record, "ApproveDate"))
        modified = parse_datetime(node_text(record, "ModifyDate"))
        publish_date = approved.date() if approved else query_day

        status = node_text(record, "ContentsStatus").upper() or "I"
        modify_id = parse_int(node_text(record, "ModifyId"), default=1)
        is_modified = status == "U" or modify_id > 1
        summary, summary_source = make_summary(
            [
                node_text(record, "SubTitle1"),
                node_text(record, "SubTitle2"),
                node_text(record, "SubTitle3"),
            ],
            content_text,
        )

        hash_value = content_hash(
            article_id,
            title,
            summary,
            content_html,
            status,
            str(modify_id),
            modified.isoformat() if modified else "",
        )

        articles.append(
            {
                "id": article_id,
                "title": title,
                "summary": summary,
                "summary_source": summary_source,
                "ministry": node_text(record, "MinisterCode") or "기관 미상",
                "approved_at": approved.isoformat() if approved else f"{publish_date.isoformat()}T00:00:00+09:00",
                "modified_at": modified.isoformat() if modified else None,
                "publish_date": publish_date.isoformat(),
                "contents_status": status,
                "modify_id": modify_id,
                "is_modified": is_modified,
                "grouping_code": grouping_code,
                "original_url": original_url,
                "content_html": content_html,
                "content_text": content_text,
                "content_hash": hash_value,
                "collected_at": collected_at,
                "source_name": "대한민국 정책브리핑",
            }
        )

    return articles


def fetch_day(
    session: requests.Session,
    api_url: str,
    service_key: str,
    query_day: date,
) -> list[dict]:
    compact_date = query_day.strftime("%Y%m%d")
    response = session.get(
        api_url,
        params={
            "serviceKey": service_key,
            "startDate": compact_date,
            "endDate": compact_date,
        },
        timeout=(15, 90),
    )
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: API 요청 실패")
    return parse_response(response.text, query_day)


def safe_history_name(article: dict) -> str:
    modify_id = article.get("modify_id", 0)
    collected_at = str(article.get("collected_at", "")).replace(":", "-")
    digest = str(article.get("content_hash", ""))[:10]
    return f"modify-{modify_id}_{collected_at}_{digest}.json"


def upsert_article(data_dir: Path, article: dict, save_history: bool = True) -> str:
    publish_date = date.fromisoformat(article["publish_date"])
    day_dir = data_dir / f"{publish_date.year:04d}" / f"{publish_date.month:02d}" / f"{publish_date.day:02d}"
    articles_path = day_dir / "articles.json"
    payload = read_json(
        articles_path,
        {
            "schema_version": 1,
            "date": publish_date.isoformat(),
            "source": "대한민국 정책브리핑 OpenAPI",
            "articles": [],
        },
    )

    existing_articles = payload.get("articles", [])
    by_id = {str(item.get("id")): item for item in existing_articles if item.get("id")}
    existing = by_id.get(article["id"])

    if existing and existing.get("content_hash") == article.get("content_hash"):
        return "unchanged"

    if existing and save_history:
        history_path = day_dir / "revisions" / article["id"] / safe_history_name(existing)
        if not history_path.exists():
            write_json(history_path, existing)

    by_id[article["id"]] = article
    merged = sorted(
        by_id.values(),
        key=lambda item: (item.get("approved_at") or "", item.get("id") or ""),
        reverse=True,
    )
    payload["articles"] = merged
    payload["generated_at"] = max(
        (item.get("collected_at") for item in merged if item.get("collected_at")),
        default=now_iso(),
    )
    payload["article_count"] = len(merged)
    payload["modified_count"] = sum(bool(item.get("is_modified")) for item in merged)
    write_json(articles_path, payload)
    return "updated" if existing else "created"


def main() -> int:
    args = parse_args()
    try:
        collect_range = resolve_range(args)
        service_key = normalize_service_key(os.getenv("DATA_GO_KR_SERVICE_KEY", ""))
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    save_history = os.getenv("SAVE_REVISION_HISTORY", "true").lower() not in {"0", "false", "no"}

    print(
        f"수집 기간: {collect_range.start.isoformat()} ~ {collect_range.end.isoformat()} "
        f"({collect_range.days}일)"
    )
    session = create_session()
    stats = {"created": 0, "updated": 0, "unchanged": 0, "received": 0}
    failed_dates: list[str] = []
    successful_dates = 0

    for index, query_day in enumerate(collect_range.iter_days(), start=1):
        try:
            articles = fetch_day(session, args.api_url, service_key, query_day)
            successful_dates += 1
            stats["received"] += len(articles)
            for article in articles:
                result = upsert_article(data_dir, article, save_history=save_history)
                stats[result] += 1
            print(
                f"[{index}/{collect_range.days}] {query_day.isoformat()}: "
                f"보도자료 {len(articles)}건"
            )
        except Exception as exc:  # noqa: BLE001 - 날짜별 장애를 분리해 보고한다.
            failed_dates.append(query_day.isoformat())
            print(f"::warning title=수집 실패::{query_day.isoformat()} - {exc}", file=sys.stderr)
            if not args.continue_on_error:
                return 1

        if args.request_delay > 0 and index < collect_range.days:
            time.sleep(args.request_delay)

    if successful_dates == 0:
        print("오류: 모든 날짜의 수집에 실패했습니다.", file=sys.stderr)
        return 1

    if stats["received"] == 0:
        message = (
            "API 요청은 완료됐지만 보도자료가 0건입니다. "
            "수집 기간, API 활용승인 상태, 인증키를 확인하세요."
        )
        if args.require_records:
            print(f"오류: {message}", file=sys.stderr)
            return 3
        print(f"::warning title=수집 결과 0건::{message}", file=sys.stderr)

    build_indexes(data_dir)
    print(
        "완료: "
        f"API 수신 {stats['received']}건, 신규 {stats['created']}건, "
        f"갱신 {stats['updated']}건, 변경 없음 {stats['unchanged']}건"
    )
    if failed_dates:
        print(f"경고: 실패 날짜 {', '.join(failed_dates)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
