"""College schedules, scores and lines from CollegeFootballData.com (free API key required).

Free tier is ~1,000 calls/month; a full refresh costs 4 calls per season.
"""
import re

import httpx

from .. import db
from ..config import CFBD_API_KEY

BASE = "https://api.collegefootballdata.com"
PREFERRED_BOOKS = ["consensus", "DraftKings", "ESPN Bet", "Bovada", "William Hill (New Jersey)"]


def _get(obj: dict, *keys):
    """CFBD has used both camelCase and snake_case field names across API versions."""
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    return None


def _client() -> httpx.Client:
    if not CFBD_API_KEY:
        raise RuntimeError("CFBD_API_KEY is not set. Get a free key at https://collegefootballdata.com/key")
    return httpx.Client(
        base_url=BASE, timeout=60, headers={"Authorization": f"Bearer {CFBD_API_KEY}"}
    )


def _home_spread(line: dict, home: str) -> float | None:
    """Convert a CFBD line to the betting convention (negative = home favored)."""
    formatted = _get(line, "formattedSpread", "formatted_spread")
    if formatted:
        m = re.match(r"^(.*)\s+([-+]?\d+(?:\.\d+)?)$", formatted.strip())
        if m:
            fav, num = m.group(1).strip(), abs(float(m.group(2)))
            return -num if fav == home else num
    spread = _get(line, "spread")
    return float(spread) if spread is not None else None


def _pick_line(lines: list[dict]) -> dict | None:
    by_book = {l.get("provider"): l for l in lines if _get(l, "spread", "overUnder", "over_under") is not None}
    for book in PREFERRED_BOOKS:
        if book in by_book:
            return by_book[book]
    return next(iter(by_book.values()), None)


def _int(v):
    return int(v) if v is not None else None


def fetch_season(client: httpx.Client, season: int) -> list[dict]:
    rows: dict[str, dict] = {}
    for season_type in ("regular", "postseason"):
        games = client.get("/games", params={"year": season, "seasonType": season_type})
        games.raise_for_status()
        for g in games.json():
            home_div = _get(g, "homeClassification", "home_division")
            away_div = _get(g, "awayClassification", "away_division")
            if "fbs" not in (home_div, away_div):
                continue
            gid = str(g["id"])
            rows[gid] = {
                "league": "cfb",
                "game_id": gid,
                "season": season,
                "week": _get(g, "week"),
                "season_type": season_type,
                "game_date": _get(g, "startDate", "start_date"),
                "home": _get(g, "homeTeam", "home_team"),
                "away": _get(g, "awayTeam", "away_team"),
                "home_score": _int(_get(g, "homePoints", "home_points")),
                "away_score": _int(_get(g, "awayPoints", "away_points")),
                "neutral": 1 if _get(g, "neutralSite", "neutral_site") else 0,
                "home_div": home_div,
                "away_div": away_div,
            }

        lines = client.get("/lines", params={"year": season, "seasonType": season_type})
        lines.raise_for_status()
        for entry in lines.json():
            row = rows.get(str(entry["id"]))
            line = _pick_line(entry.get("lines") or [])
            if not row or not line:
                continue
            row["home_spread"] = _home_spread(line, row["home"])
            row["total_line"] = _get(line, "overUnder", "over_under")
            row["home_ml"] = _int(_get(line, "homeMoneyline", "home_moneyline"))
            row["away_ml"] = _int(_get(line, "awayMoneyline", "away_moneyline"))
    return list(rows.values())


def refresh(seasons: list[int]) -> int:
    total = 0
    with _client() as client:
        for season in seasons:
            total += db.upsert_games(fetch_season(client, season))
    return total
