from __future__ import annotations

from kalshi_trading_system.models.tennis_observer import (
    TennisObserverConfig,
    associated_tennis_tickers,
    discover_tennis_watchlist,
    is_tennis_ticker,
)


def tennis_market(ticker: str = "KXATPMATCH-26OCT13TEST-AAA") -> dict[str, object]:
    return {
        "ticker": ticker,
        "title": "Test Player wins",
        "status": "active",
        "yes_bid_dollars": "0.51",
        "yes_ask_dollars": "0.52",
        "no_bid_dollars": "0.48",
        "no_ask_dollars": "0.49",
        "volume_24h_fp": "2500",
        "open_interest_fp": "3000",
    }


def test_is_tennis_ticker_matches_main_tennis_prefixes() -> None:
    assert is_tennis_ticker("KXATPMATCH-26OCT13TEST-AAA")
    assert is_tennis_ticker("KXWTACHALLENGERMATCH-26OCT13TEST-AAA")
    assert not is_tennis_ticker("KXNBAGAME-26OCT13CLEORL-CLE")


def test_associated_tennis_tickers_extracts_only_tennis_contracts() -> None:
    market = {
        "custom_strike": {
            "Associated Markets": (
                "KXATPMATCH-26OCT13TEST-AAA,"
                "KXWTAGTOTAL-26OCT13TEST-21,"
                "KXNBAGAME-26OCT13CLEORL-CLE"
            )
        }
    }

    assert associated_tennis_tickers(market) == [
        "KXATPMATCH-26OCT13TEST-AAA",
        "KXWTAGTOTAL-26OCT13TEST-21",
    ]


def test_discover_tennis_watchlist_ranks_liquid_observation_rows() -> None:
    class FakeClient:
        def get_open_markets(self, max_markets, page_limit, max_pages):
            assert max_markets == 20
            return [
                {
                    "ticker": "KXMVECROSSCATEGORY-TEST",
                    "title": "yes Test Player",
                    "custom_strike": {"Associated Markets": "KXATPMATCH-26OCT13TEST-AAA"},
                }
            ]

        def get_market(self, ticker):
            assert ticker == "KXATPMATCH-26OCT13TEST-AAA"
            return tennis_market(ticker)

        def enrich_with_orderbooks(self, markets):
            return list(markets)

    rows, metadata = discover_tennis_watchlist(
        FakeClient(),  # type: ignore[arg-type]
        TennisObserverConfig(scan_limit=20, candidate_limit=10, orderbook_limit=5),
    )

    assert metadata["candidate_tickers"] == 1
    assert metadata["watch_liquid"] == 1
    assert rows[0]["action"] == "WATCH_LIQUID"
    assert rows[0]["stability_score"] > 0
    assert "NO_INDEPENDENT_TENNIS_MODEL" in rows[0]["risk_flags"]


def test_discover_tennis_watchlist_blocks_wide_spread() -> None:
    class FakeClient:
        def get_open_markets(self, max_markets, page_limit, max_pages):
            return [{"ticker": "KXATPMATCH-26OCT13TEST-AAA", "title": "ATP test"}]

        def get_market(self, ticker):
            return tennis_market(ticker)

        def enrich_with_orderbooks(self, markets):
            row = dict(markets[0])
            row["yes_bid_dollars"] = "0.30"
            row["yes_ask_dollars"] = "0.45"
            row["no_bid_dollars"] = "0.55"
            row["no_ask_dollars"] = "0.70"
            return [row]

    rows, metadata = discover_tennis_watchlist(
        FakeClient(),  # type: ignore[arg-type]
        TennisObserverConfig(scan_limit=20, candidate_limit=10, orderbook_limit=5, max_spread=0.06),
    )

    assert metadata["watch_liquid"] == 0
    assert rows[0]["action"] == "NO_TRADE"
    assert "WIDE_SPREAD" in rows[0]["risk_flags"]
