# Supabase Setup

This project uses Supabase as a lightweight cloud sink for Streamlit dashboards.

The free-plan-friendly design is:

- `market_state`: one row per ticker, updated with upsert every monitor run.
- `market_observations`: sampled history, default every 5 minutes.
- `signal_events`: actionable paper signals only.
- `kalshi_monitor_runs`: lightweight run metadata.
- `system_heartbeat`: one row showing monitor health.

This avoids storing a full 30-second JSON snapshot forever.

## 1. Create Tables

Open Supabase SQL Editor and run:

```sql
-- paste docs/supabase/schema.sql
```

The schema enables public SELECT policies so a Streamlit app can read public market data with the anon key. Writes should use the service role key only from your local monitor or a trusted server.

## 2. Configure Local Monitor

Create or update `.env`:

```text
SUPABASE_ENABLED=true
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_HISTORY_INTERVAL_SECONDS=300
SUPABASE_RETENTION_DAYS=14
SUPABASE_CLEANUP_INTERVAL_SECONDS=3600
```

Never commit `.env`.

Then restart the LaunchAgent:

```bash
/Users/libaijie/Downloads/Github_project/kalshi-trading-system/scripts/load_kalshi_launchagent.command
```

## 3. Configure Streamlit Read-Only Dashboard

For Streamlit Cloud, set these secrets:

```text
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
```

Do not put `SUPABASE_SERVICE_ROLE_KEY` in Streamlit Cloud unless the app is private and you fully trust that deployment. The dashboard only needs read access.

## Free Plan Notes

Supabase Free projects currently have a 500 MB database size quota. With the default settings, only the latest market state is updated every run, while historical observations are sampled every 5 minutes and cleaned after 14 days.

If database size grows too fast, increase `SUPABASE_HISTORY_INTERVAL_SECONDS` or lower `SUPABASE_RETENTION_DAYS`.
