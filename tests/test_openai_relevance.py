from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from collector.classify_relevance import PendingArticle, load_policy
from collector.classify_relevance_openai import (
    call_openai,
    finalize_openai_record,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers: dict[str, str] = {}
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
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
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.response


class OpenAIRelevanceTests(unittest.TestCase):
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

    def test_openai_chat_completion_is_mapped(self) -> None:
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
        response = FakeResponse(
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
        session = FakeSession(response)

        result = call_openai(
            [self.pending()],
            policy=self.policy,
            endpoint="https://api.openai.com/v1/chat/completions",
            model="gpt-4.1-mini",
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
            "gpt-4.1-mini",
        )
        self.assertEqual(
            session.calls[0]["json"]["response_format"]["type"],
            "json_schema",
        )

    def test_openai_record_preserves_provider_and_model(self) -> None:
        record = finalize_openai_record(
            {
                "level": "important",
                "confidence": 0.9,
                "reason": "정책 영향이 있습니다.",
                "signals": ["AI"],
            },
            source_hash="source-hash",
            policy=self.policy,
            model="gpt-4.1-mini",
            method="openai-api",
        )

        self.assertEqual(record["method"], "openai-api")
        self.assertEqual(record["model"], "openai/gpt-4.1-mini")
        self.assertEqual(record["prompt_version"], "ip-office-relevance-v1.0")


if __name__ == "__main__":
    unittest.main()
