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

## Run the Background Monitor

The dashboard is for viewing and manual paper trades. The monitor is the process that keeps saving snapshots even when the browser is closed.

```bash
cd /Users/libaijie/Downloads/Github_project/kalshi-trading-system
source .venv/bin/activate
python scripts/monitor_markets.py --interval 30 --max-markets 50
```

For a local Mac run where you want to reduce sleep interruptions while the lid stays open:

```bash
caffeinate -dimsu python scripts/monitor_markets.py --interval 30 --max-markets 50
```

The monitor saves every scan to `data/kalshi_paper.sqlite3`, writes a latest CSV to `outputs/kalshi_latest_signals.csv`, and updates a heartbeat that appears in the Streamlit `Monitor` tab.

Important limitation: a local laptop is not a true 24/7 server. If the Mac sleeps or the lid is closed, scanning pauses. Already committed SQLite rows should remain on disk, but no new market data is collected during sleep. For real always-on monitoring, run this on a VPS or cloud machine with the same paper-only defaults.

## Optional Supabase Sink

For a Streamlit Cloud dashboard, use Supabase as the shared cloud database:

```bash
# Run once in Supabase SQL Editor:
# docs/supabase/schema.sql

# Local monitor .env:
SUPABASE_ENABLED=true
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_HISTORY_INTERVAL_SECONDS=300
SUPABASE_RETENTION_DAYS=14

# Streamlit Cloud secrets:
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
```

The monitor upserts `market_state` every scan, samples `market_observations` every 5 minutes, and cleans old history so Supabase Free is not filled by 30-second full snapshots. See `docs/supabase/README.md`.

## Safety Defaults

```text
PAPER_TRADING_ONLY=true
MAX_MARKETS=50
REFRESH_SECONDS=10
MAX_RISK_PER_TRADE_PCT=1.0
MAX_DAILY_LOSS_PCT=3.0
SUPABASE_ENABLED=false
```

## Interpreting Signals

- `BUY_YES_PAPER`: paper-only signal where estimated YES edge clears fee, spread, and slippage buffers.
- `BUY_NO_PAPER`: paper-only signal where estimated NO edge clears fee, spread, and slippage buffers.
- `WATCH`: market is tradable enough to watch, but no fee-adjusted edge.
- `NO_TRADE`: blocked by liquidity, depth, or spread filters.

Microprice-based fair value is not enough to trade real money. Before live trading, the next step is to plug in a domain model, run paper trading for several weeks, and check realized PnL, drawdown, fill quality, and whether the edge survives fees.
