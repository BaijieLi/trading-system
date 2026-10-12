from kalshi_trading_system.models.fees import estimate_fee_dollars


def test_fee_is_rounded_up_and_largest_near_midpoint() -> None:
    assert estimate_fee_dollars(0.5) == 0.02
    assert estimate_fee_dollars(0.01) == 0.01
    assert estimate_fee_dollars(0.99) == 0.01

