"""NFL schedule, scores and closing lines from nflverse (free, no API key, 1999-present)."""
import csv
import io

import httpx

from .. import db
from .teams import nfl_code

GAMES_CSV = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


def _num(v: str, cast=float):
    if v in ("", "NA", None):
        return None
    try:
        return cast(float(v)) if cast is int else cast(v)
    except ValueError:
        return None


def parse_row(r: dict) -> dict:
    spread_line = _num(r.get("spread_line"))  # nflverse: positive = home favored
    return {
        "league": "nfl",
        "game_id": r["game_id"],
        "season": int(r["season"]),
        "week": _num(r.get("week"), int),
        "season_type": "regular" if r.get("game_type") == "REG" else "postseason",
        "game_date": f"{r['gameday']}T{r.get('gametime') or '00:00'}",
        "home": nfl_code(r["home_team"]),
        "away": nfl_code(r["away_team"]),
        "home_score": _num(r.get("home_score"), int),
        "away_score": _num(r.get("away_score"), int),
        "neutral": 1 if r.get("location") == "Neutral" else 0,
        "home_div": None,
        "away_div": None,
        "home_spread": -spread_line if spread_line is not None else None,
        "total_line": _num(r.get("total_line")),
        "home_ml": _num(r.get("home_moneyline"), int),
        "away_ml": _num(r.get("away_moneyline"), int),
        "home_spread_odds": _num(r.get("home_spread_odds"), int),
        "away_spread_odds": _num(r.get("away_spread_odds"), int),
        "over_odds": _num(r.get("over_odds"), int),
        "under_odds": _num(r.get("under_odds"), int),
        "home_qb": r.get("home_qb_name") or None,
        "away_qb": r.get("away_qb_name") or None,
        "home_rest": _num(r.get("home_rest"), int),
        "away_rest": _num(r.get("away_rest"), int),
        "roof": r.get("roof") or None,
        "div_game": _num(r.get("div_game"), int),
    }


def refresh() -> int:
    resp = httpx.get(GAMES_CSV, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    rows = [parse_row(r) for r in csv.DictReader(io.StringIO(resp.text))]
    return db.upsert_games(rows)
