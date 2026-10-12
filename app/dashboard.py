from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from kalshi_trading_system.collectors.kalshi_public import KalshiPublicClient  # noqa: E402
from kalshi_trading_system.config import DEFAULT_SERIES, SETTINGS  # noqa: E402
from kalshi_trading_system.execution.exit_strategy import SELL_ACTIONS, evaluate_open_positions  # noqa: E402
from kalshi_trading_system.execution.paper_broker import simulate_trade  # noqa: E402
from kalshi_trading_system.models.discovery import DiscoveryConfig, discover_market_signals  # noqa: E402
from kalshi_trading_system.models.edge import analyze_markets  # noqa: E402
from kalshi_trading_system.storage.sqlite_store import (  # noqa: E402
    latest_heartbeat,
    latest_signal_snapshot,
    open_paper_trades,
    recent_paper_exits,
    recent_monitor_runs,
    save_paper_exit,
    save_signals,
    save_trade,
)
from kalshi_trading_system.storage.supabase_store import SupabaseReader  # noqa: E402
from kalshi_trading_system.utils.system import process_memory_mb  # noqa: E402


st.set_page_config(page_title="Kalshi Trading Radar", page_icon="📈", layout="wide")


@st.cache_data(ttl=10, show_spinner=False)
def load_signals(
    series: tuple[str, ...],
    max_markets: int,
    discover: bool,
    discovery_scan_limit: int,
    discovery_candidates: int,
    discovery_final_limit: int,
) -> tuple[pd.DataFrame, int, dict[str, object]]:
    client = KalshiPublicClient()
    if discover:
        signals, metadata = discover_market_signals(
            client,
            DiscoveryConfig(
                scan_limit=discovery_scan_limit,
                candidate_limit=discovery_candidates,
                final_limit=discovery_final_limit,
            ),
        )
        return pd.DataFrame(signals), int(metadata.get("markets_seen") or 0), metadata
    markets = client.get_markets(series_tickers=list(series), max_markets=max_markets)
    enriched = client.enrich_with_orderbooks(markets)
    signals = analyze_markets(enriched)
    return pd.DataFrame(signals), len(enriched), {"mode": "series"}


@st.cache_data(ttl=5, show_spinner=False)
def load_monitor_state() -> tuple[dict[str, object] | None, dict[str, object] | None, list[dict[str, object]]]:
    return latest_heartbeat(), latest_signal_snapshot(), recent_monitor_runs(limit=10)


@st.cache_data(ttl=10, show_spinner=False)
def load_cloud_state() -> tuple[dict[str, object] | None, list[dict[str, object]], list[dict[str, object]], bool]:
    reader = SupabaseReader()
    if not reader.enabled:
        return None, [], [], False
    return reader.heartbeat(), reader.market_state(limit=200), reader.monitor_runs(limit=10), True


def age_label(iso_timestamp: str) -> str:
    try:
        value = datetime.fromisoformat(iso_timestamp)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - value).total_seconds()))
    except ValueError:
        return "unknown"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


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
    discover = st.checkbox(
        "Discover broader market universe",
        value=False,
        help="Scans open Kalshi markets, filters for liquid candidates, then ranks a smaller watchlist.",
    )
    discovery_scan_limit = st.slider(
        "Discovery scan limit",
        min_value=100,
        max_value=3000,
        value=min(SETTINGS.discovery_scan_limit, 1000),
        step=100,
        disabled=not discover,
    )
    discovery_candidates = st.slider(
        "Discovery orderbooks",
        min_value=20,
        max_value=150,
        value=min(SETTINGS.discovery_candidate_limit, 80),
        step=10,
        disabled=not discover,
    )
    discovery_final_limit = st.slider(
        "Discovery watchlist",
        min_value=10,
        max_value=100,
        value=min(SETTINGS.discovery_final_limit, 50),
        step=10,
        disabled=not discover,
    )
    st.caption(f"Refresh target: {SETTINGS.refresh_seconds}s. Streamlit cache TTL: 10s.")

    heartbeat, latest_snapshot, monitor_runs = load_monitor_state()
    st.header("Background Monitor")
    if heartbeat:
        st.write(f"Status: **{heartbeat['status']}**")
        st.caption(f"Last heartbeat: {age_label(str(heartbeat['updated_at']))}")
    else:
        st.caption("No background monitor heartbeat yet.")
    st.code("python scripts/monitor_markets.py --interval 30 --max-markets 50", language="bash")

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
    df, scanned, scan_metadata = load_signals(
        series,
        max_markets,
        discover,
        discovery_scan_limit,
        discovery_candidates,
        discovery_final_limit,
    )

if not df.empty and manual_fair and not discover:
    # Recalculate only the displayed rows when manual overrides are entered.
    client = KalshiPublicClient()
    markets = client.enrich_with_orderbooks(client.get_markets(series_tickers=list(series), max_markets=max_markets))
    df = pd.DataFrame(analyze_markets(markets, manual_fair=manual_fair))
elif manual_fair and discover:
    st.info("Manual fair overrides are applied only in fixed-series mode. Discovery mode ranks the broad watchlist first.")

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
    "risk_flags",
    "market_url",
]

tab_cloud, tab_monitor, tab_signals, tab_paper, tab_notes = st.tabs(
    ["Cloud", "Monitor", "Signals", "Paper Trades", "Reality Check"]
)

with tab_cloud:
    st.subheader("Supabase Cloud State")
    cloud_heartbeat, cloud_rows, cloud_runs, cloud_enabled = load_cloud_state()
    if not cloud_enabled:
        st.info("Set SUPABASE_URL and SUPABASE_ANON_KEY to read the cloud-backed latest market state.")
    else:
        if cloud_heartbeat:
            cloud_cols = st.columns(4)
            cloud_cols[0].metric("cloud status", cloud_heartbeat.get("status", "unknown"))
            cloud_cols[1].metric("updated", age_label(str(cloud_heartbeat.get("updated_at", ""))))
            metadata = cloud_heartbeat.get("metadata") or {}
            cloud_cols[2].metric("markets", metadata.get("markets_scanned", 0))
            cloud_cols[3].metric("actionable", metadata.get("actionable_count", 0))
            st.caption(str(cloud_heartbeat.get("message", "")))
        if cloud_rows:
            cloud_df = pd.DataFrame(cloud_rows)
            available_cols = [col for col in display_cols if col in cloud_df.columns]
            st.dataframe(
                cloud_df[available_cols],
                use_container_width=True,
                hide_index=True,
                column_config={"market_url": st.column_config.LinkColumn("market_url", display_text="Open")},
            )
        else:
            st.caption("No cloud market rows yet.")
        if cloud_runs:
            st.subheader("Cloud Monitor Runs")
            st.dataframe(pd.DataFrame(cloud_runs), use_container_width=True, hide_index=True)

with tab_monitor:
    st.subheader("Background Monitor Health")
    if heartbeat:
        metadata = heartbeat.get("metadata") or {}
        monitor_cols = st.columns(5)
        monitor_cols[0].metric("status", str(heartbeat["status"]))
        monitor_cols[1].metric("last heartbeat", age_label(str(heartbeat["updated_at"])))
        monitor_cols[2].metric("last saved", metadata.get("signals_saved", 0))
        monitor_cols[3].metric("actionable", metadata.get("actionable_count", 0))
        monitor_cols[4].metric("monitor MB", metadata.get("memory_mb", 0))
        st.caption(str(heartbeat["message"]))
    else:
        st.info("Start the background monitor to get automatic snapshots and heartbeat checks.")

    st.code(
        "cd /Users/libaijie/Downloads/Github_project/kalshi-trading-system\n"
        "source .venv/bin/activate\n"
        "python scripts/monitor_markets.py --interval 30 --max-markets 50",
        language="bash",
    )

    if latest_snapshot:
        st.subheader("Latest Saved Snapshot")
        snapshot_rows = latest_snapshot.get("rows") or []
        st.caption(
            f"Snapshot #{latest_snapshot['id']} saved {age_label(str(latest_snapshot['created_at']))} "
            f"from source={latest_snapshot['source']}"
        )
        if snapshot_rows:
            snapshot_df = pd.DataFrame(snapshot_rows)
            available_snapshot_cols = [col for col in display_cols if col in snapshot_df.columns]
            st.dataframe(
                snapshot_df[available_snapshot_cols],
                use_container_width=True,
                hide_index=True,
                column_config={"market_url": st.column_config.LinkColumn("market_url", display_text="Open")},
            )
    else:
        st.caption("No saved snapshots yet.")

    if monitor_runs:
        st.subheader("Recent Monitor Runs")
        st.dataframe(pd.DataFrame(monitor_runs), use_container_width=True, hide_index=True)

with tab_signals:
    st.subheader("Fee/Spread-Adjusted Signals")
    if discover:
        st.caption(
            "Discovery mode: scanned {markets_seen} open markets, loaded {orderbooks_loaded} candidate orderbooks.".format(
                markets_seen=scan_metadata.get("markets_seen", scanned),
                orderbooks_loaded=scan_metadata.get("orderbooks_loaded", len(df)),
            )
        )
    available_display_cols = [col for col in display_cols if col in filtered.columns]
    st.dataframe(
        filtered[available_display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "market_url": st.column_config.LinkColumn("market_url", display_text="Open"),
        },
    )
    st.download_button(
        "Download signals CSV",
        filtered[available_display_cols].to_csv(index=False).encode("utf-8"),
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

    st.divider()
    st.subheader("Open Paper Positions")
    open_positions = open_paper_trades(limit=50)
    if not open_positions:
        st.caption("No open paper positions yet.")
    else:
        exit_rows = evaluate_open_positions(open_positions, df.to_dict("records"))
        exit_df = pd.DataFrame(exit_rows)
        exit_cols = [
            "trade_id",
            "ticker",
            "side",
            "contracts",
            "action",
            "entry_price",
            "exit_price",
            "unrealized_pnl",
            "unrealized_roi",
            "remaining_edge",
            "side_probability",
            "reason",
        ]
        visible_exit_cols = [col for col in exit_cols if col in exit_df.columns]
        st.dataframe(exit_df[visible_exit_cols], use_container_width=True, hide_index=True)

        recommended_exits = exit_df[exit_df["action"].isin(SELL_ACTIONS)] if "action" in exit_df.columns else pd.DataFrame()
        if recommended_exits.empty:
            st.caption("No paper position currently hits a modeled sell threshold.")
        else:
            selected_trade_id = st.selectbox(
                "Recommended paper exit",
                recommended_exits["trade_id"].astype(int).tolist(),
                format_func=lambda value: f"Trade #{value}",
            )
            selected_exit = recommended_exits[recommended_exits["trade_id"] == selected_trade_id].iloc[0].to_dict()
            st.json(selected_exit)
            if st.button("Record recommended paper exit"):
                save_paper_exit(selected_exit)
                st.success(
                    "Recorded paper exit for "
                    f"{selected_exit['ticker']} at ${float(selected_exit['exit_price']):.2f}"
                )

    recent_exits = recent_paper_exits(limit=20)
    if recent_exits:
        st.subheader("Recent Paper Exits")
        st.dataframe(pd.DataFrame(recent_exits), use_container_width=True, hide_index=True)

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
    st.write(
        "Paper exit rules are deliberately simple: take profit when unrealized return clears the target, cut losses at "
        "the stop threshold, sell when the original edge disappears, and hold only while the current side still has "
        "meaningful estimated value versus the visible exit bid."
    )
