from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from collector.common import collapse_whitespace, max_iso, read_json, write_json


def compact_article(article: dict[str, Any], include_search_text: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": str(article.get("id", "")),
        "title": article.get("title", ""),
        "summary": article.get("summary", ""),
        "summary_source": article.get("summary_source", ""),
        "ministry": article.get("ministry", "기관 미상"),
        "approved_at": article.get("approved_at"),
        "modified_at": article.get("modified_at"),
        "publish_date": article.get("publish_date"),
        "contents_status": article.get("contents_status", "I"),
        "modify_id": int(article.get("modify_id") or 0),
        "is_modified": bool(article.get("is_modified")),
        "original_url": article.get("original_url", ""),
    }
    if include_search_text:
        result["search_text"] = collapse_whitespace(
            " ".join(
                [
                    str(article.get("title", "")),
                    str(article.get("summary", "")),
                    str(article.get("ministry", "")),
                    str(article.get("content_text", "")),
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
    total_articles = 0
    total_modified = 0

    for articles_path in sorted(data_dir.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/articles.json")):
        payload = read_json(articles_path, {})
        day = str(payload.get("date") or "")
        articles = payload.get("articles", [])
        if not day or not isinstance(articles, list):
            continue

        compact = [compact_article(article) for article in articles]
        day_generated_at = max_iso(article.get("collected_at") for article in articles)
        day_index = {
            "schema_version": 1,
            "date": day,
            "generated_at": day_generated_at,
            "article_count": len(compact),
            "modified_count": sum(bool(article.get("is_modified")) for article in compact),
            "articles": compact,
        }
        write_json(articles_path.parent / "index.json", day_index)

        month_key = day[:7]
        for article in articles:
            item = compact_article(article, include_search_text=True)
            item["date"] = day
            month_articles[month_key].append(item)
            all_collected_at.append(article.get("collected_at"))

        all_dates.append(day)
        total_articles += len(articles)
        total_modified += sum(bool(article.get("is_modified")) for article in articles)

    for month_key, articles in month_articles.items():
        year, month = month_key.split("-")
        articles.sort(
            key=lambda item: (item.get("approved_at") or "", item.get("id") or ""),
            reverse=True,
        )
        month_payload = {
            "schema_version": 1,
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
            "articles": articles,
        }
        write_json(data_dir / year / month / "index.json", month_payload)

    manifest = {
        "schema_version": 1,
        "last_updated": max_iso(all_collected_at),
        "available_months": sorted(month_articles.keys(), reverse=True),
        "first_date": min(all_dates) if all_dates else None,
        "last_date": max(all_dates) if all_dates else None,
        "article_count": total_articles,
        "modified_count": total_modified,
    }
    write_json(data_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="날짜별 보도자료 파일에서 대시보드 색인을 생성합니다.")
    parser.add_argument("--data-dir", default="docs/data")
    args = parser.parse_args()
    manifest = build_indexes(Path(args.data_dir))
    print(
        f"색인 완료: {manifest['article_count']}건, "
        f"가용 월 {len(manifest['available_months'])}개"
    )


if __name__ == "__main__":
    main()
