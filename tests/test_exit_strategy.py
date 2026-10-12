from kalshi_trading_system.execution.exit_strategy import evaluate_open_positions, evaluate_position_exit


def test_exit_strategy_takes_profit() -> None:
    decision = evaluate_position_exit(
        {"ticker": "KX", "side": "YES", "contracts": 10, "price": 0.40},
        {"ticker": "KX", "fair_probability": 0.70, "yes_bid": 0.52, "no_bid": 0.46, "action": "WATCH"},
        take_profit_pct=0.20,
    )

    assert decision.action == "SELL_TAKE_PROFIT"
    assert decision.should_exit
    assert decision.unrealized_pnl == 1.2


def test_exit_strategy_stops_loss() -> None:
    decision = evaluate_position_exit(
        {"ticker": "KX", "side": "NO", "contracts": 5, "price": 0.60},
        {"ticker": "KX", "fair_probability": 0.60, "yes_bid": 0.60, "no_bid": 0.50, "action": "WATCH"},
        stop_loss_pct=0.10,
    )

    assert decision.action == "SELL_STOP_LOSS"
    assert decision.unrealized_pnl == -0.5


def test_exit_strategy_sells_when_edge_is_gone() -> None:
    decision = evaluate_position_exit(
        {"ticker": "KX", "side": "YES", "contracts": 1, "price": 0.45},
        {"ticker": "KX", "fair_probability": 0.56, "yes_bid": 0.55, "no_bid": 0.43, "action": "WATCH"},
        take_profit_pct=0.50,
        min_remaining_edge=0.02,
        slippage_buffer=0.01,
    )

    assert decision.action == "SELL_EDGE_GONE"
    assert decision.remaining_edge == 0.0


def test_evaluate_open_positions_handles_missing_current_signal() -> None:
    decisions = evaluate_open_positions(
        [{"id": 7, "ticker": "KXOLD", "side": "YES", "contracts": 1, "price": 0.40}],
        [{"ticker": "KXNEW", "fair_probability": 0.50, "yes_bid": 0.48, "no_bid": 0.50}],
    )

    assert decisions[0]["trade_id"] == 7
    assert decisions[0]["action"] == "HOLD_MONITOR"
