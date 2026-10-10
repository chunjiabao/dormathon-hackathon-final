"""Chat gateway: safe FAQ cache decision, then (only if not served from cache) exactly one provider call.

cache_status semantics:
  exact_hit / semantic_hit  approved FAQ answer served, NO provider call, zero provider tokens
  bypass                    cache enabled but the safety gate rejected the request -> provider
  miss                      provider called (cache disabled, no confident match, or holdout)
  error                     provider failed (logged with zero cost, never cached)
cache_decision records the gate/match outcome for every request, prefixed 'shadow_' while the
policy is disabled, so eligibility can be measured before anyone approves caching.
"""

import time
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import Application, FaqEntry, Workspace
from app.services import cache as faq_cache
from app.services import usage_logger
from app.services.anthropic_adapter import ChatProvider, ProviderError
from app.services.categorize import categorize
from app.services.costing import PricingNotFound, TokenUsage, cost_myr, get_rates
from app.services.usage_logger import normalize_for_exact_match

SYSTEM_TEMPLATE = """You are BakeryBot, the customer assistant for Sweet Crumbs Bakery, \
a FICTITIOUS demo bakery in Malaysia.
Answer briefly (under 120 words) using only the approved facts below. \
If the answer is not in the facts, say you are not sure and suggest contacting the bakery staff.
Rules:
- You cannot place, check, change or refund orders, and you have no access to order status or live stock.
- Never ask for or accept payment details, card numbers or personal identification.
- For custom orders, direct the customer to the bakery staff.
- Prices, sizes and availability are demo-only and not guaranteed.

Approved facts (knowledge version {version}):
{facts}"""


@dataclass
class ChatResult:
    request_id: uuid.UUID
    reply: str
    cache_status: str
    usage: TokenUsage
    estimated_cost_myr: Decimal
    provider: str
    request_category: str
    cache_decision: str | None = None
    faq_intent_key: str | None = None
    similarity: float | None = None


def active_faqs(session: Session, app: Application, ws: Workspace, locale: str = "en") -> list[FaqEntry]:
    return list(
        session.scalars(
            select(FaqEntry)
            .where(
                FaqEntry.workspace_id == ws.id,
                FaqEntry.application_id == app.id,
                FaqEntry.locale == locale,
                FaqEntry.knowledge_version == ws.knowledge_version,
            )
            .order_by(FaqEntry.intent_key)
        )
    )


def build_system_prompt(faqs: list[FaqEntry], version: int) -> str:
    facts = "\n".join(f"- Q: {f.question}\n  A: {f.approved_answer}" for f in faqs) or "- (none)"
    return SYSTEM_TEMPLATE.format(version=version, facts=facts)


def handle_chat(
    session: Session, provider: ChatProvider, app: Application, message: str, locale: str,
    client_key: str | None = None,
) -> ChatResult:  # fmt: skip
    settings = get_settings()
    ws = session.get(Workspace, app.workspace_id)
    assert ws is not None
    faqs = active_faqs(session, app, ws)
    phrases = {normalize_for_exact_match(p) for f in faqs for p in [f.question, *f.aliases]}
    category = categorize(message, phrases)
    fp = usage_logger.fingerprint(ws.id, message)
    request_id = uuid.uuid4()

    try:
        rates = get_rates(session, provider.model, settings.pricing_catalog_version)
    except PricingNotFound as exc:
        raise ApiError(
            503,
            "pricing_not_configured",
            "No price is configured for the active model; cannot estimate cost.",
        ) from exc

    base = dict(
        workspace_id=ws.id,
        application_id=app.id,
        model=provider.model,
        request_category=category,
        request_fingerprint=fp,
        client_fingerprint=usage_logger.client_fingerprint(ws.id, client_key),
        pricing_version=rates.version,
    )

    start = time.perf_counter()
    policy = faq_cache.cache_policy(session, app)
    decision = faq_cache.decide(session, app, ws, policy, message, locale, fp)
    enabled = bool(policy and policy.enabled)
    if enabled and decision.eligible and not decision.holdout:
        status = "exact_hit" if decision.decision == "eligible_exact" else "semantic_hit"
        faq_cache.record_hit(session, app, ws, policy, decision, message)
        usage_logger.record(
            session,
            usage_logger.LedgerEntry(
                **{**base, "model": "faq-cache", "request_category": "static_faq"},
                provider="tokenguard-cache",
                cache_status=status,
                usage=TokenUsage(),
                estimated_cost_myr=Decimal(0),  # no provider call; local overhead is accounted separately
                latency_ms=int((time.perf_counter() - start) * 1000),
                cache_decision=decision.decision,
                faq_intent_key=decision.intent_key,
                similarity_score=decision.similarity,
            ),
            request_id,
        )
        session.commit()
        return ChatResult(
            request_id, decision.faq.approved_answer, status, TokenUsage(), Decimal(0), "tokenguard-cache",
            "static_faq", decision.decision, decision.intent_key, decision.similarity,
        )  # fmt: skip

    if not enabled:
        cache_status, label = "miss", f"shadow_{decision.decision}"
    elif decision.eligible:  # holdout: deliberately not served from cache (counterfactual group)
        cache_status, label = "miss", f"holdout_{decision.decision}"
    elif decision.decision.startswith("bypass_"):
        cache_status, label = "bypass", decision.decision
    else:
        cache_status, label = "miss", decision.decision
    base.update(cache_decision=label, faq_intent_key=decision.intent_key, similarity_score=decision.similarity)
    try:
        resp = provider.complete(
            build_system_prompt(faqs, ws.knowledge_version), message, settings.chat_max_output_tokens
        )
    except ProviderError as exc:
        # Errors are logged (zero billed tokens) and never cached.
        usage_logger.record(
            session,
            usage_logger.LedgerEntry(
                **base,
                provider=provider.name,
                cache_status="error",
                usage=TokenUsage(),
                estimated_cost_myr=Decimal(0),
                latency_ms=0,
                error_code=exc.code,
            ),
            request_id,
        )
        session.commit()
        raise ApiError(
            502, "provider_unavailable", "The assistant is temporarily unavailable. Please try again shortly."
        ) from exc

    cost = cost_myr(resp.usage, rates, settings.myr_per_usd_demo)
    usage_logger.record(
        session,
        usage_logger.LedgerEntry(
            **{**base, "model": resp.model},
            provider=resp.provider,
            cache_status=cache_status,
            usage=resp.usage,
            estimated_cost_myr=cost,
            latency_ms=resp.latency_ms,
            provider_request_id=resp.provider_request_id,
        ),
        request_id,
    )
    session.commit()
    return ChatResult(
        request_id, resp.text, cache_status, resp.usage, cost, resp.provider, category, label,
        decision.intent_key, decision.similarity,
    )  # fmt: skip
