import json

import httpx
import pytest

from book_generator.models import BookConfig
from book_generator.prompts import demo_chapter, demo_plan
from book_generator.providers import Provider


@pytest.fixture
def config():
    return BookConfig(
        id="test-book",
        title="테스트 책",
        subject="학습 과정",
        chapter_count=3,
        provider="openai",
        model="test-model",
        max_output_tokens=512,
        output_budget=10000,
    )


def response_for(provider, text, *, truncated=False):
    if provider == "openai":
        return {
            "status": "incomplete" if truncated else "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 100, "output_tokens": 110},
        }
    if provider == "claude":
        return {
            "content": [{"type": "text", "text": text}],
            "stop_reason": "max_tokens" if truncated else "end_turn",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 110,
                "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 30,
            },
        }
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}, "finishReason": "MAX_TOKENS" if truncated else "STOP"}
        ],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 100, "thoughtsTokenCount": 10},
    }


class MockAuthor:
    def __init__(self, config, key="test-secret-key"):
        self.config = config
        self.key = key
        self.requests = []
        self.chapter_number = 0

    def handle(self, request):
        self.requests.append(request)
        body = json.loads(request.content)
        structured = "text" in body or body.get("generationConfig", {}).get("responseMimeType")
        if self.config.provider == "claude":
            structured = "Return ONLY a JSON" in body["messages"][0]["content"]
        if structured:
            text = demo_plan(self.config).model_dump_json()
        else:
            self.chapter_number += 1
            text = demo_chapter(self.config, self.chapter_number, demo_plan(self.config).chapters()[0][1])
        return httpx.Response(200, json=response_for(self.config.provider, text))

    def provider(self):
        return Provider(self.config, self.key, httpx.MockTransport(self.handle))
