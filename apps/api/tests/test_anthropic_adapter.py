"""Live adapter tested offline: the real Anthropic SDK talks to an httpx MockTransport (no network)."""

import json

import anthropic
import httpx2 as httpx  # the Anthropic SDK (>=1.x) ships on httpx2
import pytest

from app.config import Settings
from app.services.anthropic_adapter import AnthropicProvider, ProviderError

MODEL = "claude-haiku-4-5-20251001"


def _provider(handler) -> tuple[AnthropicProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    provider = AnthropicProvider(Settings(anthropic_api_key="test-key", anthropic_model=MODEL))
    provider._client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(record)),
    )
    return provider, seen


def _message_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_test_123",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": [{"type": "text", "text": "We open at 10:00."}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 321,
                "output_tokens": 12,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    )


def test_usage_comes_from_response_metadata():
    provider, seen = _provider(_message_response)
    resp = provider.complete("system prompt", "When do you open?", 250)
    assert resp.text == "We open at 10:00."
    assert (resp.usage.input_tokens, resp.usage.output_tokens) == (321, 12)
    assert resp.provider == "anthropic" and resp.provider_request_id == "msg_test_123"
    assert len(seen) == 1
    sent = json.loads(seen[0].content)
    assert sent["model"] == MODEL and sent["max_tokens"] == 250 and sent["system"] == "system prompt"
    assert sent["messages"] == [{"role": "user", "content": "When do you open?"}]


@pytest.mark.parametrize(
    ("status", "code", "transient"),
    [
        (429, "provider_rate_limited", True),
        (500, "provider_http_500", True),
        (400, "provider_http_400", False),
    ],
)
def test_errors_map_to_safe_codes(status, code, transient):
    body = {"type": "error", "error": {"type": "api_error", "message": "internal detail"}}
    provider, _ = _provider(lambda r: httpx.Response(status, json=body))
    with pytest.raises(ProviderError) as exc:
        provider.complete("s", "m", 10)
    assert exc.value.code == code and exc.value.transient is transient


def test_live_mode_requires_key():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider(Settings(anthropic_api_key=None))
