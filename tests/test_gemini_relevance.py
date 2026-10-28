from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from collector.classify_relevance import PendingArticle, article_source_hash, load_policy
from collector.classify_relevance_gemini import (
    call_gemini,
    finalize_gemini_record,
    gemini_classification_is_current,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: tuple[int, int],
    ) -> FakeResponse:
        self.calls.append(
            {
                "endpoint": endpoint,
                "headers": dict(headers),
                "json": copy.deepcopy(json),
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError("준비된 모의 응답이 없습니다.")
        return self.responses.pop(0)


class GeminiRelevanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy(Path("collector/relevance_policy.json"))

    def pending(self) -> PendingArticle:
        article = {
            "id": "test-1",
            "title": "전 부처 생성형 AI 기준 시행",
            "summary": "행정기관 공통 기준을 시행한다.",
            "content_text": "전 부처가 적용받는 생성형 AI 안전 기준을 시행한다.",
            "ministry": "행정안전부",
        }
        return PendingArticle(
            path=Path("docs/data/2026/07/30/articles.json"),
            article=article,
            source_hash="source-hash",
            rule_result={
                "level": "important",
                "confidence": 0.8,
                "reason": "규칙 판정",
                "signals": ["생성형 AI"],
            },
            needs_model=True,
        )

    def successful_response(self) -> FakeResponse:
        content = {
            "results": [
                {
                    "id": "test-1",
                    "level": "critical",
                    "confidence": 0.96,
                    "reason": "전 부처 공통 기준으로 즉시 검토가 필요합니다.",
                    "signals": ["생성형 AI", "전 부처"],
                }
            ]
        }
        return FakeResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(content, ensure_ascii=False)
                        }
                    }
                ]
            },
        )

    def test_gemini_chat_completion_is_mapped(self) -> None:
        session = FakeSession([self.successful_response()])

        result = call_gemini(
            [self.pending()],
            policy=self.policy,
            endpoint="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            model="gemini-3.1-flash-lite",
            token="test-key",
            session=session,  # type: ignore[arg-type]
        )

        self.assertEqual(result["test-1"]["level"], "critical")
        self.assertEqual(
            session.calls[0]["headers"]["Authorization"],
            "Bearer test-key",
        )
        self.assertEqual(
            session.calls[0]["json"]["model"],
            "gemini-3.1-flash-lite",
        )
        self.assertEqual(
            session.calls[0]["json"]["response_format"]["type"],
            "json_schema",
        )

    def test_json_schema_error_retries_as_json_object(self) -> None:
        session = FakeSession(
            [
                FakeResponse(400, {"error": {"message": "schema unsupported"}}),
                self.successful_response(),
            ]
        )

        result = call_gemini(
            [self.pending()],
            policy=self.policy,
            endpoint="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            model="gemini-3.1-flash-lite",
            token="test-key",
            session=session,  # type: ignore[arg-type]
        )

        self.assertEqual(result["test-1"]["level"], "critical")
        self.assertEqual(session.calls[0]["json"]["response_format"]["type"], "json_schema")
        self.assertEqual(session.calls[1]["json"]["response_format"]["type"], "json_object")

    def test_transient_503_is_retried(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    503,
                    {"error": {"message": "high demand"}},
                    headers={"Retry-After": "1"},
                ),
                self.successful_response(),
            ]
        )

        with patch("collector.classify_relevance_gemini.time.sleep") as sleep:
            result = call_gemini(
                [self.pending()],
                policy=self.policy,
                endpoint="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                model="gemini-3.1-flash-lite",
                token="test-key",
                session=session,  # type: ignore[arg-type]
            )

        self.assertEqual(result["test-1"]["level"], "critical")
        self.assertEqual(len(session.calls), 2)
        sleep.assert_called_once_with(1.0)

    def test_gemini_record_preserves_provider_and_model(self) -> None:
        record = finalize_gemini_record(
            {
                "level": "important",
                "confidence": 0.9,
                "reason": "정책 영향이 있습니다.",
                "signals": ["AI"],
            },
            source_hash="source-hash",
            policy=self.policy,
            model="gemini-3.1-flash-lite",
            method="gemini-api",
        )

        self.assertEqual(record["method"], "gemini-api")
        self.assertEqual(record["model"], "google/gemini-3.1-flash-lite")
        self.assertEqual(record["prompt_version"], "ip-office-relevance-v1.0")

    def test_legacy_github_models_result_is_preserved(self) -> None:
        article: dict[str, Any] = {
            "id": "legacy-1",
            "title": "AI 기본법 개정",
            "summary": "전 부처 기준",
            "content_text": "전 부처에 적용되는 기준을 개정한다.",
            "ministry": "과학기술정보통신부",
        }
        article["ip_relevance"] = {
            "level": "critical",
            "method": "github-models",
            "model": "openai/gpt-4.1-mini",
            "prompt_version": "ip-office-relevance-v1.0",
            "source_hash": article_source_hash(article),
        }

        self.assertTrue(
            gemini_classification_is_current(
                article,
                self.policy,
                "google/gemini-3.1-flash-lite",
                True,
            )
        )

    def test_gemini_model_change_invalidates_gemini_cache(self) -> None:
        article: dict[str, Any] = {
            "id": "gemini-1",
            "title": "AI 공통기준",
            "summary": "공통기준",
            "content_text": "행정기관 공통기준을 시행한다.",
            "ministry": "행정안전부",
        }
        article["ip_relevance"] = {
            "level": "important",
            "method": "gemini-api",
            "model": "google/gemini-3.1-flash-lite",
            "prompt_version": "ip-office-relevance-v1.0",
            "source_hash": article_source_hash(article),
        }

        self.assertTrue(
            gemini_classification_is_current(
                article,
                self.policy,
                "google/gemini-3.1-flash-lite",
                True,
            )
        )
        self.assertFalse(
            gemini_classification_is_current(
                article,
                self.policy,
                "google/gemini-3.5-flash-lite",
                True,
            )
        )


if __name__ == "__main__":
    unittest.main()
