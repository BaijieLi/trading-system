from __future__ import annotations

import json
import re
from typing import Any

import requests

from kalshi_trading_system.config import SETTINGS
from kalshi_trading_system.models.edge import ticker_market_url
from kalshi_trading_system.models.fees import estimate_fee_dollars


KALSHI_TENNIS_URL = "https://kalshi.com/category/sports/tennis"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (kalshi-trading-system tennis live board)",
}
POINT_VALUES = {"0": 0, "15": 1, "30": 2, "40": 3, "AD": 4, "A": 4}


def _decode_page_payload(html: str) -> str:
    return html.replace('\\"', '"').replace("\\u0026", "&").replace("\\/", "/")


def _extract_object_at(text: str, brace_start: int) -> str:
    depth = 0
    in_string = False
    escaped = False
    for index in range(brace_start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start : index + 1]
    raise ValueError("Could not find matching JSON object close brace.")


def _extract_object_after_key(text: str, key: str) -> dict[str, Any]:
    marker = f'"{key}":'
    objects: list[dict[str, Any]] = []
    start = 0
    while True:
        start = text.find(marker, start)
        if start < 0:
            break
        index = start + len(marker)
        while index < len(text) and text[index].isspace():
            index += 1
        start = index + 1
        if index >= len(text) or text[index] != "{":
            continue
        try:
            value = json.loads(_extract_object_at(text, index))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            objects.append(value)
    if not objects:
        return {}
    return max(objects, key=lambda value: len(json.dumps(value)))


def _to_probability(cents: object) -> float:
    try:
        value = float(cents)
    except (TypeError, ValueError):
        return 0.0
    return round(value / 100.0 if value > 1 else value, 4)


def _point_value(value: object) -> int:
    text = str(value or "0").upper()
    if text in POINT_VALUES:
        return POINT_VALUES[text]
    try:
        return int(float(text))
    except ValueError:
        return 0


def _score_text(round_scores: list[dict[str, Any]]) -> str:
    values: list[str] = []
    for score in round_scores:
        game_score = str(score.get("score") if score.get("score") is not None else "")
        tiebreak = score.get("tiebreak_score")
        if tiebreak is not None:
            game_score = f"{game_score}({tiebreak})"
        values.append(game_score)
    return " ".join(values)


def _set_pair_text(first_scores: list[dict[str, Any]], second_scores: list[dict[str, Any]]) -> str:
    pairs: list[str] = []
    for first, second in zip(first_scores, second_scores, strict=False):
        first_score = str(first.get("score") if first.get("score") is not None else "")
        second_score = str(second.get("score") if second.get("score") is not None else "")
        first_tb = first.get("tiebreak_score")
        second_tb = second.get("tiebreak_score")
        if first_tb is not None:
            first_score = f"{first_score}({first_tb})"
        if second_tb is not None:
            second_score = f"{second_score}({second_tb})"
        pairs.append(f"{first_score}-{second_score}")
    return " ".join(pairs)


def _status_text(details: dict[str, Any]) -> str:
    values = [details.get("status"), details.get("match_status"), details.get("widget_status")]
    return " / ".join(str(value) for value in values if value)


def _has_live_score(details: dict[str, Any]) -> bool:
    return bool(
        details.get("competitor1_round_scores")
        or details.get("competitor2_round_scores")
        or details.get("competitor1_current_round_score") is not None
        or details.get("competitor2_current_round_score") is not None
    )


def _score_probability(
    market_midpoint: float,
    details: dict[str, Any] | None,
    competitor_id: str,
) -> float:
    if not details:
        return market_midpoint
    if competitor_id == str(details.get("competitor1_id") or ""):
        own_prefix, opp_prefix = "competitor1", "competitor2"
    elif competitor_id == str(details.get("competitor2_id") or ""):
        own_prefix, opp_prefix = "competitor2", "competitor1"
    else:
        return market_midpoint

    own_sets = int(details.get(f"{own_prefix}_overall_score") or 0)
    opp_sets = int(details.get(f"{opp_prefix}_overall_score") or 0)
    own_rounds = details.get(f"{own_prefix}_round_scores") or []
    opp_rounds = details.get(f"{opp_prefix}_round_scores") or []
    own_current_games = int((own_rounds[-1] or {}).get("score") or 0) if own_rounds else 0
    opp_current_games = int((opp_rounds[-1] or {}).get("score") or 0) if opp_rounds else 0
    own_points = _point_value(details.get(f"{own_prefix}_current_round_score"))
    opp_points = _point_value(details.get(f"{opp_prefix}_current_round_score"))
    server_bonus = 0.015 if competitor_id == str(details.get("server") or "") else -0.005
    adjustment = (
        0.12 * (own_sets - opp_sets)
        + 0.03 * (own_current_games - opp_current_games)
        + 0.012 * (own_points - opp_points)
        + server_bonus
    )
    return round(max(0.02, min(0.98, market_midpoint + adjustment)), 4)


def _paper_action(
    fair_probability: float,
    yes_bid: float,
    yes_ask: float,
    spread: float,
    has_live_score: bool,
) -> tuple[str, float, str]:
    flags: list[str] = ["HEURISTIC_ONLY"]
    if not has_live_score:
        flags.append("NO_LIVE_SCORE")
    if not yes_bid or not yes_ask:
        flags.append("NO_TWO_SIDED_QUOTE")
    if yes_bid and yes_ask and yes_ask < yes_bid:
        flags.append("CROSSED_QUOTE")
    if spread > SETTINGS.max_spread_dollars:
        flags.append("WIDE_SPREAD")
    buy_edge = fair_probability - yes_ask - estimate_fee_dollars(yes_ask) - SETTINGS.slippage_buffer_dollars
    buy_no_price = max(0.0, min(1.0, 1.0 - yes_bid))
    buy_no_edge = (1.0 - fair_probability) - buy_no_price - estimate_fee_dollars(buy_no_price) - SETTINGS.slippage_buffer_dollars
    if len(flags) > 1:
        return "NO_TRADE", 0.0, ", ".join(flags)
    if buy_edge >= SETTINGS.min_edge_dollars:
        return "BUY_YES_PAPER", round(buy_edge, 4), ", ".join(flags)
    if buy_no_edge >= SETTINGS.min_edge_dollars:
        return "BUY_NO_PAPER", round(buy_no_edge, 4), ", ".join(flags)
    return "WATCH_LIVE", round(max(buy_edge, buy_no_edge), 4), ", ".join(flags)


def _row_from_market(
    card: dict[str, Any],
    market: dict[str, Any],
    live_data: dict[str, Any] | None,
) -> dict[str, object]:
    details = live_data.get("details") if live_data else None
    details = details if isinstance(details, dict) else {}
    competitor_id = str((market.get("associated_structured_targets") or {}).get("tennis_competitor") or "")
    first_scores = details.get("competitor1_round_scores") if isinstance(details.get("competitor1_round_scores"), list) else []
    second_scores = details.get("competitor2_round_scores") if isinstance(details.get("competitor2_round_scores"), list) else []
    yes_bid = _to_probability(market.get("yes_bid"))
    yes_ask = _to_probability(market.get("yes_ask"))
    no_bid = _to_probability(market.get("no_bid")) or round(max(0.0, 1.0 - yes_ask), 4)
    no_ask = _to_probability(market.get("no_ask")) or round(max(0.0, 1.0 - yes_bid), 4)
    midpoint = round((yes_bid + yes_ask) / 2.0, 4) if yes_bid and yes_ask else _to_probability(market.get("price"))
    spread = round(yes_ask - yes_bid, 4) if yes_ask >= yes_bid else 1.0
    fair_probability = _score_probability(midpoint, details, competitor_id)
    action, edge, flags = _paper_action(fair_probability, yes_bid, yes_ask, spread, _has_live_score(details))
    server = "yes" if competitor_id and competitor_id == str(details.get("server") or "") else ""
    return {
        "match": card.get("event_title") or "",
        "competition": card.get("general_title_super") or "",
        "series_ticker": card.get("series_ticker") or "",
        "event_ticker": card.get("event_ticker") or "",
        "ticker": market.get("ticker") or "",
        "player": market.get("title") or "",
        "live_status": _status_text(details),
        "sets": _set_pair_text(first_scores, second_scores),
        "player_sets": _score_text(first_scores if competitor_id == str(details.get("competitor1_id") or "") else second_scores),
        "current_game": f"{details.get('competitor1_current_round_score', '')}-{details.get('competitor2_current_round_score', '')}",
        "server": server,
        "kalshi_mid": midpoint,
        "score_fair_probability": fair_probability,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "spread": spread,
        "paper_action": action,
        "paper_edge": edge,
        "risk_flags": flags,
        "recent_event_volume": round(float(card.get("recent_event_volume") or 0) / 100.0, 2),
        "total_event_volume": round(float(card.get("total_event_volume") or 0) / 100.0, 2),
        "start_date": card.get("start_date") or "",
        "market_url": ticker_market_url(market.get("ticker")),
        "hub_url": KALSHI_TENNIS_URL,
    }


def parse_tennis_live_payload(html: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    text = _decode_page_payload(html)
    card_feed = _extract_object_after_key(text, "initialCardFeedData")
    live_data = _extract_object_after_key(text, "initialLiveData")
    pages = card_feed.get("pages") if isinstance(card_feed.get("pages"), list) else []
    page = pages[0] if pages and isinstance(pages[0], dict) else {}
    hydrated = page.get("hydrated_data") if isinstance(page.get("hydrated_data"), dict) else {}
    cards = hydrated.get("cards") if isinstance(hydrated.get("cards"), dict) else {}
    milestones = hydrated.get("milestones") if isinstance(hydrated.get("milestones"), dict) else {}
    sections = page.get("sections") if isinstance(page.get("sections"), list) else []
    live_items = [
        item
        for section in sections
        if section.get("is_live")
        for item in (section.get("items") or [])
        if isinstance(item, dict) and item.get("event_ticker")
    ]
    live_by_milestone = {
        str(value.get("milestone_id") or key): value
        for key, value in live_data.items()
        if isinstance(value, dict)
    }
    rows: list[dict[str, object]] = []
    for event_ticker, card in cards.items():
        if not isinstance(card, dict):
            continue
        markets = card.get("markets") if isinstance(card.get("markets"), list) else []
        milestone_id = str(card.get("milestone_id") or "")
        live = live_by_milestone.get(milestone_id) or milestones.get(milestone_id)
        for market in markets:
            if isinstance(market, dict):
                rows.append(_row_from_market(card, market, live))
    rows = sorted(
        rows,
        key=lambda row: (
            1 if row.get("live_status") else 0,
            {"BUY_YES_PAPER": 3, "BUY_NO_PAPER": 3, "WATCH_LIVE": 1}.get(str(row.get("paper_action")), 0),
            float(row.get("paper_edge") or -1.0),
            float(row.get("recent_event_volume") or 0.0),
        ),
        reverse=True,
    )
    metadata = {
        "source": KALSHI_TENNIS_URL,
        "live_events_listed": len(live_items),
        "cards_loaded": len(cards),
        "live_scores_loaded": len(live_data),
        "rows": len(rows),
        "paper_actionable": sum(1 for row in rows if row.get("paper_action") in {"BUY_YES_PAPER", "BUY_NO_PAPER"}),
    }
    return rows, metadata


def fetch_tennis_live_board(url: str = KALSHI_TENNIS_URL, timeout: int = 20) -> tuple[list[dict[str, object]], dict[str, object]]:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    rows, metadata = parse_tennis_live_payload(response.text)
    metadata["http_status"] = response.status_code
    return rows, metadata
