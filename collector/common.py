from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import bleach
from bs4 import BeautifulSoup

SEOUL = ZoneInfo("Asia/Seoul")

ALLOWED_TAGS = [
    "p",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "blockquote",
    "pre",
    "code",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "a",
    "hr",
    "div",
    "span",
]

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}

REMOVE_TAGS = [
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "img",
    "picture",
    "source",
    "video",
    "audio",
    "svg",
    "canvas",
    "form",
    "input",
    "button",
    "noscript",
]


def now_iso() -> str:
    return datetime.now(SEOUL).replace(microsecond=0).isoformat()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def decode_html_entities(value: str | None, max_passes: int = 5) -> str:
    """HTML 엔터티를 최대 ``max_passes``회까지 반복 해제한다.

    정책브리핑 HTML과 JSON-LD에는 ``&amp;#039;``처럼 한 번 이상
    중첩 인코딩된 값이 포함될 수 있다. ``html.unescape``를 한 번만
    적용하면 ``&#039;``가 남으므로, 값이 더 이상 변하지 않을 때까지
    제한적으로 반복한다.
    """

    current = str(value or "")
    for _ in range(max(1, max_passes)):
        decoded = html_lib.unescape(current)
        if decoded == current:
            break
        current = decoded

    # 레이아웃을 깨뜨릴 수 있는 비가시 문자와 NBSP를 일반화한다.
    return (
        current.replace("\u00a0", " ")
        .replace("\u00ad", "")
        .replace("\u200b", "")
        .replace("\ufeff", "")
    )


def collapse_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_plain_text(value: str | None) -> str:
    return collapse_whitespace(decode_html_entities(value))


def truncate(value: str, max_chars: int = 220) -> str:
    value = collapse_whitespace(value)
    if len(value) <= max_chars:
        return value
    cut = value[: max_chars + 1]
    last_space = cut.rfind(" ")
    if last_space >= int(max_chars * 0.65):
        cut = cut[:last_space]
    else:
        cut = cut[:max_chars]
    return f"{cut.rstrip()}…"


def _decode_soup_text_nodes(soup: BeautifulSoup) -> None:
    """태그 구조는 유지하면서 텍스트 노드의 중첩 엔터티만 해제한다."""

    for node in list(soup.find_all(string=True)):
        parent_name = getattr(node.parent, "name", "")
        if parent_name in {"script", "style"}:
            continue
        original = str(node)
        decoded = decode_html_entities(original)
        if decoded != original:
            # replace_with에 문자열을 넘기면 '<'와 '>'도 텍스트로 유지되어
            # 엔터티 해제가 새 HTML 태그 생성으로 이어지지 않는다.
            node.replace_with(decoded)


def sanitize_body_html(raw_html: str, base_url: str) -> tuple[str, str]:
    """이미지·스크립트·임베드 요소를 제거하고 안전한 텍스트 중심 HTML을 반환한다."""
    soup = BeautifulSoup(raw_html or "", "html.parser")

    for node in soup.find_all(REMOVE_TAGS):
        node.decompose()

    _decode_soup_text_nodes(soup)

    for link in soup.find_all("a"):
        href = normalize_plain_text(link.get("href"))
        if href:
            link["href"] = urljoin(base_url, href)
            link["target"] = "_blank"
            link["rel"] = "noopener noreferrer"
        else:
            link.unwrap()
            continue

        if link.get("title"):
            link["title"] = normalize_plain_text(link.get("title"))

    cleaned = bleach.clean(
        str(soup),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=["http", "https"],
        strip=True,
        strip_comments=True,
    )

    safe_soup = BeautifulSoup(cleaned, "html.parser")
    _decode_soup_text_nodes(safe_soup)
    for link in safe_soup.find_all("a"):
        link["target"] = "_blank"
        link["rel"] = "noopener noreferrer"

    safe_html = str(safe_soup).strip()
    plain_text = normalize_plain_text(safe_soup.get_text(" ", strip=True))
    return safe_html, plain_text


def content_hash(*parts: str) -> str:
    source = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(source).hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp_path, path)


def max_iso(values: Iterable[str | None]) -> str | None:
    filtered = [value for value in values if value]
    return max(filtered) if filtered else None
