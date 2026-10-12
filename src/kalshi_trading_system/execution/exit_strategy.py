from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from kalshi_trading_system.config import SETTINGS


SELL_ACTIONS = {"SELL_TAKE_PROFIT", "SELL_STOP_LOSS", "SELL_EDGE_GONE", "SELL_RISK_REVERSAL"}


@dataclass(frozen=True)
class ExitDecision:
    timestamp: str
    ticker: str
    side: str
    action: str
    entry_price: float
    exit_price: float
    contracts: int
    unrealized_pnl: float
    unrealized_roi: float
    remaining_edge: float
    side_probability: float
    reason: str

    @property
    def should_exit(self) -> bool:
        return self.action in SELL_ACTIONS

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def evaluate_position_exit(
    position: dict[str, object],
    signal: dict[str, object],
    *,
    take_profit_pct: float = 0.20,
    stop_loss_pct: float = 0.12,
    min_remaining_edge: float = 0.01,
    settlement_probability: float = 0.90,
    slippage_buffer: float = SETTINGS.slippage_buffer_dollars,
) -> ExitDecision:
    """Score whether an open paper position should be sold or held.

    The remaining-edge calculation asks: "How much expected value is left from
    holding instead of exiting at the visible bid?" It is a paper-trading
    heuristic, not a live-order instruction.
    """

    side = str(position.get("side") or "").upper()
    ticker = str(position.get("ticker") or signal.get("ticker") or "")
    entry_price = _float(position.get("price"))
    contracts = max(1, _int(position.get("contracts"), 1))
    fair_probability = max(0.0, min(1.0, _float(signal.get("fair_probability"))))
    current_action = str(signal.get("action") or "")

    if side == "YES":
        exit_price = _float(signal.get("yes_bid"))
        side_probability = fair_probability
        opposite_action = "BUY_NO_PAPER"
    elif side == "NO":
        exit_price = _float(signal.get("no_bid"))
        side_probability = 1.0 - fair_probability
        opposite_action = "BUY_YES_PAPER"
    else:
        return ExitDecision(
            timestamp=datetime.now(timezone.utc).isoformat(),
            ticker=ticker,
            side=side or "UNKNOWN",
            action="HOLD_MONITOR",
            entry_price=round(entry_price, 4),
            exit_price=0.0,
            contracts=contracts,
            unrealized_pnl=0.0,
            unrealized_roi=0.0,
            remaining_edge=0.0,
            side_probability=0.0,
            reason="Unknown position side",
        )

    pnl = (exit_price - entry_price) * contracts
    roi = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
    remaining_edge = side_probability - exit_price - slippage_buffer

    if exit_price <= 0:
        action = "HOLD_MONITOR"
        reason = "No visible exit bid; cannot model an orderly exit"
    elif roi >= take_profit_pct:
        action = "SELL_TAKE_PROFIT"
        reason = "Unrealized profit reached the take-profit threshold"
    elif roi <= -stop_loss_pct:
        action = "SELL_STOP_LOSS"
        reason = "Unrealized loss reached the stop-loss threshold"
    elif current_action == opposite_action:
        action = "SELL_RISK_REVERSAL"
        reason = "Current signal favors the opposite side"
    elif remaining_edge <= min_remaining_edge:
        action = "SELL_EDGE_GONE"
        reason = "Expected value from holding is no longer meaningfully better than exiting"
    elif side_probability >= settlement_probability and remaining_edge > min_remaining_edge:
        action = "HOLD_TO_SETTLEMENT"
        reason = "High estimated side probability and positive remaining edge"
    else:
        action = "HOLD"
        reason = "Position has not hit profit, loss, or edge-exit thresholds"

    return ExitDecision(
        timestamp=datetime.now(timezone.utc).isoformat(),
        ticker=ticker,
        side=side,
        action=action,
        entry_price=round(entry_price, 4),
        exit_price=round(exit_price, 4),
        contracts=contracts,
        unrealized_pnl=round(pnl, 4),
        unrealized_roi=round(roi, 4),
        remaining_edge=round(remaining_edge, 4),
        side_probability=round(side_probability, 4),
        reason=reason,
    )


def evaluate_open_positions(
    positions: list[dict[str, object]],
    signals: list[dict[str, object]],
) -> list[dict[str, object]]:
    by_ticker = {str(signal.get("ticker") or ""): signal for signal in signals}
    decisions: list[dict[str, object]] = []
    for position in positions:
        signal = by_ticker.get(str(position.get("ticker") or ""))
        if signal is None:
            decisions.append(
                {
                    "trade_id": position.get("id"),
                    "ticker": position.get("ticker"),
                    "side": position.get("side"),
                    "action": "HOLD_MONITOR",
                    "reason": "No current signal for this ticker in the visible market universe",
                }
            )
            continue
        decision = evaluate_position_exit(position, signal).to_dict()
        decision["trade_id"] = position.get("id")
        decisions.append(decision)
    return decisions
