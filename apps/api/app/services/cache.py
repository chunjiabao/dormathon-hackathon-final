"""Safe FAQ cache decision (MASTER_BUILD_PACK §8). Never calls an LLM.

Order: safety gate -> exact match on approved FAQ phrasings/aliases -> local-embedding semantic
match (similarity >= policy threshold, margin >= 0.03 over the best different intent, and identical
key terms such as day and product names). Matching is scoped to one workspace + application +
locale + current knowledge version, and only unexpired, cacheable entries. A hit is answered with
the APPROVED FAQ answer, never with previously generated provider output.

The decision is computed for every request ("shadow" mode while the policy is disabled) so the
real eligible/match rate can be measured before anyone approves caching.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application, FaqEntry, Policy, ResponseCache, Workspace
from app.services import embeddings, faq_eligibility
from app.services.seed import FAQ_FIXTURES, load_json
from app.services.usage_logger import normalize_for_exact_match

HOLDOUT_MODULUS = 10  # 10% of eligible requests bypass the cache when the owner opts in


def match_key(text: str) -> str:
    """Exact-match key: whitespace/case normalisation plus trailing punctuation only."""
    return normalize_for_exact_match(text).replace("’", "'").strip(" ?!.")


@dataclass
class CacheDecision:
    decision: str  # eligible_exact | eligible_semantic | bypass_<reason> | no_match | ambiguous | ...
    eligible: bool = False
    faq: SimpleNamespace | None = None  # snapshot of the approved FAQ entry
    similarity: float | None = None
    holdout: bool = False

    @property
    def intent_key(self) -> str | None:
        return self.faq.intent_key if self.faq else None


@dataclass
class _Index:
    texts: list[str]
    keys: list[str]
    entries: list[FaqEntry]
    vectors: np.ndarray | None


_index_cache: dict[tuple, _Index] = {}


def products_for(app: Application) -> list[str]:
    fixture = FAQ_FIXTURES.get(app.name)
    return load_json(fixture).get("products", []) if fixture else []


def active_entries(session: Session, app: Application, ws: Workspace, locale: str, now: datetime) -> list[FaqEntry]:
    return list(
        session.scalars(
            select(FaqEntry)
            .where(
                FaqEntry.workspace_id == ws.id,  # tenant isolation: never another workspace's answers
                FaqEntry.application_id == app.id,
                FaqEntry.locale == locale,
                FaqEntry.knowledge_version == ws.knowledge_version,
                FaqEntry.cacheable.is_(True),
                or_(FaqEntry.expires_at.is_(None), FaqEntry.expires_at > now),
            )
            .order_by(FaqEntry.intent_key)
        )
    )


def _snapshot(e) -> SimpleNamespace:
    """Plain copy of an FAQ entry: the index outlives DB sessions, so it must not hold ORM objects."""
    return SimpleNamespace(
        id=getattr(e, "id", None), intent_key=e.intent_key, question=e.question, aliases=list(e.aliases),
        approved_answer=e.approved_answer, locale=getattr(e, "locale", "en"),
        knowledge_version=getattr(e, "knowledge_version", None),
    )  # fmt: skip


def _index(entries: list[FaqEntry], semantic: bool) -> _Index:
    key = (tuple((e.id if hasattr(e, "id") else None, e.intent_key, e.question, tuple(e.aliases),
                  e.approved_answer) for e in entries), semantic)  # fmt: skip
    if key in _index_cache:
        return _index_cache[key]
    texts, owners = [], []
    for e in map(_snapshot, entries):
        for t in [e.question, *e.aliases]:
            texts.append(t)
            owners.append(e)
    vectors = embeddings.embed(texts) if semantic and texts else None
    idx = _Index(texts=texts, keys=[match_key(t) for t in texts], entries=owners, vectors=vectors)
    if len(_index_cache) > 64:
        _index_cache.clear()
    _index_cache[key] = idx
    return idx


def decide(
    session: Session, app: Application, ws: Workspace, policy: Policy | None, message: str, locale: str,
    fingerprint: str, now: datetime | None = None,
) -> CacheDecision:  # fmt: skip
    now = now or datetime.now(UTC)
    products = products_for(app)
    gate = faq_eligibility.check(message, locale, products)
    if not gate.eligible:
        return CacheDecision(f"bypass_{gate.reason}")
    entries = active_entries(session, app, ws, locale, now)
    threshold = float(policy.similarity_threshold) if policy else 0.95
    result = match(entries, products, message, threshold)
    if (
        result.eligible
        and policy is not None
        and policy.holdout_enabled
        and int(fingerprint[:8], 16) % HOLDOUT_MODULUS == 0
    ):
        result.holdout = True
    return result


def match(entries: list, products: list[str], message: str, threshold: float) -> CacheDecision:
    """Pure matcher over approved entries (objects with intent_key/question/aliases). Gate already passed."""
    if not entries:
        return CacheDecision("no_approved_faq")
    semantic_ok = get_settings().embedding_mode == "local"
    try:
        idx = _index(entries, semantic_ok)
    except embeddings.EmbeddingUnavailable:
        semantic_ok, idx = False, _index(entries, False)

    q = match_key(message)
    exact = {idx.entries[i].intent_key: idx.entries[i] for i, k in enumerate(idx.keys) if k == q}
    if len(exact) == 1:
        result = CacheDecision("eligible_exact", True, next(iter(exact.values())), 1.0)
    elif len(exact) > 1:
        return CacheDecision("ambiguous_exact")
    elif not semantic_ok:
        return CacheDecision("no_match_exact_only")
    else:
        qv = np.asarray(embeddings.embed_one(normalize_for_exact_match(message)), dtype=np.float32)
        sims = idx.vectors @ qv
        best_by_intent: dict[str, tuple[float, int]] = {}
        for i, s in enumerate(sims):
            k = idx.entries[i].intent_key
            if k not in best_by_intent or s > best_by_intent[k][0]:
                best_by_intent[k] = (float(s), i)
        ranked = sorted(best_by_intent.values(), reverse=True)
        best, best_i = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else -1.0
        if best < threshold:
            return CacheDecision("below_threshold", similarity=best)
        if best - second < get_settings().semantic_margin:
            return CacheDecision("ambiguous_margin", similarity=best)
        q_terms = faq_eligibility.key_terms(normalize_for_exact_match(message), products)
        f_terms = faq_eligibility.key_terms(normalize_for_exact_match(idx.texts[best_i]), products)
        if q_terms != f_terms:
            return CacheDecision("key_term_mismatch", similarity=best)
        result = CacheDecision("eligible_semantic", True, idx.entries[best_i], best)
    return result


def record_hit(session: Session, app: Application, ws: Workspace, policy: Policy, d: CacheDecision, message: str):
    """Upsert the response_cache row (approved answer only) and bump its hit counter."""
    now = datetime.now(UTC)
    qhash = hashlib.sha256(f"{ws.id}:{app.id}:{match_key(message)}".encode()).hexdigest()
    row = session.scalar(
        select(ResponseCache).where(
            ResponseCache.application_id == app.id,
            ResponseCache.normalized_query_hash == qhash,
            ResponseCache.locale == d.faq.locale,
            ResponseCache.knowledge_version == d.faq.knowledge_version,
        )
    )
    if row is None or row.expires_at <= now:
        if row is not None:
            session.delete(row)
            session.flush()
        row = ResponseCache(
            workspace_id=ws.id, application_id=app.id, faq_entry_id=d.faq.id, normalized_query_hash=qhash,
            answer=d.faq.approved_answer, locale=d.faq.locale, knowledge_version=d.faq.knowledge_version,
            expires_at=now + timedelta(hours=policy.ttl_hours), hit_count=0,
        )  # fmt: skip
        session.add(row)
    row.hit_count += 1
    row.last_hit_at = now


def bump_knowledge_version(session: Session, ws: Workspace) -> int:
    """Invalidate every cached answer for the workspace; new FAQ entries must be approved for the new version."""
    ws.knowledge_version += 1
    session.execute(delete(ResponseCache).where(ResponseCache.workspace_id == ws.id))
    session.commit()
    _index_cache.clear()
    return ws.knowledge_version


def cache_policy(session: Session, app: Application) -> Policy | None:
    return session.scalar(select(Policy).where(Policy.application_id == app.id, Policy.policy_type == "semantic_cache"))
