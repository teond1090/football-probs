import copy
import csv
import io
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, odds_math
from .backtest import run_backtest
from .config import (AUTO_REFRESH_HOURS, CFBD_API_KEY, ODDS_API_KEY, REFRESH_COOLDOWN_MINUTES,
                     ROOT, current_season)
from .data import cfb, nfl, odds_api
from .edges import build_board
from .models.ratings import RatingEngine, build_engine
from .best_odds import attach_best_odds
from .sharp import SHARP_FALLBACK, SHARP_PRIMARY, books_seen, filter_books, find_value
from .parlays import best_bets_parlay_history, legs_for_week, suggestions
from .picks import (TIER_ORDER, apply_calibration, best_bets, best_bets_record, compute_all_picks,
                    fit_calibration, record, week_label)

LEAGUES = ("nfl", "cfb")
log = logging.getLogger("football")

_engines: dict[str, RatingEngine] = {}
_picks: dict[str, tuple] = {}


def _auto_refresh() -> None:
    """Refresh any league whose data is older than AUTO_REFRESH_HOURS."""
    for league in LEAGUES:
        if league == "cfb" and not CFBD_API_KEY:
            continue
        last = db.get_meta(f"{league}_refreshed_at")
        stale = last is None or datetime.now() - datetime.fromisoformat(last) > timedelta(hours=AUTO_REFRESH_HOURS)
        if stale:
            try:
                n = refresh_league(league)
                log.warning("auto-refreshed %s: %d games", league, n)
            except Exception as e:  # never block startup on a data source hiccup
                log.warning("auto-refresh of %s failed: %s", league, e)


def _auto_refresh_loop() -> None:
    while True:
        _auto_refresh()
        time.sleep(3600)


@asynccontextmanager
async def lifespan(_app):
    if AUTO_REFRESH_HOURS > 0:
        threading.Thread(target=_auto_refresh_loop, daemon=True).start()
    yield


app = FastAPI(title="Football Probabilities", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def _league(league: str) -> str:
    if league not in LEAGUES:
        raise HTTPException(404, f"Unknown league '{league}'")
    return league


def get_engine(league: str) -> RatingEngine:
    if league not in _engines:
        _engines[league] = build_engine(league, db.load_games(league), track_history=True)
    return _engines[league]


def get_picks(league: str) -> tuple[dict, dict, dict]:
    """(picks by week, week start dates, calibration). Every pick carries calibrated fair_prob."""
    if league not in _picks:
        all_picks, starts, _ = compute_all_picks(league, db.load_games(league))
        first = min(k[0] for k in all_picks)
        cal = fit_calibration([ps for k, ps in all_picks.items() if k[0] >= first + 3])
        for ps in all_picks.values():
            apply_calibration(ps, cal)
        _picks[league] = (all_picks, starts, cal)
    return _picks[league]


def _known_teams(league: str) -> set[str]:
    season = current_season()
    return {t for g in db.load_games(league) if g["season"] >= season - 1 for t in (g["home"], g["away"])}


def _allowed(books: str | None) -> set[str] | None:
    """Parse the ?books= filter (comma-separated Odds API bookmaker keys)."""
    keys = {b.strip() for b in (books or "").split(",") if b.strip()}
    return keys or None


def _live_week(league: str, picks: list[dict], cal: dict,
               allowed: set[str] | None = None) -> tuple[list[dict], dict]:
    """A copy of the week's picks with the best line/price across all sportsbooks attached."""
    picks = copy.deepcopy(picks)
    status = {"enabled": bool(ODDS_API_KEY), "matched": 0, "fetched_at": None, "error": None}
    if not ODDS_API_KEY or all(p["completed"] for p in picks):
        return picks, status
    try:
        odds = odds_api.get_odds(league)
    except Exception as e:  # never break picks over an odds hiccup
        status["error"] = f"Odds API error: {e}"
        return picks, status
    status["fetched_at"] = odds.get("fetched_at")
    status["remaining"] = odds.get("remaining")
    status["error"] = odds.get("error")
    events = filter_books(odds.get("events", []), allowed)
    status["matched"] = attach_best_odds(league, picks, events, cal, _known_teams(league))
    return picks, status


def refresh_league(league: str, seasons: list[int] | None = None) -> int:
    if league == "nfl":
        n = nfl.refresh()
    else:
        if seasons is None:
            # First run pulls a decade of history; later runs only the current season.
            has_data = db.get_meta("cfb_refreshed_at") is not None
            cur = current_season()
            seasons = [cur] if has_data else list(range(cur - 10, cur + 1))
        n = cfb.refresh(seasons)
    db.set_meta(f"{league}_refreshed_at", datetime.now().isoformat(timespec="seconds"))
    _engines.pop(league, None)
    _picks.pop(league, None)
    return n


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/status")
def status():
    with db.connect() as conn:
        counts = {
            r["league"]: {"games": r["n"], "first_season": r["lo"], "last_season": r["hi"]}
            for r in conn.execute(
                "SELECT league, COUNT(*) n, MIN(season) lo, MAX(season) hi FROM games GROUP BY league"
            )
        }
    return {
        "season": current_season(),
        "keys": {"odds_api": bool(ODDS_API_KEY), "cfbd": bool(CFBD_API_KEY)},
        "leagues": {
            lg: {**counts.get(lg, {"games": 0}), "refreshed_at": db.get_meta(f"{lg}_refreshed_at")}
            for lg in LEAGUES
        },
    }


@app.post("/api/refresh/{league}")
def refresh(league: str):
    last = db.get_meta(f"{_league(league)}_refreshed_at")
    if last and datetime.now() - datetime.fromisoformat(last) < timedelta(minutes=REFRESH_COOLDOWN_MINUTES):
        return {"league": league, "games_upserted": 0, "skipped": "Data was refreshed in the last few minutes."}
    try:
        n = refresh_league(_league(league))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"league": league, "games_upserted": n}


@app.get("/api/board/{league}")
def board(league: str, min_ev: float = 0.03, kelly: float = 0.25, force: bool = False,
          books: str | None = None):
    games = db.load_games(_league(league))
    if not games:
        raise HTTPException(400, f"No {league.upper()} data yet - click Refresh data first.")
    try:
        odds = odds_api.get_odds(league, force=force)
    except Exception as e:  # network / quota errors shouldn't break the board
        odds = {"events": [], "error": f"Odds API error: {e}"}
    odds = {**odds, "events": filter_books(odds.get("events", []), _allowed(books))}
    return build_board(league, get_engine(league), games, odds, min_ev=min_ev, kelly=kelly,
                       cal=get_picks(league)[2])


@app.get("/api/ratings/{league}")
def ratings(league: str):
    games = db.load_games(_league(league))
    season = current_season()
    active = {t for g in games if g["season"] >= season - 1 for t in (g["home"], g["away"])
              if league == "nfl" or g[("home_div" if t == g["home"] else "away_div")] == "fbs"}
    return get_engine(league).rankings(active or None)


@app.get("/api/backtest/{league}")
def backtest(league: str, start: int | None = None, min_ev: float = 0.02):
    games = db.load_games(_league(league))
    if not games:
        raise HTTPException(400, f"No {league.upper()} data yet - click Refresh data first.")
    first = min(g["season"] for g in games)
    start = start or first + 3   # give ratings a few seasons to settle
    return run_backtest(league, games, start, min_ev)


# --- Weekly picks -------------------------------------------------------------------------------

def _key_id(key: tuple) -> str:
    return f"{key[0]}-{key[1]}-{key[2]}"


def _ordered(keys, starts: dict) -> list[tuple]:
    return sorted(keys, key=lambda k: (starts[k], k))


def _default_week(all_picks: dict, starts: dict) -> tuple:
    """The first week of the latest season that still has games to play."""
    keys = _ordered(all_picks, starts)
    latest = max(k[0] for k in keys)
    for k in keys:
        if k[0] == latest and any(not p["completed"] for p in all_picks[k]):
            return k
    return keys[-1]


def _select_week(league: str, week: str | None) -> tuple[dict, dict, tuple]:
    if not db.load_games(league):
        raise HTTPException(400, f"No {league.upper()} data yet - click Refresh data first.")
    all_picks, starts, _ = get_picks(league)
    if week:
        key = next((k for k in all_picks if _key_id(k) == week), None)
        if key is None:
            raise HTTPException(404, f"Unknown week '{week}'")
    else:
        key = _default_week(all_picks, starts)
    return all_picks, starts, key


def _sorted_picks(picks: list[dict]) -> list[dict]:
    return sorted(picks, key=lambda p: (TIER_ORDER[p["best_tier"]], -p["confidence"]))


@app.get("/api/picks/{league}")
def weekly_picks(league: str, week: str | None = None, books: str | None = None):
    all_picks, starts, key = _select_week(_league(league), week)
    cal = get_picks(league)[2]
    week_picks, odds_status = _live_week(league, all_picks[key], cal, _allowed(books))
    season = key[0]
    seasons = sorted({k[0] for k in all_picks}, reverse=True)
    season_keys = _ordered((k for k in all_picks if k[0] == season), starts)
    first = min(seasons)
    recent_from = season - 5

    def history(lo: int) -> dict:
        weeks = [ps for k, ps in all_picks.items() if lo <= k[0] < season]
        return {"from": lo, "to": season - 1,
                "record": record([p for ps in weeks for p in ps]),
                "best_bets": best_bets_record(weeks)}

    return {
        "league": league,
        "week": {"id": _key_id(key), "label": week_label(key), "season": season, "start": starts[key]},
        "weeks": [{"id": _key_id(k), "label": week_label(k), "start": starts[k]} for k in season_keys],
        "seasons": [
            {"season": s, "first_week": _key_id(_ordered((k for k in all_picks if k[0] == s), starts)[0])}
            for s in seasons
        ],
        "picks": _sorted_picks(week_picks),
        "best_bets": best_bets(week_picks),
        "calibration": cal,
        "odds": odds_status,
        "best_bets_week": best_bets_record([all_picks[key]]),
        "best_bets_season": best_bets_record([all_picks[k] for k in season_keys]),
        "week_record": record(all_picks[key]),
        "season_record": record([p for k in season_keys for p in all_picks[k]]),
        "history": {"all_time": history(first + 3), "recent": history(recent_from)},
    }


@app.get("/api/picks/{league}/csv")
def weekly_picks_csv(league: str, week: str | None = None):
    all_picks, _, key = _select_week(_league(league), week)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["kickoff", "away", "home", "proj_away", "proj_home", "winner", "win_prob",
                "spread_pick", "spread_prob", "spread_tier", "spread_result",
                "total_pick", "total_prob", "total_tier", "total_result", "notes"])
    for p in _sorted_picks(all_picks[key]):
        sp, tp = p.get("spread"), p.get("total")
        w.writerow([
            p["kickoff"], p["away"], p["home"], p["proj_away"], p["proj_home"],
            p["winner"]["team"], p["winner"]["prob"],
            f"{sp['team']} {sp['line']:+g}" if sp else "", sp["prob"] if sp else "",
            sp["tier"] if sp else "", (sp or {}).get("result") or "",
            f"{tp['side']} {tp['line']:g}" if tp else "", tp["prob"] if tp else "",
            tp["tier"] if tp else "", (tp or {}).get("result") or "",
            "; ".join(p["notes"]),
        ])
    name = f"{league}-picks-{_key_id(key)}.csv"
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- Sharp-book value ----------------------------------------------------------------------------

@app.get("/api/sharp/{league}")
def sharp_value(league: str, min_ev: float = 0.01, kelly: float = 0.25, books: str | None = None,
                force: bool = False):
    _league(league)
    try:
        odds = odds_api.get_odds(league, force=force)
    except Exception as e:
        raise HTTPException(502, f"Odds API error: {e}")
    if odds.get("error"):
        raise HTTPException(400, odds["error"])
    events = odds.get("events", [])
    result = find_value(events, _allowed(books), min_ev=min_ev, kelly=kelly)
    have_sharp = any(b["key"] == SHARP_PRIMARY for e in events for b in e.get("bookmakers", []))
    return {
        "league": league, **result,
        "books": books_seen(events),
        "sharp_books": [SHARP_PRIMARY, *SHARP_FALLBACK],
        "pinnacle_available": have_sharp,
        "odds_fetched_at": odds.get("fetched_at"), "odds_remaining": odds.get("remaining"),
    }


# --- Parlays -------------------------------------------------------------------------------------

@app.get("/api/parlays/{league}")
def parlays(league: str, week: str | None = None, books: str | None = None):
    all_picks, starts, key = _select_week(_league(league), week)
    cal = get_picks(league)[2]
    week_picks, odds_status = _live_week(league, all_picks[key], cal, _allowed(books))
    legs = legs_for_week(week_picks, cal)
    season = key[0]
    first = min(k[0] for k in all_picks)

    def hist(lo: int) -> dict:
        weeks = [ps for k, ps in all_picks.items() if lo <= k[0] < season]
        return {"from": lo, "to": season - 1,
                "two": best_bets_parlay_history(weeks, 2), "three": best_bets_parlay_history(weeks, 3)}

    return {
        "league": league,
        "week": {"id": _key_id(key), "label": week_label(key), "season": season},
        "legs": sorted(legs, key=lambda l: (l["kickoff"] or "", l["game"], l["market"])),
        "suggestions": suggestions(legs, week_picks) if legs else {},
        "history": {"all_time": hist(first + 3), "recent": hist(season - 5)},
        "calibration": cal,
        "odds": odds_status,
    }


# --- Matchup calculator & team pages ------------------------------------------------------------

@app.get("/api/matchup/{league}")
def matchup(league: str, home: str, away: str, neutral: bool = False):
    eng = get_engine(_league(league))
    for t in (home, away):
        if t not in eng.elo:
            raise HTTPException(404, f"Unknown team '{t}'")
    pred = eng.predict({"home": home, "away": away, "season": current_season(), "neutral": int(neutral)})
    fair = round(-pred.home_margin * 2) / 2
    total = round(pred.total * 2) / 2
    return {
        "home": home, "away": away, "neutral": neutral,
        "prediction": pred.as_dict(),
        "alt_spreads": [
            {"home_spread": s, "home_cover": round(pred.home_cover_prob(s), 4),
             "fair_price": odds_math.prob_to_american(pred.home_cover_prob(s))}
            for s in (fair + d for d in range(-10, 11))
        ],
        "alt_totals": [
            {"line": t, "over": round(pred.over_prob(t), 4),
             "fair_price": odds_math.prob_to_american(pred.over_prob(t))}
            for t in (total + d for d in range(-8, 9))
        ],
    }


@app.get("/api/team/{league}/{team}")
def team_detail(league: str, team: str):
    eng = get_engine(_league(league))
    if team not in eng.elo:
        raise HTTPException(404, f"Unknown team '{team}'")
    all_picks, starts, _ = get_picks(league)
    season = max(k[0] for k in all_picks)
    games = [p for k in _ordered(all_picks, starts) if k[0] >= season - 1
             for p in all_picks[k] if team in (p["home"], p["away"])]
    return {
        "team": team,
        "rating": next(r for r in eng.rankings() if r["team"] == team),
        "history": [{"date": d, "elo": e} for d, e in eng.history.get(team, []) if d >= str(season - 3)],
        "games": [p for p in games if p["completed"]][-12:] + [p for p in games if not p["completed"]][:3],
    }


# --- Bet tracker --------------------------------------------------------------------------------

class BetIn(BaseModel):
    league: str
    game: str
    market: str
    selection: str
    line: float | None = None
    price: int
    stake: float
    model_prob: float | None = None
    book: str | None = None
    notes: str | None = None


class BetUpdate(BaseModel):
    result: str


@app.get("/api/bets")
def list_bets():
    with db.connect() as conn:
        bets = [dict(r) for r in conn.execute("SELECT * FROM bets ORDER BY id DESC")]
    settled = [b for b in bets if b["result"] != "pending"]
    for b in bets:
        b["profit"] = round(odds_math.profit(b["stake"], b["price"], b["result"]), 2)
        b["ev"] = (round(odds_math.expected_value(b["model_prob"], b["price"]), 4)
                   if b["model_prob"] is not None else None)
    staked = sum(b["stake"] for b in settled)
    pnl = sum(b["profit"] for b in bets)
    return {
        "bets": bets,
        "summary": {
            "count": len(bets),
            "settled": len(settled),
            "record": "-".join(str(sum(b["result"] == r for b in settled)) for r in ("win", "loss", "push")),
            "staked": round(staked, 2),
            "profit": round(pnl, 2),
            "roi": round(pnl / staked, 4) if staked else None,
            "expected_profit": round(sum(b["stake"] * b["ev"] for b in settled if b["ev"] is not None), 2),
        },
    }


@app.post("/api/bets")
def add_bet(bet: BetIn):
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO bets (league, game, market, selection, line, price, stake, model_prob, book, notes) "
            "VALUES (:league, :game, :market, :selection, :line, :price, :stake, :model_prob, :book, :notes)",
            bet.model_dump(),
        )
        return {"id": cur.lastrowid}


@app.patch("/api/bets/{bet_id}")
def settle_bet(bet_id: int, upd: BetUpdate):
    if upd.result not in ("pending", "win", "loss", "push"):
        raise HTTPException(400, "result must be pending, win, loss or push")
    with db.connect() as conn:
        conn.execute("UPDATE bets SET result = ? WHERE id = ?", (upd.result, bet_id))
    return {"ok": True}


@app.delete("/api/bets/{bet_id}")
def delete_bet(bet_id: int):
    with db.connect() as conn:
        conn.execute("DELETE FROM bets WHERE id = ?", (bet_id,))
    return {"ok": True}
