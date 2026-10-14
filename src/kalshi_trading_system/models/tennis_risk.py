from __future__ import annotations

from math import floor
from typing import Iterable

from kalshi_trading_system.models.fees import total_cost


BUY_ACTIONS = {"BUY_YES_PAPER", "BUY_NO_PAPER"}


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _entry_side_and_price(row: dict[str, object]) -> tuple[str, float]:
    action = str(row.get("paper_action") or "")
    if action == "BUY_YES_PAPER":
        return "YES", _as_float(row.get("yes_ask"))
    if action == "BUY_NO_PAPER":
        return "NO", _as_float(row.get("no_ask"))
    return "", 0.0


def tennis_cash_review_plan(
    rows: Iterable[dict[str, object]],
    *,
    bankroll_dollars: float = 8.0,
    max_position_dollars: float = 2.0,
    min_edge: float = 0.06,
    max_spread: float = 0.06,
) -> list[dict[str, object]]:
    """Create manual-review trade plans for live tennis rows.

    This intentionally does not place orders. It turns paper-only signals into
    bounded, human-confirmed trade candidates with explicit budget and exit
    rules.
    """

    plans: list[dict[str, object]] = []
    remaining_bankroll = max(0.0, bankroll_dollars)
    per_position_cap = max(0.0, min(max_position_dollars, bankroll_dollars))

    for row in sorted(rows, key=lambda item: _as_float(item.get("paper_edge")), reverse=True):
        side, entry_price = _entry_side_and_price(row)
        action = str(row.get("paper_action") or "")
        edge = _as_float(row.get("paper_edge"))
        spread = _as_float(row.get("spread"))
        risk_flags = str(row.get("risk_flags") or "")

        blockers: list[str] = []
        if action not in BUY_ACTIONS:
            blockers.append("not a buy signal")
        if "HEURISTIC_ONLY" not in risk_flags:
            blockers.append("missing heuristic risk flag")
        if any(flag in risk_flags for flag in ("NO_LIVE_SCORE", "NO_TWO_SIDED_QUOTE", "CROSSED_QUOTE", "WIDE_SPREAD")):
            blockers.append(risk_flags)
        if edge < min_edge:
            blockers.append(f"edge {edge:.3f} below {min_edge:.3f}")
        if spread > max_spread:
            blockers.append(f"spread {spread:.3f} above {max_spread:.3f}")
        if entry_price <= 0 or entry_price >= 1:
            blockers.append("invalid entry price")
        if remaining_bankroll <= 0:
            blockers.append("bankroll cap already allocated")

        contracts = 0
        estimated_cost = 0.0
        if not blockers:
            per_contract_cost = total_cost(entry_price, 1)
            cash_to_use = min(per_position_cap, remaining_bankroll)
            contracts = max(0, floor(cash_to_use / per_contract_cost))
            estimated_cost = total_cost(entry_price, contracts) if contracts else 0.0
            if contracts <= 0:
                blockers.append("budget too small for one contract after fee estimate")
            else:
                remaining_bankroll -= estimated_cost

        review_action = f"MANUAL_REVIEW_BUY_{side}" if not blockers else "SKIP"
        plans.append(
            {
                "match": row.get("match", ""),
                "player": row.get("player", ""),
                "review_action": review_action,
                "side": side,
                "suggested_contracts": contracts,
                "estimated_cost": round(estimated_cost, 2),
                "max_loss": round(estimated_cost, 2),
                "entry_price": round(entry_price, 4),
                "paper_edge": round(edge, 4),
                "score_fair_probability": round(_as_float(row.get("score_fair_probability")), 4),
                "spread": round(spread, 4),
                "exit_plan": (
                    "After manual entry: consider selling only on +20% ROI, -12% stop, edge <= 0.01, "
                    "or signal reversal. Otherwise hold/monitor."
                ),
                "reason": "passes tennis-only budget and liquidity checks" if not blockers else "; ".join(blockers),
                "market_url": row.get("market_url", ""),
            }
        )

    actionable = [plan for plan in plans if str(plan.get("review_action", "")).startswith("MANUAL_REVIEW")]
    skipped = [plan for plan in plans if not str(plan.get("review_action", "")).startswith("MANUAL_REVIEW")]
    return actionable + skipped
