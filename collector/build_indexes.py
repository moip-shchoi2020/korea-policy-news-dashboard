from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from collector.common import (
    max_iso,
    normalize_plain_text,
    read_json,
    write_json,
)

RELEVANCE_LEVELS = ("critical", "important", "normal", "unrelated", "unclassified")
RELEVANCE_LABELS = {
    "critical": "매우 중요",
    "important": "중요",
    "normal": "보통",
    "unrelated": "관계없음",
    "unclassified": "미분류",
}
RELEVANCE_SCORES = {
    "critical": 4,
    "important": 3,
    "normal": 2,
    "unrelated": 1,
    "unclassified": 0,
}
RELEVANCE_ACTIONS = {
    "critical": "즉시 검토",
    "important": "동향 추적",
    "normal": "참고",
    "unrelated": "제외",
    "unclassified": "검토 필요",
}


def _normalize_url(value: Any) -> str:
    return normalize_plain_text(str(value or ""))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_relevance(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    level = str(raw.get("level") or "unclassified")
    if level not in RELEVANCE_LEVELS:
        level = "unclassified"
    signals = raw.get("signals") if isinstance(raw.get("signals"), list) else []
    method = normalize_plain_text(str(raw.get("method") or "unclassified"))
    confidence = round(max(0.0, min(1.0, _safe_float(raw.get("confidence")))), 2)
    return {
        "level": level,
        "label": normalize_plain_text(str(raw.get("label") or RELEVANCE_LABELS[level])),
        "score": int(raw.get("score") or RELEVANCE_SCORES[level]),
        "confidence": confidence,
        "reason": normalize_plain_text(str(raw.get("reason") or "")),
        "signals": [
            normalize_plain_text(str(item))
            for item in signals
            if normalize_plain_text(str(item))
        ][:5],
        "recommended_action": normalize_plain_text(
            str(raw.get("recommended_action") or RELEVANCE_ACTIONS[level])
        ),
        "method": method,
        "model": normalize_plain_text(str(raw.get("model") or "")) or None,
        "prompt_version": normalize_plain_text(str(raw.get("prompt_version") or "")) or None,
        "classified_at": raw.get("classified_at"),
    }


def relevance_counts(articles: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        normalize_relevance(article.get("ip_relevance"))["level"]
        for article in articles
    )
    return {level: int(counts.get(level, 0)) for level in RELEVANCE_LEVELS}


def compact_article(article: dict[str, Any], include_search_text: bool = False) -> dict[str, Any]:
    title = normalize_plain_text(str(article.get("title", "")))
    summary = normalize_plain_text(str(article.get("summary", "")))
    ministry = normalize_plain_text(str(article.get("ministry", "기관 미상"))) or "기관 미상"

    result: dict[str, Any] = {
        "id": str(article.get("id", "")),
        "title": title,
        "summary": summary,
        "summary_source": article.get("summary_source", ""),
        "ministry": ministry,
        "approved_at": article.get("approved_at"),
        "modified_at": article.get("modified_at"),
        "publish_date": article.get("publish_date"),
        "contents_status": article.get("contents_status", "I"),
        "modify_id": int(article.get("modify_id") or 0),
        "is_modified": bool(article.get("is_modified")),
        "original_url": _normalize_url(article.get("original_url", "")),
        "ip_relevance": normalize_relevance(article.get("ip_relevance")),
    }
    if include_search_text:
        result["search_text"] = normalize_plain_text(
            " ".join(
                [
                    title,
                    summary,
                    ministry,
                    normalize_plain_text(str(article.get("content_text", ""))),
                ]
            )
        )
    return result


def build_indexes(data_dir: Path | str = Path("docs/data")) -> dict[str, Any]:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    month_articles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_dates: list[str] = []
    all_collected_at: list[str | None] = []
    all_raw_articles: list[dict[str, Any]] = []
    total_articles = 0
    total_modified = 0
    prompt_versions: Counter[str] = Counter()

    for articles_path in sorted(
        data_dir.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/articles.json")
    ):
        payload = read_json(articles_path, {})
        day = str(payload.get("date") or "")
        articles = payload.get("articles", [])
        if not day or not isinstance(articles, list):
            continue

        valid_articles = [article for article in articles if isinstance(article, dict)]
        compact = [compact_article(article) for article in valid_articles]
        day_generated_at = max_iso(article.get("collected_at") for article in valid_articles)
        day_counts = relevance_counts(valid_articles)
        day_index = {
            "schema_version": 2,
            "date": day,
            "generated_at": day_generated_at,
            "article_count": len(compact),
            "modified_count": sum(bool(article.get("is_modified")) for article in compact),
            "relevance_counts": day_counts,
            "classified_count": len(compact) - day_counts["unclassified"],
            "articles": compact,
        }
        write_json(articles_path.parent / "index.json", day_index)

        month_key = day[:7]
        for article in valid_articles:
            item = compact_article(article, include_search_text=True)
            item["date"] = day
            month_articles[month_key].append(item)
            all_collected_at.append(article.get("collected_at"))
            all_raw_articles.append(article)
            version = str(item["ip_relevance"].get("prompt_version") or "")
            if version:
                prompt_versions[version] += 1

        all_dates.append(day)
        total_articles += len(valid_articles)
        total_modified += sum(bool(article.get("is_modified")) for article in valid_articles)

    for month_key, articles in month_articles.items():
        year, month = month_key.split("-")
        articles.sort(
            key=lambda item: (
                int(item.get("ip_relevance", {}).get("score") or 0),
                item.get("approved_at") or "",
                item.get("id") or "",
            ),
            reverse=True,
        )
        month_counts = relevance_counts(articles)
        month_payload = {
            "schema_version": 2,
            "month": month_key,
            "generated_at": max_iso(
                read_json(
                    data_dir / year / month / str(day).zfill(2) / "articles.json",
                    {},
                ).get("generated_at")
                for day in range(1, 32)
            ),
            "article_count": len(articles),
            "modified_count": sum(bool(article.get("is_modified")) for article in articles),
            "relevance_counts": month_counts,
            "classified_count": len(articles) - month_counts["unclassified"],
            "articles": articles,
        }
        write_json(data_dir / year / month / "index.json", month_payload)

    total_counts = relevance_counts(all_raw_articles)
    manifest = {
        "schema_version": 2,
        "last_updated": max_iso(all_collected_at),
        "available_months": sorted(month_articles.keys(), reverse=True),
        "first_date": min(all_dates) if all_dates else None,
        "last_date": max(all_dates) if all_dates else None,
        "article_count": total_articles,
        "modified_count": total_modified,
        "relevance_counts": total_counts,
        "classified_count": total_articles - total_counts["unclassified"],
        "unclassified_count": total_counts["unclassified"],
        "classification_prompt_version": prompt_versions.most_common(1)[0][0]
        if prompt_versions
        else None,
    }
    write_json(data_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="날짜별 보도자료 파일에서 대시보드 색인을 생성합니다.")
    parser.add_argument("--data-dir", default="docs/data")
    args = parser.parse_args()
    manifest = build_indexes(Path(args.data_dir))
    counts = manifest.get("relevance_counts", {})
    print(
        f"색인 완료: {manifest['article_count']}건, "
        f"가용 월 {len(manifest['available_months'])}개 · "
        f"매우 중요 {counts.get('critical', 0)} / 중요 {counts.get('important', 0)} / "
        f"보통 {counts.get('normal', 0)} / 관계없음 {counts.get('unrelated', 0)} / "
        f"미분류 {counts.get('unclassified', 0)}"
    )


if __name__ == "__main__":
    main()
