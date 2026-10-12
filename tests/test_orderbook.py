from kalshi_trading_system.models.orderbook import quote_from_market


def test_quote_from_market_uses_no_bid_as_yes_ask() -> None:
    market = {
        "ticker": "KXTEST",
        "title": "Test market?",
        "yes_bid_dollars": "0.40",
        "yes_ask_dollars": "0.00",
        "no_bid_dollars": "0.55",
        "volume_24h_fp": "100",
        "open_interest_fp": "500",
    }
    quote = quote_from_market(market)
    assert quote.yes_bid == 0.4
    assert round(quote.yes_ask, 2) == 0.45
    assert round(quote.spread, 2) == 0.05


def test_quote_from_orderbook_prefers_depth() -> None:
    market = {
        "ticker": "KXTEST",
        "title": "Test market?",
        "orderbook": {
            "orderbook_fp": {
                "yes_dollars": [["0.41", "10"], ["0.40", "20"]],
                "no_dollars": [["0.53", "12"]],
            }
        },
    }
    quote = quote_from_market(market)
    assert quote.yes_bid == 0.41
    assert quote.yes_ask == 0.47
    assert quote.yes_bid_size == 10
