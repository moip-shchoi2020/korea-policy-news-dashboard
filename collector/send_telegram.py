from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")
DATA_DIR = Path("docs/data")
CONFIG_PATH = DATA_DIR / "config.json"
TELEGRAM_API_ROOT = "https://api.telegram.org"
MAX_TELEGRAM_TEXT = 3800  # Bot API 한도 4096자보다 여유 있게 분할

LEVEL_ORDER = {
    "critical": 4,
    "important": 3,
    "normal": 2,
    "unrelated": 1,
    "unclassified": 0,
}
LEVEL_META = {
    "critical": ("🔴", "매우 중요"),
    "important": ("🟠", "중요"),
    "normal": ("🔵", "보통"),
    "unrelated": ("⚪", "관계없음"),
    "unclassified": ("◻️", "미분류"),
}


@dataclass(frozen=True)
class DigestResult:
    report_date: str
    keywords: list[str]
    articles: list[dict[str, Any]]
    matched_articles: list[dict[str, Any]]
    selected_articles: list[dict[str, Any]]
    counts: dict[str, int]
    dashboard_url: str


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def decode_html_entities(value: Any, max_passes: int = 5) -> str:
    current = str(value or "")
    for _ in range(max_passes):
        decoded = html.unescape(current)
        if decoded == current:
            break
        current = decoded
    return current


def normalize_text(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        decode_html_entities(value)
        .replace("\u00a0", " ")
        .replace("\u00ad", "")
        .replace("\u200b", "")
        .replace("\ufeff", ""),
    ).strip()


def truncate(value: Any, limit: int) -> str:
    text = normalize_text(value)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def parse_keywords(value: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in re.split(r"[\n,;]+", value or ""):
        keyword = normalize_text(raw)
        key = keyword.casefold()
        if keyword and key not in seen:
            seen.add(key)
            result.append(keyword)
    return result


def keyword_matches(text: str, keyword: str) -> bool:
    normalized_text = normalize_text(text).casefold()
    normalized_keyword = normalize_text(keyword).casefold()
    if not normalized_keyword:
        return False
    if re.fullmatch(r"[a-z0-9+#._-]+", keyword, flags=re.IGNORECASE):
        return re.search(
            rf"(^|[^a-z0-9]){re.escape(normalized_keyword)}($|[^a-z0-9])",
            normalized_text,
            flags=re.IGNORECASE,
        ) is not None
    return normalized_keyword in normalized_text


def article_search_text(article: dict[str, Any]) -> str:
    return " ".join(
        normalize_text(article.get(key, ""))
        for key in ("title", "summary", "ministry", "content_text", "search_text")
    )


def matched_keywords(article: dict[str, Any], keywords: list[str]) -> list[str]:
    if not keywords:
        return []
    text = article_search_text(article)
    return [keyword for keyword in keywords if keyword_matches(text, keyword)]


def article_level(article: dict[str, Any]) -> str:
    relevance = article.get("ip_relevance")
    level = relevance.get("level") if isinstance(relevance, dict) else None
    return str(level) if str(level) in LEVEL_ORDER else "unclassified"


def article_datetime_key(article: dict[str, Any]) -> str:
    return str(
        article.get("approved_at")
        or article.get("modified_at")
        or article.get("publish_date")
        or ""
    )


def safe_int_env(name: str, default: int, minimum: int = 0, maximum: int = 1000) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def derive_dashboard_url() -> str:
    configured = normalize_text(os.getenv("DASHBOARD_URL", ""))
    if configured:
        return configured.rstrip("/") + "/"

    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    if "/" not in repository:
        return ""
    owner, name = repository.split("/", 1)
    if name.casefold() == f"{owner}.github.io".casefold():
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{name}/"


def select_articles(
    matched: list[dict[str, Any]],
    *,
    max_critical: int,
    max_important: int,
    max_normal: int,
    max_unclassified: int,
    max_total: int,
) -> list[dict[str, Any]]:
    limits = {
        "critical": max_critical,
        "important": max_important,
        "normal": max_normal,
        "unclassified": max_unclassified,
        "unrelated": 0,
    }
    selected: list[dict[str, Any]] = []
    used = Counter()
    for article in sorted(
        matched,
        key=lambda item: (
            LEVEL_ORDER[article_level(item)],
            article_datetime_key(item),
            str(item.get("id") or ""),
        ),
        reverse=True,
    ):
        level = article_level(article)
        if used[level] >= limits[level]:
            continue
        selected.append(article)
        used[level] += 1
        if len(selected) >= max_total:
            break
    return selected


def build_digest(report_date: str | None = None) -> DigestResult:
    now = datetime.now(KST)
    day = report_date or os.getenv("REPORT_DATE", "").strip() or now.date().isoformat()
    try:
        parsed = datetime.strptime(day, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"REPORT_DATE 형식이 잘못되었습니다: {day}") from exc

    config = read_json(CONFIG_PATH, {})
    configured_keywords = os.getenv("TELEGRAM_KEYWORDS", "").strip()
    if configured_keywords:
        keywords = parse_keywords(configured_keywords)
    else:
        defaults = config.get("default_keywords", []) if isinstance(config, dict) else []
        keywords = [normalize_text(item) for item in defaults if normalize_text(item)]

    articles_path = DATA_DIR / parsed.strftime("%Y") / parsed.strftime("%m") / parsed.strftime("%d") / "articles.json"
    payload = read_json(articles_path, {})
    raw_articles = payload.get("articles", []) if isinstance(payload, dict) else []
    articles = [item for item in raw_articles if isinstance(item, dict)]

    matched: list[dict[str, Any]] = []
    for article in articles:
        hits = matched_keywords(article, keywords)
        if keywords and not hits:
            continue
        copied = dict(article)
        copied["_telegram_matched_keywords"] = hits
        matched.append(copied)

    counts = Counter(article_level(article) for article in matched)
    normalized_counts = {level: int(counts.get(level, 0)) for level in LEVEL_ORDER}

    selected = select_articles(
        matched,
        max_critical=safe_int_env("TELEGRAM_MAX_CRITICAL", 20),
        max_important=safe_int_env("TELEGRAM_MAX_IMPORTANT", 20),
        max_normal=safe_int_env("TELEGRAM_MAX_NORMAL", 5),
        max_unclassified=safe_int_env("TELEGRAM_MAX_UNCLASSIFIED", 3),
        max_total=safe_int_env("TELEGRAM_MAX_ARTICLES", 30, minimum=1),
    )

    return DigestResult(
        report_date=day,
        keywords=keywords,
        articles=articles,
        matched_articles=matched,
        selected_articles=selected,
        counts=normalized_counts,
        dashboard_url=derive_dashboard_url(),
    )


def escape(value: Any) -> str:
    return html.escape(normalize_text(value), quote=True)


def display_time(article: dict[str, Any]) -> str:
    raw = article_datetime_key(article)
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(KST)
        return parsed.strftime("%H:%M")
    except ValueError:
        match = re.search(r"(\d{1,2}):(\d{2})", raw)
        return match.group(0) if match else ""


def report_slot() -> str:
    explicit = normalize_text(os.getenv("TELEGRAM_REPORT_TITLE", ""))
    if explicit:
        return explicit
    now = datetime.now(KST)
    if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return "수동 브리핑"
    return "오전 브리핑" if now.hour < 12 else "오후 브리핑"


def header_block(result: DigestResult) -> str:
    counts = result.counts
    keyword_text = ", ".join(result.keywords) if result.keywords else "전체 보도자료"
    lines = [
        f"<b>정부 보도자료 AI·정보화 동향 · {escape(report_slot())}</b>",
        f"{escape(result.report_date)} · 키워드: {escape(keyword_text)}",
        "",
        (
            f"🔴 매우 중요 <b>{counts['critical']}</b> · "
            f"🟠 중요 <b>{counts['important']}</b> · "
            f"🔵 보통 <b>{counts['normal']}</b>"
        ),
        (
            f"⚪ 관계없음 <b>{counts['unrelated']}</b> · "
            f"◻️ 미분류 <b>{counts['unclassified']}</b> · "
            f"키워드 일치 <b>{len(result.matched_articles)}</b>건"
        ),
    ]
    if not result.articles:
        lines.extend(["", "오늘 날짜 폴더에 수집된 보도자료가 아직 없습니다."])
    elif not result.matched_articles:
        lines.extend(["", "현재 공유 키워드와 일치하는 보도자료가 없습니다."])
    return "\n".join(lines)


def article_block(index: int, article: dict[str, Any]) -> str:
    level = article_level(article)
    emoji, label = LEVEL_META[level]
    title = escape(truncate(article.get("title"), 170) or "제목 없음")
    ministry = escape(truncate(article.get("ministry") or "기관 미상", 60))
    time_text = display_time(article)
    meta = f"{ministry}{f' · {time_text}' if time_text else ''}"

    summary = truncate(article.get("summary"), 220)
    relevance = article.get("ip_relevance") if isinstance(article.get("ip_relevance"), dict) else {}
    reason = truncate(relevance.get("reason"), 180)
    matched = article.get("_telegram_matched_keywords", [])
    matched_text = ", ".join(str(item) for item in matched if item)
    url = normalize_text(article.get("original_url"))

    lines = [
        f"{emoji} <b>{index}. [{escape(label)}] {title}</b>",
        escape(meta),
    ]
    if summary:
        lines.append(escape(summary))
    if reason and level in {"critical", "important"}:
        lines.append(f"<i>판정:</i> {escape(reason)}")
    if matched_text:
        lines.append(f"<i>일치:</i> {escape(matched_text)}")
    if article.get("is_modified"):
        lines.append("<b>수정된 보도자료</b>")
    if url.startswith(("https://", "http://")):
        lines.append(f'<a href="{html.escape(url, quote=True)}">정책브리핑 원문 열기</a>')
    return "\n".join(lines)


def build_message_chunks(result: DigestResult) -> list[str]:
    chunks = [header_block(result)]
    if not result.selected_articles:
        return chunks

    omitted = len(result.matched_articles) - len(result.selected_articles)
    blocks = [article_block(index, article) for index, article in enumerate(result.selected_articles, 1)]
    if omitted > 0:
        blocks.append(f"그 밖의 키워드 일치 자료 {omitted}건은 대시보드에서 확인할 수 있습니다.")

    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= MAX_TELEGRAM_TEXT:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = block
        if len(current) > MAX_TELEGRAM_TEXT:
            current = current[: MAX_TELEGRAM_TEXT - 1].rstrip() + "…"
    if current:
        chunks.append(current)
    return chunks


def parse_chat_ids(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n,;]+", raw or "") if item.strip()]


def send_message(
    session: requests.Session,
    token: str,
    chat_id: str,
    text: str,
    *,
    dashboard_url: str = "",
    include_button: bool = False,
) -> None:
    endpoint = f"{TELEGRAM_API_ROOT}/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    if include_button and dashboard_url.startswith(("https://", "http://")):
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "대시보드 열기", "url": dashboard_url}]]
        }

    for attempt in range(1, 4):
        response = session.post(endpoint, json=payload, timeout=(10, 30))
        if response.ok:
            return
        retry_after = 0
        try:
            body = response.json()
            retry_after = int(body.get("parameters", {}).get("retry_after") or 0)
            description = normalize_text(body.get("description") or response.text)
        except (ValueError, TypeError):
            description = truncate(response.text, 300)
        if response.status_code == 429 and retry_after > 0 and attempt < 3:
            time.sleep(min(retry_after + 1, 30))
            continue
        if response.status_code >= 500 and attempt < 3:
            time.sleep(2**attempt)
            continue
        raise RuntimeError(
            f"Telegram sendMessage 실패: HTTP {response.status_code} - {description}"
        )
    raise RuntimeError("Telegram sendMessage 재시도 횟수를 초과했습니다.")


def append_step_summary(result: DigestResult, chunks: int, recipients: int) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n### 텔레그램 브리핑 발송\n")
        handle.write(f"- 기준일: `{result.report_date}`\n")
        handle.write(f"- 키워드 일치: `{len(result.matched_articles)}건`\n")
        handle.write(f"- 상세 포함: `{len(result.selected_articles)}건`\n")
        handle.write(f"- 수신 대상: `{recipients}`\n")
        handle.write(f"- 메시지 묶음: `{chunks}`\n")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="대시보드 당일 현황을 Telegram Bot으로 발송합니다.")
    parser.add_argument("--date", help="발송 기준일 YYYY-MM-DD (기본: 한국시간 오늘)")
    parser.add_argument("--preview", action="store_true", help="Telegram으로 보내지 않고 메시지만 출력")
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = build_digest(args.date)
    chunks = build_message_chunks(result)

    if args.preview:
        for index, chunk in enumerate(chunks, 1):
            print(f"--- message {index}/{len(chunks)} ---")
            print(chunk)
        return 0

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = parse_chat_ids(os.getenv("TELEGRAM_CHAT_ID", ""))
    if not token or not chat_ids:
        print(
            "Warning: TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 없어 텔레그램 발송을 생략합니다.",
            file=sys.stderr,
        )
        return 0

    session = requests.Session()
    for chat_id in chat_ids:
        for index, chunk in enumerate(chunks):
            send_message(
                session,
                token,
                chat_id,
                chunk,
                dashboard_url=result.dashboard_url,
                include_button=index == len(chunks) - 1,
            )
            if index < len(chunks) - 1:
                time.sleep(0.4)

    append_step_summary(result, len(chunks), len(chat_ids))
    print(
        f"텔레그램 발송 완료: {result.report_date}, "
        f"키워드 일치 {len(result.matched_articles)}건, "
        f"상세 {len(result.selected_articles)}건, "
        f"수신 대상 {len(chat_ids)}개, 메시지 {len(chunks)}개"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
