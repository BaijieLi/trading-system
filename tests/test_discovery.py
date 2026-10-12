from __future__ import annotations

from kalshi_trading_system.models.discovery import (
    DiscoveryConfig,
    discover_market_signals,
    markets_from_events,
    prefilter_markets,
    rank_discovered_signals,
)


def liquid_market(ticker: str, volume: str = "1000", open_interest: str = "500") -> dict[str, object]:
    return {
        "ticker": ticker,
        "series_ticker": ticker.split("-", 1)[0],
        "title": f"{ticker} test",
        "yes_bid_dollars": "0.40",
        "yes_ask_dollars": "0.43",
        "no_bid_dollars": "0.56",
        "no_ask_dollars": "0.60",
        "yes_ask_size_fp": "50",
        "volume_24h_fp": volume,
        "open_interest_fp": open_interest,
    }


def test_prefilter_excludes_combo_markets_by_default() -> None:
    markets = [
        liquid_market("KXBTC-26JAN01-Y"),
        {
            **liquid_market("KXCROSSCATEGORY-26JAN01-Y"),
            "custom_strike": {"Associated Markets": "KXONE,KXTWO"},
        },
    ]

    filtered = prefilter_markets(
        markets,
        DiscoveryConfig(min_volume_24h=10, min_open_interest=10, include_combo_markets=False),
    )

    assert [market["ticker"] for market in filtered] == ["KXBTC-26JAN01-Y"]


def test_rank_discovered_signals_adds_scores() -> None:
    signals = [
        {
            "ticker": "LOW",
            "action": "NO_TRADE",
            "expected_value": -0.01,
            "spread": 0.5,
            "volume_24h": 10,
            "open_interest": 10,
            "liquidity_score": 1,
            "risk_flags": "WIDE_SPREAD",
        },
        {
            "ticker": "HIGH",
            "action": "WATCH",
            "expected_value": 0.01,
            "spread": 0.02,
            "volume_24h": 1000,
            "open_interest": 500,
            "liquidity_score": 5,
            "risk_flags": "",
        },
    ]

    ranked = rank_discovered_signals(signals, final_limit=2)

    assert ranked[0]["ticker"] == "HIGH"
    assert ranked[0]["discovery_score"] > ranked[1]["discovery_score"]
    assert "quote_quality_score" in ranked[0]


def test_markets_from_events_carries_event_metadata() -> None:
    markets = markets_from_events(
        [
            {
                "event_ticker": "KXEVENT-26JAN01",
                "series_ticker": "KXEVENT",
                "category": "Economics",
                "markets": [{"ticker": "KXEVENT-26JAN01-Y", "title": "Test"}],
            }
        ]
    )

    assert markets[0]["event_ticker"] == "KXEVENT-26JAN01"
    assert markets[0]["series_ticker"] == "KXEVENT"
    assert markets[0]["category"] == "Economics"


def test_discover_market_signals_uses_broad_market_client() -> None:
    class FakeClient:
        def get_open_events(self, max_events, page_limit, max_pages):
            return [
                {
                    "event_ticker": "KXHIGH-26JAN01",
                    "series_ticker": "KXHIGH",
                    "markets": [
                        liquid_market("KXLOW-26JAN01-Y", volume="1", open_interest="1"),
                        liquid_market("KXHIGH-26JAN01-Y", volume="1000", open_interest="500"),
                    ],
                }
            ]

        def enrich_with_orderbooks(self, markets):
            return list(markets)

    signals, metadata = discover_market_signals(
        FakeClient(),  # type: ignore[arg-type]
        DiscoveryConfig(scan_limit=10, candidate_limit=5, final_limit=5, min_volume_24h=10, min_open_interest=10),
    )

    assert metadata["events_seen"] == 1
    assert metadata["markets_seen"] == 2
    assert metadata["candidates"] == 1
    assert signals[0]["ticker"] == "KXHIGH-26JAN01-Y"
    assert signals[0]["series_ticker"] == "KXHIGH"
