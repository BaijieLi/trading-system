# Kalshi Trading Radar

A lightweight Kalshi market scanner for research and paper trading.

This project is intentionally conservative. It does **not** place real orders. It scans public Kalshi market data, parses top-of-book quotes, estimates fees/spread/slippage, and records paper trades for later review.

## What It Does

- Reads public Kalshi markets and orderbooks.
- Skips markets with no two-sided quote, wide spreads, low volume, or weak visible depth.
- Estimates a fair probability from microprice unless you provide a manual/model fair value.
- Calculates fee-adjusted expected value for YES and NO.
- Shows paper-only BUY/NO_TRADE/WATCH signals.
- Tracks open paper positions and generates SELL/HOLD exit guidance from the latest bid, fair probability, unrealized PnL, and remaining edge.
- Links each signal to Kalshi's ticker resolver so the exact contract can be opened from the dashboard.
- Can run a broader market discovery scan that ranks liquid candidates before loading orderbooks.
- Tracks memory usage so it does not overload your computer.
- Saves signal snapshots, paper trades, and paper exits to SQLite.
- Includes an NBA live scoreboard tab that uses ESPN as the primary live source and compares it against NBA liveData to flag stale provider responses.
- Adds a transparent NBA score-clock win probability heuristic for live games, finals, and scheduled games.

## What It Does Not Do

- It does not promise profit.
- It does not scrape private data.
- It does not use LinkedIn/Handshake-style scraping.
- It does not submit live Kalshi orders.
- It does not run an all-market high-frequency scanner or place trades automatically.

## Run Locally

```bash
cd /Users/libaijie/Downloads/Github_project/kalshi-trading-system
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/scan_markets.py --max-markets 20
streamlit run app/dashboard.py --server.port 8504
```

To scan a broader open-market universe and rank a candidate watchlist:

```bash
python scripts/scan_markets.py \
  --discover \
  --discovery-scan-limit 1000 \
  --discovery-candidates 80 \
  --discovery-final-limit 50
```

Discovery mode first scans open market metadata, filters out low-liquidity markets, loads orderbooks only for the strongest candidates, and then ranks them with a conservative score based on liquidity, spread/quote quality, and paper edge. It still does not mean "buy"; it means "worth watching first."

## Run the Background Monitor

The dashboard is for viewing and manual paper trades. The monitor is the process that keeps saving snapshots even when the browser is closed.

```bash
cd /Users/libaijie/Downloads/Github_project/kalshi-trading-system
source .venv/bin/activate
python scripts/monitor_markets.py --interval 30 --max-markets 50
```

For a broader watchlist monitor, use a slower interval so API usage stays reasonable:

```bash
python scripts/monitor_markets.py --discover --interval 120 --discovery-scan-limit 1000 --discovery-candidates 80
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
DISCOVERY_SCAN_LIMIT=1000
DISCOVERY_CANDIDATE_LIMIT=80
DISCOVERY_FINAL_LIMIT=50
MAX_RISK_PER_TRADE_PCT=1.0
MAX_DAILY_LOSS_PCT=3.0
SUPABASE_ENABLED=false
```

## Interpreting Signals

- `BUY_YES_PAPER`: paper-only signal where estimated YES edge clears fee, spread, and slippage buffers.
- `BUY_NO_PAPER`: paper-only signal where estimated NO edge clears fee, spread, and slippage buffers.
- `WATCH`: market is tradable enough to watch, but no fee-adjusted edge.
- `NO_TRADE`: blocked by liquidity, depth, or spread filters.

## Paper Exit Guidance

After a paper trade is recorded, the dashboard treats it as an open position until a paper exit is recorded. The `Paper Trades` tab compares the entry price with the current visible bid and assigns one of these exit actions:

- `SELL_TAKE_PROFIT`: unrealized return cleared the take-profit threshold.
- `SELL_STOP_LOSS`: unrealized return crossed the stop-loss threshold.
- `SELL_EDGE_GONE`: holding is no longer meaningfully better than exiting at the visible bid.
- `SELL_RISK_REVERSAL`: the latest signal favors the opposite side.
- `HOLD`: no exit threshold has fired.
- `HOLD_TO_SETTLEMENT`: the estimated side probability is high and remaining edge is still positive.
- `HOLD_MONITOR`: the position needs more data before an orderly exit can be modeled.

Microprice-based fair value is not enough to trade real money. Before live trading, the next step is to plug in a domain model, run paper trading for several weeks, and check realized PnL, drawdown, fill quality, and whether the edge survives fees.

## NBA Live Scores

The Streamlit dashboard includes an `NBA Live` tab for checking current NBA scores while reviewing sports-related markets. It intentionally does not rely on Kalshi for scoreboard truth. ESPN is used as the primary scoreboard source, while NBA liveData is queried as a comparison source when available. The default scoreboard date uses `America/New_York` so cloud deployments do not jump to tomorrow when the server clock is already past midnight UTC. If the two providers disagree, the dashboard shows a warning instead of silently trusting stale data.

The same tab also shows `predicted_winner`, `home_win_prob`, `away_win_prob`, and `confidence`. This is a simple score-clock heuristic: finals are assigned to the actual winner, scheduled games are treated as 50/50 unless a future team-strength model is added, and live games use current score margin plus estimated minutes remaining. It is for situational awareness, not a betting line.

The `NBA vs Kalshi Market Edge` section performs a bounded scan of open Kalshi events, keeps only markets that mention both teams in a listed NBA game, loads a capped number of orderbooks, and compares the model win probability against fee-adjusted YES/NO prices. It stays paper-only and blocks ambiguous markets where the dashboard cannot infer which team a YES contract represents.
