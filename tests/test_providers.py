import asyncio
import json

import httpx
import pytest
from conftest import response_for

from book_generator.models import BookConfig, plan_schema
from book_generator.providers import Provider, ProviderError, parse_plan


@pytest.mark.parametrize("name", ["openai", "claude", "gemini"])
def test_provider_headers_payload_usage_and_no_key_in_body(config, name):
    config = BookConfig.model_validate(
        {**config.model_dump(), "provider": name, "workspace_id": "wrkspc_test"}
    )
    captured = []

    def handle(request):
        captured.append(request)
        return httpx.Response(200, json=response_for(name, '{"parts":[]}'))

    result = asyncio.run(
        Provider(config, "a-secret-not-a-model", httpx.MockTransport(handle)).complete(
            "system", "JSON please", 512, structured=True
        )
    )
    request = captured[0]
    body = json.loads(request.content)
    assert "a-secret-not-a-model" not in request.content.decode()
    assert "a-secret-not-a-model" not in str(request.url)
    assert result.output_tokens == 110
    assert result.input_tokens == (150 if name == "claude" else 100)
    assert not result.truncated
    if name == "openai":
        assert request.headers["authorization"] == "Bearer a-secret-not-a-model"
        assert body["store"] is False and body["max_output_tokens"] == 512
        assert body["text"]["format"]["strict"] is True
        assert "title" in body["text"]["format"]["schema"]["$defs"]["ChapterPlan"]["properties"]
    elif name == "claude":
        assert request.headers["x-api-key"] == "a-secret-not-a-model"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert request.headers["anthropic-workspace-id"] == "wrkspc_test"
        assert body["max_tokens"] == 512
    else:
        assert request.headers["x-goog-api-key"] == "a-secret-not-a-model"
        assert body["generationConfig"]["maxOutputTokens"] == 512
        assert body["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.parametrize("name", ["openai", "claude", "gemini"])
def test_truncated_response_is_reported(config, name):
    config = BookConfig.model_validate({**config.model_dump(), "provider": name})
    result = asyncio.run(
        Provider(
            config,
            "secret",
            httpx.MockTransport(
                lambda request: httpx.Response(200, json=response_for(name, "unfinished", truncated=True))
            ),
        ).complete("system", "prompt", 512)
    )
    assert result.truncated


def test_failure_is_redacted_and_not_retried(config):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(429, json={"error": "echoing-secret-key"})

    with pytest.raises(ProviderError) as error:
        asyncio.run(
            Provider(config, "echoing-secret-key", httpx.MockTransport(handle)).complete("s", "p", 512)
        )
    assert "429" in str(error.value) and "echoing-secret-key" not in str(error.value)
    assert len(requests) == 1


def test_missing_usage_is_not_silently_zero(config):
    with pytest.raises(ProviderError):
        asyncio.run(
            Provider(
                config,
                "secret",
                httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"status": "completed", "output": []})
                ),
            ).complete("s", "p", 512)
        )


def test_parse_plan_and_schema():
    assert parse_plan('```json\n{"parts": []}\n```') == {"parts": []}
    assert "title" in plan_schema()["$defs"]["ChapterPlan"]["properties"]
