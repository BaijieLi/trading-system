from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from kalshi_trading_system.execution.risk_manager import approve_paper_order


@dataclass(frozen=True)
class PaperTrade:
    timestamp: str
    ticker: str
    side: str
    contracts: int
    price: float
    notional: float
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def simulate_trade(signal: dict[str, object], bankroll: float, requested_contracts: int = 1) -> PaperTrade | None:
    action = str(signal.get("action") or "")
    if action == "BUY_YES_PAPER":
        price = float(signal.get("yes_ask") or 0)
        side = "YES"
    elif action == "BUY_NO_PAPER":
        price = float(signal.get("no_ask") or 0)
        side = "NO"
    else:
        return None

    decision = approve_paper_order(action, price, bankroll=bankroll)
    if not decision.approved:
        return None
    contracts = max(1, min(requested_contracts, decision.max_contracts))
    return PaperTrade(
        timestamp=datetime.now(timezone.utc).isoformat(),
        ticker=str(signal.get("ticker") or ""),
        side=side,
        contracts=contracts,
        price=price,
        notional=round(contracts * price, 2),
        reason=str(signal.get("reason") or ""),
    )

