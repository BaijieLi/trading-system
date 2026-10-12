from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from kalshi_trading_system.collectors.kalshi_public import KalshiPublicClient  # noqa: E402
from kalshi_trading_system.config import DEFAULT_SERIES, SETTINGS  # noqa: E402
from kalshi_trading_system.models.discovery import DiscoveryConfig, discover_market_signals  # noqa: E402
from kalshi_trading_system.models.edge import analyze_markets  # noqa: E402


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Scan Kalshi public markets for paper-trading signals.")
    parser.add_argument("--series", default=",".join(DEFAULT_SERIES), help="Comma-separated Kalshi series tickers.")
    parser.add_argument("--max-markets", type=int, default=SETTINGS.max_markets)
    parser.add_argument("--discover", action="store_true", help="Scan a broad open-market universe and rank candidates.")
    parser.add_argument("--discovery-scan-limit", type=int, default=SETTINGS.discovery_scan_limit)
    parser.add_argument("--discovery-candidates", type=int, default=SETTINGS.discovery_candidate_limit)
    parser.add_argument("--discovery-final-limit", type=int, default=SETTINGS.discovery_final_limit)
    parser.add_argument("--discovery-min-volume", type=float, default=SETTINGS.discovery_min_volume_24h)
    parser.add_argument("--discovery-min-open-interest", type=float, default=SETTINGS.discovery_min_open_interest)
    parser.add_argument("--include-combos", action="store_true", help="Include cross-category combo markets.")
    parser.add_argument("--output", default="", help="Optional CSV path.")
    args = parser.parse_args()

    client = KalshiPublicClient()
    if args.discover:
        signals, metadata = discover_market_signals(
            client,
            DiscoveryConfig(
                scan_limit=args.discovery_scan_limit,
                candidate_limit=args.discovery_candidates,
                final_limit=args.discovery_final_limit,
                min_volume_24h=args.discovery_min_volume,
                min_open_interest=args.discovery_min_open_interest,
                include_combo_markets=args.include_combos,
            ),
        )
        print(
            "Discovery scanned {markets_seen} markets, loaded {orderbooks_loaded} orderbooks, ranked {final_limit}.".format(
                **metadata
            ),
            file=sys.stderr,
        )
    else:
        series = [item.strip() for item in args.series.split(",") if item.strip()]
        markets = client.get_markets(series_tickers=series, max_markets=args.max_markets)
        enriched = client.enrich_with_orderbooks(markets)
        signals = analyze_markets(enriched)

    fields = [
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
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with Path(args.output).open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(signals)
        print(f"Wrote {len(signals)} signals to {args.output}")
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(signals[:25])


if __name__ == "__main__":
    main()
