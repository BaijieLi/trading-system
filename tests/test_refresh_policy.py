from __future__ import annotations

from kalshi_trading_system.models.refresh_policy import refresh_delay_seconds


def test_refresh_delay_uses_selected_delay_when_provider_is_ok() -> None:
    assert refresh_delay_seconds(60, "ok") == 60


def test_refresh_delay_backs_off_on_rate_limit() -> None:
    assert refresh_delay_seconds(60, "rate_limited") == 180


def test_refresh_delay_respects_larger_retry_after() -> None:
    assert refresh_delay_seconds(60, "stale_rate_limited", retry_after="240") == 240
