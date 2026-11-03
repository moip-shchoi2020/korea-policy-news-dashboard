"""대한민국 정책브리핑 보도자료 수집기.

대시보드와 Telegram은 ``docs/data/config.json``의 기본 키워드와
``keyword_aliases``를 공통으로 사용한다. Telegram 실행 시에는 대표 키워드를
유사어까지 확장하고, 대시보드와 동일하게 키워드 일치를 필수 조건으로 둔다.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "docs" / "data" / "config.json"


def _normalize_keyword(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_keyword_list(value: str | Iterable[Any]) -> list[str]:
    if isinstance(value, str):
        values: Iterable[Any] = re.split(r"[\n,;]+", value)
    else:
        values = value

    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        keyword = _normalize_keyword(raw)
        key = keyword.casefold()
        if keyword and key not in seen:
            seen.add(key)
            result.append(keyword)
    return result


def expand_keyword_aliases(
    keywords: Iterable[Any],
    alias_groups: dict[str, Any] | None,
) -> list[str]:
    groups: list[list[str]] = []
    if isinstance(alias_groups, dict):
        for canonical, aliases in alias_groups.items():
            raw_aliases = aliases if isinstance(aliases, list) else []
            group = parse_keyword_list([canonical, *raw_aliases])
            if group:
                groups.append(group)

    expanded: list[str] = []
    seen: set[str] = set()
    for raw_keyword in keywords:
        keyword = _normalize_keyword(raw_keyword)
        if not keyword:
            continue
        lookup = keyword.casefold()
        matched_group = next(
            (
                group
                for group in groups
                if any(item.casefold() == lookup for item in group)
            ),
            [keyword],
        )
        for item in matched_group:
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            expanded.append(item)
    return expanded


def load_keyword_config(path: Path = _DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def configure_telegram_keyword_environment(
    config_path: Path = _DEFAULT_CONFIG_PATH,
) -> list[str]:
    """Telegram CLI가 대시보드와 같은 키워드 판정 조건을 사용하게 한다."""

    config = load_keyword_config(config_path)
    configured = os.getenv("TELEGRAM_KEYWORDS", "").strip()
    base_keywords = (
        parse_keyword_list(configured)
        if configured
        else parse_keyword_list(config.get("default_keywords", []))
    )

    expansion_enabled = os.getenv("TELEGRAM_EXPAND_KEYWORDS", "true").strip().casefold()
    if expansion_enabled in {"0", "false", "no", "off"}:
        expanded = base_keywords
    else:
        expanded = expand_keyword_aliases(base_keywords, config.get("keyword_aliases"))

    if base_keywords:
        os.environ["TELEGRAM_DISPLAY_KEYWORDS"] = ",".join(base_keywords)
    if expanded:
        os.environ["TELEGRAM_KEYWORDS"] = ",".join(expanded)

    # 명시적으로 false를 지정한 경우에만 키워드 게이트를 해제할 수 있다.
    os.environ.setdefault("TELEGRAM_REQUIRE_KEYWORD_MATCH", "true")
    return expanded


# ``python -m collector.send_telegram`` 실행 전에 패키지 초기화가 먼저 수행된다.
# 다른 수집·분류 모듈에서는 아래 환경변수를 참조하지 않으므로 부작용이 없다.
configure_telegram_keyword_environment()
