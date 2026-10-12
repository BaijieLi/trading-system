from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_DB = Path("data/kalshi_paper.sqlite3")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_column(conn: sqlite3.Connection, table: str, column_sql: str) -> None:
    column_name = column_sql.split()[0]
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_sql}")


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    _ensure_column(conn, "signal_snapshots", "row_count INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "signal_snapshots", "actionable_count INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "signal_snapshots", "source TEXT NOT NULL DEFAULT 'manual'")
    _ensure_column(conn, "signal_snapshots", "metadata_json TEXT NOT NULL DEFAULT '{}'")
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            status TEXT NOT NULL,
            series TEXT NOT NULL,
            max_markets INTEGER NOT NULL,
            markets_scanned INTEGER NOT NULL,
            signals_saved INTEGER NOT NULL,
            actionable_count INTEGER NOT NULL,
            error_message TEXT NOT NULL,
            memory_mb REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS system_heartbeat (
            component TEXT PRIMARY KEY,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def save_signals(
    signals: Iterable[dict[str, object]],
    path: str | Path = DEFAULT_DB,
    source: str = "manual",
    metadata: dict[str, object] | None = None,
) -> int:
    rows = list(signals)
    actionable_count = sum(1 for row in rows if row.get("action") in {"BUY_YES_PAPER", "BUY_NO_PAPER"})
    payload = json.dumps(rows)
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO signal_snapshots
                (created_at, payload_json, row_count, actionable_count, source, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now_iso(),
                payload,
                len(rows),
                actionable_count,
                source,
                json.dumps(metadata or {}),
            ),
        )
        conn.commit()
    return len(rows)


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


def save_heartbeat(
    status: str,
    message: str,
    component: str = "market_monitor",
    metadata: dict[str, object] | None = None,
    path: str | Path = DEFAULT_DB,
) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO system_heartbeat (component, updated_at, status, message, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(component) DO UPDATE SET
                updated_at = excluded.updated_at,
                status = excluded.status,
                message = excluded.message,
                metadata_json = excluded.metadata_json
            """,
            (component, utc_now_iso(), status, message, json.dumps(metadata or {})),
        )
        conn.commit()


def record_monitor_run(
    started_at: str,
    status: str,
    series: list[str],
    max_markets: int,
    markets_scanned: int,
    signals_saved: int,
    actionable_count: int,
    error_message: str = "",
    memory_mb: float = 0.0,
    path: str | Path = DEFAULT_DB,
) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO monitor_runs (
                started_at, finished_at, status, series, max_markets, markets_scanned,
                signals_saved, actionable_count, error_message, memory_mb
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started_at,
                utc_now_iso(),
                status,
                ",".join(series),
                max_markets,
                markets_scanned,
                signals_saved,
                actionable_count,
                error_message[:1000],
                memory_mb,
            ),
        )
        conn.commit()


def latest_heartbeat(
    component: str = "market_monitor",
    path: str | Path = DEFAULT_DB,
) -> dict[str, object] | None:
    with connect(path) as conn:
        row = conn.execute(
            """
            SELECT component, updated_at, status, message, metadata_json
            FROM system_heartbeat
            WHERE component = ?
            """,
            (component,),
        ).fetchone()
    if row is None:
        return None
    return {
        "component": row["component"],
        "updated_at": row["updated_at"],
        "status": row["status"],
        "message": row["message"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def latest_signal_snapshot(path: str | Path = DEFAULT_DB) -> dict[str, object] | None:
    with connect(path) as conn:
        row = conn.execute(
            """
            SELECT id, created_at, payload_json, row_count, actionable_count, source, metadata_json
            FROM signal_snapshots
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    rows = json.loads(row["payload_json"] or "[]")
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "rows": rows,
        "row_count": row["row_count"] or len(rows),
        "actionable_count": row["actionable_count"],
        "source": row["source"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def recent_monitor_runs(limit: int = 20, path: str | Path = DEFAULT_DB) -> list[dict[str, object]]:
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT started_at, finished_at, status, series, max_markets, markets_scanned,
                   signals_saved, actionable_count, error_message, memory_mb
            FROM monitor_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
