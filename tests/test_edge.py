from kalshi_trading_system.models.edge import analyze_market


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

