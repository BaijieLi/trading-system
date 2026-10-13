from __future__ import annotations

from kalshi_trading_system.models.nba_market_edge import (
    NBAMarketEdgeConfig,
    analyze_nba_market_edges,
    candidate_nba_markets,
    discover_nba_market_edges,
)


def scoreboard_row() -> dict[str, object]:
    return {
        "away": "OKC",
        "away_name": "Oklahoma City Thunder",
        "away_score": 81,
        "away_win_prob": 0.25,
        "home": "ATL",
        "home_name": "Atlanta Hawks",
        "home_score": 87,
        "home_win_prob": 0.75,
        "status": "In Progress",
        "period": 4,
        "clock": "9:10",
        "minutes_remaining_est": 9.17,
        "predicted_winner": "ATL",
        "confidence": 0.75,
    }


def liquid_market(title: str = "Will the Atlanta Hawks win?") -> dict[str, object]:
    return {
        "ticker": "KXNBA-OKCATL-ATL",
        "event_ticker": "KXNBA-OKCATL",
        "event_title": "OKC Thunder vs ATL Hawks",
        "series_ticker": "KXNBA",
        "category": "Sports",
        "title": title,
        "yes_bid_dollars": "0.50",
        "yes_ask_dollars": "0.55",
        "no_bid_dollars": "0.44",
        "no_ask_dollars": "0.50",
        "yes_ask_size_fp": "100",
        "volume_24h_fp": "1200",
        "open_interest_fp": "800",
    }


def test_candidate_nba_markets_requires_both_teams() -> None:
    markets = [
        liquid_market(),
        {
            **liquid_market("Will the Atlanta Hawks make the playoffs?"),
            "event_title": "Atlanta Hawks season markets",
        },
    ]

    candidates = candidate_nba_markets(markets, [scoreboard_row()], limit=10)

    assert [candidate["ticker"] for candidate in candidates] == ["KXNBA-OKCATL-ATL"]


def test_analyze_nba_market_edges_detects_fee_adjusted_yes_edge() -> None:
    candidate = liquid_market()
    candidate["_nba_game"] = {
        "game_key": "OKC@ATL",
        "away": "OKC",
        "away_aliases": {"OKC", "Oklahoma City Thunder", "Thunder"},
        "away_win_prob": 0.25,
        "away_score": 81,
        "home": "ATL",
        "home_aliases": {"ATL", "Atlanta Hawks", "Hawks"},
        "home_win_prob": 0.75,
        "home_score": 87,
        "status": "In Progress",
        "period": 4,
        "clock": "9:10",
        "minutes_remaining_est": 9.17,
        "predicted_winner": "ATL",
        "confidence": 0.75,
    }

    rows = analyze_nba_market_edges([candidate], NBAMarketEdgeConfig(min_edge=0.08, max_spread=0.08))

    assert rows[0]["action"] == "PAPER_BUY_YES"
    assert rows[0]["yes_team"] == "ATL"
    assert rows[0]["fee_adjusted_yes_edge"] > 0.08


def test_analyze_nba_market_edges_blocks_ambiguous_yes_team() -> None:
    candidate = liquid_market("OKC Thunder vs ATL Hawks")
    candidate["_nba_game"] = {
        "game_key": "OKC@ATL",
        "away": "OKC",
        "away_aliases": {"OKC", "Oklahoma City Thunder", "Thunder"},
        "away_win_prob": 0.25,
        "home": "ATL",
        "home_aliases": {"ATL", "Atlanta Hawks", "Hawks"},
        "home_win_prob": 0.75,
        "status": "In Progress",
        "minutes_remaining_est": 9.17,
    }

    rows = analyze_nba_market_edges([candidate], NBAMarketEdgeConfig(max_spread=0.08))

    assert rows[0]["action"] == "NO_TRADE"
    assert "CANNOT_INFER_YES_TEAM" in rows[0]["risk_flags"]


def test_discover_nba_market_edges_uses_bounded_client_scan() -> None:
    class FakeClient:
        def get_open_events(self, max_events, page_limit, max_pages):
            assert max_events == 20
            return [
                {
                    "event_ticker": "KXNBA-OKCATL",
                    "series_ticker": "KXNBA",
                    "title": "OKC Thunder vs ATL Hawks",
                    "category": "Sports",
                    "markets": [liquid_market()],
                }
            ]

        def enrich_with_orderbooks(self, markets):
            return list(markets)

    rows, metadata = discover_nba_market_edges(
        FakeClient(),  # type: ignore[arg-type]
        [scoreboard_row()],
        NBAMarketEdgeConfig(scan_limit=20, candidate_limit=5, orderbook_limit=5, min_edge=0.08, max_spread=0.08),
    )

    assert metadata["events_scanned"] == 1
    assert metadata["candidates"] == 1
    assert metadata["actionable"] == 1
    assert rows[0]["action"] == "PAPER_BUY_YES"
