from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from kalshi_trading_system.config import SETTINGS


DEFAULT_STATE_PATH = Path("data/supabase_sync_state.json")
ACTIONABLE_ACTIONS = {"BUY_YES_PAPER", "BUY_NO_PAPER"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _series_ticker(ticker: object) -> str:
    return str(ticker or "").split("-", 1)[0]


def _normalize_supabase_url(url: str) -> str:
    cleaned = url.rstrip("/")
    rest_suffix = "/rest/v1"
    if cleaned.endswith(rest_suffix):
        return cleaned[: -len(rest_suffix)]
    return cleaned


class SupabaseStore:
    def __init__(
        self,
        url: str = SETTINGS.supabase_url,
        service_role_key: str = SETTINGS.supabase_service_role_key,
        enabled: bool = SETTINGS.supabase_enabled,
        timeout: int = SETTINGS.supabase_request_timeout_seconds,
        state_path: Path = DEFAULT_STATE_PATH,
        history_interval_seconds: int = SETTINGS.supabase_history_interval_seconds,
        cleanup_interval_seconds: int = SETTINGS.supabase_cleanup_interval_seconds,
        retention_days: int = SETTINGS.supabase_retention_days,
    ) -> None:
        self.url = _normalize_supabase_url(url)
        self.service_role_key = service_role_key
        self._enabled = enabled
        self.timeout = timeout
        self.state_path = state_path
        self.history_interval = timedelta(seconds=max(60, history_interval_seconds))
        self.cleanup_interval = timedelta(seconds=max(300, cleanup_interval_seconds))
        self.retention = timedelta(days=max(1, retention_days))

    @property
    def enabled(self) -> bool:
        return bool(self._enabled and self.url and self.service_role_key)

    def sync(
        self,
        signals: list[dict[str, object]],
        status: str,
        message: str,
        metadata: dict[str, object],
        observed_at: str,
    ) -> dict[str, object]:
        if not self.enabled:
            return {"enabled": False}

        now = _parse_iso(observed_at) or _utc_now()
        state = self._load_state()
        self.upsert_market_state(signals, observed_at=observed_at)
        self.upsert_heartbeat(status=status, message=message, metadata=metadata, observed_at=observed_at)
        self.insert_monitor_run(status=status, message=message, metadata=metadata, observed_at=observed_at)

        wrote_observations = False
        last_history_at = _parse_iso(state.get("last_history_at"))
        if last_history_at is None or now - last_history_at >= self.history_interval:
            self.insert_market_observations(signals, observed_at=observed_at)
            state["last_history_at"] = observed_at
            wrote_observations = True

        actionable_rows = [row for row in signals if row.get("action") in ACTIONABLE_ACTIONS]
        if actionable_rows:
            self.insert_signal_events(actionable_rows, observed_at=observed_at)

        cleaned = False
        last_cleanup_at = _parse_iso(state.get("last_cleanup_at"))
        if last_cleanup_at is None or now - last_cleanup_at >= self.cleanup_interval:
            self.cleanup_old_rows(cutoff=(now - self.retention).isoformat())
            state["last_cleanup_at"] = observed_at
            cleaned = True

        self._save_state(state)
        return {
            "enabled": True,
            "latest_rows": len(signals),
            "observation_rows": len(signals) if wrote_observations else 0,
            "signal_event_rows": len(actionable_rows),
            "cleanup_ran": cleaned,
        }

    def upsert_market_state(self, signals: list[dict[str, object]], observed_at: str) -> None:
        rows = [self._market_state_row(row, observed_at=observed_at) for row in signals]
        self._upsert("market_state", rows, on_conflict="ticker")

    def insert_market_observations(self, signals: list[dict[str, object]], observed_at: str) -> None:
        rows = [self._observation_row(row, observed_at=observed_at) for row in signals]
        self._insert("market_observations", rows)

    def insert_signal_events(self, signals: list[dict[str, object]], observed_at: str) -> None:
        rows = [self._signal_event_row(row, observed_at=observed_at) for row in signals]
        self._insert("signal_events", rows)

    def insert_monitor_run(
        self,
        status: str,
        message: str,
        metadata: dict[str, object],
        observed_at: str,
    ) -> None:
        self._insert(
            "kalshi_monitor_runs",
            [
                {
                    "observed_at": observed_at,
                    "status": status,
                    "message": message,
                    "markets_scanned": int(metadata.get("markets_scanned") or 0),
                    "signals_saved": int(metadata.get("signals_saved") or 0),
                    "actionable_count": int(metadata.get("actionable_count") or 0),
                    "memory_mb": _float_or_none(metadata.get("memory_mb")),
                    "metadata": metadata,
                }
            ],
        )

    def upsert_heartbeat(
        self,
        status: str,
        message: str,
        metadata: dict[str, object],
        observed_at: str,
    ) -> None:
        self._upsert(
            "system_heartbeat",
            [
                {
                    "component": "kalshi_market_monitor",
                    "updated_at": observed_at,
                    "status": status,
                    "message": message,
                    "metadata": metadata,
                }
            ],
            on_conflict="component",
        )

    def cleanup_old_rows(self, cutoff: str) -> None:
        self._delete("market_observations", {"observed_at": f"lt.{cutoff}"})
        self._delete("signal_events", {"observed_at": f"lt.{cutoff}"})
        self._delete("kalshi_monitor_runs", {"observed_at": f"lt.{cutoff}"})

    def _request(
        self,
        method: str,
        table: str,
        params: dict[str, str] | None = None,
        payload: object | None = None,
        prefer: str = "return=minimal",
    ) -> None:
        if not self.url or not self.service_role_key:
            raise RuntimeError("Supabase URL/key are required when Supabase sync is enabled.")
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }
        response = requests.request(
            method,
            f"{self.url}/rest/v1/{table}",
            headers=headers,
            params=params or {},
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()

    def _insert(self, table: str, rows: list[dict[str, object]]) -> None:
        if rows:
            self._request("POST", table, payload=rows)

    def _upsert(self, table: str, rows: list[dict[str, object]], on_conflict: str) -> None:
        if rows:
            self._request(
                "POST",
                table,
                params={"on_conflict": on_conflict},
                payload=rows,
                prefer="resolution=merge-duplicates,return=minimal",
            )

    def _delete(self, table: str, params: dict[str, str]) -> None:
        self._request("DELETE", table, params=params)

    def _market_state_row(self, row: dict[str, object], observed_at: str) -> dict[str, object]:
        ticker = str(row.get("ticker") or "")
        return {
            "ticker": ticker,
            "updated_at": observed_at,
            "series_ticker": _series_ticker(ticker),
            "title": str(row.get("title") or ""),
            "action": str(row.get("action") or ""),
            "fair_probability": _float_or_none(row.get("fair_probability")),
            "yes_bid": _float_or_none(row.get("yes_bid")),
            "yes_ask": _float_or_none(row.get("yes_ask")),
            "no_bid": _float_or_none(row.get("no_bid")),
            "no_ask": _float_or_none(row.get("no_ask")),
            "spread": _float_or_none(row.get("spread")),
            "expected_value": _float_or_none(row.get("expected_value")),
            "expected_roi": _float_or_none(row.get("expected_roi")),
            "fee_estimate": _float_or_none(row.get("fee_estimate")),
            "volume_24h": _float_or_none(row.get("volume_24h")),
            "open_interest": _float_or_none(row.get("open_interest")),
            "risk_flags": str(row.get("risk_flags") or ""),
            "reason": str(row.get("reason") or ""),
            "market_url": str(row.get("market_url") or ""),
        }

    def _observation_row(self, row: dict[str, object], observed_at: str) -> dict[str, object]:
        state_row = self._market_state_row(row, observed_at=observed_at)
        state_row.pop("updated_at")
        state_row["observed_at"] = observed_at
        return state_row

    def _signal_event_row(self, row: dict[str, object], observed_at: str) -> dict[str, object]:
        return {
            "observed_at": observed_at,
            "ticker": str(row.get("ticker") or ""),
            "series_ticker": _series_ticker(row.get("ticker")),
            "title": str(row.get("title") or ""),
            "action": str(row.get("action") or ""),
            "expected_value": _float_or_none(row.get("expected_value")),
            "expected_roi": _float_or_none(row.get("expected_roi")),
            "price": _float_or_none(row.get("yes_ask") if row.get("action") == "BUY_YES_PAPER" else row.get("no_ask")),
            "risk_flags": str(row.get("risk_flags") or ""),
            "reason": str(row.get("reason") or ""),
            "market_url": str(row.get("market_url") or ""),
            "payload": row,
        }

    def _load_state(self) -> dict[str, str]:
        try:
            return json.loads(self.state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: dict[str, str]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True))


class SupabaseReader:
    def __init__(
        self,
        url: str = SETTINGS.supabase_url,
        anon_key: str = SETTINGS.supabase_anon_key,
        timeout: int = SETTINGS.supabase_request_timeout_seconds,
    ) -> None:
        self.url = _normalize_supabase_url(url)
        self.anon_key = anon_key
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.anon_key)

    def market_state(self, limit: int = 200) -> list[dict[str, object]]:
        return self._get(
            "market_state",
            {
                "select": "*",
                "order": "expected_value.desc.nullslast",
                "limit": str(limit),
            },
        )

    def heartbeat(self) -> dict[str, object] | None:
        rows = self._get(
            "system_heartbeat",
            {
                "select": "*",
                "component": "eq.kalshi_market_monitor",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def monitor_runs(self, limit: int = 20) -> list[dict[str, object]]:
        return self._get(
            "kalshi_monitor_runs",
            {
                "select": "*",
                "order": "observed_at.desc",
                "limit": str(limit),
            },
        )

    def _get(self, table: str, params: dict[str, str]) -> list[dict[str, object]]:
        if not self.enabled:
            return []
        response = requests.get(
            f"{self.url}/rest/v1/{table}",
            headers={
                "apikey": self.anon_key,
                "Authorization": f"Bearer {self.anon_key}",
            },
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
