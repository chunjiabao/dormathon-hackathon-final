"""Deterministic safety gate for the FAQ cache (no LLM classification).

A request may only be answered from an approved FAQ if it passes every rule here. Rules are
deliberately conservative; false negatives (unsafe requests that slip through) remain possible,
which is why caching is additionally limited to approved FAQ intents with exact/alias matches or
very high-similarity, key-term-consistent semantic matches.
"""

import re
from dataclasses import dataclass

from app.services.usage_logger import normalize_for_exact_match

MAX_CACHEABLE_CHARS = 200

_RULES: list[tuple[str, re.Pattern]] = [
    ("pii", re.compile(
        r"[\w.+-]+@[\w-]+\.[\w.]+"                      # email
        r"|\+?\d[\d\s-]{7,}\d"                            # phone-like digit runs
        r"|\b\d{6}-\d{2}-\d{4}\b"                         # Malaysian IC format
        r"|\bmy (name|address|phone|number|email|ic|card|account number)\b"
        r"|\bi live (at|in)\b|\bjalan\b|\bpostcode\b", re.I)),
    ("account_specific", re.compile(
        r"\bmy (order|orders|booking|account|payment|parcel|delivery|refund|purchase)\b"
        r"|\border\s*(#|no\.?|number|status|id)\b|#\s*\d+|\b(refund|cancel|invoice|receipt|tracking|track)\b", re.I)),
    ("dynamic", re.compile(
        r"\b(today|tomorrow|tonight|yesterday|now|currently|right now|at the moment)\b"
        r"|\b(this|next|last) (week|weekend|month|morning|afternoon|evening)\b"
        r"|\b(in stock|out of stock|sold out|stock|any left|still have)\b"
        r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d"
        r"|\b\d{1,2}\s*(am|pm)\b|\bo'clock\b", re.I)),
    ("discount", re.compile(r"\b(discount|promo|promotion|coupon|voucher|sale|deal|offer code|cheaper)\b", re.I)),
    ("contains_number", re.compile(r"\d")),
    ("negation", re.compile(
        r"\b(not|no|never|without|except|instead|unless)\b|n't\b|\bcannot\b", re.I)),
    ("multiple_questions", re.compile(
        r"\?.*\?|\b(and|also|plus)\b.*\b(what|when|how|do|does|is|are|can|where|which)\b", re.I)),
]  # fmt: skip

# Minimal English function-word list; a query with none of these is treated as non-English.
_ENGLISH_HINTS = {
    "what", "when", "how", "do", "does", "is", "are", "can", "you", "your", "the", "a", "an", "i", "much", "time",
    "open", "close", "which", "where", "have", "any", "price", "deliver", "show", "me", "there", "of", "on", "to",
}  # fmt: skip


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reason: str | None = None


def check(message: str, locale: str, products: list[str] | None = None) -> Eligibility:
    if locale != "en":
        return Eligibility(False, "locale_unsupported")
    if len(message) > MAX_CACHEABLE_CHARS:
        return Eligibility(False, "too_long")
    if re.search(r"[^\x00-\x7F‘’]", message):
        return Eligibility(False, "non_english")
    norm = normalize_for_exact_match(message)
    words = set(re.findall(r"[a-z']+", norm))
    if not words & _ENGLISH_HINTS:
        return Eligibility(False, "non_english")
    for reason, pattern in _RULES:
        if pattern.search(norm):
            return Eligibility(False, reason)
    if products:
        mentioned = mentioned_products(norm, products)
        if len(mentioned) > 1:
            return Eligibility(False, "conflicting_products")
    return Eligibility(True)


def mentioned_products(norm: str, products: list[str]) -> set[str]:
    """Distinct catalog products mentioned; a longer name absorbs its shorter prefix forms."""
    found = {p for p in products if re.search(rf"\b{re.escape(p)}\b", norm)}
    return {p for p in found if not any(p != q and p in q for q in found)}


_DAYS = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend|weekday|holiday)s?"


def key_terms(norm: str, products: list[str]) -> frozenset[str]:
    """Terms that change the answer if they differ: day names (plural folded) and product names."""
    days = set(re.findall(rf"\b{_DAYS}\b", norm))  # findall returns the captured base name
    return frozenset(days | mentioned_products(norm, products))
