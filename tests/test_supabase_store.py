from __future__ import annotations

from kalshi_trading_system.storage.supabase_store import SupabaseStore


class FakeResponse:
    def raise_for_status(self) -> None:
        return None


def sample_signal(action: str = "WATCH") -> dict[str, object]:
    return {
        "ticker": "KXTEST-26JAN01-Y",
        "title": "Test market",
        "action": action,
        "fair_probability": 0.55,
        "yes_bid": 0.4,
        "yes_ask": 0.42,
        "no_bid": 0.56,
        "no_ask": 0.6,
        "spread": 0.02,
        "expected_value": 0.04,
        "expected_roi": 0.095,
        "fee_estimate": 0.02,
        "volume_24h": 100,
        "open_interest": 200,
        "risk_flags": "",
        "reason": "test",
        "market_url": "https://kalshi.com/markets/KXTEST",
    }


def test_supabase_sync_writes_latest_history_and_cleanup(monkeypatch, tmp_path):
    calls = []

    def fake_request(method, url, headers, params, json, timeout):
        calls.append({"method": method, "url": url, "headers": headers, "params": params, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("requests.request", fake_request)
    store = SupabaseStore(
        url="https://example.supabase.co",
        service_role_key="secret",
        enabled=True,
        state_path=tmp_path / "state.json",
        history_interval_seconds=300,
        cleanup_interval_seconds=3600,
        retention_days=14,
    )

    result = store.sync(
        [sample_signal("BUY_YES_PAPER")],
        status="OK",
        message="Saved 1 signal.",
        metadata={"markets_scanned": 1, "signals_saved": 1, "actionable_count": 1, "memory_mb": 12.5},
        observed_at="2026-01-01T00:00:00+00:00",
    )

    called_tables = [call["url"].rsplit("/", 1)[-1] for call in calls]
    assert result["enabled"] is True
    assert "market_state" in called_tables
    assert "system_heartbeat" in called_tables
    assert "kalshi_monitor_runs" in called_tables
    assert "market_observations" in called_tables
    assert "signal_events" in called_tables
    market_state_delete = next(
        call for call in calls if call["method"] == "DELETE" and call["url"].endswith("/market_state")
    )
    market_state_upsert = next(
        call for call in calls if call["method"] == "POST" and call["url"].endswith("/market_state")
    )
    assert market_state_delete["params"]["ticker"] == "not.is.null"
    assert market_state_upsert["headers"]["Authorization"] == "Bearer secret"
    assert market_state_upsert["params"]["on_conflict"] == "ticker"
    assert result["market_state_replaced"] is True


def test_supabase_history_interval_skips_frequent_observations(monkeypatch, tmp_path):
    calls = []

    def fake_request(method, url, headers, params, json, timeout):
        calls.append({"method": method, "url": url, "params": params, "json": json})
        return FakeResponse()

    monkeypatch.setattr("requests.request", fake_request)
    store = SupabaseStore(
        url="https://example.supabase.co",
        service_role_key="secret",
        enabled=True,
        state_path=tmp_path / "state.json",
        history_interval_seconds=300,
        cleanup_interval_seconds=3600,
        retention_days=14,
    )
    first_args = {
        "signals": [sample_signal()],
        "status": "OK",
        "message": "Saved.",
        "metadata": {"markets_scanned": 1, "signals_saved": 1, "actionable_count": 0, "memory_mb": 12.5},
    }

    store.sync(**first_args, observed_at="2026-01-01T00:00:00+00:00")
    calls.clear()
    store.sync(**first_args, observed_at="2026-01-01T00:01:00+00:00")

    called_tables = [call["url"].rsplit("/", 1)[-1] for call in calls]
    assert "market_state" in called_tables
    assert any(call["method"] == "DELETE" and call["url"].endswith("/market_state") for call in calls)
    assert "market_observations" not in called_tables


def test_supabase_url_accepts_rest_endpoint():
    store = SupabaseStore(
        url="https://example.supabase.co/rest/v1/",
        service_role_key="secret",
        enabled=True,
    )

    assert store.url == "https://example.supabase.co"
