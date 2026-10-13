from __future__ import annotations

from datetime import date, datetime, timezone
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from kalshi_trading_system.collectors.kalshi_public import KalshiPublicClient  # noqa: E402
from kalshi_trading_system.collectors.nba_live import (  # noqa: E402
    NBA_SCOREBOARD_TIMEZONE,
    default_nba_scoreboard_date,
    fetch_best_nba_scoreboard,
)
from kalshi_trading_system.config import DEFAULT_SERIES, SETTINGS  # noqa: E402
from kalshi_trading_system.execution.exit_strategy import SELL_ACTIONS, evaluate_open_positions  # noqa: E402
from kalshi_trading_system.execution.paper_broker import simulate_trade  # noqa: E402
from kalshi_trading_system.models.discovery import DiscoveryConfig, discover_market_signals  # noqa: E402
from kalshi_trading_system.models.edge import analyze_markets, ticker_market_url  # noqa: E402
from kalshi_trading_system.models.nba_market_edge import (  # noqa: E402
    NBAMarketEdgeConfig,
    discover_nba_market_edges,
    discover_nba_raw_board,
)
from kalshi_trading_system.models.tennis_observer import (  # noqa: E402
    TennisObserverConfig,
    discover_tennis_watchlist,
)
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

NBA_EDGE_ROW_FIELDS = (
    "away",
    "away_name",
    "away_score",
    "away_win_prob",
    "home",
    "home_name",
    "home_score",
    "home_win_prob",
    "game_time_utc",
    "status",
    "period",
    "clock",
    "minutes_remaining_est",
    "predicted_winner",
    "confidence",
)


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


@st.cache_data(ttl=15, show_spinner=False)
def load_nba_scoreboard(game_date: date, include_comparison: bool) -> tuple[pd.DataFrame, dict[str, object]]:
    result = fetch_best_nba_scoreboard(game_date=game_date, include_comparison=include_comparison)
    return pd.DataFrame(result.rows), result.metadata


@st.cache_data(ttl=15, show_spinner=False)
def load_nba_market_edges(
    scoreboard_signature: tuple[tuple[object, ...], ...],
    scan_limit: int,
    candidate_limit: int,
    orderbook_limit: int,
    min_edge: float,
    max_spread: float,
    manual_tickers: tuple[str, ...],
) -> tuple[pd.DataFrame, dict[str, object]]:
    scoreboard_rows = [dict(zip(NBA_EDGE_ROW_FIELDS, values, strict=False)) for values in scoreboard_signature]
    client = KalshiPublicClient()
    config = NBAMarketEdgeConfig(
        scan_limit=scan_limit,
        max_pages=max(1, (scan_limit + 199) // 200),
        candidate_limit=candidate_limit,
        orderbook_limit=orderbook_limit,
        min_edge=min_edge,
        max_spread=max_spread,
    )
    rows, metadata = discover_nba_market_edges(
        client,
        scoreboard_rows,
        config=config,
        manual_tickers=manual_tickers,
    )
    return pd.DataFrame(rows), metadata


@st.cache_data(ttl=15, show_spinner=False)
def load_nba_kalshi_board(
    scoreboard_signature: tuple[tuple[object, ...], ...],
    scan_limit: int,
    orderbook_limit: int,
    min_edge: float,
    max_spread: float,
    manual_tickers: tuple[str, ...],
) -> tuple[pd.DataFrame, dict[str, object]]:
    scoreboard_rows = [dict(zip(NBA_EDGE_ROW_FIELDS, values, strict=False)) for values in scoreboard_signature]
    client = KalshiPublicClient()
    config = NBAMarketEdgeConfig(
        scan_limit=scan_limit,
        max_pages=max(1, (scan_limit + 199) // 200),
        orderbook_limit=orderbook_limit,
        min_edge=min_edge,
        max_spread=max_spread,
    )
    rows, metadata = discover_nba_raw_board(
        client,
        scoreboard_rows,
        config=config,
        manual_tickers=manual_tickers,
    )
    return pd.DataFrame(rows), metadata


@st.cache_data(ttl=20, show_spinner=False)
def load_tennis_watchlist(
    scan_limit: int,
    candidate_limit: int,
    orderbook_limit: int,
    max_spread: float,
    min_volume_24h: float,
    min_open_interest: float,
) -> tuple[pd.DataFrame, dict[str, object]]:
    client = KalshiPublicClient()
    rows, metadata = discover_tennis_watchlist(
        client,
        TennisObserverConfig(
            scan_limit=scan_limit,
            max_pages=max(1, (scan_limit + 999) // 1000),
            candidate_limit=candidate_limit,
            orderbook_limit=orderbook_limit,
            max_spread=max_spread,
            min_volume_24h=min_volume_24h,
            min_open_interest=min_open_interest,
        ),
    )
    return pd.DataFrame(rows), metadata


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


def refresh_dataframe_market_urls(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "ticker" not in df.columns:
        return df
    next_df = df.copy()
    next_df["market_url"] = next_df["ticker"].map(ticker_market_url)
    return next_df


def nba_edge_signature(nba_df: pd.DataFrame) -> tuple[tuple[object, ...], ...]:
    if nba_df.empty:
        return ()
    safe_df = nba_df.copy()
    for column in NBA_EDGE_ROW_FIELDS:
        if column not in safe_df.columns:
            safe_df[column] = ""
    return tuple(tuple(row[column] for column in NBA_EDGE_ROW_FIELDS) for _, row in safe_df.iterrows())


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
df = refresh_dataframe_market_urls(df)

if not df.empty and manual_fair and not discover:
    # Recalculate only the displayed rows when manual overrides are entered.
    client = KalshiPublicClient()
    markets = client.enrich_with_orderbooks(client.get_markets(series_tickers=list(series), max_markets=max_markets))
    df = pd.DataFrame(analyze_markets(markets, manual_fair=manual_fair))
    df = refresh_dataframe_market_urls(df)
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

tab_cloud, tab_monitor, tab_signals, tab_nba, tab_tennis, tab_paper, tab_notes = st.tabs(
    ["Cloud", "Monitor", "Signals", "NBA Live", "Tennis", "Paper Trades", "Reality Check"]
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
            cloud_df = refresh_dataframe_market_urls(pd.DataFrame(cloud_rows))
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
            snapshot_df = refresh_dataframe_market_urls(pd.DataFrame(snapshot_rows))
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

with tab_nba:
    st.subheader("NBA Live Scoreboard")
    st.caption(
        "Uses ESPN as the primary live scoreboard and compares against NBA liveData when available. "
        "This helps catch stale provider data during preseason and live games."
    )
    nba_cols = st.columns([1, 1, 2])
    selected_nba_date = nba_cols[0].date_input("Game date", value=default_nba_scoreboard_date())
    include_nba_compare = nba_cols[1].checkbox("Compare NBA liveData", value=True)
    nba_cols[2].caption(
        f"Default date uses {NBA_SCOREBOARD_TIMEZONE}. Refresh TTL: 15s. "
        "Re-run/reload the app for the newest provider response."
    )

    with st.spinner("Loading NBA live scoreboard..."):
        nba_df, nba_metadata = load_nba_scoreboard(selected_nba_date, include_nba_compare)

    selected_source = str(nba_metadata.get("selected_source") or "unknown")
    nba_metric_cols = st.columns(4)
    nba_metric_cols[0].metric("selected source", selected_source)
    nba_metric_cols[1].metric("games", int(nba_metadata.get("games") or len(nba_df)))
    comparison = nba_metadata.get("comparison") if isinstance(nba_metadata.get("comparison"), dict) else {}
    nba_metric_cols[2].metric("source mismatches", int(comparison.get("mismatch_count") or 0))
    nba_metric_cols[3].metric("fetched", age_label(str(nba_metadata.get("dashboard_fetched_at") or "")))

    if nba_metadata.get("nba_provider_time"):
        st.caption(
            "NBA liveData provider timestamp: "
            f"{nba_metadata.get('nba_provider_time')} for game date {nba_metadata.get('nba_game_date', '')}."
        )
    errors = nba_metadata.get("errors") or []
    if errors:
        st.warning(" | ".join(str(error) for error in errors))
    mismatches = comparison.get("mismatches") if isinstance(comparison, dict) else []
    if mismatches:
        st.warning("Provider disagreement detected: " + " ; ".join(str(item) for item in mismatches))

    if nba_df.empty:
        st.info("No NBA games returned for this date/source.")
    else:
        nba_display_cols = [
            "source",
            "status",
            "period",
            "clock",
            "predicted_winner",
            "confidence",
            "away_win_prob",
            "home_win_prob",
            "away",
            "away_score",
            "home",
            "home_score",
            "minutes_remaining_est",
            "score_margin_home",
            "venue",
            "game_time_utc",
            "game_url",
        ]
        available_nba_cols = [col for col in nba_display_cols if col in nba_df.columns]
        st.dataframe(
            nba_df[available_nba_cols],
            use_container_width=True,
            hide_index=True,
            column_config={"game_url": st.column_config.LinkColumn("game_url", display_text="Gamecast")},
        )
        st.download_button(
            "Download NBA scoreboard CSV",
            nba_df[available_nba_cols].to_csv(index=False).encode("utf-8"),
            file_name="nba_live_scoreboard.csv",
            mime="text/csv",
        )

    st.divider()
    st.subheader("NBA vs Kalshi Market Edge")
    st.caption(
        "This section shows raw Kalshi NBA moneyline and total-market quotes for the games above first. "
        "The action column remains paper-only and uses a simple score-clock heuristic, not financial advice."
    )
    edge_cols = st.columns(5)
    compare_kalshi_nba = edge_cols[0].checkbox("Compare Kalshi markets", value=True)
    nba_edge_scan_limit = edge_cols[1].slider("Market scan cap", min_value=100, max_value=3000, value=1000, step=100)
    nba_edge_orderbooks = edge_cols[2].slider("Orderbook cap", min_value=5, max_value=50, value=30, step=5)
    nba_edge_min = edge_cols[3].slider("Min edge", min_value=0.03, max_value=0.20, value=0.08, step=0.01)
    nba_edge_spread = edge_cols[4].slider("Max spread", min_value=0.02, max_value=0.15, value=0.06, step=0.01)
    manual_nba_ticker_text = st.text_area(
        "Optional Kalshi NBA market tickers",
        placeholder="Paste one ticker per line if a market is not found by the bounded scan.",
        height=70,
    )
    manual_nba_tickers = tuple(
        item.strip()
        for item in manual_nba_ticker_text.replace(",", "\n").splitlines()
        if item.strip()
    )

    if nba_df.empty:
        st.info("Load a scoreboard first before comparing against Kalshi markets.")
    elif compare_kalshi_nba:
        with st.spinner("Loading live Kalshi NBA moneyline and total quotes..."):
            nba_board_df, nba_board_metadata = load_nba_kalshi_board(
                nba_edge_signature(nba_df),
                nba_edge_scan_limit,
                nba_edge_orderbooks,
                nba_edge_min,
                nba_edge_spread,
                manual_nba_tickers,
            )
        edge_metric_cols = st.columns(6)
        edge_metric_cols[0].metric("NBA games above", len(nba_df))
        edge_metric_cols[1].metric("Kalshi markets scanned", int(nba_board_metadata.get("markets_scanned") or 0))
        edge_metric_cols[2].metric("quotes found", int(nba_board_metadata.get("markets_found") or 0))
        edge_metric_cols[3].metric("moneyline", int(nba_board_metadata.get("game_markets") or 0))
        edge_metric_cols[4].metric("totals", int(nba_board_metadata.get("total_markets") or 0))
        edge_metric_cols[5].metric("paper actionable", int(nba_board_metadata.get("actionable") or 0))
        edge_errors = nba_board_metadata.get("errors") or []
        if edge_errors:
            st.warning(" | ".join(str(error) for error in edge_errors))
        if nba_board_df.empty:
            st.info(
                "NBA games exist in the scoreboard above, but no Kalshi NBA moneyline/total quotes were found. "
                "If you see a specific game ticker on Kalshi, paste it above."
            )
        else:
            st.caption(
                "YES/NO bid/ask are Kalshi live quote fields. For TOTAL rows, YES usually means the Over side. "
                "For MONEYLINE rows, YES means the team shown in side_or_line wins."
            )
            nba_board_cols = [
                "game",
                "status",
                "period",
                "clock",
                "score",
                "current_total",
                "market_type",
                "side_or_line",
                "action",
                "model_probability",
                "fee_adjusted_edge",
                "total_line",
                "projected_total",
                "yes_bid",
                "yes_ask",
                "no_bid",
                "no_ask",
                "spread",
                "volume_24h",
                "open_interest",
                "kalshi_status",
                "risk_flags",
                "title",
                "market_url",
                "hub_url",
            ]
            visible_edge_cols = [col for col in nba_board_cols if col in nba_board_df.columns]
            st.dataframe(
                nba_board_df[visible_edge_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "market_url": st.column_config.LinkColumn("market_url", display_text="Open"),
                    "hub_url": st.column_config.LinkColumn("hub_url", display_text="NBA Hub"),
                },
            )
            st.download_button(
                "Download NBA/Kalshi board CSV",
                nba_board_df[visible_edge_cols].to_csv(index=False).encode("utf-8"),
                file_name="nba_kalshi_board.csv",
                mime="text/csv",
            )

with tab_tennis:
    st.subheader("Tennis Watchlist")
    st.caption(
        "Tennis is observation-only here. Kalshi tennis prices move quickly point-by-point, and this app does not "
        "have an independent player model yet, so it ranks market quality instead of issuing buy signals."
    )
    tennis_cols = st.columns(6)
    tennis_scan_limit = tennis_cols[0].slider("Tennis scan cap", min_value=500, max_value=3000, value=2500, step=250)
    tennis_candidates = tennis_cols[1].slider("Tennis candidates", min_value=20, max_value=160, value=120, step=20)
    tennis_orderbooks = tennis_cols[2].slider("Tennis orderbooks", min_value=10, max_value=80, value=40, step=10)
    tennis_spread = tennis_cols[3].slider("Tennis max spread", min_value=0.01, max_value=0.15, value=0.06, step=0.01)
    tennis_min_volume = tennis_cols[4].number_input("Min volume", min_value=0.0, max_value=100000.0, value=1000.0, step=500.0)
    tennis_min_oi = tennis_cols[5].number_input("Min open interest", min_value=0.0, max_value=100000.0, value=1000.0, step=500.0)

    with st.spinner("Loading Kalshi tennis markets..."):
        tennis_df, tennis_metadata = load_tennis_watchlist(
            tennis_scan_limit,
            tennis_candidates,
            tennis_orderbooks,
            tennis_spread,
            tennis_min_volume,
            tennis_min_oi,
        )
    tennis_metric_cols = st.columns(5)
    tennis_metric_cols[0].metric("markets scanned", int(tennis_metadata.get("markets_scanned") or 0))
    tennis_metric_cols[1].metric("candidate tickers", int(tennis_metadata.get("candidate_tickers") or 0))
    tennis_metric_cols[2].metric("quotes found", int(tennis_metadata.get("markets_found") or 0))
    tennis_metric_cols[3].metric("orderbooks", int(tennis_metadata.get("orderbooks_loaded") or 0))
    tennis_metric_cols[4].metric("watch liquid", int(tennis_metadata.get("watch_liquid") or 0))
    tennis_errors = tennis_metadata.get("errors") or []
    if tennis_errors:
        st.warning(" | ".join(str(error) for error in tennis_errors))
    if tennis_df.empty:
        st.info("No tennis markets found in the current bounded Kalshi scan.")
    else:
        tennis_cols_display = [
            "action",
            "stability_score",
            "series_ticker",
            "title",
            "yes_bid",
            "yes_ask",
            "no_bid",
            "no_ask",
            "spread",
            "midpoint",
            "volume_24h",
            "open_interest",
            "kalshi_status",
            "risk_flags",
            "market_url",
            "hub_url",
        ]
        visible_tennis_cols = [col for col in tennis_cols_display if col in tennis_df.columns]
        st.dataframe(
            tennis_df[visible_tennis_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "market_url": st.column_config.LinkColumn("market_url", display_text="Open"),
                "hub_url": st.column_config.LinkColumn("hub_url", display_text="Tennis Hub"),
            },
        )
        st.download_button(
            "Download tennis watchlist CSV",
            tennis_df[visible_tennis_cols].to_csv(index=False).encode("utf-8"),
            file_name="tennis_watchlist.csv",
            mime="text/csv",
        )

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
