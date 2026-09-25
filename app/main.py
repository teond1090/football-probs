from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, odds_math
from .backtest import run_backtest
from .config import CFBD_API_KEY, ODDS_API_KEY, ROOT, current_season
from .data import cfb, nfl, odds_api
from .edges import build_board
from .models.ratings import RatingEngine, build_engine

LEAGUES = ("nfl", "cfb")
app = FastAPI(title="Football Probabilities")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

_engines: dict[str, RatingEngine] = {}


def _league(league: str) -> str:
    if league not in LEAGUES:
        raise HTTPException(404, f"Unknown league '{league}'")
    return league


def get_engine(league: str) -> RatingEngine:
    if league not in _engines:
        _engines[league] = build_engine(league, db.load_games(league))
    return _engines[league]


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
    try:
        n = refresh_league(_league(league))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"league": league, "games_upserted": n}


@app.get("/api/board/{league}")
def board(league: str, min_ev: float = 0.03, kelly: float = 0.25, force: bool = False):
    games = db.load_games(_league(league))
    if not games:
        raise HTTPException(400, f"No {league.upper()} data yet - click Refresh data first.")
    try:
        odds = odds_api.get_odds(league, force=force)
    except Exception as e:  # network / quota errors shouldn't break the board
        odds = {"events": [], "error": f"Odds API error: {e}"}
    return build_board(league, get_engine(league), games, odds, min_ev=min_ev, kelly=kelly)


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
