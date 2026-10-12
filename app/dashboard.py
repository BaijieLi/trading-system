from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from kalshi_trading_system.collectors.kalshi_public import KalshiPublicClient  # noqa: E402
from kalshi_trading_system.config import DEFAULT_SERIES, SETTINGS  # noqa: E402
from kalshi_trading_system.execution.paper_broker import simulate_trade  # noqa: E402
from kalshi_trading_system.models.edge import analyze_markets  # noqa: E402
from kalshi_trading_system.storage.sqlite_store import save_signals, save_trade  # noqa: E402
from kalshi_trading_system.utils.system import process_memory_mb  # noqa: E402


load_dotenv()
st.set_page_config(page_title="Kalshi Trading Radar", page_icon="📈", layout="wide")


@st.cache_data(ttl=10, show_spinner=False)
def load_signals(series: tuple[str, ...], max_markets: int) -> tuple[pd.DataFrame, int]:
    client = KalshiPublicClient()
    markets = client.get_markets(series_tickers=list(series), max_markets=max_markets)
    enriched = client.enrich_with_orderbooks(markets)
    signals = analyze_markets(enriched)
    return pd.DataFrame(signals), len(enriched)


def parse_manual_fair(text: str) -> dict[str, float]:
    overrides: dict[str, float] = {}
    for line in text.splitlines():
        if "," not in line:
            continue
        ticker, value = [part.strip() for part in line.split(",", 1)]
        try:
            probability = float(value)
        except ValueError:
            continue
        overrides[ticker] = probability / 100.0 if probability > 1 else probability
    return overrides


st.title("Kalshi Trading Radar")
st.caption("Public data scanner, fee/spread-adjusted edge calculator, and paper-trading dashboard.")

st.warning(
    "Paper-trading mode only. This dashboard does not place real Kalshi orders. "
    "Signals are research outputs, not financial advice."
)

with st.sidebar:
    st.header("Market Universe")
    series_text = st.text_area(
        "Series tickers",
        value=",".join(DEFAULT_SERIES),
        help="Comma-separated series tickers. Keep this small to protect memory and API usage.",
    )
    max_markets = st.slider("Max markets", min_value=5, max_value=50, value=min(SETTINGS.max_markets, 50), step=5)
    st.caption(f"Refresh target: {SETTINGS.refresh_seconds}s. Streamlit cache TTL: 10s.")

    st.header("Manual Fair Values")
    manual_text = st.text_area(
        "Optional ticker,fair_probability",
        placeholder="KXEXAMPLE-26JAN01-Y,0.62\nKXEXAMPLE-26JAN01-N,54",
        help="Use your own model probability here. Without this, the app uses microprice as a market-pressure estimate.",
        height=120,
    )
    bankroll = st.number_input("Paper bankroll", min_value=50.0, max_value=100000.0, value=SETTINGS.bankroll_dollars, step=50.0)
    min_ev = st.slider("Minimum EV shown", min_value=-0.20, max_value=0.20, value=-0.05, step=0.01)
    actions = st.multiselect(
        "Actions",
        ["BUY_YES_PAPER", "BUY_NO_PAPER", "WATCH", "NO_TRADE"],
        default=["BUY_YES_PAPER", "BUY_NO_PAPER", "WATCH"],
    )

series = tuple(item.strip() for item in series_text.split(",") if item.strip())
manual_fair = parse_manual_fair(manual_text)

with st.spinner("Loading public Kalshi markets and orderbooks..."):
    df, scanned = load_signals(series, max_markets)

if not df.empty and manual_fair:
    # Recalculate only the displayed rows when manual overrides are entered.
    client = KalshiPublicClient()
    markets = client.enrich_with_orderbooks(client.get_markets(series_tickers=list(series), max_markets=max_markets))
    df = pd.DataFrame(analyze_markets(markets, manual_fair=manual_fair))

if df.empty:
    st.error("No markets returned for the selected series.")
    st.stop()

filtered = df[df["expected_value"] >= min_ev]
if actions:
    filtered = filtered[filtered["action"].isin(actions)]
filtered = filtered.sort_values(["action", "expected_value"], ascending=[True, False])

metric_cols = st.columns(6)
metric_cols[0].metric("markets scanned", scanned)
metric_cols[1].metric("visible signals", len(filtered))
metric_cols[2].metric("actionable", int(df["action"].isin(["BUY_YES_PAPER", "BUY_NO_PAPER"]).sum()))
metric_cols[3].metric("wide/no-liq blocks", int((df["action"] == "NO_TRADE").sum()))
metric_cols[4].metric("memory MB", f"{process_memory_mb():.0f}")
metric_cols[5].metric("paper only", "ON" if SETTINGS.paper_trading_only else "OFF")

display_cols = [
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

tab_signals, tab_paper, tab_notes = st.tabs(["Signals", "Paper Trade", "Reality Check"])

with tab_signals:
    st.subheader("Fee/Spread-Adjusted Signals")
    st.dataframe(
        filtered[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "market_url": st.column_config.LinkColumn("market_url", display_text="Open"),
        },
    )
    st.download_button(
        "Download signals CSV",
        filtered[display_cols].to_csv(index=False).encode("utf-8"),
        file_name="kalshi_signals.csv",
        mime="text/csv",
    )
    if st.button("Save snapshot to SQLite"):
        save_signals(filtered.to_dict("records"))
        st.success("Saved signal snapshot to data/kalshi_paper.sqlite3")

with tab_paper:
    st.subheader("Paper Trade One Signal")
    actionable = filtered[filtered["action"].isin(["BUY_YES_PAPER", "BUY_NO_PAPER"])]
    if actionable.empty:
        st.info("No actionable paper signal under current filters.")
    else:
        selected = st.selectbox("Signal", actionable["ticker"].tolist())
        contracts = st.number_input("Requested contracts", min_value=1, max_value=1000, value=1)
        signal = actionable[actionable["ticker"] == selected].iloc[0].to_dict()
        st.json(signal)
        if st.button("Record paper trade"):
            trade = simulate_trade(signal, bankroll=bankroll, requested_contracts=int(contracts))
            if trade is None:
                st.error("Risk manager rejected this paper order.")
            else:
                save_trade(trade.to_dict())
                st.success(f"Recorded paper {trade.side} trade: {trade.contracts} contracts at ${trade.price:.2f}")

with tab_notes:
    st.subheader("Why this is conservative")
    st.write(
        "Orderbook microprice is not a true probability model. It is only a market-pressure estimate. "
        "A real edge should come from an external model, then be tested after fees, spread, slippage, and uncertainty."
    )
    st.write(
        "Default blockers: no two-sided quote, wide spread, low 24h volume, or low visible depth. "
        "This is designed to avoid the common trap of buying markets that look cheap but cannot be exited."
    )

