from __future__ import annotations

import math


def estimate_fee_dollars(price: float, contracts: int = 1) -> float:
    """Conservative retail-style fee estimate per trade.

    Kalshi fees can vary by product and schedule. This uses a transparent
    approximation commonly expressed as 7 cents * contracts * p * (1-p),
    rounded up to the nearest cent. Treat it as a safety haircut, not an
    official statement of exact fees.
    """

    price = max(0.0, min(1.0, price))
    raw = 0.07 * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0) / 100.0


def total_cost(price: float, contracts: int = 1) -> float:
    return price * contracts + estimate_fee_dollars(price, contracts)

