"""Provider cost estimation from actual token counts and a versioned price catalog.

Costs are estimates: USD provider rates converted with a fixed, explicitly configured demo FX
rate (MYR_PER_USD_DEMO), never a live rate.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PricingCatalog

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Rates:
    model: str
    version: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    cache_read_usd_per_million: Decimal
    cache_write_usd_per_million: Decimal


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class PricingNotFound(LookupError):
    pass


def _rates_from_row(row: PricingCatalog) -> Rates:
    return Rates(
        model=row.model,
        version=row.version,
        input_usd_per_million=Decimal(row.input_usd_per_million),
        output_usd_per_million=Decimal(row.output_usd_per_million),
        # A model without cache pricing cannot report cache tokens; treat missing as zero-rated.
        cache_read_usd_per_million=Decimal(row.cache_read_usd_per_million or 0),
        cache_write_usd_per_million=Decimal(row.cache_write_usd_per_million or 0),
    )


def get_rates(session: Session, model: str, version: str, on: date | None = None) -> Rates:
    stmt = select(PricingCatalog).where(
        PricingCatalog.provider == "anthropic",
        PricingCatalog.model == model,
        PricingCatalog.version == version,
    )
    if on is not None:
        stmt = stmt.where(PricingCatalog.effective_from <= on)
    row = session.scalars(stmt.order_by(PricingCatalog.effective_from.desc())).first()
    if row is None:
        raise PricingNotFound(f"No pricing for model '{model}' in catalog version '{version}'.")
    return _rates_from_row(row)


def cost_usd(usage: TokenUsage, rates: Rates) -> Decimal:
    if min(usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, usage.cache_write_tokens) < 0:
        raise ValueError("token counts must be non-negative")
    total = (
        usage.input_tokens * rates.input_usd_per_million
        + usage.output_tokens * rates.output_usd_per_million
        + usage.cache_read_tokens * rates.cache_read_usd_per_million
        + usage.cache_write_tokens * rates.cache_write_usd_per_million
    )
    return total / MILLION


def cost_myr(usage: TokenUsage, rates: Rates, myr_per_usd: float) -> Decimal:
    return (cost_usd(usage, rates) * Decimal(str(myr_per_usd))).quantize(Decimal("0.00000001"))
