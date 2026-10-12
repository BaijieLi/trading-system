from kalshi_trading_system.storage.sqlite_store import (
    latest_heartbeat,
    latest_signal_snapshot,
    open_paper_trades,
    recent_paper_exits,
    recent_paper_trades,
    recent_monitor_runs,
    record_monitor_run,
    save_heartbeat,
    save_paper_exit,
    save_signals,
    save_trade,
)


def test_save_signals_and_latest_snapshot(tmp_path):
    db_path = tmp_path / "paper.sqlite3"
    count = save_signals(
        [
            {"ticker": "KX1", "action": "BUY_YES_PAPER", "expected_value": 0.04},
            {"ticker": "KX2", "action": "WATCH", "expected_value": 0.0},
        ],
        path=db_path,
        source="monitor",
        metadata={"series": ["KXTEST"]},
    )

    snapshot = latest_signal_snapshot(path=db_path)

    assert count == 2
    assert snapshot is not None
    assert snapshot["row_count"] == 2
    assert snapshot["actionable_count"] == 1
    assert snapshot["source"] == "monitor"
    assert snapshot["metadata"]["series"] == ["KXTEST"]


def test_heartbeat_upsert_and_monitor_history(tmp_path):
    db_path = tmp_path / "paper.sqlite3"
    save_heartbeat("STARTING", "first", path=db_path)
    save_heartbeat("OK", "second", metadata={"signals_saved": 3}, path=db_path)
    record_monitor_run(
        started_at="2026-01-01T00:00:00+00:00",
        status="OK",
        series=["KXTEST"],
        max_markets=10,
        markets_scanned=8,
        signals_saved=8,
        actionable_count=2,
        memory_mb=42.5,
        path=db_path,
    )

    heartbeat = latest_heartbeat(path=db_path)
    runs = recent_monitor_runs(path=db_path)

    assert heartbeat is not None
    assert heartbeat["status"] == "OK"
    assert heartbeat["message"] == "second"
    assert heartbeat["metadata"]["signals_saved"] == 3
    assert len(runs) == 1
    assert runs[0]["markets_scanned"] == 8


def test_paper_trade_open_and_exit_flow(tmp_path):
    db_path = tmp_path / "paper.sqlite3"
    save_trade(
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "ticker": "KX1",
            "side": "YES",
            "contracts": 3,
            "price": 0.40,
            "notional": 1.20,
            "reason": "test entry",
        },
        path=db_path,
    )

    open_trades = open_paper_trades(path=db_path)
    all_trades = recent_paper_trades(path=db_path)

    assert len(open_trades) == 1
    assert len(all_trades) == 1
    assert open_trades[0]["ticker"] == "KX1"

    save_paper_exit(
        {
            "trade_id": open_trades[0]["id"],
            "timestamp": "2026-01-01T01:00:00+00:00",
            "ticker": "KX1",
            "side": "YES",
            "contracts": 3,
            "entry_price": 0.40,
            "exit_price": 0.52,
            "unrealized_pnl": 0.36,
            "unrealized_roi": 0.30,
            "reason": "take profit",
        },
        path=db_path,
    )

    assert open_paper_trades(path=db_path) == []
    exits = recent_paper_exits(path=db_path)
    assert len(exits) == 1
    assert exits[0]["realized_pnl"] == 0.36
