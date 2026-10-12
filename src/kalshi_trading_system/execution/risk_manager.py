from __future__ import annotations

from dataclasses import dataclass

from kalshi_trading_system.config import SETTINGS


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    max_contracts: int
    reason: str


def approve_paper_order(
    action: str,
    price: float,
    bankroll: float = SETTINGS.bankroll_dollars,
    max_risk_pct: float = SETTINGS.max_risk_per_trade_pct,
) -> RiskDecision:
    if action not in {"BUY_YES_PAPER", "BUY_NO_PAPER"}:
        return RiskDecision(False, 0, "Signal is not actionable")
    if price <= 0 or price >= 1:
        return RiskDecision(False, 0, "Invalid or extreme price")
    max_risk_dollars = bankroll * max_risk_pct / 100.0
    max_contracts = int(max_risk_dollars // price)
    if max_contracts <= 0:
        return RiskDecision(False, 0, "Bankroll limit allows zero contracts")
    return RiskDecision(True, max_contracts, "Approved for paper trading only")

