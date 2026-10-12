from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_SERIES = (
    "KXHIGHNY",
    "KXHIGHDEN",
    "KXBTCD",
    "KXNASDAQ100D",
    "KXSPY",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class Settings:
    base_url: str = os.getenv("KALSHI_BASE_URL", "https://external-api.kalshi.com/trade-api/v2")
    paper_trading_only: bool = _env_bool("PAPER_TRADING_ONLY", True)
    max_markets: int = int(os.getenv("MAX_MARKETS", "50"))
    refresh_seconds: int = int(os.getenv("REFRESH_SECONDS", "10"))
    bankroll_dollars: float = float(os.getenv("BANKROLL_DOLLARS", "1000"))
    max_risk_per_trade_pct: float = float(os.getenv("MAX_RISK_PER_TRADE_PCT", "1.0"))
    max_daily_loss_pct: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "3.0"))
    min_edge_dollars: float = float(os.getenv("MIN_EDGE_DOLLARS", "0.03"))
    max_spread_dollars: float = float(os.getenv("MAX_SPREAD_DOLLARS", "0.08"))
    min_volume_24h: float = float(os.getenv("MIN_VOLUME_24H", "10"))
    slippage_buffer_dollars: float = float(os.getenv("SLIPPAGE_BUFFER_DOLLARS", "0.01"))


SETTINGS = Settings()

