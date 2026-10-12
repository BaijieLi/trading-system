from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_DB = Path("data/kalshi_paper.sqlite3")


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            contracts INTEGER NOT NULL,
            price REAL NOT NULL,
            notional REAL NOT NULL,
            reason TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def save_signals(signals: Iterable[dict[str, object]], path: str | Path = DEFAULT_DB) -> None:
    payload = json.dumps(list(signals))
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO signal_snapshots (created_at, payload_json) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), payload),
        )
        conn.commit()


def save_trade(trade: dict[str, object], path: str | Path = DEFAULT_DB) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO paper_trades (created_at, ticker, side, contracts, price, notional, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(trade["timestamp"]),
                str(trade["ticker"]),
                str(trade["side"]),
                int(trade["contracts"]),
                float(trade["price"]),
                float(trade["notional"]),
                str(trade["reason"]),
            ),
        )
        conn.commit()

