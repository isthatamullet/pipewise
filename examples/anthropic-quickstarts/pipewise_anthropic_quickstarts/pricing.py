"""Per-model price table for cost estimation.

Prices are USD per million tokens, as published by Anthropic. Adopters
should refresh this table when models change pricing. Keep it small —
listing every variant ages poorly.

Source: https://docs.claude.com/en/docs/about-claude/pricing
"""

from __future__ import annotations

# (input_per_million_usd, output_per_million_usd)
_PRICE_TABLE: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-opus-4-20250514": (15.00, 75.00),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Return USD cost estimate, or None when the model isn't in the table.

    Returning None (rather than 0) is the honest answer for unknown models —
    pipewise's ``CostBudgetScorer`` distinguishes "no data" from "below
    budget" and we shouldn't conflate them.
    """
    prices = _PRICE_TABLE.get(model)
    if prices is None:
        return None
    in_price, out_price = prices
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price
