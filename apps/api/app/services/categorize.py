"""Deterministic request-category assignment for the usage ledger (no LLM).

Categories match the forecasting segments: static_faq, order_enquiry, complex_support, other.
This only labels traffic for cost attribution; cache eligibility is decided separately and
far more conservatively in faq_eligibility.
"""

import re

from app.services.usage_logger import normalize_for_exact_match

CATEGORIES = ("static_faq", "order_enquiry", "complex_support", "other")

_ORDER = re.compile(r"\b(my order|order\s*#?\d+|order status|track|refund|cancel|invoice|receipt)\b", re.I)
_COMPLEX = re.compile(r"\b(complain|complaint|allerg|wrong|damaged|problem|issue|broken|sick)\w*", re.I)
_FAQ_HINT = re.compile(
    r"\b(open|close|hours?|sunday|saturday|deliver\w*|pick\s*up|pickup|collect|cakes?|price"
    r"|how much|custom)\b",
    re.I,
)


def categorize(message: str, faq_phrases: set[str]) -> str:
    norm = normalize_for_exact_match(message)
    if _ORDER.search(norm):
        return "order_enquiry"
    if _COMPLEX.search(norm) or len(norm) > 400:
        return "complex_support"
    if norm in faq_phrases or _FAQ_HINT.search(norm):
        return "static_faq"
    return "other"
