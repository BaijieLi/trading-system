from kalshi_trading_system.collectors.nba_live import (
    compare_scoreboards,
    parse_espn_scoreboard,
    parse_nba_livedata_scoreboard,
)


def test_parse_espn_scoreboard() -> None:
    payload = {
        "events": [
            {
                "id": "401",
                "date": "2026-10-12T23:00Z",
                "competitions": [
                    {
                        "venue": {"fullName": "Test Arena"},
                        "status": {
                            "period": 3,
                            "displayClock": "1:36",
                            "type": {"description": "In Progress"},
                        },
                        "competitors": [
                            {
                                "homeAway": "away",
                                "score": "73",
                                "team": {"abbreviation": "OKC", "displayName": "Oklahoma City Thunder"},
                            },
                            {
                                "homeAway": "home",
                                "score": "77",
                                "team": {"abbreviation": "ATL", "displayName": "Atlanta Hawks"},
                            },
                        ],
                    }
                ],
            }
        ]
    }

    result = parse_espn_scoreboard(payload)

    assert result.metadata["source"] == "ESPN"
    assert result.rows[0]["away"] == "OKC"
    assert result.rows[0]["home_score"] == 77
    assert result.rows[0]["game_url"] == "https://www.espn.com/nba/game/_/gameId/401"


def test_parse_nba_livedata_scoreboard() -> None:
    payload = {
        "meta": {"time": "2026-10-12 08:55:03.553"},
        "scoreboard": {
            "gameDate": "2026-10-12",
            "games": [
                {
                    "gameId": "001",
                    "gameTimeUTC": "2026-10-12T23:00:00Z",
                    "gameStatusText": "3rd Qtr",
                    "period": 3,
                    "gameClock": "PT01M36.00S",
                    "awayTeam": {"teamTricode": "OKC", "teamName": "Thunder", "score": 73},
                    "homeTeam": {"teamTricode": "ATL", "teamName": "Hawks", "score": 77},
                    "arenaName": "Test Arena",
                }
            ],
        },
    }

    result = parse_nba_livedata_scoreboard(payload)

    assert result.metadata["provider_time"] == "2026-10-12 08:55:03.553"
    assert result.rows[0]["source"] == "NBA liveData"
    assert result.rows[0]["away_score"] == 73


def test_compare_scoreboards_detects_stale_provider_score() -> None:
    espn = [
        {"away": "OKC", "home": "ATL", "away_score": 79, "home_score": 79, "status": "End of Period"},
    ]
    nba = [
        {"away": "OKC", "home": "ATL", "away_score": 73, "home_score": 77, "status": "3rd Qtr"},
    ]

    comparison = compare_scoreboards(espn, nba)

    assert comparison["matched_games"] == 1
    assert comparison["mismatch_count"] == 1
    assert "OKC@ATL" in comparison["mismatches"][0]
