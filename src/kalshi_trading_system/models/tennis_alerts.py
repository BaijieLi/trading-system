from __future__ import annotations

from typing import Iterable


WATCH_ACTIONS = {"WATCH_LIVE", "NO_TRADE", ""}
ACTIONABLE_ACTIONS = {"BUY_YES_PAPER", "BUY_NO_PAPER"}


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _row_key(row: dict[str, object]) -> str:
    return str(row.get("ticker") or "").strip()


def detect_tennis_live_changes(
    previous_rows: Iterable[dict[str, object]],
    current_rows: Iterable[dict[str, object]],
    *,
    probability_threshold: float = 0.05,
    edge_threshold: float = 0.03,
) -> list[dict[str, object]]:
    """Compare consecutive live tennis snapshots and return notable row-level changes."""
    previous = {_row_key(row): row for row in previous_rows if _row_key(row)}
    alerts: list[dict[str, object]] = []

    for current in current_rows:
        ticker = _row_key(current)
        if not ticker:
            continue
        old = previous.get(ticker)
        if not old:
            continue

        changes: list[str] = []
        for field, label in (
            ("sets", "score"),
            ("current_game", "game"),
            ("server", "server"),
            ("live_status", "status"),
        ):
            before = str(old.get(field) or "")
            after = str(current.get(field) or "")
            if before != after and (before or after):
                changes.append(f"{label}: {before or '-'} -> {after or '-'}")

        old_action = str(old.get("paper_action") or "")
        new_action = str(current.get("paper_action") or "")
        if old_action != new_action:
            changes.append(f"action: {old_action or '-'} -> {new_action or '-'}")

        old_probability = _as_float(old.get("score_fair_probability"))
        new_probability = _as_float(current.get("score_fair_probability"))
        probability_delta = new_probability - old_probability
        if abs(probability_delta) >= probability_threshold:
            changes.append(f"probability: {old_probability:.2f} -> {new_probability:.2f}")

        old_edge = _as_float(old.get("paper_edge"))
        new_edge = _as_float(current.get("paper_edge"))
        edge_delta = new_edge - old_edge
        if abs(edge_delta) >= edge_threshold:
            changes.append(f"edge: {old_edge:.3f} -> {new_edge:.3f}")

        old_ask = _as_float(old.get("yes_ask"))
        new_ask = _as_float(current.get("yes_ask"))
        if abs(new_ask - old_ask) >= probability_threshold:
            changes.append(f"yes ask: {old_ask:.2f} -> {new_ask:.2f}")

        if changes:
            alerts.append(
                {
                    "match": current.get("match", ""),
                    "player": current.get("player", ""),
                    "ticker": ticker,
                    "paper_action": new_action,
                    "paper_edge": round(new_edge, 4),
                    "score_fair_probability": round(new_probability, 4),
                    "changes": " | ".join(changes),
                    "market_url": current.get("market_url", ""),
                }
            )

    return sorted(
        alerts,
        key=lambda row: (
            str(row.get("paper_action") or "") not in ACTIONABLE_ACTIONS,
            -abs(_as_float(row.get("paper_edge"))),
            str(row.get("match") or ""),
        ),
    )
