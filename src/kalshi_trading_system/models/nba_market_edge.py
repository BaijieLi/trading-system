from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

import requests

from kalshi_trading_system.collectors.kalshi_public import KalshiPublicClient
from kalshi_trading_system.collectors.nba_live import NBA_SCOREBOARD_TIMEZONE
from kalshi_trading_system.config import SETTINGS
from kalshi_trading_system.models.discovery import markets_from_events
from kalshi_trading_system.models.edge import ticker_market_url
from kalshi_trading_system.models.fees import estimate_fee_dollars
from kalshi_trading_system.models.orderbook import Quote, quote_from_market


NBA_CONTEXT_TERMS = ("nba", "basketball", "pro basketball")
KALSHI_NBA_TEAM_CODES = {
    "ATL": "ATL",
    "BKN": "BKN",
    "BOS": "BOS",
    "CHA": "CHA",
    "CHI": "CHI",
    "CLE": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GS": "GSW",
    "GSW": "GSW",
    "HOU": "HOU",
    "IND": "IND",
    "LAC": "LAC",
    "LAL": "LAL",
    "MEM": "MEM",
    "MIA": "MIA",
    "MIL": "MIL",
    "MIN": "MIN",
    "NO": "NOP",
    "NOP": "NOP",
    "NY": "NYK",
    "NYK": "NYK",
    "OKC": "OKC",
    "ORL": "ORL",
    "PHI": "PHI",
    "PHO": "PHX",
    "PHX": "PHX",
    "POR": "POR",
    "SA": "SAS",
    "SAS": "SAS",
    "SAC": "SAC",
    "TOR": "TOR",
    "UTA": "UTA",
    "UTAH": "UTA",
    "WAS": "WAS",
    "WSH": "WAS",
}
NBA_ASSOCIATED_TICKER_RE = re.compile(r"\bKXNBA(?:GAME|TOTAL)-[A-Z0-9]+(?:-[A-Z0-9.]+)?\b")
ACTION_RANK = {
    "PAPER_BUY_YES": 4,
    "PAPER_BUY_NO": 4,
    "WATCH_TOTAL": 2,
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
        aliases.add(parts[0])
        aliases.add(parts[-1])
    if len(parts) >= 2:
        aliases.add(" ".join(parts[:-1]))
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
        "game_time_utc": str(row.get("game_time_utc") or ""),
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


def _kalshi_team_code(code: object) -> str:
    code_text = str(code or "").strip().upper()
    return KALSHI_NBA_TEAM_CODES.get(code_text, code_text)


def _kalshi_date_code(game: dict[str, object]) -> str:
    game_time = str(game.get("game_time_utc") or "").strip()
    if not game_time:
        return ""
    try:
        parsed = datetime.fromisoformat(game_time.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_date = parsed.astimezone(ZoneInfo(NBA_SCOREBOARD_TIMEZONE))
    return local_date.strftime("%y%b%d").upper()


def kalshi_nba_event_tickers(scoreboard_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    games = [_game_from_scoreboard_row(row) for row in scoreboard_rows]
    rows: list[dict[str, object]] = []
    for game in games:
        date_code = _kalshi_date_code(game)
        away_code = _kalshi_team_code(game.get("away"))
        home_code = _kalshi_team_code(game.get("home"))
        if not date_code or not away_code or not home_code:
            continue
        game_slug = f"{date_code}{away_code}{home_code}"
        game_event_ticker = f"KXNBAGAME-{game_slug}"
        total_event_ticker = f"KXNBATOTAL-{game_slug}"
        rows.append(
            {
                "game": game,
                "game_key": game["game_key"],
                "game_event_ticker": game_event_ticker,
                "total_event_ticker": total_event_ticker,
                "away_market_ticker": f"{game_event_ticker}-{away_code}",
                "home_market_ticker": f"{game_event_ticker}-{home_code}",
            }
        )
    return rows


def _associated_ticker_values(market: dict[str, Any]) -> list[str]:
    values = [
        str(market.get("ticker") or ""),
        str(market.get("event_ticker") or ""),
        str(market.get("title") or ""),
        str(market.get("event_title") or ""),
    ]
    custom_strike = market.get("custom_strike")
    if isinstance(custom_strike, dict):
        values.extend(str(value) for value in custom_strike.values())
    return values


def associated_nba_market_tickers(market: dict[str, Any], event_prefixes: set[str]) -> list[str]:
    tickers: list[str] = []
    for value in _associated_ticker_values(market):
        for match in NBA_ASSOCIATED_TICKER_RE.findall(value):
            # Event tickers have one dash. Tradable contract tickers include
            # the final side/line suffix, which is what get_market needs.
            if match.count("-") < 2:
                continue
            if any(match.startswith(f"{prefix}-") for prefix in event_prefixes):
                tickers.append(match)
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


def _fetch_market(client: KalshiPublicClient, ticker: str, errors: list[str], quiet_404: bool = True) -> dict[str, Any] | None:
    try:
        return client.get_market(ticker)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        if not (quiet_404 and status_code == 404):
            errors.append(f"{ticker} failed: {exc}")
    except requests.RequestException as exc:
        errors.append(f"{ticker} failed: {exc}")
    return None


def _total_line(market: dict[str, Any], ticker: str) -> float:
    title = str(market.get("title") or "")
    match = re.search(r"\bOver\s+(\d+(?:\.\d+)?)\b", title, flags=re.IGNORECASE)
    if match:
        return _float(match.group(1))
    suffix = ticker.rsplit("-", 1)[-1]
    value = _float(suffix, 0.0)
    if value <= 0:
        return 0.0
    if "." not in suffix:
        return value - 0.5
    return value


def _current_total(game: dict[str, object]) -> int:
    return int(_float(game.get("away_score")) + _float(game.get("home_score")))


def _pace_projected_total(game: dict[str, object]) -> float:
    current_total = _current_total(game)
    status = str(game.get("status") or "").lower()
    if "final" in status:
        return float(current_total)
    minutes_remaining = max(0.0, _float(game.get("minutes_remaining_est"), 48.0))
    elapsed = 48.0 - minutes_remaining
    if elapsed <= 1.0:
        return 0.0
    return current_total / elapsed * 48.0


def _rough_over_probability(projected_total: float, line: float, minutes_remaining: float) -> float:
    if projected_total <= 0 or line <= 0:
        return 0.0
    scale = max(6.0, 18.0 * math.sqrt(max(minutes_remaining, 0.5) / 48.0))
    return 1.0 / (1.0 + math.exp(-(projected_total - line) / scale))


def _market_type_from_ticker(ticker: str) -> str:
    if ticker.startswith("KXNBATOTAL-"):
        return "TOTAL"
    if ticker.startswith("KXNBAGAME-"):
        return "MONEYLINE"
    return "UNKNOWN"


def _side_or_line(market: dict[str, Any], game: dict[str, object], market_type: str) -> str:
    ticker = str(market.get("ticker") or "")
    if market_type == "TOTAL":
        line = _total_line(market, ticker)
        return f"YES = Over {line:g}" if line else "YES = Over"
    yes_team = _infer_yes_team(market, game)
    if yes_team:
        return f"YES = {yes_team}"
    suffix = ticker.rsplit("-", 1)[-1]
    return f"YES = {suffix}" if suffix else ""


def _raw_board_row(
    market: dict[str, Any],
    game: dict[str, object],
    config: NBAMarketEdgeConfig,
) -> dict[str, object]:
    quote = quote_from_market(market)
    market_type = _market_type_from_ticker(quote.ticker)
    edge = _edge_row(market, config) if market_type == "MONEYLINE" else {}
    line = _total_line(market, quote.ticker) if market_type == "TOTAL" else 0.0
    projected_total = _pace_projected_total(game) if market_type == "TOTAL" else 0.0
    minutes_remaining = _float(game.get("minutes_remaining_est"), 48.0)
    over_probability = _rough_over_probability(projected_total, line, minutes_remaining) if market_type == "TOTAL" else 0.0
    current_total = _current_total(game)

    if market_type == "TOTAL":
        action = "WATCH_TOTAL"
        reason = "Raw total market quote; pace projection is a rough scoreboard heuristic"
    else:
        action = str(edge.get("action") or "WATCH")
        reason = str(edge.get("reason") or "")

    return {
        "game": game.get("game_key", ""),
        "status": game.get("status", ""),
        "period": game.get("period", ""),
        "clock": game.get("clock", ""),
        "score": f"{int(_float(game.get('away_score')))}-{int(_float(game.get('home_score')))}",
        "current_total": current_total,
        "market_type": market_type,
        "side_or_line": _side_or_line(market, game, market_type),
        "ticker": quote.ticker,
        "title": quote.title,
        "kalshi_status": str(market.get("status") or ""),
        "yes_bid": round(quote.yes_bid, 3),
        "yes_ask": round(quote.yes_ask, 3),
        "no_bid": round(quote.no_bid, 3),
        "no_ask": round(quote.no_ask, 3),
        "spread": round(quote.spread, 3),
        "volume_24h": round(quote.volume_24h, 2),
        "open_interest": round(quote.open_interest, 2),
        "model_probability": edge.get("model_yes_probability", round(over_probability, 3)),
        "fee_adjusted_edge": edge.get("best_fee_adjusted_edge", 0.0),
        "projected_total": round(projected_total, 1) if projected_total else 0.0,
        "total_line": round(line, 1) if line else 0.0,
        "action": action,
        "reason": reason,
        "risk_flags": edge.get("risk_flags", ""),
        "market_url": ticker_market_url(quote.ticker),
        "hub_url": "https://kalshi.com/hubs/nba",
    }


def _game_for_ticker(
    ticker: str,
    direct_ticker_to_game: dict[str, dict[str, object]],
    event_ticker_to_game: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    if ticker in direct_ticker_to_game:
        return direct_ticker_to_game[ticker]
    for event_ticker, game in event_ticker_to_game.items():
        if ticker.startswith(f"{event_ticker}-"):
            return game
    return None


def discover_nba_raw_board(
    client: KalshiPublicClient,
    scoreboard_rows: list[dict[str, object]],
    config: NBAMarketEdgeConfig | None = None,
    manual_tickers: tuple[str, ...] = (),
) -> tuple[list[dict[str, object]], dict[str, object]]:
    config = config or NBAMarketEdgeConfig()
    errors: list[str] = []
    ticker_rows = kalshi_nba_event_tickers(scoreboard_rows)
    direct_ticker_to_game: dict[str, dict[str, object]] = {}
    event_ticker_to_game: dict[str, dict[str, object]] = {}
    direct_tickers: list[str] = []
    for row in ticker_rows:
        game = row["game"]
        if not isinstance(game, dict):
            continue
        game_event_ticker = str(row.get("game_event_ticker") or "")
        total_event_ticker = str(row.get("total_event_ticker") or "")
        event_ticker_to_game[game_event_ticker] = game
        event_ticker_to_game[total_event_ticker] = game
        for key in ("away_market_ticker", "home_market_ticker"):
            ticker = str(row.get(key) or "")
            if ticker:
                direct_tickers.append(ticker)
                direct_ticker_to_game[ticker] = game

    scanned_markets: list[dict[str, Any]] = []
    associated_tickers: list[str] = []
    event_prefixes = set(event_ticker_to_game)
    try:
        scanned_markets = client.get_open_markets(
            max_markets=config.scan_limit,
            page_limit=min(1000, max(config.page_limit, 1)),
            max_pages=config.max_pages,
        )
        for market in scanned_markets:
            associated_tickers.extend(associated_nba_market_tickers(market, event_prefixes))
    except requests.RequestException as exc:
        errors.append(f"Kalshi market scan failed: {exc}")

    all_tickers = _dedupe_tickers([*direct_tickers, *associated_tickers, *manual_tickers])
    markets: list[dict[str, Any]] = []
    for ticker in all_tickers:
        game = _game_for_ticker(ticker, direct_ticker_to_game, event_ticker_to_game)
        if game is None:
            continue
        market = _fetch_market(client, ticker, errors)
        if market is None:
            continue
        row = dict(market)
        row["_nba_game"] = game
        markets.append(row)

    markets = _dedupe_candidates(markets)
    enriched = client.enrich_with_orderbooks(markets[: config.orderbook_limit])
    rows = [_raw_board_row(market, market["_nba_game"], config) for market in enriched if isinstance(market.get("_nba_game"), dict)]
    rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("game") or ""),
            0 if row.get("market_type") == "MONEYLINE" else 1,
            -float(row.get("volume_24h") or 0.0),
        ),
    )
    metadata = {
        "scoreboard_games": len(ticker_rows),
        "markets_scanned": len(scanned_markets),
        "direct_tickers": len(_dedupe_tickers(direct_tickers)),
        "associated_tickers": len(_dedupe_tickers(associated_tickers)),
        "markets_found": len(markets),
        "orderbooks_loaded": len(enriched),
        "game_markets": sum(1 for row in rows if row.get("market_type") == "MONEYLINE"),
        "total_markets": sum(1 for row in rows if row.get("market_type") == "TOTAL"),
        "actionable": sum(1 for row in rows if str(row.get("action") or "").startswith("PAPER_BUY")),
        "errors": errors[:10],
    }
    return rows, metadata


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
