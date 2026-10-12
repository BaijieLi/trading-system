from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _best_bid(levels: list[list[Any]] | None) -> tuple[float, float]:
    if not levels:
        return 0.0, 0.0
    parsed = [(_float(price), _float(size)) for price, size in levels if _float(price) > 0]
    if not parsed:
        return 0.0, 0.0
    return max(parsed, key=lambda item: item[0])


def _depth(levels: list[list[Any]] | None, top_n: int = 5) -> float:
    if not levels:
        return 0.0
    return sum(_float(size) for _, size in levels[:top_n])


@dataclass(frozen=True)
class Quote:
    ticker: str
    title: str
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    yes_bid_size: float
    yes_ask_size: float
    no_bid_size: float
    no_ask_size: float
    volume_24h: float
    open_interest: float
    close_time: str
    event_ticker: str

    @property
    def has_two_sided_yes(self) -> bool:
        return self.yes_bid > 0 and self.yes_ask > 0 and self.yes_ask >= self.yes_bid

    @property
    def spread(self) -> float:
        if not self.has_two_sided_yes:
            return 1.0
        return self.yes_ask - self.yes_bid

    @property
    def midpoint(self) -> float:
        if not self.has_two_sided_yes:
            return 0.0
        return (self.yes_bid + self.yes_ask) / 2.0

    @property
    def microprice(self) -> float:
        bid_size = max(self.yes_bid_size, 0.0)
        ask_size = max(self.yes_ask_size, 0.0)
        if not self.has_two_sided_yes or bid_size + ask_size <= 0:
            return self.midpoint
        return (self.yes_ask * bid_size + self.yes_bid * ask_size) / (bid_size + ask_size)


def quote_from_market(market: dict[str, Any]) -> Quote:
    orderbook = market.get("orderbook") or {}
    orderbook_fp = orderbook.get("orderbook_fp") or {}
    yes_levels = orderbook_fp.get("yes_dollars") or []
    no_levels = orderbook_fp.get("no_dollars") or []
    best_yes_bid, best_yes_size = _best_bid(yes_levels)
    best_no_bid, best_no_size = _best_bid(no_levels)

    yes_bid = best_yes_bid or _float(market.get("yes_bid_dollars"))
    no_bid = best_no_bid or _float(market.get("no_bid_dollars"))
    yes_ask = _float(market.get("yes_ask_dollars")) or (1.0 - no_bid if no_bid > 0 else 0.0)
    no_ask = _float(market.get("no_ask_dollars")) or (1.0 - yes_bid if yes_bid > 0 else 0.0)
    yes_ask_size = best_no_size or _float(market.get("yes_ask_size_fp"))
    no_ask_size = best_yes_size or _float(market.get("no_ask_size_fp"))

    return Quote(
        ticker=str(market.get("ticker") or ""),
        title=str(market.get("title") or ""),
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=no_bid,
        no_ask=no_ask,
        yes_bid_size=best_yes_size or _float(market.get("yes_bid_size_fp")),
        yes_ask_size=yes_ask_size,
        no_bid_size=best_no_size,
        no_ask_size=no_ask_size,
        volume_24h=_float(market.get("volume_24h_fp")),
        open_interest=_float(market.get("open_interest_fp")),
        close_time=str(market.get("close_time") or ""),
        event_ticker=str(market.get("event_ticker") or ""),
    )

