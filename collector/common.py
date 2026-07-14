from __future__ import annotations

import hashlib
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
    "a": ["href", "title"],
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


def collapse_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


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


def sanitize_body_html(raw_html: str, base_url: str) -> tuple[str, str]:
    """이미지·스크립트·임베드 요소를 제거하고 안전한 텍스트 중심 HTML을 반환한다."""
    soup = BeautifulSoup(raw_html or "", "html.parser")

    for node in soup.find_all(REMOVE_TAGS):
        node.decompose()

    for link in soup.find_all("a"):
        href = collapse_whitespace(link.get("href"))
        if href:
            link["href"] = urljoin(base_url, href)
        else:
            link.unwrap()

    cleaned = bleach.clean(
        str(soup),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=["http", "https"],
        strip=True,
        strip_comments=True,
    )

    safe_soup = BeautifulSoup(cleaned, "html.parser")
    for link in safe_soup.find_all("a"):
        link["target"] = "_blank"
        link["rel"] = "noopener noreferrer"

    safe_html = str(safe_soup).strip()
    plain_text = collapse_whitespace(safe_soup.get_text(" ", strip=True))
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
