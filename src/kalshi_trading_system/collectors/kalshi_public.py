from __future__ import annotations

import logging
from typing import Any

import requests

from kalshi_trading_system.config import DEFAULT_SERIES, SETTINGS


LOGGER = logging.getLogger(__name__)
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (kalshi-trading-system paper scanner)",
}


class KalshiPublicClient:
    def __init__(self, base_url: str = SETTINGS.base_url, timeout: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}{path}",
            params=params or {},
            headers=HEADERS,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_markets(
        self,
        series_tickers: list[str] | None = None,
        max_markets: int = SETTINGS.max_markets,
        status: str = "open",
    ) -> list[dict[str, Any]]:
        series_tickers = [ticker.strip() for ticker in (series_tickers or list(DEFAULT_SERIES)) if ticker.strip()]
        markets: list[dict[str, Any]] = []
        if series_tickers:
            per_series_limit = max(1, min(100, max_markets // max(1, len(series_tickers)) + 10))
            for series in series_tickers:
                try:
                    payload = self._get(
                        "/markets",
                        {"limit": per_series_limit, "status": status, "series_ticker": series},
                    )
                    markets.extend(payload.get("markets", []))
                except requests.RequestException as exc:
                    LOGGER.warning("failed to fetch series %s: %s", series, exc)
        else:
            payload = self._get("/markets", {"limit": max_markets, "status": status})
            markets.extend(payload.get("markets", []))

        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for market in markets:
            ticker = str(market.get("ticker") or "")
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            unique.append(market)
            if len(unique) >= max_markets:
                break
        return unique

    def get_orderbook(self, ticker: str, depth: int = 10) -> dict[str, Any]:
        return self._get(f"/markets/{ticker}/orderbook", {"depth": depth})

    def enrich_with_orderbooks(self, markets: list[dict[str, Any]], depth: int = 10) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for market in markets:
            ticker = str(market.get("ticker") or "")
            row = dict(market)
            try:
                row["orderbook"] = self.get_orderbook(ticker, depth=depth)
            except requests.RequestException as exc:
                row["orderbook_error"] = str(exc)
            enriched.append(row)
        return enriched

