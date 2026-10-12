from __future__ import annotations

from dataclasses import asdict, dataclass

from kalshi_trading_system.config import SETTINGS
from kalshi_trading_system.models.fees import estimate_fee_dollars
from kalshi_trading_system.models.orderbook import Quote, quote_from_market


@dataclass(frozen=True)
class Signal:
    ticker: str
    title: str
    action: str
    fair_probability: float
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    spread: float
    expected_value: float
    expected_roi: float
    fee_estimate: float
    volume_24h: float
    open_interest: float
    reason: str
    risk_flags: str
    market_url: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def market_url(event_ticker: str, ticker: str) -> str:
    if event_ticker:
        return f"https://kalshi.com/markets/{event_ticker}"
    return f"https://kalshi.com/markets/{ticker}"


def estimate_fair_probability(quote: Quote, manual_fair: float | None = None) -> float:
    if manual_fair is not None:
        return max(0.0, min(1.0, manual_fair))
    # Microprice is a market-pressure estimate, not a true forecasting model.
    return max(0.0, min(1.0, quote.microprice or quote.midpoint))


def analyze_market(
    market: dict[str, object],
    manual_fair: float | None = None,
    min_edge: float = SETTINGS.min_edge_dollars,
    max_spread: float = SETTINGS.max_spread_dollars,
    min_volume_24h: float = SETTINGS.min_volume_24h,
    slippage_buffer: float = SETTINGS.slippage_buffer_dollars,
) -> Signal:
    quote = quote_from_market(market)
    flags: list[str] = []
    if not quote.has_two_sided_yes:
        flags.append("NO_TWO_SIDED_QUOTE")
    if quote.spread > max_spread:
        flags.append("WIDE_SPREAD")
    if quote.volume_24h < min_volume_24h:
        flags.append("LOW_VOLUME")
    if quote.yes_ask_size <= 0 and quote.no_ask_size <= 0:
        flags.append("LOW_DEPTH")

    fair = estimate_fair_probability(quote, manual_fair=manual_fair)
    yes_fee = estimate_fee_dollars(quote.yes_ask)
    no_fee = estimate_fee_dollars(quote.no_ask)
    yes_ev = fair - quote.yes_ask - yes_fee - slippage_buffer
    no_ev = (1.0 - fair) - quote.no_ask - no_fee - slippage_buffer

    if flags:
        action = "NO_TRADE"
        ev = max(yes_ev, no_ev)
        fee = yes_fee if yes_ev >= no_ev else no_fee
        reason = "Blocked by liquidity/risk filters"
    elif yes_ev >= min_edge and yes_ev >= no_ev:
        action = "BUY_YES_PAPER"
        ev = yes_ev
        fee = yes_fee
        reason = "Estimated YES edge clears fee, spread, and slippage buffers"
    elif no_ev >= min_edge:
        action = "BUY_NO_PAPER"
        ev = no_ev
        fee = no_fee
        reason = "Estimated NO edge clears fee, spread, and slippage buffers"
    else:
        action = "WATCH"
        ev = max(yes_ev, no_ev)
        fee = yes_fee if yes_ev >= no_ev else no_fee
        reason = "No fee-adjusted edge"

    price = quote.yes_ask if yes_ev >= no_ev else quote.no_ask
    roi = ev / price if price > 0 else 0.0
    return Signal(
        ticker=quote.ticker,
        title=quote.title,
        action=action,
        fair_probability=round(fair, 4),
        yes_bid=round(quote.yes_bid, 4),
        yes_ask=round(quote.yes_ask, 4),
        no_bid=round(quote.no_bid, 4),
        no_ask=round(quote.no_ask, 4),
        spread=round(quote.spread, 4),
        expected_value=round(ev, 4),
        expected_roi=round(roi, 4),
        fee_estimate=round(fee, 4),
        volume_24h=round(quote.volume_24h, 2),
        open_interest=round(quote.open_interest, 2),
        reason=reason,
        risk_flags=", ".join(flags),
        market_url=market_url(quote.event_ticker, quote.ticker),
    )


def analyze_markets(markets: list[dict[str, object]], manual_fair: dict[str, float] | None = None) -> list[dict[str, object]]:
    manual_fair = manual_fair or {}
    signals = [analyze_market(market, manual_fair=manual_fair.get(str(market.get("ticker") or ""))) for market in markets]
    return sorted((signal.to_dict() for signal in signals), key=lambda row: float(row["expected_value"]), reverse=True)

