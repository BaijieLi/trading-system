from __future__ import annotations

from kalshi_trading_system.models.nba_market_edge import (
    NBAMarketEdgeConfig,
    analyze_nba_market_edges,
    associated_nba_market_tickers,
    candidate_nba_markets,
    discover_nba_raw_board,
    discover_nba_market_edges,
    kalshi_nba_event_tickers,
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
        "game_time_utc": "2026-10-12T23:00Z",
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


def test_kalshi_nba_event_tickers_use_eastern_game_date_and_team_codes() -> None:
    rows = kalshi_nba_event_tickers(
        [
            {
                "away": "MIN",
                "away_name": "Minnesota Timberwolves",
                "home": "NY",
                "home_name": "New York Knicks",
                "game_time_utc": "2026-10-12T23:30Z",
            },
            {
                "away": "SA",
                "away_name": "San Antonio Spurs",
                "home": "UTAH",
                "home_name": "Utah Jazz",
                "game_time_utc": "2026-10-13T01:00Z",
            },
        ]
    )

    assert rows[0]["game_event_ticker"] == "KXNBAGAME-26OCT12MINNYK"
    assert rows[0]["home_market_ticker"] == "KXNBAGAME-26OCT12MINNYK-NYK"
    assert rows[1]["game_event_ticker"] == "KXNBAGAME-26OCT12SASUTA"
    assert rows[1]["away_market_ticker"] == "KXNBAGAME-26OCT12SASUTA-SAS"


def test_associated_nba_market_tickers_extracts_hidden_total_and_game_contracts() -> None:
    market = {
        "custom_strike": {
            "Associated Markets": (
                "KXNBAGAME-26OCT12MINNYK-MIN,"
                "KXNBATOTAL-26OCT12MINNYK-226,"
                "KXNBAGAME-26OCT12SASUTA-UTA"
            )
        }
    }

    tickers = associated_nba_market_tickers(
        market,
        {"KXNBAGAME-26OCT12MINNYK", "KXNBATOTAL-26OCT12MINNYK"},
    )

    assert tickers == ["KXNBAGAME-26OCT12MINNYK-MIN", "KXNBATOTAL-26OCT12MINNYK-226"]


def test_discover_nba_raw_board_fetches_direct_and_associated_markets() -> None:
    class FakeClient:
        def get_open_markets(self, max_markets, page_limit, max_pages):
            assert max_markets == 20
            return [
                {
                    "ticker": "KXMVECROSSCATEGORY-TEST",
                    "custom_strike": {
                        "Associated Markets": "KXNBATOTAL-26OCT12MINNYK-226",
                    },
                }
            ]

        def get_market(self, ticker):
            markets = {
                "KXNBAGAME-26OCT12MINNYK-MIN": {
                    "ticker": "KXNBAGAME-26OCT12MINNYK-MIN",
                    "event_ticker": "KXNBAGAME-26OCT12MINNYK",
                    "title": "Minnesota wins",
                    "category": "Sports",
                    "status": "active",
                    "yes_bid_dollars": "0.70",
                    "yes_ask_dollars": "0.72",
                    "no_bid_dollars": "0.28",
                    "no_ask_dollars": "0.30",
                    "volume_24h_fp": "1000",
                    "open_interest_fp": "500",
                },
                "KXNBAGAME-26OCT12MINNYK-NYK": {
                    "ticker": "KXNBAGAME-26OCT12MINNYK-NYK",
                    "event_ticker": "KXNBAGAME-26OCT12MINNYK",
                    "title": "New York wins",
                    "category": "Sports",
                    "status": "active",
                    "yes_bid_dollars": "0.28",
                    "yes_ask_dollars": "0.30",
                    "no_bid_dollars": "0.70",
                    "no_ask_dollars": "0.72",
                    "volume_24h_fp": "900",
                    "open_interest_fp": "400",
                },
                "KXNBATOTAL-26OCT12MINNYK-226": {
                    "ticker": "KXNBATOTAL-26OCT12MINNYK-226",
                    "event_ticker": "KXNBATOTAL-26OCT12MINNYK",
                    "title": "Full Game: Over 225.5 points scored",
                    "category": "Sports",
                    "status": "active",
                    "yes_bid_dollars": "0.55",
                    "yes_ask_dollars": "0.58",
                    "no_bid_dollars": "0.42",
                    "no_ask_dollars": "0.45",
                    "volume_24h_fp": "800",
                    "open_interest_fp": "300",
                },
            }
            if ticker not in markets:
                raise AssertionError(f"unexpected ticker {ticker}")
            return markets[ticker]

        def enrich_with_orderbooks(self, markets):
            return list(markets)

    scoreboard = {
        "away": "MIN",
        "away_name": "Minnesota Timberwolves",
        "away_score": 88,
        "away_win_prob": 0.78,
        "home": "NY",
        "home_name": "New York Knicks",
        "home_score": 78,
        "home_win_prob": 0.22,
        "status": "In Progress",
        "period": 3,
        "clock": "10:53",
        "minutes_remaining_est": 22.88,
        "predicted_winner": "MIN",
        "confidence": 0.78,
        "game_time_utc": "2026-10-12T23:30Z",
    }

    rows, metadata = discover_nba_raw_board(
        FakeClient(),  # type: ignore[arg-type]
        [scoreboard],
        NBAMarketEdgeConfig(scan_limit=20, orderbook_limit=10),
    )

    assert metadata["markets_found"] == 3
    assert metadata["game_markets"] == 2
    assert metadata["total_markets"] == 1
    assert {row["market_type"] for row in rows} == {"MONEYLINE", "TOTAL"}
    total_row = next(row for row in rows if row["market_type"] == "TOTAL")
    assert total_row["side_or_line"] == "YES = Over 225.5"
