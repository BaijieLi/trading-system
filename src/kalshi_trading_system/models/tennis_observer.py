from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import requests

from kalshi_trading_system.collectors.kalshi_public import KalshiPublicClient
from kalshi_trading_system.models.edge import ticker_market_url
from kalshi_trading_system.models.orderbook import Quote, quote_from_market


TENNIS_SERIES_PREFIXES = {
    "KXATPMATCH",
    "KXWTAMATCH",
    "KXATPCHALLENGERMATCH",
    "KXWTACHALLENGERMATCH",
    "KXITFMATCH",
    "KXITFWMATCH",
    "KXATPGTOTAL",
    "KXWTAGTOTAL",
    "KXATPSETWINNER",
    "KXWTASETWINNER",
}
TENNIS_TERMS = (
    "tennis",
    "atp",
    "wta",
    "itf",
    "grand slam",
    "australian open",
    "french open",
    "wimbledon",
    "us open",
)


@dataclass(frozen=True)
class TennisObserverConfig:
    scan_limit: int = 2500
    page_limit: int = 1000
    max_pages: int = 3
    candidate_limit: int = 120
    orderbook_limit: int = 40
    max_spread: float = 0.06
    min_volume_24h: float = 1000.0
    min_open_interest: float = 1000.0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _series(ticker: object) -> str:
    return str(ticker or "").split("-", 1)[0].upper()


def is_tennis_ticker(ticker: object) -> bool:
    return _series(ticker) in TENNIS_SERIES_PREFIXES


def _market_text(market: dict[str, Any]) -> str:
    values = [
        str(market.get("ticker") or ""),
        str(market.get("event_ticker") or ""),
        str(market.get("series_ticker") or ""),
        str(market.get("title") or ""),
        str(market.get("subtitle") or ""),
        str(market.get("event_title") or ""),
        str(market.get("category") or ""),
    ]
    custom_strike = market.get("custom_strike")
    if isinstance(custom_strike, dict):
        values.extend(str(value) for value in custom_strike.values())
    return " ".join(values).lower()


def _looks_tennis_related(market: dict[str, Any]) -> bool:
    ticker = str(market.get("ticker") or "")
    if is_tennis_ticker(ticker):
        return True
    text = _market_text(market)
    return any(term in text for term in TENNIS_TERMS)


def associated_tennis_tickers(market: dict[str, Any]) -> list[str]:
    custom_strike = market.get("custom_strike")
    if not isinstance(custom_strike, dict):
        return []
    associated = str(custom_strike.get("Associated Markets") or "")
    tickers: list[str] = []
    for value in associated.split(","):
        ticker = value.strip().upper()
        if ticker and is_tennis_ticker(ticker):
            tickers.append(ticker)
    return _dedupe_tickers(tickers)


def _dedupe_tickers(tickers: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for ticker in tickers:
        ticker = str(ticker or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        deduped.append(ticker)
    return deduped


def _fetch_market(client: KalshiPublicClient, ticker: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        return client.get_market(ticker)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code != 404:
            errors.append(f"{ticker} failed: {exc}")
    except requests.RequestException as exc:
        errors.append(f"{ticker} failed: {exc}")
    return None


def _stability_score(quote: Quote, config: TennisObserverConfig) -> float:
    if not quote.has_two_sided_yes:
        return 0.0
    spread_score = max(0.0, 1.0 - quote.spread / max(config.max_spread, 0.01)) * 45.0
    liquidity_score = min(35.0, math.log10(quote.volume_24h + quote.open_interest + 1.0) * 7.0)
    midpoint = quote.midpoint
    balance_score = max(0.0, 1.0 - abs(midpoint - 0.5) * 1.5) * 20.0
    return round(spread_score + liquidity_score + balance_score, 1)


def _risk_flags(quote: Quote, market: dict[str, Any], config: TennisObserverConfig) -> list[str]:
    flags: list[str] = ["NO_INDEPENDENT_TENNIS_MODEL"]
    if not quote.has_two_sided_yes:
        flags.append("NO_TWO_SIDED_QUOTE")
    if quote.spread > config.max_spread:
        flags.append("WIDE_SPREAD")
    if quote.volume_24h < config.min_volume_24h:
        flags.append("LOW_VOLUME")
    if quote.open_interest < config.min_open_interest:
        flags.append("LOW_OPEN_INTEREST")
    if quote.yes_ask >= 0.95 or quote.yes_ask <= 0.05:
        flags.append("EXTREME_PRICE")
    status = str(market.get("status") or "").lower()
    if status and status not in {"active", "open"}:
        flags.append(f"STATUS_{status.upper()}")
    return flags


def _row_from_market(market: dict[str, Any], config: TennisObserverConfig) -> dict[str, object]:
    quote = quote_from_market(market)
    flags = _risk_flags(quote, market, config)
    hard_flags = set(flags) - {"NO_INDEPENDENT_TENNIS_MODEL"}
    action = "WATCH_LIQUID" if not hard_flags else "NO_TRADE"
    reason = (
        "Narrow/liquid tennis quote; observation only until you have an external model"
        if action == "WATCH_LIQUID"
        else "Blocked by tennis volatility, liquidity, spread, or missing independent model"
    )
    return {
        "series_ticker": _series(quote.ticker),
        "ticker": quote.ticker,
        "title": quote.title,
        "action": action,
        "stability_score": _stability_score(quote, config),
        "yes_bid": round(quote.yes_bid, 3),
        "yes_ask": round(quote.yes_ask, 3),
        "no_bid": round(quote.no_bid, 3),
        "no_ask": round(quote.no_ask, 3),
        "spread": round(quote.spread, 3),
        "midpoint": round(quote.midpoint, 3),
        "volume_24h": round(quote.volume_24h, 2),
        "open_interest": round(quote.open_interest, 2),
        "kalshi_status": str(market.get("status") or ""),
        "reason": reason,
        "risk_flags": ", ".join(flags),
        "market_url": ticker_market_url(quote.ticker),
        "hub_url": "https://kalshi.com/hubs/tennis",
    }


def discover_tennis_watchlist(
    client: KalshiPublicClient,
    config: TennisObserverConfig | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    config = config or TennisObserverConfig()
    errors: list[str] = []
    scanned: list[dict[str, Any]] = []
    try:
        scanned = client.get_open_markets(
            max_markets=config.scan_limit,
            page_limit=config.page_limit,
            max_pages=config.max_pages,
        )
    except requests.RequestException as exc:
        return [], {
            "markets_scanned": 0,
            "candidate_tickers": 0,
            "markets_found": 0,
            "orderbooks_loaded": 0,
            "watch_liquid": 0,
            "errors": [f"Kalshi tennis scan failed: {exc}"],
        }

    candidate_tickers: list[str] = []
    direct_markets: list[dict[str, Any]] = []
    for market in scanned:
        if not _looks_tennis_related(market):
            continue
        ticker = str(market.get("ticker") or "").strip().upper()
        if is_tennis_ticker(ticker):
            candidate_tickers.append(ticker)
            direct_markets.append(market)
        candidate_tickers.extend(associated_tennis_tickers(market))

    candidate_tickers = _dedupe_tickers(candidate_tickers)[: config.candidate_limit]
    direct_by_ticker = {str(market.get("ticker") or "").upper(): market for market in direct_markets}
    markets: list[dict[str, Any]] = []
    for ticker in candidate_tickers:
        market = direct_by_ticker.get(ticker) or _fetch_market(client, ticker, errors)
        if market:
            markets.append(dict(market))

    markets = _dedupe_markets(markets)
    markets = sorted(
        markets,
        key=lambda market: (_float(market.get("volume_24h_fp")) + _float(market.get("open_interest_fp"))),
        reverse=True,
    )[: config.orderbook_limit]
    enriched = client.enrich_with_orderbooks(markets)
    rows = [_row_from_market(market, config) for market in enriched]
    rows = sorted(
        rows,
        key=lambda row: (
            1 if row.get("action") == "WATCH_LIQUID" else 0,
            float(row.get("stability_score") or 0.0),
            float(row.get("volume_24h") or 0.0),
        ),
        reverse=True,
    )
    metadata = {
        "markets_scanned": len(scanned),
        "candidate_tickers": len(candidate_tickers),
        "markets_found": len(markets),
        "orderbooks_loaded": len(enriched),
        "watch_liquid": sum(1 for row in rows if row.get("action") == "WATCH_LIQUID"),
        "errors": errors[:10],
    }
    return rows, metadata


def _dedupe_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for market in markets:
        ticker = str(market.get("ticker") or "")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        deduped.append(market)
    return deduped
