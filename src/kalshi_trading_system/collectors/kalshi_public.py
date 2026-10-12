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

    def get_markets_page(
        self,
        limit: int = 100,
        status: str = "open",
        cursor: str = "",
        series_ticker: str = "",
    ) -> tuple[list[dict[str, Any]], str]:
        params: dict[str, Any] = {"limit": max(1, min(1000, limit)), "status": status}
        if cursor:
            params["cursor"] = cursor
        if series_ticker:
            params["series_ticker"] = series_ticker
        payload = self._get("/markets", params)
        return payload.get("markets", []), str(payload.get("cursor") or "")

    def get_open_markets(
        self,
        max_markets: int = 1000,
        page_limit: int = 500,
        max_pages: int = 4,
        status: str = "open",
    ) -> list[dict[str, Any]]:
        markets: list[dict[str, Any]] = []
        cursor = ""
        pages = 0
        while len(markets) < max_markets and pages < max_pages:
            batch, cursor = self.get_markets_page(
                limit=min(page_limit, max_markets - len(markets)),
                status=status,
                cursor=cursor,
            )
            markets.extend(batch)
            pages += 1
            if not cursor or not batch:
                break
        return markets[:max_markets]

    def get_events_page(
        self,
        limit: int = 100,
        status: str = "open",
        cursor: str = "",
        with_nested_markets: bool = True,
    ) -> tuple[list[dict[str, Any]], str]:
        params: dict[str, Any] = {
            "limit": max(1, min(200, limit)),
            "status": status,
            "with_nested_markets": str(with_nested_markets).lower(),
        }
        if cursor:
            params["cursor"] = cursor
        payload = self._get("/events", params)
        return payload.get("events", []), str(payload.get("cursor") or "")

    def get_open_events(
        self,
        max_events: int = 1000,
        page_limit: int = 200,
        max_pages: int = 5,
        status: str = "open",
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        cursor = ""
        pages = 0
        while len(events) < max_events and pages < max_pages:
            batch, cursor = self.get_events_page(
                limit=min(page_limit, max_events - len(events)),
                status=status,
                cursor=cursor,
                with_nested_markets=True,
            )
            events.extend(batch)
            pages += 1
            if not cursor or not batch:
                break
        return events[:max_events]

    def get_markets(
        self,
        series_tickers: list[str] | None = None,
        max_markets: int = SETTINGS.max_markets,
        status: str = "open",
    ) -> list[dict[str, Any]]:
        if series_tickers is None:
            series_tickers = list(DEFAULT_SERIES)
        series_tickers = [ticker.strip() for ticker in series_tickers if ticker.strip()]
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
