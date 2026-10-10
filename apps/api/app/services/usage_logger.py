"""Usage ledger: one row per gateway request, metadata only (never the raw message)."""

import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ApiRequest
from app.services.costing import TokenUsage

_WS = re.compile(r"\s+")


def normalize_for_exact_match(message: str) -> str:
    """Collapse whitespace and lowercase only; numbers, dates, negations and names are preserved."""
    return _WS.sub(" ", message).strip().lower()


def fingerprint(workspace_id: uuid.UUID, message: str) -> str:
    """Keyed HMAC so the ledger cannot be reversed by hashing guessed messages."""
    key = get_settings().effective_fingerprint_secret.encode()
    payload = f"{workspace_id}:{normalize_for_exact_match(message)}".encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def client_fingerprint(workspace_id: uuid.UUID, client_key: str | None) -> str | None:
    if not client_key:
        return None
    key = get_settings().effective_fingerprint_secret.encode()
    return hmac.new(key, f"client:{workspace_id}:{client_key}".encode(), hashlib.sha256).hexdigest()


@dataclass
class LedgerEntry:
    workspace_id: uuid.UUID
    application_id: uuid.UUID
    provider: str
    model: str
    request_category: str
    cache_status: str
    request_fingerprint: str
    pricing_version: str
    usage: TokenUsage
    estimated_cost_myr: Decimal
    latency_ms: int
    provider_request_id: str | None = None
    error_code: str | None = None
    faq_intent_key: str | None = None
    similarity_score: float | None = None
    client_fingerprint: str | None = None
    cache_decision: str | None = None


def record(session: Session, entry: LedgerEntry, request_id: uuid.UUID | None = None) -> ApiRequest:
    row = ApiRequest(
        id=request_id or uuid.uuid4(),
        workspace_id=entry.workspace_id,
        application_id=entry.application_id,
        occurred_at=datetime.now(UTC),
        provider=entry.provider,
        model=entry.model,
        request_category=entry.request_category,
        input_tokens=entry.usage.input_tokens,
        output_tokens=entry.usage.output_tokens,
        cache_read_tokens=entry.usage.cache_read_tokens,
        cache_write_tokens=entry.usage.cache_write_tokens,
        estimated_cost_myr=entry.estimated_cost_myr,
        cache_status=entry.cache_status,
        latency_ms=entry.latency_ms,
        provider_request_id=entry.provider_request_id,
        data_origin="real",  # gateway traffic is never synthetic; mock calls are flagged via provider
        request_fingerprint=entry.request_fingerprint,
        client_fingerprint=entry.client_fingerprint,
        cache_decision=entry.cache_decision,
        pricing_version=entry.pricing_version,
        error_code=entry.error_code,
        faq_intent_key=entry.faq_intent_key,
        similarity_score=None if entry.similarity_score is None else Decimal(str(round(entry.similarity_score, 5))),
    )
    session.add(row)
    session.flush()
    return row
