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
from kalshi_trading_system.models.edge import analyze_markets  # noqa: E402


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Scan Kalshi public markets for paper-trading signals.")
    parser.add_argument("--series", default=",".join(DEFAULT_SERIES), help="Comma-separated Kalshi series tickers.")
    parser.add_argument("--max-markets", type=int, default=SETTINGS.max_markets)
    parser.add_argument("--output", default="", help="Optional CSV path.")
    args = parser.parse_args()

    series = [item.strip() for item in args.series.split(",") if item.strip()]
    client = KalshiPublicClient()
    markets = client.get_markets(series_tickers=series, max_markets=args.max_markets)
    enriched = client.enrich_with_orderbooks(markets)
    signals = analyze_markets(enriched)

    fields = [
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

