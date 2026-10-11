from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from .models import BookConfig, plan_schema


class ProviderError(Exception):
    """Safe, predefined errors; never include provider bodies, headers, or credentials."""


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    truncated: bool = False


def _tokens(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderError("API 응답에 유효한 사용량 정보가 없습니다. 예약한 출력 한도를 유지합니다.")
    return value


class Provider:
    def __init__(self, config: BookConfig, key: str, transport=None):
        self.config = config
        self._key = key
        self.transport = transport

    def forget_key(self):
        self._key = ""

    async def complete(self, system: str, prompt: str, limit: int, *, structured=False) -> Completion:
        if not self._key or any(char in self._key for char in "\r\n"):
            raise ProviderError("유효한 API 키가 필요합니다.")
        provider = self.config.provider
        if provider == "openai":
            url = "https://api.openai.com/v1/responses"
            headers = {"Authorization": "Bearer " + self._key}
            body = {
                "model": self.config.model,
                "instructions": system,
                "input": prompt,
                "max_output_tokens": limit,
                "store": False,
            }
            if structured:
                body["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": "book_plan",
                        "strict": True,
                        "schema": plan_schema(),
                    }
                }
        elif provider == "claude":
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01"}
            if self.config.workspace_id:
                headers["anthropic-workspace-id"] = self.config.workspace_id
            body = {
                "model": self.config.model,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": limit,
            }
        else:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.config.model}:generateContent"
            )
            headers = {"x-goog-api-key": self._key}
            body = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": limit},
            }
            if structured:
                body["generationConfig"]["responseMimeType"] = "application/json"
        try:
            # No retries, redirects, environment proxies, or SDK request-body logging.
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(180, connect=15),
                transport=self.transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(url, headers=headers, json=body)
        except (httpx.HTTPError, ValueError):
            raise ProviderError(
                "API 연결이 완료되지 않았습니다. 자동 재시도하지 않으며 해당 호출은 과금될 수 있습니다."
            ) from None
        if response.status_code != 200:
            label = {
                400: "모델 ID·요청 한도·계정 설정을 확인하세요.",
                401: "API 키를 확인하세요.",
                403: "키 권한과 모델 접근 권한을 확인하세요.",
                404: "모델 ID를 확인하세요.",
                429: "계정 잔액 또는 요청 한도를 확인한 뒤 이어서 실행하세요.",
            }.get(response.status_code, "제공자 오류입니다. 잠시 후 이어서 실행하세요.")
            raise ProviderError(f"API HTTP {response.status_code}: {label}")
        try:
            data = response.json()
            if provider == "openai":
                result = "\n".join(
                    block["text"]
                    for item in data.get("output", [])
                    for block in item.get("content", [])
                    if block.get("type") == "output_text"
                )
                usage = data["usage"]
                return Completion(
                    result,
                    _tokens(usage["input_tokens"]),
                    _tokens(usage["output_tokens"]),
                    data.get("status") != "completed",
                )
            if provider == "claude":
                result = "\n".join(
                    block["text"] for block in data.get("content", []) if block.get("type") == "text"
                )
                usage = data["usage"]
                # Cache creation/read are separate input usage fields in Messages.
                input_count = _tokens(usage["input_tokens"]) + _tokens(
                    usage.get("cache_creation_input_tokens", 0)
                )
                input_count += _tokens(usage.get("cache_read_input_tokens", 0))
                return Completion(
                    result,
                    input_count,
                    _tokens(usage["output_tokens"]),
                    data.get("stop_reason") != "end_turn",
                )
            candidate = data.get("candidates", [{}])[0]
            result = "\n".join(
                block["text"]
                for block in candidate.get("content", {}).get("parts", [])
                if "text" in block and not block.get("thought")
            )
            usage = data["usageMetadata"]
            # The thinking tokens consume output budget too.
            output_count = _tokens(usage["candidatesTokenCount"]) + _tokens(
                usage.get("thoughtsTokenCount", 0)
            )
            return Completion(
                result,
                _tokens(usage["promptTokenCount"]),
                output_count,
                candidate.get("finishReason") != "STOP",
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError(
                "API 응답 형식을 해석하지 못했습니다. 예약한 출력 한도를 유지합니다."
            ) from None


def parse_plan(text: str) -> dict:
    """Some providers wrap JSON in a Markdown fence despite the instruction."""
    value = text.strip()
    if value.startswith("```") and value.endswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(value)
