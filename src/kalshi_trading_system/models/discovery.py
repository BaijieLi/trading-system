from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from kalshi_trading_system.collectors.kalshi_public import KalshiPublicClient
from kalshi_trading_system.config import SETTINGS
from kalshi_trading_system.models.edge import analyze_markets


ACTION_SCORE = {
    "BUY_YES_PAPER": 4.0,
    "BUY_NO_PAPER": 4.0,
    "WATCH": 2.0,
    "NO_TRADE": 0.0,
}


@dataclass(frozen=True)
class DiscoveryConfig:
    scan_limit: int = SETTINGS.discovery_scan_limit
    candidate_limit: int = SETTINGS.discovery_candidate_limit
    final_limit: int = SETTINGS.discovery_final_limit
    page_limit: int = SETTINGS.discovery_page_limit
    max_pages: int = SETTINGS.discovery_max_pages
    min_volume_24h: float = SETTINGS.discovery_min_volume_24h
    min_open_interest: float = SETTINGS.discovery_min_open_interest
    include_combo_markets: bool = SETTINGS.discovery_include_combo_markets


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _series_ticker(market: dict[str, Any]) -> str:
    ticker = str(market.get("ticker") or "")
    return str(market.get("series_ticker") or ticker.split("-", 1)[0])


def _is_combo_market(market: dict[str, Any]) -> bool:
    custom_strike = market.get("custom_strike")
    if isinstance(custom_strike, dict) and (
        custom_strike.get("Associated Markets") or custom_strike.get("Associated Events")
    ):
        return True
    return "CROSSCATEGORY" in str(market.get("ticker") or "")


def liquidity_score(market: dict[str, Any]) -> float:
    volume = max(0.0, _float(market.get("volume_24h_fp")))
    open_interest = max(0.0, _float(market.get("open_interest_fp")))
    return round((2.0 * math.log10(volume + 1.0)) + math.log10(open_interest + 1.0), 4)


def prefilter_markets(markets: list[dict[str, Any]], config: DiscoveryConfig) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for market in markets:
        ticker = str(market.get("ticker") or "")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        if not config.include_combo_markets and _is_combo_market(market):
            continue
        volume = _float(market.get("volume_24h_fp"))
        open_interest = _float(market.get("open_interest_fp"))
        if volume < config.min_volume_24h and open_interest < config.min_open_interest:
            continue
        row = dict(market)
        row["liquidity_score"] = liquidity_score(market)
        filtered.append(row)
    return sorted(filtered, key=lambda row: float(row["liquidity_score"]), reverse=True)


def markets_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = []
    for event in events:
        for market in event.get("markets") or []:
            row = dict(market)
            row.setdefault("event_ticker", event.get("event_ticker"))
            row.setdefault("series_ticker", event.get("series_ticker"))
            row.setdefault("event_title", event.get("title"))
            row.setdefault("category", event.get("category"))
            markets.append(row)
    return markets


def quote_quality_score(signal: dict[str, object]) -> float:
    flags = str(signal.get("risk_flags") or "")
    spread = max(0.0, _float(signal.get("spread")))
    volume = max(0.0, _float(signal.get("volume_24h")))
    open_interest = max(0.0, _float(signal.get("open_interest")))
    spread_score = max(0.0, 1.0 - spread / max(SETTINGS.max_spread_dollars, 0.01)) * 3.0
    depth_score = min(2.0, math.log10(volume + open_interest + 1.0) / 2.0)
    flag_penalty = 0.75 * len([flag for flag in flags.split(",") if flag.strip()])
    return round(max(0.0, spread_score + depth_score - flag_penalty), 4)


def discovery_score(signal: dict[str, object]) -> float:
    ev = _float(signal.get("expected_value"))
    action = str(signal.get("action") or "")
    liquidity = _float(signal.get("liquidity_score"))
    quality = quote_quality_score(signal)
    ev_bonus = max(0.0, ev) * 25.0
    return round(ACTION_SCORE.get(action, 0.0) + liquidity + quality + ev_bonus, 4)


def rank_discovered_signals(signals: list[dict[str, object]], final_limit: int) -> list[dict[str, object]]:
    for signal in signals:
        signal["quote_quality_score"] = quote_quality_score(signal)
        signal["discovery_score"] = discovery_score(signal)
    return sorted(
        signals,
        key=lambda row: (
            float(row.get("discovery_score") or 0.0),
            float(row.get("expected_value") or 0.0),
            float(row.get("volume_24h") or 0.0),
        ),
        reverse=True,
    )[:final_limit]


def discover_market_signals(
    client: KalshiPublicClient | None = None,
    config: DiscoveryConfig | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    client = client or KalshiPublicClient()
    config = config or DiscoveryConfig()
    events = client.get_open_events(
        max_events=config.scan_limit,
        page_limit=config.page_limit,
        max_pages=config.max_pages,
    )
    markets = markets_from_events(events)
    candidates = prefilter_markets(markets, config)[: config.candidate_limit]
    enriched = client.enrich_with_orderbooks(candidates)
    signals = analyze_markets(enriched)
    by_ticker = {str(market.get("ticker") or ""): market for market in candidates}
    for signal in signals:
        source_market = by_ticker.get(str(signal.get("ticker") or ""), {})
        signal["series_ticker"] = _series_ticker(source_market)
        signal["liquidity_score"] = _float(source_market.get("liquidity_score"))
    ranked = rank_discovered_signals(signals, final_limit=config.final_limit)
    metadata = {
        "mode": "discover",
        "events_seen": len(events),
        "markets_seen": len(markets),
        "candidates": len(candidates),
        "orderbooks_loaded": len(enriched),
        "final_limit": config.final_limit,
        "scan_limit": config.scan_limit,
    }
    return ranked, metadata
