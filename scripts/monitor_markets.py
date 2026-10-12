from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from kalshi_trading_system.collectors.kalshi_public import KalshiPublicClient  # noqa: E402
from kalshi_trading_system.config import DEFAULT_SERIES, SETTINGS  # noqa: E402
from kalshi_trading_system.models.discovery import DiscoveryConfig, discover_market_signals  # noqa: E402
from kalshi_trading_system.models.edge import analyze_markets  # noqa: E402
from kalshi_trading_system.storage.sqlite_store import (  # noqa: E402
    record_monitor_run,
    save_heartbeat,
    save_signals,
    utc_now_iso,
)
from kalshi_trading_system.storage.supabase_store import SupabaseStore  # noqa: E402
from kalshi_trading_system.utils.system import process_memory_mb  # noqa: E402


LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
FIELDS = [
    "discovery_score",
    "liquidity_score",
    "quote_quality_score",
    "series_ticker",
    "ticker",
    "title",
    "action",
    "fair_probability",
    "yes_bid",
    "yes_ask",
    "no_bid",
    "no_ask",
    "spread",
    "expected_value",
    "expected_roi",
    "fee_estimate",
    "volume_24h",
    "open_interest",
    "risk_flags",
    "market_url",
]


def parse_series(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def write_latest_csv(signals: list[dict[str, object]], output: str) -> None:
    if not output:
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(signals)


def run_once(
    series: list[str],
    max_markets: int,
    latest_csv: str = "",
    supabase_store: SupabaseStore | None = None,
    discover: bool = False,
    discovery_config: DiscoveryConfig | None = None,
) -> dict[str, object]:
    started_at = utc_now_iso()
    client = KalshiPublicClient()
    discovery_metadata: dict[str, object] = {}
    if discover:
        signals, discovery_metadata = discover_market_signals(client, discovery_config)
        markets_scanned = int(discovery_metadata.get("orderbooks_loaded") or len(signals))
        source = "monitor_discovery"
    else:
        markets = client.get_markets(series_tickers=series, max_markets=max_markets)
        enriched = client.enrich_with_orderbooks(markets)
        signals = analyze_markets(enriched)
        markets_scanned = len(enriched)
        source = "monitor"
    saved = save_signals(
        signals,
        source=source,
        metadata={
            "series": series,
            "max_markets": max_markets,
            "markets_scanned": markets_scanned,
            "discover": discover,
            **discovery_metadata,
        },
    )
    write_latest_csv(signals, latest_csv)
    actionable = sum(1 for row in signals if row.get("action") in {"BUY_YES_PAPER", "BUY_NO_PAPER"})
    memory_mb = process_memory_mb()
    status = "OK" if markets_scanned else "WARN"
    message = (
        f"Saved {saved} signals from {markets_scanned} markets."
        if markets_scanned
        else "No markets scanned. Check network, Kalshi API availability, or series tickers."
    )
    metadata = {
        "series": series,
        "max_markets": max_markets,
        "markets_scanned": markets_scanned,
        "signals_saved": saved,
        "actionable_count": actionable,
        "memory_mb": round(memory_mb, 2),
        "discover": discover,
        **discovery_metadata,
    }
    record_monitor_run(
        started_at=started_at,
        status=status,
        series=series,
        max_markets=max_markets,
        markets_scanned=markets_scanned,
        signals_saved=saved,
        actionable_count=actionable,
        memory_mb=memory_mb,
    )
    save_heartbeat(
        status=status,
        message=message,
        metadata=metadata,
    )
    supabase_result: dict[str, object] = {"enabled": False}
    if supabase_store is not None and supabase_store.enabled:
        try:
            supabase_result = supabase_store.sync(
                signals,
                status=status,
                message=message,
                metadata=metadata,
                observed_at=utc_now_iso(),
            )
        except Exception as exc:  # pragma: no cover - network defensive guard
            supabase_result = {"enabled": True, "error": f"{type(exc).__name__}: {exc}"}
            logging.warning("supabase sync failed: %s", supabase_result["error"])
    return {
        "signals_saved": saved,
        "markets_scanned": markets_scanned,
        "actionable_count": actionable,
        "memory_mb": memory_mb,
        "supabase": supabase_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a continuous paper-trading Kalshi market monitor.")
    parser.add_argument("--series", default=",".join(DEFAULT_SERIES), help="Comma-separated Kalshi series tickers.")
    parser.add_argument("--max-markets", type=int, default=SETTINGS.max_markets)
    parser.add_argument("--interval", type=int, default=max(SETTINGS.refresh_seconds, 10), help="Seconds between scans.")
    parser.add_argument("--once", action="store_true", help="Run one scan, save it, then exit.")
    parser.add_argument("--latest-csv", default="outputs/kalshi_latest_signals.csv", help="Optional latest snapshot CSV.")
    parser.add_argument("--no-supabase", action="store_true", help="Disable Supabase sync even when env vars are set.")
    parser.add_argument("--discover", action="store_true", help="Scan broad open markets and monitor ranked candidates.")
    parser.add_argument("--discovery-scan-limit", type=int, default=SETTINGS.discovery_scan_limit)
    parser.add_argument("--discovery-candidates", type=int, default=SETTINGS.discovery_candidate_limit)
    parser.add_argument("--discovery-final-limit", type=int, default=SETTINGS.discovery_final_limit)
    parser.add_argument("--discovery-min-volume", type=float, default=SETTINGS.discovery_min_volume_24h)
    parser.add_argument("--discovery-min-open-interest", type=float, default=SETTINGS.discovery_min_open_interest)
    parser.add_argument("--include-combos", action="store_true", help="Include cross-category combo markets.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    series = parse_series(args.series)
    interval = max(5, int(args.interval))
    supabase_store = None if args.no_supabase else SupabaseStore()
    discovery_config = DiscoveryConfig(
        scan_limit=args.discovery_scan_limit,
        candidate_limit=args.discovery_candidates,
        final_limit=args.discovery_final_limit,
        min_volume_24h=args.discovery_min_volume,
        min_open_interest=args.discovery_min_open_interest,
        include_combo_markets=args.include_combos,
    )
    logging.info(
        "starting monitor: mode=%s series=%s max_markets=%s interval=%ss",
        "discover" if args.discover else "series",
        ",".join(series),
        args.max_markets,
        interval,
    )
    if supabase_store is not None and supabase_store.enabled:
        logging.info(
            "supabase sync enabled: history_interval=%ss retention=%sd",
            SETTINGS.supabase_history_interval_seconds,
            SETTINGS.supabase_retention_days,
        )
    save_heartbeat(
        status="STARTING",
        message="Monitor process started.",
        metadata={"series": series, "max_markets": args.max_markets, "interval": interval, "discover": args.discover},
    )

    while True:
        started_at = utc_now_iso()
        try:
            result = run_once(
                series=series,
                max_markets=args.max_markets,
                latest_csv=args.latest_csv,
                supabase_store=supabase_store,
                discover=args.discover,
                discovery_config=discovery_config,
            )
            logging.info(
                "saved=%s scanned=%s actionable=%s memory_mb=%.1f supabase=%s",
                result["signals_saved"],
                result["markets_scanned"],
                result["actionable_count"],
                result["memory_mb"],
                result["supabase"],
            )
        except KeyboardInterrupt:
            save_heartbeat(status="STOPPED", message="Monitor stopped by keyboard interrupt.")
            logging.info("monitor stopped")
            break
        except Exception as exc:  # pragma: no cover - defensive process guard
            message = f"{type(exc).__name__}: {exc}"
            logging.exception("scan failed")
            record_monitor_run(
                started_at=started_at,
                status="ERROR",
                series=series,
                max_markets=args.max_markets,
                markets_scanned=0,
                signals_saved=0,
                actionable_count=0,
                error_message=message,
                memory_mb=process_memory_mb(),
            )
            save_heartbeat(status="ERROR", message=message, metadata={"series": series, "max_markets": args.max_markets})
        if args.once:
            break
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            save_heartbeat(status="STOPPED", message="Monitor stopped by keyboard interrupt.")
            logging.info("monitor stopped")
            break


if __name__ == "__main__":
    main()
