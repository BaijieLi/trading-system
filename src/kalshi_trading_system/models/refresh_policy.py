from __future__ import annotations


def _as_int(value: object) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def refresh_delay_seconds(
    selected_seconds: int,
    fetch_status: str,
    *,
    retry_after: object = None,
    rate_limit_floor_seconds: int = 180,
) -> int:
    """Choose a Streamlit auto-refresh delay without hammering rate-limited pages."""

    selected = max(30, int(selected_seconds))
    if fetch_status not in {"rate_limited", "stale_rate_limited"}:
        return selected
    retry_delay = _as_int(retry_after) or 0
    return max(selected, retry_delay, rate_limit_floor_seconds)
