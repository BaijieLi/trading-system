from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

import requests

from kalshi_trading_system.collectors.kalshi_public import KalshiPublicClient
from kalshi_trading_system.config import SETTINGS
from kalshi_trading_system.models.discovery import markets_from_events
from kalshi_trading_system.models.edge import ticker_market_url
from kalshi_trading_system.models.fees import estimate_fee_dollars
from kalshi_trading_system.models.orderbook import Quote, quote_from_market


NBA_CONTEXT_TERMS = ("nba", "basketball", "pro basketball")
ACTION_RANK = {
    "PAPER_BUY_YES": 4,
    "PAPER_BUY_NO": 4,
    "WATCH": 2,
    "NO_TRADE": 0,
}


@dataclass(frozen=True)
class NBAMarketEdgeConfig:
    scan_limit: int = 500
    page_limit: int = 200
    max_pages: int = 3
    candidate_limit: int = 40
    orderbook_limit: int = 30
    min_edge: float = 0.08
    max_spread: float = 0.06
    min_minutes_remaining: float = 2.0
    slippage_buffer: float = SETTINGS.slippage_buffer_dollars


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _contains_alias(text: str, aliases: set[str]) -> bool:
    clean = f" {_clean_text(text)} "
    for alias in aliases:
        clean_alias = _clean_text(alias)
        if len(clean_alias) >= 2 and f" {clean_alias} " in clean:
            return True
    return False


def _alias_count(text: str, aliases: set[str]) -> int:
    clean = f" {_clean_text(text)} "
    count = 0
    for alias in aliases:
        clean_alias = _clean_text(alias)
        if len(clean_alias) >= 2 and f" {clean_alias} " in clean:
            count += 1
    return count


def _team_aliases(code: object, name: object) -> set[str]:
    code_text = str(code or "").strip()
    name_text = str(name or "").strip()
    aliases = {code_text, name_text}
    parts = [part for part in re.split(r"\s+", name_text) if part]
    if parts:
        aliases.add(parts[-1])
    if len(parts) >= 2:
        aliases.add(" ".join(parts[-2:]))
    if len(parts) >= 3 and parts[0].lower() in {"oklahoma", "new", "golden"}:
        aliases.add(" ".join(parts[:2]))
    return {alias for alias in aliases if alias}


def _game_from_scoreboard_row(row: dict[str, object]) -> dict[str, object]:
    away = str(row.get("away") or "")
    home = str(row.get("home") or "")
    away_name = str(row.get("away_name") or away)
    home_name = str(row.get("home_name") or home)
    return {
        "game_key": f"{away}@{home}",
        "away": away,
        "away_name": away_name,
        "away_aliases": _team_aliases(away, away_name),
        "away_win_prob": _float(row.get("away_win_prob"), 0.5),
        "away_score": _float(row.get("away_score")),
        "home": home,
        "home_name": home_name,
        "home_aliases": _team_aliases(home, home_name),
        "home_win_prob": _float(row.get("home_win_prob"), 0.5),
        "home_score": _float(row.get("home_score")),
        "status": str(row.get("status") or ""),
        "period": row.get("period"),
        "clock": str(row.get("clock") or ""),
        "minutes_remaining_est": _float(row.get("minutes_remaining_est"), 48.0),
        "predicted_winner": str(row.get("predicted_winner") or ""),
        "confidence": _float(row.get("confidence"), 0.5),
    }


def _market_text(market: dict[str, Any], primary_only: bool = False) -> str:
    fields = ["title", "subtitle", "yes_sub_title"]
    if not primary_only:
        fields.extend(["event_title", "category", "event_ticker", "ticker", "series_ticker"])
    custom_strike = market.get("custom_strike")
    values = [str(market.get(field) or "") for field in fields]
    if isinstance(custom_strike, dict) and not primary_only:
        values.extend(str(value) for value in custom_strike.values())
    return " ".join(values)


def _has_nba_context(market: dict[str, Any]) -> bool:
    text = _market_text(market)
    category = _clean_text(market.get("category"))
    return category == "sports" or any(term in _clean_text(text) for term in NBA_CONTEXT_TERMS)


def _matches_game(market: dict[str, Any], game: dict[str, object]) -> bool:
    if not _has_nba_context(market):
        return False
    text = _market_text(market)
    return _contains_alias(text, game["away_aliases"]) and _contains_alias(text, game["home_aliases"])


def _infer_yes_team(market: dict[str, Any], game: dict[str, object]) -> str:
    primary = _market_text(market, primary_only=True)
    away_count = _alias_count(primary, game["away_aliases"])
    home_count = _alias_count(primary, game["home_aliases"])
    if away_count > 0 and home_count == 0:
        return str(game["away"])
    if home_count > 0 and away_count == 0:
        return str(game["home"])
    return ""


def _candidate_score(market: dict[str, Any], game: dict[str, object]) -> float:
    volume = max(0.0, _float(market.get("volume_24h_fp")))
    open_interest = max(0.0, _float(market.get("open_interest_fp")))
    yes_team = _infer_yes_team(market, game)
    side_bonus = 5.0 if yes_team else 0.0
    return 10.0 + side_bonus + math.log10(volume + open_interest + 1.0)


def candidate_nba_markets(
    markets: list[dict[str, Any]],
    scoreboard_rows: list[dict[str, object]],
    limit: int,
) -> list[dict[str, Any]]:
    games = [_game_from_scoreboard_row(row) for row in scoreboard_rows]
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for market in markets:
        ticker = str(market.get("ticker") or "")
        if not ticker:
            continue
        for game in games:
            if not _matches_game(market, game):
                continue
            key = (ticker, str(game["game_key"]))
            if key in seen:
                continue
            seen.add(key)
            row = dict(market)
            row["_nba_game"] = game
            row["_nba_candidate_score"] = _candidate_score(market, game)
            candidates.append(row)
    return sorted(candidates, key=lambda row: float(row["_nba_candidate_score"]), reverse=True)[:limit]


def _edge_row(market: dict[str, Any], config: NBAMarketEdgeConfig) -> dict[str, object]:
    game = market.get("_nba_game")
    if not isinstance(game, dict):
        game = {}
    quote = quote_from_market(market)
    yes_team = _infer_yes_team(market, game)
    yes_probability = 0.0
    if yes_team == game.get("home"):
        yes_probability = _float(game.get("home_win_prob"), 0.5)
    elif yes_team == game.get("away"):
        yes_probability = _float(game.get("away_win_prob"), 0.5)

    yes_fee = estimate_fee_dollars(quote.yes_ask)
    no_fee = estimate_fee_dollars(quote.no_ask)
    yes_edge = yes_probability - quote.yes_ask - yes_fee - config.slippage_buffer
    no_probability = 1.0 - yes_probability if yes_team else 0.0
    no_edge = no_probability - quote.no_ask - no_fee - config.slippage_buffer
    best_edge = max(yes_edge, no_edge)
    best_price = quote.yes_ask if yes_edge >= no_edge else quote.no_ask
    flags = _risk_flags(quote, game, yes_team, config)

    if flags:
        action = "NO_TRADE"
        reason = "Blocked by mapping/liquidity/timing filters"
    elif yes_edge >= config.min_edge and yes_edge >= no_edge:
        action = "PAPER_BUY_YES"
        reason = "Model probability is above fee-adjusted YES ask"
    elif no_edge >= config.min_edge:
        action = "PAPER_BUY_NO"
        reason = "Model probability is below fee-adjusted NO ask"
    else:
        action = "WATCH"
        reason = "No fee-adjusted edge yet"

    return {
        "game": game.get("game_key", ""),
        "status": game.get("status", ""),
        "period": game.get("period", ""),
        "clock": game.get("clock", ""),
        "score": f"{int(_float(game.get('away_score')))}-{int(_float(game.get('home_score')))}",
        "predicted_winner": game.get("predicted_winner", ""),
        "confidence": round(_float(game.get("confidence")), 3),
        "ticker": quote.ticker,
        "title": quote.title,
        "yes_team": yes_team or "UNKNOWN",
        "model_yes_probability": round(yes_probability, 3) if yes_team else 0.0,
        "kalshi_midpoint": round(quote.midpoint, 3),
        "yes_bid": round(quote.yes_bid, 3),
        "yes_ask": round(quote.yes_ask, 3),
        "no_bid": round(quote.no_bid, 3),
        "no_ask": round(quote.no_ask, 3),
        "spread": round(quote.spread, 3),
        "fee_adjusted_yes_edge": round(yes_edge, 3) if yes_team else 0.0,
        "fee_adjusted_no_edge": round(no_edge, 3) if yes_team else 0.0,
        "best_fee_adjusted_edge": round(best_edge, 3) if yes_team else 0.0,
        "expected_roi": round(best_edge / best_price, 3) if yes_team and best_price > 0 else 0.0,
        "volume_24h": round(quote.volume_24h, 2),
        "open_interest": round(quote.open_interest, 2),
        "action": action,
        "reason": reason,
        "risk_flags": ", ".join(flags),
        "market_url": ticker_market_url(quote.ticker),
    }


def _risk_flags(
    quote: Quote,
    game: dict[str, object],
    yes_team: str,
    config: NBAMarketEdgeConfig,
) -> list[str]:
    flags: list[str] = []
    if not yes_team:
        flags.append("CANNOT_INFER_YES_TEAM")
    if not quote.has_two_sided_yes:
        flags.append("NO_TWO_SIDED_QUOTE")
    if quote.spread > config.max_spread:
        flags.append("WIDE_SPREAD")
    status = str(game.get("status") or "").lower()
    if "final" in status:
        flags.append("GAME_FINAL")
    minutes_remaining = _float(game.get("minutes_remaining_est"), 48.0)
    if 0 < minutes_remaining <= config.min_minutes_remaining:
        flags.append("LATE_GAME_VOLATILITY")
    return flags


def analyze_nba_market_edges(
    markets: list[dict[str, Any]],
    config: NBAMarketEdgeConfig | None = None,
) -> list[dict[str, object]]:
    config = config or NBAMarketEdgeConfig()
    rows = [_edge_row(market, config) for market in markets]
    return sorted(
        rows,
        key=lambda row: (
            ACTION_RANK.get(str(row.get("action") or ""), 0),
            float(row.get("best_fee_adjusted_edge") or 0.0),
            float(row.get("volume_24h") or 0.0),
        ),
        reverse=True,
    )


def discover_nba_market_edges(
    client: KalshiPublicClient,
    scoreboard_rows: list[dict[str, object]],
    config: NBAMarketEdgeConfig | None = None,
    manual_tickers: tuple[str, ...] = (),
) -> tuple[list[dict[str, object]], dict[str, object]]:
    config = config or NBAMarketEdgeConfig()
    errors: list[str] = []
    events: list[dict[str, Any]] = []
    try:
        events = client.get_open_events(
            max_events=config.scan_limit,
            page_limit=config.page_limit,
            max_pages=config.max_pages,
        )
    except requests.RequestException as exc:
        errors.append(f"Kalshi event scan failed: {exc}")

    markets = markets_from_events(events)
    candidates = candidate_nba_markets(markets, scoreboard_rows, config.candidate_limit)
    manual_markets = _manual_candidates(client, scoreboard_rows, manual_tickers, errors)
    candidates = _dedupe_candidates([*manual_markets, *candidates])[: config.orderbook_limit]
    enriched = client.enrich_with_orderbooks(candidates)
    rows = analyze_nba_market_edges(enriched, config)
    metadata = {
        "events_scanned": len(events),
        "markets_seen": len(markets),
        "candidates": len(candidates),
        "orderbooks_loaded": len(enriched),
        "matched_edges": len(rows),
        "actionable": sum(1 for row in rows if str(row.get("action") or "").startswith("PAPER_BUY")),
        "errors": errors,
    }
    return rows, metadata


def _manual_candidates(
    client: KalshiPublicClient,
    scoreboard_rows: list[dict[str, object]],
    manual_tickers: tuple[str, ...],
    errors: list[str],
) -> list[dict[str, Any]]:
    games = [_game_from_scoreboard_row(row) for row in scoreboard_rows]
    candidates: list[dict[str, Any]] = []
    for ticker in manual_tickers:
        ticker = ticker.strip()
        if not ticker:
            continue
        try:
            market = client.get_market(ticker)
        except requests.RequestException as exc:
            errors.append(f"Manual ticker {ticker} failed: {exc}")
            continue
        for game in games:
            if _matches_game(market, game):
                row = dict(market)
                row["_nba_game"] = game
                row["_nba_candidate_score"] = _candidate_score(market, game) + 100.0
                candidates.append(row)
                break
    return candidates


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        game = candidate.get("_nba_game") or {}
        key = (str(candidate.get("ticker") or ""), str(game.get("game_key") if isinstance(game, dict) else ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return sorted(deduped, key=lambda row: float(row.get("_nba_candidate_score") or 0.0), reverse=True)
