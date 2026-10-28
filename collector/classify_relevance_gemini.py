from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import requests

from collector.classify_relevance import (
    DEFAULT_POLICY_PATH,
    LEVEL_LABELS,
    PendingArticle,
    VALID_LEVELS,
    article_excerpt,
    article_source_hash,
    build_system_prompt,
    chunks,
    classification_is_current,
    finalize_record,
    iter_article_files,
    load_policy,
    parse_model_content,
    response_schema,
    rule_classify,
    save_records,
)
from collector.common import read_json

DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DEFAULT_MODEL = "gemini-3.1-flash-lite"
LEGACY_CACHE_MODEL = "openai/gpt-4.1-mini"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="저장된 보도자료를 2026-07-29 기준으로 Gemini API를 이용해 분류합니다."
    )
    parser.add_argument("--data-dir", default="docs/data")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--endpoint", default=os.getenv("GEMINI_API_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--max-articles", type=int, default=300)
    parser.add_argument("--request-delay", type=float, default=4.1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--rules-only", action="store_true")
    parser.add_argument(
        "--require-ai",
        action="store_true",
        help="GEMINI_API_KEY가 없거나 모델 호출에 실패하면 종료코드 1을 반환합니다.",
    )
    return parser.parse_args()


def call_gemini(
    batch: list[PendingArticle],
    *,
    policy: dict[str, Any],
    endpoint: str,
    model: str,
    token: str,
    session: requests.Session,
) -> dict[str, dict[str, Any]]:
    article_payload = [
        {
            "id": str(item.article.get("id", "")),
            "ministry": str(item.article.get("ministry", "기관 미상")),
            "rule_hint": item.rule_result.get("level"),
            "document": article_excerpt(item.article),
        }
        for item in batch
    ]
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": build_system_prompt(policy)},
            {
                "role": "user",
                "content": (
                    "다음 보도자료를 각각 판정하십시오. 반환 형식은 "
                    '{"results":[{"id":"문서 ID","level":"critical|important|normal|unrelated",'
                    '"confidence":0.0,"reason":"근거","signals":["신호"]}]} 입니다.\n'
                    + json.dumps(article_payload, ensure_ascii=False)
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 1800,
        "response_format": response_schema(),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.post(endpoint, headers=headers, json=body, timeout=(10, 90))
            if response.status_code == 429 and attempt < 2:
                retry_after = float(response.headers.get("Retry-After", "8"))
                time.sleep(max(retry_after, 4.0))
                continue
            if (
                response.status_code in {400, 422}
                and body.get("response_format", {}).get("type") == "json_schema"
            ):
                # 계정·모델 조합에서 JSON Schema가 허용되지 않으면 JSON object 모드로 재시도한다.
                body["response_format"] = {"type": "json_object"}
                continue
            if response.status_code >= 400:
                preview = " ".join(response.text.split())[:500]
                raise RuntimeError(f"Gemini API HTTP {response.status_code}: {preview}")

            parsed = parse_model_content(response.json())
            results = parsed.get("results")
            if not isinstance(results, list):
                raise RuntimeError("AI JSON 응답에 results 배열이 없습니다.")

            mapped: dict[str, dict[str, Any]] = {}
            for result in results:
                if not isinstance(result, dict):
                    continue
                article_id = str(result.get("id", ""))
                level = str(result.get("level", ""))
                if article_id and level in VALID_LEVELS:
                    mapped[article_id] = result
            return mapped
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(3 * (attempt + 1))

    raise RuntimeError(str(last_error or "Gemini API 요청 실패"))


def finalize_gemini_record(
    base: dict[str, Any],
    *,
    source_hash: str,
    policy: dict[str, Any],
    model: str,
    method: str,
) -> dict[str, Any]:
    provider_model = f"google/{model}"
    record = finalize_record(
        base,
        source_hash=source_hash,
        policy=policy,
        model=provider_model,
        method=method,
    )
    if method == "gemini-api":
        record["model"] = provider_model
    return record


def gemini_classification_is_current(
    article: dict[str, Any],
    policy: dict[str, Any],
    model: str,
    token_available: bool,
) -> bool:
    """기존 정상 판정을 보존하면서 Gemini 판정의 모델 변경은 감지합니다."""

    current = article.get("ip_relevance")
    if not isinstance(current, dict):
        return False
    method = str(current.get("method") or "")

    # 2026-07-29까지의 정상 GitHub Models 판정은 공급자 교체와 무관하게 보존한다.
    compatibility_model = LEGACY_CACHE_MODEL if method == "github-models" else model
    if not classification_is_current(article, policy, compatibility_model, token_available):
        return False

    # Gemini로 생성한 결과는 현재 설정 모델과 같을 때만 재사용한다.
    if method == "gemini-api":
        return current.get("model") == model
    return True


def collect_pending_gemini(
    data_dir: Path,
    policy: dict[str, Any],
    model: str,
    token_available: bool,
    force: bool,
    max_articles: int,
) -> tuple[list[PendingArticle], Counter[str]]:
    pending: list[PendingArticle] = []
    stats: Counter[str] = Counter()
    for path in iter_article_files(data_dir):
        payload = read_json(path, {})
        articles = payload.get("articles")
        if not isinstance(articles, list):
            continue
        for article in articles:
            if not isinstance(article, dict):
                continue
            stats["scanned"] += 1
            if not force and gemini_classification_is_current(
                article, policy, model, token_available
            ):
                stats["cached"] += 1
                continue
            rule_result, needs_model = rule_classify(article, policy)
            pending.append(
                PendingArticle(
                    path=path,
                    article=article,
                    source_hash=article_source_hash(article),
                    rule_result=rule_result,
                    needs_model=needs_model,
                )
            )
            if len(pending) >= max_articles:
                stats["limited"] += 1
                return pending, stats
    return pending, stats


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir)
    policy = load_policy(Path(args.policy))
    token = os.getenv("GEMINI_API_KEY", "").strip()
    token_available = bool(token) and not args.rules_only
    provider_model = f"google/{args.model}"

    print(f"지식재산처 연관도 분석 기준: {policy['prompt_version']}", flush=True)
    print(f"AI 모델: {provider_model}", flush=True)
    print(
        "분석 방식: "
        + ("Gemini API + 2026-07-29 규칙 사전판정" if token_available else "규칙 기반 대체"),
        flush=True,
    )
    if not token_available and not args.rules_only:
        print(
            "::warning title=AI 키 미등록::GEMINI_API_KEY가 없어 모델 검토 대상은 "
            "rules-fallback으로 저장됩니다.",
            file=sys.stderr,
            flush=True,
        )
        if args.require_ai:
            return 1

    pending, scan_stats = collect_pending_gemini(
        data_dir,
        policy,
        provider_model,
        token_available,
        args.force,
        max(1, args.max_articles),
    )
    print(
        f"검사 {scan_stats['scanned']}건 / 캐시 재사용 {scan_stats['cached']}건 / "
        f"이번 분석 대상 {len(pending)}건",
        flush=True,
    )
    if not pending:
        print("새로 판정할 보도자료가 없습니다.", flush=True)
        return 0

    records: list[tuple[PendingArticle, dict[str, Any]]] = []
    model_candidates: list[PendingArticle] = []
    for item in pending:
        if item.needs_model and token_available:
            model_candidates.append(item)
        else:
            fallback_method = (
                "rules-fallback" if item.needs_model and not token_available else "rules"
            )
            records.append(
                (
                    item,
                    finalize_gemini_record(
                        item.rule_result,
                        source_hash=item.source_hash,
                        policy=policy,
                        model=args.model,
                        method=fallback_method,
                    ),
                )
            )

    ai_failed = False
    if model_candidates:
        session = requests.Session()
        batches = list(chunks(model_candidates, max(1, args.batch_size)))
        for batch_index, batch in enumerate(batches, start=1):
            ids = [str(item.article.get("id", "")) for item in batch]
            print(
                f"AI 분석 {batch_index}/{len(batches)}: {len(batch)}건 ({', '.join(ids)})",
                flush=True,
            )
            try:
                model_results = call_gemini(
                    batch,
                    policy=policy,
                    endpoint=args.endpoint,
                    model=args.model,
                    token=token,
                    session=session,
                )
            except Exception as exc:  # 모델 장애가 전체 수집·배포를 막지 않게 한다.
                ai_failed = True
                print(
                    f"::warning title=AI 판정 대체::{exc}. 이 묶음은 규칙 판정으로 저장합니다.",
                    file=sys.stderr,
                    flush=True,
                )
                model_results = {}

            for item in batch:
                article_id = str(item.article.get("id", ""))
                model_record = model_results.get(article_id)
                if model_record is None:
                    base_record = dict(item.rule_result)
                    method = "rules-fallback"
                    ai_failed = True
                else:
                    base_record = model_record
                    method = "gemini-api"
                records.append(
                    (
                        item,
                        finalize_gemini_record(
                            base_record,
                            source_hash=item.source_hash,
                            policy=policy,
                            model=args.model,
                            method=method,
                        ),
                    )
                )
            if batch_index < len(batches):
                time.sleep(max(0.0, args.request_delay))

    counts = save_records(records)
    labels = [
        f"{LEVEL_LABELS[level]} {counts[level]}건"
        for level in ("critical", "important", "normal", "unrelated")
    ]
    fallback_count = sum(
        1 for _, record in records if record.get("method") == "rules-fallback"
    )
    ai_count = sum(1 for _, record in records if record.get("method") == "gemini-api")
    rule_count = len(records) - ai_count - fallback_count
    print(
        "연관도 분석 완료: "
        + " / ".join(labels)
        + f" · AI {ai_count}건 · 규칙 {rule_count}건 · AI 실패 대체 {fallback_count}건",
        flush=True,
    )
    if scan_stats["limited"]:
        print(
            f"::warning title=분석 건수 제한::한 번에 {args.max_articles}건까지만 처리했습니다. "
            "다음 실행에서 남은 자료를 이어서 분석합니다.",
            file=sys.stderr,
        )
    if args.require_ai and ai_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
