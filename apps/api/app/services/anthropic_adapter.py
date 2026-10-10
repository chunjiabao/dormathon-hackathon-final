"""Typed provider adapter: live Anthropic Messages API or a clearly labelled mock.

Only BakeryBot's uncached response generation may call Anthropic. The mock never makes a
network call; its token counts are rough estimates and its provider is recorded as
'anthropic-mock' so mock traffic is never mistaken for real provider usage.
"""

import hashlib
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.config import Settings, get_settings
from app.services.costing import TokenUsage


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    usage: TokenUsage
    model: str
    provider: str
    provider_request_id: str | None
    latency_ms: int


class ProviderError(Exception):
    """Safe-to-surface provider failure. `code` is a short machine-readable reason."""

    def __init__(self, code: str, transient: bool = False):
        super().__init__(code)
        self.code, self.transient = code, transient


class ChatProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, message: str, max_tokens: int) -> ProviderResponse: ...


class MockProvider:
    """Deterministic offline stand-in. Counts calls so tests can assert no provider call on cache hits."""

    name = "anthropic-mock"

    def __init__(self, model: str):
        self.model = model
        self.calls = 0
        self.fail_next: ProviderError | None = None

    def complete(self, system: str, message: str, max_tokens: int) -> ProviderResponse:
        start = time.perf_counter()
        self.calls += 1
        if self.fail_next is not None:
            err, self.fail_next = self.fail_next, None
            raise err
        text = (
            "[Mock mode: no Anthropic call was made] Thanks for your question! For anything not covered "
            "by our FAQ, please contact Sweet Crumbs Bakery staff directly."
        )
        digest = hashlib.sha256(message.encode()).hexdigest()[:16]
        # ~4 characters per token is a rough heuristic, labelled as mock data.
        usage = TokenUsage(
            input_tokens=max(1, (len(system) + len(message)) // 4),
            output_tokens=min(max_tokens, max(1, len(text) // 4)),
        )
        return ProviderResponse(
            text=text,
            usage=usage,
            model=self.model,
            provider=self.name,
            # Globally unique (the ledger enforces uniqueness across restarts); digest aids debugging only.
            provider_request_id=f"mock_{uuid.uuid4().hex}_{digest}",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings):
        import anthropic

        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_MODE=live requires ANTHROPIC_API_KEY.")
        self._anthropic = anthropic
        self.model = settings.anthropic_model
        # SDK retries only transient errors (connection, 408/409/429/5xx) with bounded exponential backoff.
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.provider_timeout_s,
            max_retries=settings.provider_max_retries,
        )

    def validate_model(self) -> None:
        try:
            self._client.models.retrieve(self.model)
        except self._anthropic.AuthenticationError as exc:
            raise RuntimeError("Anthropic rejected ANTHROPIC_API_KEY (authentication failed).") from exc
        except self._anthropic.NotFoundError as exc:
            raise RuntimeError(
                f"ANTHROPIC_MODEL '{self.model}' is not available for this API key. "
                "Set ANTHROPIC_MODEL to a supported model id."
            ) from exc

    def complete(self, system: str, message: str, max_tokens: int) -> ProviderResponse:
        a = self._anthropic
        start = time.perf_counter()
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": message}],
            )
        except a.APITimeoutError as exc:
            raise ProviderError("provider_timeout", transient=True) from exc
        except a.RateLimitError as exc:
            raise ProviderError("provider_rate_limited", transient=True) from exc
        except a.APIConnectionError as exc:
            raise ProviderError("provider_unreachable", transient=True) from exc
        except a.APIStatusError as exc:
            raise ProviderError(f"provider_http_{exc.status_code}", transient=exc.status_code >= 500) from exc
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()
        u = resp.usage
        usage = TokenUsage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", None) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", None) or 0,
        )
        return ProviderResponse(
            text=text or "Sorry, I could not produce an answer. Please contact our staff.",
            usage=usage,
            model=resp.model,
            provider=self.name,
            provider_request_id=resp.id,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )


@lru_cache
def get_provider() -> ChatProvider:
    settings = get_settings()
    if settings.provider_mode == "live":
        return AnthropicProvider(settings)
    return MockProvider(settings.anthropic_model)
