from kalshi_trading_system.models.edge import analyze_market, market_url, refresh_market_urls


def test_analyze_market_blocks_illiquid_market() -> None:
    signal = analyze_market({"ticker": "KX", "title": "Empty"})
    assert signal.action == "NO_TRADE"
    assert "NO_TWO_SIDED_QUOTE" in signal.risk_flags


def test_analyze_market_detects_manual_yes_edge() -> None:
    market = {
        "ticker": "KX",
        "title": "Liquid test",
        "yes_bid_dollars": "0.40",
        "yes_ask_dollars": "0.42",
        "no_bid_dollars": "0.57",
        "no_ask_dollars": "0.60",
        "yes_ask_size_fp": "100",
        "volume_24h_fp": "1000",
        "open_interest_fp": "1000",
    }
    signal = analyze_market(market, manual_fair=0.55, min_edge=0.02, max_spread=0.05)
    assert signal.action == "BUY_YES_PAPER"
    assert signal.expected_value > 0


def test_market_url_uses_ticker_resolver() -> None:
    assert market_url("KXEVENT", "KXEVENT-26JAN01-Y") == (
        "https://kalshi.com/markets_by_ticker/kxevent-26jan01-y"
    )


def test_market_url_uses_known_kalshi_market_routes_for_sports() -> None:
    assert market_url("KXNBAGAME-26OCT12MINNYK", "KXNBAGAME-26OCT12MINNYK-MIN") == (
        "https://kalshi.com/markets/kxnbagame/nba-game/kxnbagame-26oct12minnyk-min"
    )


def test_refresh_market_urls_replaces_stale_event_links() -> None:
    rows = [
        {
            "ticker": "KXBTCD-26OCT1317-T92249.99",
            "market_url": "https://kalshi.com/markets/kxbtcd-26oct1317",
        }
    ]

    refreshed = refresh_market_urls(rows)

    assert refreshed[0]["market_url"] == (
        "https://kalshi.com/markets_by_ticker/kxbtcd-26oct1317-t92249.99"
    )
