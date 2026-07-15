from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
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
BASE_URL = "https://www.korea.kr"
DEFAULT_LIST_URL = f"{BASE_URL}/briefing/pressReleaseList.do"
DEFAULT_CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT_SECONDS", "8"))
DEFAULT_READ_TIMEOUT = float(os.getenv("READ_TIMEOUT_SECONDS", "20"))
_DETAIL_THREAD = threading.local()


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


@dataclass(frozen=True)
class ListEntry:
    article_id: str
    title: str
    lead: str
    ministry: str
    publish_date: date
    original_url: str


@dataclass(frozen=True)
class ParsedListPage:
    entries: list[ListEntry]
    total_count: int | None
    candidate_count: int
    dates_seen: tuple[str, ...]


@dataclass(frozen=True)
class DayResult:
    articles: list[dict[str, Any]]
    list_count: int
    pages_fetched: int
    detail_failures: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="대한민국 정책브리핑 보도자료 목록과 상세페이지를 날짜별로 수집합니다."
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
        "--list-url",
        default=os.getenv("KOREA_PRESS_LIST_URL", DEFAULT_LIST_URL),
        help="정책브리핑 보도자료 목록 URL",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=float(os.getenv("REQUEST_DELAY_SECONDS", "0.15")),
        help="정책브리핑 요청 사이의 대기 시간(초, 기본 0.15)",
    )
    parser.add_argument(
        "--max-pages-per-day",
        type=int,
        default=int(os.getenv("MAX_PAGES_PER_DAY", "10")),
        help="하루 목록에서 확인할 최대 페이지 수(기본 10)",
    )
    parser.add_argument(
        "--detail-workers",
        type=int,
        default=int(os.getenv("DETAIL_WORKERS", "3")),
        help="상세 본문 동시 요청 수(기본 3, 최대 권장 4)",
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
    if args.max_pages_per_day < 1:
        raise ValueError("max-pages-per-day는 1 이상이어야 합니다.")
    if args.request_delay < 0:
        raise ValueError("request-delay는 0 이상이어야 합니다.")
    if args.detail_workers < 1 or args.detail_workers > 4:
        raise ValueError("detail-workers는 1 이상 4 이하여야 합니다.")
    return result


def create_session() -> requests.Session:
    retry = Retry(
        total=1,
        connect=1,
        read=1,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36 "
                "korea-policy-dashboard/2.0"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
            "Referer": f"{BASE_URL}/",
            "Cache-Control": "no-cache",
        }
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def detail_session() -> requests.Session:
    session = getattr(_DETAIL_THREAD, "session", None)
    if session is None:
        session = create_session()
        _DETAIL_THREAD.session = session
    return session


def response_preview(content: bytes | str, max_chars: int = 300) -> str:
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = content
    return collapse_whitespace(text)[:max_chars]


def request_page(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, str] | None = None,
    timeout: tuple[float, float] = (DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT),
) -> bytes:
    response = session.get(url, params=params, timeout=timeout, allow_redirects=True)
    if response.status_code >= 400:
        preview = response_preview(response.content)
        suffix = f"; 응답={preview}" if preview else ""
        raise RuntimeError(f"HTTP {response.status_code}: 정책브리핑 요청 실패{suffix}")
    if not response.content:
        raise RuntimeError("정책브리핑 응답이 비어 있습니다.")
    return response.content


def clean_text(value: str | None) -> str:
    return collapse_whitespace(html_lib.unescape(value or ""))


def parse_site_date(value: str) -> date | None:
    value = clean_text(value)
    patterns = (
        (r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", (1, 2, 3)),
        (r"(\d{1,2})/(\d{1,2})/(\d{4})", (3, 1, 2)),
    )
    for pattern, order in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        parts = [int(match.group(index)) for index in order]
        try:
            return date(parts[0], parts[1], parts[2])
        except ValueError:
            continue
    return None


def parse_datetime(value: str) -> datetime | None:
    value = clean_text(value)
    if not value:
        return None

    # ISO 8601의 Z 표기를 Python이 이해하는 +00:00으로 변환한다.
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SEOUL)
        return parsed.astimezone(SEOUL)
    except ValueError:
        pass

    formats = (
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y.%m.%d %H:%M:%S",
        "%Y%m%d%H%M%S",
        "%Y-%m-%d",
        "%Y.%m.%d",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt).replace(tzinfo=SEOUL)
            return parsed
        except ValueError:
            continue
    return None


def article_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("newsId", [])
    if values and values[0].strip():
        return values[0].strip()
    match = re.search(r"(?:newsId=|/)(\d{6,})", url)
    return match.group(1) if match else ""


def canonical_detail_url(url: str, article_id: str) -> str:
    if article_id:
        return f"{BASE_URL}/briefing/pressReleaseView.do?newsId={article_id}"
    return urljoin(BASE_URL, html_lib.unescape(url))


def parse_total_count(soup: BeautifulSoup) -> int | None:
    text = collapse_whitespace(soup.get_text(" ", strip=True))
    match = re.search(r"총\s*([\d,]+)\s*건", text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def source_parts(scope: Any) -> tuple[str, str]:
    source = scope.select_one("span.source")
    if source is None:
        return "", ""
    parts = [clean_text(node.get_text(" ", strip=True)) for node in source.find_all("span")]
    parts = [part for part in parts if part]
    date_text = next((part for part in parts if parse_site_date(part)), "")
    ministry = next((part for part in reversed(parts) if part != date_text), "")
    return date_text, ministry


def parse_list_page(html_content: bytes | str, query_day: date) -> ParsedListPage:
    soup = BeautifulSoup(html_content, "html.parser")
    total_count = parse_total_count(soup)
    entries: list[ListEntry] = []
    seen_ids: set[str] = set()
    candidate_count = 0
    dates_seen: set[str] = set()

    for anchor in soup.select('a[href*="pressReleaseView.do"]'):
        href = clean_text(anchor.get("href"))
        full_url = urljoin(BASE_URL, href)
        if "/briefing/pressReleaseView.do" not in urlparse(full_url).path:
            continue

        scope = anchor.find_parent("li") or anchor
        title_node = scope.select_one("strong") or anchor.select_one("strong")
        lead_node = scope.select_one("span.lead") or anchor.select_one("span.lead")
        date_text, ministry = source_parts(scope)
        if not date_text and scope is not anchor:
            date_text, ministry = source_parts(anchor)

        # 목록 본문 항목은 제목과 출처 영역을 함께 갖는다. 이를 요구해
        # 페이지 하단의 추천 링크가 수집되는 것을 막는다.
        if title_node is None or not date_text:
            continue

        publish_date = parse_site_date(date_text)
        if publish_date is None:
            continue
        candidate_count += 1
        dates_seen.add(publish_date.isoformat())
        if publish_date != query_day:
            continue

        article_id = article_id_from_url(full_url)
        title = clean_text(title_node.get_text(" ", strip=True))
        lead = clean_text(lead_node.get_text(" ", strip=True)) if lead_node else ""
        if not article_id or not title or article_id in seen_ids:
            continue

        seen_ids.add(article_id)
        entries.append(
            ListEntry(
                article_id=article_id,
                title=title,
                lead=lead,
                ministry=ministry or "기관 미상",
                publish_date=publish_date,
                original_url=canonical_detail_url(full_url, article_id),
            )
        )

    return ParsedListPage(
        entries=entries,
        total_count=total_count,
        candidate_count=candidate_count,
        dates_seen=tuple(sorted(dates_seen)),
    )


def iter_jsonld_objects(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, (list, dict)):
            yield from iter_jsonld_objects(graph)
        for child in value.values():
            if child is graph:
                continue
            if isinstance(child, (list, dict)):
                yield from iter_jsonld_objects(child)
    elif isinstance(value, list):
        for item in value:
            yield from iter_jsonld_objects(item)


def extract_article_jsonld(soup: BeautifulSoup) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in iter_jsonld_objects(payload):
            kind = obj.get("@type", "")
            kinds = kind if isinstance(kind, list) else [kind]
            score = 0
            if any(str(item).casefold() in {"newsarticle", "article", "reportagenewsarticle"} for item in kinds):
                score += 3
            if obj.get("headline"):
                score += 2
            if obj.get("datePublished"):
                score += 1
            if score:
                obj = dict(obj)
                obj["__score"] = score
                candidates.append(obj)
    if not candidates:
        return {}
    candidates.sort(key=lambda item: int(item.get("__score", 0)), reverse=True)
    result = candidates[0]
    result.pop("__score", None)
    return result


def jsonld_text(value: Any) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        for key in ("name", "text", "description"):
            if isinstance(value.get(key), str):
                return clean_text(value[key])
    return ""


def find_body_node(soup: BeautifulSoup) -> Any | None:
    selectors = (
        "div.view_cont",
        "article div.view_cont",
        "div.articleBody",
        "div.article_body",
        "div.viewContent",
        "div.contentArea",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if node is not None and clean_text(node.get_text(" ", strip=True)):
            return node
    return None


def build_article_from_detail(entry: ListEntry, html_content: bytes | str) -> dict[str, Any]:
    soup = BeautifulSoup(html_content, "html.parser")
    metadata = extract_article_jsonld(soup)
    body_node = find_body_node(soup)

    title = jsonld_text(metadata.get("headline")) or entry.title
    description = jsonld_text(metadata.get("description"))
    raw_body = str(body_node) if body_node is not None else description
    content_html, content_text = sanitize_body_html(raw_body, entry.original_url)

    # 상세 본문이 비어 있을 때 목록 요약을 최소 본문으로 보존한다.
    if not content_text and entry.lead:
        fallback_html = f"<p>{html_lib.escape(entry.lead)}</p>"
        content_html, content_text = sanitize_body_html(fallback_html, entry.original_url)

    summary_source = "list_lead" if entry.lead else ("description" if description else "body_excerpt")
    summary = truncate(entry.lead or description or content_text, 240)

    approved = parse_datetime(str(metadata.get("datePublished") or ""))
    if approved is None:
        approved = datetime.combine(entry.publish_date, datetime.min.time(), tzinfo=SEOUL)

    modified = parse_datetime(str(metadata.get("dateModified") or ""))
    explicit_modified = bool(modified and modified > approved)

    hash_value = content_hash(
        entry.article_id,
        title,
        summary,
        entry.ministry,
        content_html,
    )
    collected_at = now_iso()

    return {
        "id": entry.article_id,
        "title": title,
        "summary": summary,
        "summary_source": summary_source,
        "ministry": entry.ministry or "기관 미상",
        "approved_at": approved.isoformat(),
        "modified_at": modified.isoformat() if explicit_modified and modified else None,
        "publish_date": entry.publish_date.isoformat(),
        "contents_status": "U" if explicit_modified else "I",
        "modify_id": 2 if explicit_modified else 1,
        "is_modified": explicit_modified,
        "grouping_code": "brief-html",
        "original_url": entry.original_url,
        "content_html": content_html,
        "content_text": content_text,
        "content_hash": hash_value,
        "collected_at": collected_at,
        "source_name": "대한민국 정책브리핑",
        "source_method": "pressReleaseList.do HTML",
    }


def build_fallback_article(entry: ListEntry) -> dict[str, Any]:
    fallback_html = f"<p>{html_lib.escape(entry.lead)}</p>" if entry.lead else ""
    content_html, content_text = sanitize_body_html(fallback_html, entry.original_url)
    approved = datetime.combine(entry.publish_date, datetime.min.time(), tzinfo=SEOUL)
    summary = truncate(entry.lead, 240)
    return {
        "id": entry.article_id,
        "title": entry.title,
        "summary": summary,
        "summary_source": "list_lead" if summary else "none",
        "ministry": entry.ministry or "기관 미상",
        "approved_at": approved.isoformat(),
        "modified_at": None,
        "publish_date": entry.publish_date.isoformat(),
        "contents_status": "I",
        "modify_id": 1,
        "is_modified": False,
        "grouping_code": "brief-html",
        "original_url": entry.original_url,
        "content_html": content_html,
        "content_text": content_text,
        "content_hash": content_hash(entry.article_id, entry.title, summary, entry.ministry, content_html),
        "collected_at": now_iso(),
        "source_name": "대한민국 정책브리핑",
        "source_method": "pressReleaseList.do HTML (detail fallback)",
    }


def fetch_list_entries(
    session: requests.Session,
    list_url: str,
    query_day: date,
    *,
    max_pages: int,
    request_delay: float,
) -> tuple[list[ListEntry], int]:
    all_entries: list[ListEntry] = []
    seen_ids: set[str] = set()
    expected_total: int | None = None
    pages_fetched = 0
    last_page_had_entries = False

    for page_no in range(1, max_pages + 1):
        print(
            f"    목록 페이지 {page_no} 확인 중 ({query_day.isoformat()})",
            flush=True,
        )
        content = request_page(
            session,
            list_url,
            params={
                "pageIndex": str(page_no),
                "startDate": query_day.isoformat(),
                "endDate": query_day.isoformat(),
                "period": "",
                "srchWord": "",
                "repCode": "",
                "repCodeType": "",
            },
        )
        pages_fetched += 1
        parsed = parse_list_page(content, query_day)

        if page_no == 1:
            # 날짜 검색 결과의 총 건수라면 페이지 종료 판단에 활용한다.
            # 전체 누적 건수가 표시되는 화면도 있으므로 지나치게 큰 값은 무시한다.
            if parsed.total_count is not None and parsed.total_count <= 1000:
                expected_total = parsed.total_count

            if parsed.total_count is None and parsed.candidate_count == 0:
                preview = response_preview(content)
                raise RuntimeError(
                    "목록 페이지에서 총 건수와 보도자료 항목을 찾지 못했습니다. "
                    f"사이트 구조 또는 차단 응답을 확인하세요. 응답={preview}"
                )

            if not parsed.entries and parsed.candidate_count > 0:
                seen = ", ".join(parsed.dates_seen[:5]) or "알 수 없음"
                raise RuntimeError(
                    f"요청일 {query_day.isoformat()} 대신 다른 날짜 항목이 반환됐습니다 "
                    f"(화면 날짜: {seen}). 날짜 검색 파라미터가 적용되지 않았을 수 있습니다."
                )

        new_entries = [entry for entry in parsed.entries if entry.article_id not in seen_ids]
        for entry in new_entries:
            seen_ids.add(entry.article_id)
            all_entries.append(entry)

        last_page_had_entries = bool(parsed.entries)

        if expected_total is not None and len(all_entries) >= expected_total:
            return all_entries[:expected_total], pages_fetched

        if not parsed.entries:
            return all_entries, pages_fetched

        if not new_entries:
            return all_entries, pages_fetched

        if request_delay > 0:
            time.sleep(request_delay)

    if last_page_had_entries:
        raise RuntimeError(
            f"하루 최대 페이지 수 {max_pages}에 도달했습니다. "
            "자료 누락을 막기 위해 MAX_PAGES_PER_DAY를 늘려 다시 실행하세요."
        )
    return all_entries, pages_fetched


def fetch_detail_article(
    entry: ListEntry,
    *,
    request_delay: float,
) -> tuple[dict[str, Any], bool]:
    try:
        detail_content = request_page(detail_session(), entry.original_url)
        article = build_article_from_detail(entry, detail_content)
        failed = False
    except Exception as exc:  # noqa: BLE001 - 개별 상세 실패는 목록 데이터로 보완한다.
        print(
            f"::warning title=본문 수집 실패::{entry.article_id} - {exc}",
            file=sys.stderr,
            flush=True,
        )
        article = build_fallback_article(entry)
        failed = True
    if request_delay > 0:
        time.sleep(request_delay)
    return article, failed


def fetch_day(
    session: requests.Session,
    list_url: str,
    query_day: date,
    *,
    max_pages: int,
    request_delay: float,
    detail_workers: int,
) -> DayResult:
    entries, pages_fetched = fetch_list_entries(
        session,
        list_url,
        query_day,
        max_pages=max_pages,
        request_delay=request_delay,
    )

    if not entries:
        return DayResult(
            articles=[],
            list_count=0,
            pages_fetched=pages_fetched,
            detail_failures=0,
        )

    print(
        f"    목록 {len(entries)}건 확인. 본문 수집 시작 "
        f"(동시 요청 {min(detail_workers, len(entries))}개)",
        flush=True,
    )

    articles_by_id: dict[str, dict[str, Any]] = {}
    detail_failures = 0
    workers = min(detail_workers, len(entries))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="korea-detail") as executor:
        futures = {
            executor.submit(
                fetch_detail_article,
                entry,
                request_delay=request_delay,
            ): entry
            for entry in entries
        }
        completed = 0
        for future in as_completed(futures):
            entry = futures[future]
            try:
                article, failed = future.result()
            except Exception as exc:  # 방어적 폴백
                print(
                    f"::warning title=본문 작업 실패::{entry.article_id} - {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                article = build_fallback_article(entry)
                failed = True
            articles_by_id[entry.article_id] = article
            detail_failures += int(failed)
            completed += 1
            if completed == 1 or completed % 5 == 0 or completed == len(entries):
                print(
                    f"    본문 진행 {completed}/{len(entries)} "
                    f"(실패 {detail_failures})",
                    flush=True,
                )

    articles = [
        articles_by_id[entry.article_id]
        for entry in entries
        if entry.article_id in articles_by_id
    ]
    return DayResult(
        articles=articles,
        list_count=len(entries),
        pages_fetched=pages_fetched,
        detail_failures=detail_failures,
    )


# ---------------------------------------------------------------------------
# 기존 XML 단위 테스트와의 호환성
# ---------------------------------------------------------------------------

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


def parse_int(value: str, default: int = 0) -> int:
    match = re.search(r"-?\d+", value or "")
    return int(match.group()) if match else default


def make_summary(subtitles: list[str], body_text: str) -> tuple[str, str]:
    subtitle = " · ".join(dict.fromkeys(filter(None, (collapse_whitespace(v) for v in subtitles))))
    if subtitle:
        return truncate(subtitle, 240), "subtitle"
    return truncate(body_text, 240), "body_excerpt"


def parse_response(xml_text: str | bytes, query_day: date) -> list[dict[str, Any]]:
    """이전 OpenAPI XML fixture를 사용하는 저장소 단위 테스트용 호환 함수."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"XML을 해석하지 못했습니다: {response_preview(xml_text)}") from exc

    result_code = ""
    result_message = ""
    for node in root.iter():
        name = local_name(node.tag).lower()
        if name == "resultcode" and not result_code:
            result_code = collapse_whitespace(node.text)
        elif name in {"resultmsg", "resultmessage"} and not result_message:
            result_message = collapse_whitespace(node.text)
    if result_code and result_code not in {"0", "00", "0000"}:
        raise RuntimeError(f"API 오류 {result_code}: {result_message or '메시지 없음'}")

    collected_at = now_iso()
    articles: list[dict[str, Any]] = []
    for record in find_records(root):
        grouping_code = node_text(record, "GroupingCode")
        if grouping_code.casefold() != "brief":
            continue
        article_id = node_text(record, "NewsItemId")
        title = node_text(record, "Title")
        if not article_id or not title:
            continue
        original_url = node_text(record, "OriginalUrl") or canonical_detail_url("", article_id)
        content_html, content_text = sanitize_body_html(
            node_text(record, "DataContents"), original_url
        )
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
        hash_value = content_hash(article_id, title, summary, node_text(record, "MinisterCode"), content_html)
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
                "source_method": "legacy XML fixture",
            }
        )
    return articles


def safe_history_name(article: dict[str, Any]) -> str:
    modify_id = article.get("modify_id", 0)
    collected_at = str(article.get("collected_at", "")).replace(":", "-")
    digest = str(article.get("content_hash", ""))[:10]
    return f"modify-{modify_id}_{collected_at}_{digest}.json"


def upsert_article(data_dir: Path, article: dict[str, Any], save_history: bool = True) -> str:
    publish_date = date.fromisoformat(str(article["publish_date"]))
    day_dir = data_dir / f"{publish_date.year:04d}" / f"{publish_date.month:02d}" / f"{publish_date.day:02d}"
    articles_path = day_dir / "articles.json"
    payload = read_json(
        articles_path,
        {
            "schema_version": 2,
            "date": publish_date.isoformat(),
            "source": "대한민국 정책브리핑 보도자료 HTML",
            "articles": [],
        },
    )

    existing_articles = payload.get("articles", [])
    by_id = {str(item.get("id")): item for item in existing_articles if item.get("id")}
    existing = by_id.get(str(article["id"]))

    if existing and existing.get("content_hash") == article.get("content_hash"):
        return "unchanged"

    if existing:
        if save_history:
            history_path = day_dir / "revisions" / str(article["id"]) / safe_history_name(existing)
            if not history_path.exists():
                write_json(history_path, existing)

        # HTML 수집에는 OpenAPI의 변경횟수가 없으므로 이전 저장본과 본문·제목·요약의
        # 해시가 달라진 시점을 수정으로 판정한다.
        previous_modify_id = int(existing.get("modify_id") or 1)
        detected_modify_id = int(article.get("modify_id") or 1)
        article["contents_status"] = "U"
        article["is_modified"] = True
        article["modify_id"] = max(previous_modify_id + 1, detected_modify_id)
        article["modified_at"] = article.get("modified_at") or now_iso()
        article["approved_at"] = existing.get("approved_at") or article.get("approved_at")
        article["publish_date"] = existing.get("publish_date") or article.get("publish_date")

    by_id[str(article["id"])] = article
    merged = sorted(
        by_id.values(),
        key=lambda item: (item.get("approved_at") or "", item.get("id") or ""),
        reverse=True,
    )
    payload["schema_version"] = 2
    payload["source"] = "대한민국 정책브리핑 보도자료 HTML"
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
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    save_history = os.getenv("SAVE_REVISION_HISTORY", "true").lower() not in {"0", "false", "no"}

    print("수집 방식: 정책브리핑 보도자료 목록·상세페이지 HTML", flush=True)
    print(f"목록 주소: {args.list_url}", flush=True)
    print(
        f"수집 기간: {collect_range.start.isoformat()} ~ {collect_range.end.isoformat()} "
        f"({collect_range.days}일)",
        flush=True,
    )
    print(
        f"요청 제한: 연결 {DEFAULT_CONNECT_TIMEOUT:g}초 / 읽기 {DEFAULT_READ_TIMEOUT:g}초 / "
        f"본문 동시 요청 {args.detail_workers}개",
        flush=True,
    )

    session = create_session()
    stats = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "received": 0,
        "detail_failures": 0,
        "pages": 0,
    }
    failed_dates: list[str] = []
    successful_dates = 0

    for index, query_day in enumerate(collect_range.iter_days(), start=1):
        print(
            f"[{index}/{collect_range.days}] {query_day.isoformat()}: 수집 시작",
            flush=True,
        )
        try:
            result = fetch_day(
                session,
                args.list_url,
                query_day,
                max_pages=args.max_pages_per_day,
                request_delay=args.request_delay,
                detail_workers=args.detail_workers,
            )
            successful_dates += 1
            stats["received"] += len(result.articles)
            stats["detail_failures"] += result.detail_failures
            stats["pages"] += result.pages_fetched
            for article in result.articles:
                outcome = upsert_article(data_dir, article, save_history=save_history)
                stats[outcome] += 1
            print(
                f"[{index}/{collect_range.days}] {query_day.isoformat()}: "
                f"목록 {result.list_count}건 / 저장 대상 {len(result.articles)}건 / "
                f"목록 페이지 {result.pages_fetched}개 / 본문 실패 {result.detail_failures}건",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - 날짜별 장애를 분리해 보고한다.
            failed_dates.append(query_day.isoformat())
            print(
                f"::warning title=수집 실패::{query_day.isoformat()} - {exc}",
                file=sys.stderr,
                flush=True,
            )
            if not args.continue_on_error:
                return 1

    if successful_dates == 0:
        print("오류: 모든 날짜의 목록 수집에 실패했습니다.", file=sys.stderr)
        return 1

    if stats["received"] == 0:
        message = (
            "정책브리핑 보도자료 목록 요청은 완료됐지만 전체 수집 결과가 0건입니다. "
            "평일이 포함된 기간이라면 목록 HTML 구조 또는 접근 상태를 확인하세요."
        )
        if args.require_records:
            print(f"오류: {message}", file=sys.stderr)
            return 3
        print(f"::warning title=수집 결과 0건::{message}", file=sys.stderr)

    build_indexes(data_dir)
    print(
        "완료: "
        f"목록 수신 {stats['received']}건, 신규 {stats['created']}건, "
        f"갱신 {stats['updated']}건, 변경 없음 {stats['unchanged']}건, "
        f"본문 실패 {stats['detail_failures']}건",
        flush=True,
    )
    if failed_dates:
        print(f"경고: 실패 날짜 {', '.join(failed_dates)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
