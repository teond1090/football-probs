"""Live sportsbook lines from The Odds API (https://the-odds-api.com).

Each fetch of one league costs 3 credits (moneyline + spreads + totals, US books).
Responses are cached in SQLite so refreshing the dashboard doesn't burn the free quota.
"""
import json
from datetime import datetime, timedelta, timezone

import httpx

from .. import db
from ..config import ODDS_API_KEY, ODDS_CACHE_MINUTES, ODDS_FORCE_COOLDOWN_MINUTES

SPORT_KEYS = {"nfl": "americanfootball_nfl", "cfb": "americanfootball_ncaaf"}
URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"


def get_odds(league: str, force: bool = False) -> dict:
    """Returns {"events": [...], "fetched_at": iso, "remaining": str|None, "cached": bool}."""
    if not ODDS_API_KEY:
        return {"events": [], "fetched_at": None, "remaining": None, "cached": False,
                "error": "ODDS_API_KEY not set - showing model lines only."}

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM odds_cache WHERE league = ?", (league,)).fetchone()
    if row:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"])
        # "force" (the Refresh odds button) still can't fire more often than the cooldown
        limit = ODDS_FORCE_COOLDOWN_MINUTES if force else ODDS_CACHE_MINUTES
        if age < timedelta(minutes=limit):
            return {"events": json.loads(row["payload"]), "fetched_at": row["fetched_at"],
                    "remaining": row["remaining"], "cached": True}

    resp = httpx.get(
        URL.format(sport=SPORT_KEYS[league]),
        params={
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
        },
        timeout=30,
    )
    resp.raise_for_status()
    events = resp.json()
    fetched_at = datetime.now(timezone.utc).isoformat()
    remaining = resp.headers.get("x-requests-remaining")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO odds_cache (league, fetched_at, remaining, payload) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (league) DO UPDATE SET fetched_at = excluded.fetched_at, "
            "remaining = excluded.remaining, payload = excluded.payload",
            (league, fetched_at, remaining, json.dumps(events)),
        )
    return {"events": events, "fetched_at": fetched_at, "remaining": remaining, "cached": False}
