# Kalshi Trading Radar

A lightweight Kalshi market scanner for research and paper trading.

This project is intentionally conservative. It does **not** place real orders. It scans public Kalshi market data, parses top-of-book quotes, estimates fees/spread/slippage, and records paper trades for later review.

## What It Does

- Reads public Kalshi markets and orderbooks.
- Skips markets with no two-sided quote, wide spreads, low volume, or weak visible depth.
- Estimates a fair probability from microprice unless you provide a manual/model fair value.
- Calculates fee-adjusted expected value for YES and NO.
- Shows paper-only BUY/NO_TRADE/WATCH signals.
- Tracks memory usage so it does not overload your computer.
- Saves signal snapshots and paper trades to SQLite.

## What It Does Not Do

- It does not promise profit.
- It does not scrape private data.
- It does not use LinkedIn/Handshake-style scraping.
- It does not submit live Kalshi orders.
- It does not run an all-market high-frequency scanner.

## Run Locally

```bash
cd /Users/libaijie/Downloads/Github_project/kalshi-trading-system
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/scan_markets.py --max-markets 20
streamlit run app/dashboard.py --server.port 8504
```

## Safety Defaults

```text
PAPER_TRADING_ONLY=true
MAX_MARKETS=50
REFRESH_SECONDS=10
MAX_RISK_PER_TRADE_PCT=1.0
MAX_DAILY_LOSS_PCT=3.0
```

## Interpreting Signals

- `BUY_YES_PAPER`: paper-only signal where estimated YES edge clears fee, spread, and slippage buffers.
- `BUY_NO_PAPER`: paper-only signal where estimated NO edge clears fee, spread, and slippage buffers.
- `WATCH`: market is tradable enough to watch, but no fee-adjusted edge.
- `NO_TRADE`: blocked by liquidity, depth, or spread filters.

Microprice-based fair value is not enough to trade real money. Before live trading, the next step is to plug in a domain model, run paper trading for several weeks, and check realized PnL, drawdown, fill quality, and whether the edge survives fees.

