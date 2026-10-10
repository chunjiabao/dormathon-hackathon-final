from decimal import Decimal

import pytest

from app.services.costing import Rates, TokenUsage, cost_myr, cost_usd

RATES = Rates("m", "v1", Decimal(1), Decimal(5), Decimal("0.1"), Decimal("1.25"))


def test_cost_uses_each_token_type_at_its_rate():
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_write_tokens=1_000_000,
    )
    assert cost_usd(usage, RATES) == Decimal("7.35")


def test_myr_conversion_uses_configured_fx():
    usage = TokenUsage(input_tokens=1000, output_tokens=200)
    # (1000*1 + 200*5)/1e6 = 0.002 USD * 4.7 = 0.0094 MYR
    assert cost_myr(usage, RATES, 4.70) == Decimal("0.00940000")


def test_zero_tokens_cost_zero():
    assert cost_myr(TokenUsage(), RATES, 4.70) == 0


def test_negative_tokens_rejected():
    with pytest.raises(ValueError):
        cost_usd(TokenUsage(input_tokens=-1), RATES)
