from __future__ import annotations

from kalshi_trading_system.models.tennis_risk import tennis_cash_review_plan


def test_tennis_cash_review_plan_sizes_candidates_inside_bankroll() -> None:
    rows = [
        {
            "match": "Player One vs Player Two",
            "player": "Player One",
            "ticker": "KXTEST-ONE",
            "paper_action": "BUY_YES_PAPER",
            "paper_edge": 0.09,
            "score_fair_probability": 0.7,
            "yes_ask": 0.55,
            "no_ask": 0.48,
            "spread": 0.03,
            "risk_flags": "HEURISTIC_ONLY",
            "market_url": "https://kalshi.com/markets/kxtest-one",
        }
    ]

    plans = tennis_cash_review_plan(rows, bankroll_dollars=8.0, max_position_dollars=2.0)

    assert plans[0]["review_action"] == "MANUAL_REVIEW_BUY_YES"
    assert plans[0]["ticker"] == "KXTEST-ONE"
    assert plans[0]["side"] == "YES"
    assert plans[0]["suggested_contracts"] >= 1
    assert 0 < float(plans[0]["estimated_cost"]) <= 2.0
    assert "passes tennis-only" in str(plans[0]["reason"])


def test_tennis_cash_review_plan_blocks_weak_or_risky_rows() -> None:
    rows = [
        {
            "match": "Player One vs Player Two",
            "player": "Player One",
            "paper_action": "BUY_YES_PAPER",
            "paper_edge": 0.02,
            "yes_ask": 0.55,
            "spread": 0.08,
            "risk_flags": "HEURISTIC_ONLY, WIDE_SPREAD",
        }
    ]

    plans = tennis_cash_review_plan(rows, bankroll_dollars=8.0, max_position_dollars=2.0)

    assert plans[0]["review_action"] == "SKIP"
    assert plans[0]["suggested_contracts"] == 0
    assert "WIDE_SPREAD" in str(plans[0]["reason"])


def test_tennis_cash_review_plan_never_allocates_beyond_bankroll() -> None:
    rows = [
        {
            "match": f"Match {index}",
            "player": f"Player {index}",
            "paper_action": "BUY_YES_PAPER",
            "paper_edge": 0.09,
            "score_fair_probability": 0.7,
            "yes_ask": 0.55,
            "no_ask": 0.48,
            "spread": 0.03,
            "risk_flags": "HEURISTIC_ONLY",
        }
        for index in range(10)
    ]

    plans = tennis_cash_review_plan(rows, bankroll_dollars=3.0, max_position_dollars=2.0)
    allocated = sum(float(plan["estimated_cost"]) for plan in plans)

    assert allocated <= 3.0
