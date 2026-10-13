from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import requests


ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
NBA_LIVEDATA_SCOREBOARD_URL = (
    "https://nba-prod-us-east-1-mediaops-stats.s3.amazonaws.com/NBA/liveData/scoreboard/"
    "todaysScoreboard_00.json"
)

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (kalshi-trading-system nba live monitor)",
}


@dataclass(frozen=True)
class ScoreboardResult:
    rows: list[dict[str, object]]
    metadata: dict[str, object]


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _espn_team(competitors: list[dict[str, Any]], home_away: str) -> dict[str, Any]:
    for competitor in competitors:
        if competitor.get("homeAway") == home_away:
            return competitor
    return {}


def parse_espn_scoreboard(payload: dict[str, Any], fetched_at: datetime | None = None) -> ScoreboardResult:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    rows: list[dict[str, object]] = []
    for event in payload.get("events", []):
        competition = (event.get("competitions") or [{}])[0]
        status = competition.get("status") or {}
        status_type = status.get("type") or {}
        competitors = competition.get("competitors") or []
        away = _espn_team(competitors, "away")
        home = _espn_team(competitors, "home")
        away_team = away.get("team") or {}
        home_team = home.get("team") or {}
        game_id = str(event.get("id") or competition.get("id") or "")
        rows.append(
            {
                "source": "ESPN",
                "game_id": game_id,
                "game_time_utc": str(event.get("date") or ""),
                "status": str(status_type.get("description") or status_type.get("detail") or ""),
                "period": _safe_int(status.get("period")),
                "clock": str(status.get("displayClock") or ""),
                "away": str(away_team.get("abbreviation") or away_team.get("displayName") or ""),
                "away_name": str(away_team.get("displayName") or ""),
                "away_score": _safe_int(away.get("score")),
                "home": str(home_team.get("abbreviation") or home_team.get("displayName") or ""),
                "home_name": str(home_team.get("displayName") or ""),
                "home_score": _safe_int(home.get("score")),
                "venue": str((competition.get("venue") or {}).get("fullName") or ""),
                "game_url": f"https://www.espn.com/nba/game/_/gameId/{game_id}" if game_id else "",
                "fetched_at": fetched_at.isoformat(),
            }
        )
    return ScoreboardResult(
        rows=rows,
        metadata={
            "source": "ESPN",
            "fetched_at": fetched_at.isoformat(),
            "games": len(rows),
            "season": (payload.get("season") or {}).get("slug", ""),
        },
    )


def parse_nba_livedata_scoreboard(payload: dict[str, Any], fetched_at: datetime | None = None) -> ScoreboardResult:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    meta = payload.get("meta") or {}
    scoreboard = payload.get("scoreboard") or {}
    rows: list[dict[str, object]] = []
    for game in scoreboard.get("games", []):
        away = game.get("awayTeam") or {}
        home = game.get("homeTeam") or {}
        rows.append(
            {
                "source": "NBA liveData",
                "game_id": str(game.get("gameId") or ""),
                "game_time_utc": str(game.get("gameTimeUTC") or game.get("gameEt") or ""),
                "status": str(game.get("gameStatusText") or ""),
                "period": _safe_int(game.get("period")),
                "clock": str(game.get("gameClock") or ""),
                "away": str(away.get("teamTricode") or ""),
                "away_name": str(away.get("teamName") or ""),
                "away_score": _safe_int(away.get("score")),
                "home": str(home.get("teamTricode") or ""),
                "home_name": str(home.get("teamName") or ""),
                "home_score": _safe_int(home.get("score")),
                "venue": str(game.get("arenaName") or ""),
                "game_url": "",
                "fetched_at": fetched_at.isoformat(),
            }
        )
    return ScoreboardResult(
        rows=rows,
        metadata={
            "source": "NBA liveData",
            "fetched_at": fetched_at.isoformat(),
            "provider_time": str(meta.get("time") or ""),
            "game_date": str(scoreboard.get("gameDate") or ""),
            "games": len(rows),
        },
    )


def _get_json(url: str, params: dict[str, str] | None = None, timeout: int = 15) -> dict[str, Any]:
    response = requests.get(url, params=params or {}, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_espn_scoreboard(game_date: date | None = None, timeout: int = 15) -> ScoreboardResult:
    params = {"dates": game_date.strftime("%Y%m%d")} if game_date else None
    return parse_espn_scoreboard(_get_json(ESPN_SCOREBOARD_URL, params=params, timeout=timeout))


def fetch_nba_livedata_scoreboard(timeout: int = 15) -> ScoreboardResult:
    return parse_nba_livedata_scoreboard(_get_json(NBA_LIVEDATA_SCOREBOARD_URL, timeout=timeout))


def compare_scoreboards(primary: list[dict[str, object]], secondary: list[dict[str, object]]) -> dict[str, object]:
    primary_pairs = {(row.get("away"), row.get("home")): row for row in primary}
    secondary_pairs = {(row.get("away"), row.get("home")): row for row in secondary}
    mismatches: list[str] = []
    for teams, primary_row in primary_pairs.items():
        secondary_row = secondary_pairs.get(teams)
        if not secondary_row:
            continue
        if (
            primary_row.get("away_score") != secondary_row.get("away_score")
            or primary_row.get("home_score") != secondary_row.get("home_score")
            or primary_row.get("status") != secondary_row.get("status")
        ):
            mismatches.append(
                f"{teams[0]}@{teams[1]} ESPN {primary_row.get('away_score')}-{primary_row.get('home_score')} "
                f"{primary_row.get('status')} vs NBA {secondary_row.get('away_score')}-{secondary_row.get('home_score')} "
                f"{secondary_row.get('status')}"
            )
    return {
        "matched_games": len(set(primary_pairs) & set(secondary_pairs)),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:5],
    }


def fetch_best_nba_scoreboard(game_date: date | None = None, include_comparison: bool = True) -> ScoreboardResult:
    fetched_at = datetime.now(timezone.utc)
    errors: list[str] = []
    espn_result: ScoreboardResult | None = None
    nba_result: ScoreboardResult | None = None
    try:
        espn_result = fetch_espn_scoreboard(game_date=game_date)
    except requests.RequestException as exc:
        errors.append(f"ESPN failed: {exc}")
    if include_comparison:
        try:
            nba_result = fetch_nba_livedata_scoreboard()
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"NBA liveData failed: {exc}")

    if espn_result is not None:
        metadata = dict(espn_result.metadata)
        metadata["selected_source"] = "ESPN"
        metadata["errors"] = errors
        metadata["dashboard_fetched_at"] = fetched_at.isoformat()
        if nba_result is not None:
            metadata["nba_provider_time"] = nba_result.metadata.get("provider_time", "")
            metadata["nba_game_date"] = nba_result.metadata.get("game_date", "")
            metadata["comparison"] = compare_scoreboards(espn_result.rows, nba_result.rows)
        return ScoreboardResult(rows=espn_result.rows, metadata=metadata)

    if nba_result is not None:
        metadata = dict(nba_result.metadata)
        metadata["selected_source"] = "NBA liveData"
        metadata["errors"] = errors
        metadata["dashboard_fetched_at"] = fetched_at.isoformat()
        return ScoreboardResult(rows=nba_result.rows, metadata=metadata)

    return ScoreboardResult(
        rows=[],
        metadata={"selected_source": "none", "errors": errors, "dashboard_fetched_at": fetched_at.isoformat()},
    )
