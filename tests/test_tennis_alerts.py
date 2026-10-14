from __future__ import annotations

from kalshi_trading_system.models.tennis_alerts import detect_tennis_live_changes


def test_detect_tennis_live_changes_reports_score_price_and_action_moves() -> None:
    previous = [
        {
            "match": "Player One vs Player Two",
            "player": "Player One",
            "ticker": "KXTEST-ONE",
            "sets": "6-4 1-2",
            "current_game": "30-15",
            "server": "yes",
            "live_status": "live",
            "paper_action": "WATCH_LIVE",
            "paper_edge": 0.01,
            "score_fair_probability": 0.54,
            "yes_ask": 0.52,
            "market_url": "https://kalshi.com/markets/kxtest-one",
        }
    ]
    current = [
        {
            "match": "Player One vs Player Two",
            "player": "Player One",
            "ticker": "KXTEST-ONE",
            "sets": "6-4 2-2",
            "current_game": "40-15",
            "server": "yes",
            "live_status": "live",
            "paper_action": "BUY_YES_PAPER",
            "paper_edge": 0.08,
            "score_fair_probability": 0.63,
            "yes_ask": 0.55,
            "market_url": "https://kalshi.com/markets/kxtest-one",
        }
    ]

    alerts = detect_tennis_live_changes(previous, current, probability_threshold=0.05, edge_threshold=0.03)

    assert len(alerts) == 1
    assert alerts[0]["ticker"] == "KXTEST-ONE"
    assert alerts[0]["paper_action"] == "BUY_YES_PAPER"
    assert "score: 6-4 1-2 -> 6-4 2-2" in str(alerts[0]["changes"])
    assert "game: 30-15 -> 40-15" in str(alerts[0]["changes"])
    assert "action: WATCH_LIVE -> BUY_YES_PAPER" in str(alerts[0]["changes"])
    assert "probability: 0.54 -> 0.63" in str(alerts[0]["changes"])
    assert "edge: 0.010 -> 0.080" in str(alerts[0]["changes"])


def test_detect_tennis_live_changes_respects_thresholds() -> None:
    previous = [
        {
            "ticker": "KXTEST-ONE",
            "sets": "6-4",
            "current_game": "30-15",
            "paper_action": "WATCH_LIVE",
            "paper_edge": 0.01,
            "score_fair_probability": 0.54,
            "yes_ask": 0.52,
        }
    ]
    current = [
        {
            "ticker": "KXTEST-ONE",
            "sets": "6-4",
            "current_game": "30-15",
            "paper_action": "WATCH_LIVE",
            "paper_edge": 0.02,
            "score_fair_probability": 0.55,
            "yes_ask": 0.53,
        }
    ]

    alerts = detect_tennis_live_changes(previous, current, probability_threshold=0.05, edge_threshold=0.03)

    assert alerts == []


def test_detect_tennis_live_changes_uses_existing_rows_as_baseline() -> None:
    current = [
        {
            "ticker": "KXTEST-ONE",
            "sets": "6-4",
            "current_game": "30-15",
            "paper_action": "BUY_YES_PAPER",
            "paper_edge": 0.08,
            "score_fair_probability": 0.63,
        }
    ]

    alerts = detect_tennis_live_changes([], current)

    assert alerts == []
