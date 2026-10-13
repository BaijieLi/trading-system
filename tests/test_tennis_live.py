from __future__ import annotations

import json

from kalshi_trading_system.models.tennis_live import parse_tennis_live_payload


def sample_tennis_html(include_live_score: bool = True) -> str:
    card_feed = {
        "pages": [
            {
                "sections": [
                    {
                        "is_live": True,
                        "items": [{"event_ticker": "KXATPMATCH-26OCT13TEST"}],
                    }
                ],
                "hydrated_data": {
                    "cards": {
                        "KXATPMATCH-26OCT13TEST": {
                            "event_title": "Player One vs Player Two",
                            "general_title_super": "ATP Test",
                            "series_ticker": "KXATPMATCH",
                            "event_ticker": "KXATPMATCH-26OCT13TEST",
                            "milestone_id": "match-1",
                            "recent_event_volume": 123400,
                            "total_event_volume": 456700,
                            "start_date": "2026-10-13T17:00:00Z",
                            "markets": [
                                {
                                    "ticker": "KXATPMATCH-26OCT13TEST-ONE",
                                    "title": "Player One",
                                    "yes_bid": 50,
                                    "yes_ask": 52,
                                    "associated_structured_targets": {"tennis_competitor": "p1"},
                                },
                                {
                                    "ticker": "KXATPMATCH-26OCT13TEST-TWO",
                                    "title": "Player Two",
                                    "yes_bid": 48,
                                    "yes_ask": 50,
                                    "associated_structured_targets": {"tennis_competitor": "p2"},
                                },
                            ],
                        }
                    }
                },
            }
        ]
    }
    live_data = {}
    if include_live_score:
        live_data = {
            "match-1": {
                "details": {
                    "status": "live",
                    "match_status": "2nd_set",
                    "widget_status": "live",
                    "competitor1_id": "p1",
                    "competitor2_id": "p2",
                    "server": "p1",
                    "competitor1_overall_score": 1,
                    "competitor2_overall_score": 0,
                    "competitor1_current_round_score": "40",
                    "competitor2_current_round_score": "15",
                    "competitor1_round_scores": [{"score": 6}, {"score": 4}],
                    "competitor2_round_scores": [{"score": 3}, {"score": 2}],
                }
            }
        }
    return (
        "<script>"
        f'"initialCardFeedData":{json.dumps(card_feed)},'
        f'"initialLiveData":{json.dumps(live_data)}'
        "</script>"
    )


def test_parse_tennis_live_payload_extracts_live_scores_and_quotes() -> None:
    rows, metadata = parse_tennis_live_payload(sample_tennis_html())

    assert metadata["live_events_listed"] == 1
    assert metadata["cards_loaded"] == 1
    assert metadata["live_scores_loaded"] == 1
    assert metadata["rows"] == 2
    first = rows[0]
    assert first["match"] == "Player One vs Player Two"
    assert first["competition"] == "ATP Test"
    assert first["sets"] == "6-3 4-2"
    assert first["current_game"] == "40-15"
    assert first["server"] == "yes"
    assert first["yes_bid"] == 0.5
    assert first["yes_ask"] == 0.52
    assert first["no_ask"] == 0.5
    assert first["paper_action"] == "BUY_YES_PAPER"
    assert first["paper_edge"] > 0
    assert "HEURISTIC_ONLY" in str(first["risk_flags"])


def test_parse_tennis_live_payload_can_emit_buy_no_paper() -> None:
    rows, metadata = parse_tennis_live_payload(sample_tennis_html())

    assert metadata["paper_actionable"] == 2
    player_two = next(row for row in rows if row["player"] == "Player Two")
    assert player_two["paper_action"] == "BUY_NO_PAPER"
    assert player_two["paper_edge"] > 0


def test_parse_tennis_live_payload_blocks_when_score_missing() -> None:
    rows, metadata = parse_tennis_live_payload(sample_tennis_html(include_live_score=False))

    assert metadata["live_scores_loaded"] == 0
    assert rows[0]["paper_action"] == "NO_TRADE"
    assert "NO_LIVE_SCORE" in str(rows[0]["risk_flags"])
