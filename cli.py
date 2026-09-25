"""Command-line entry point.

    python cli.py refresh nfl
    python cli.py refresh cfb --seasons 2015-2026
    python cli.py backtest nfl --start 2010 --min-ev 0.03
    python cli.py board nfl
    python cli.py ratings cfb
    python cli.py serve
"""
import argparse
import json

from app import db
from app.backtest import run_backtest
from app.data import odds_api
from app.edges import build_board
from app.main import refresh_league
from app.models.ratings import build_engine


def _seasons(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    if "-" in spec:
        lo, hi = spec.split("-")
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in spec.split(",")]


def pct(x):
    return "-" if x is None else f"{x * 100:.1f}%"


def cmd_refresh(a):
    n = refresh_league(a.league, _seasons(a.seasons))
    print(f"{a.league.upper()}: upserted {n} games")


def cmd_backtest(a):
    games = db.load_games(a.league)
    start = a.start or min(g["season"] for g in games) + 3
    r = run_backtest(a.league, games, start, a.min_ev)
    if a.json:
        print(json.dumps(r, indent=2))
        return
    print(f"\n{a.league.upper()} backtest  seasons {start}+  min EV {pct(a.min_ev)}  "
          f"({r['games_evaluated']} games)\n")
    print(f"{'market':<10}{'bets':>7}{'W-L-P':>14}{'win%':>8}{'units':>9}{'ROI':>8}")
    for m, s in r["markets"].items():
        wlp = f"{s['wins']}-{s['losses']}-{s['pushes']}"
        print(f"{m:<10}{s['bets']:>7}{wlp:>14}{pct(s['win_pct']):>8}{s['units']:>9}{pct(s['roi']):>8}")
    acc = r["accuracy"]
    print("\nPrediction error (lower is better):")
    print(f"  margin MAE  model {acc['model_margin_mae']}  vs market {acc['market_margin_mae']}")
    print(f"  total  MAE  model {acc['model_total_mae']}  vs market {acc['market_total_mae']}")
    print(f"  ML Brier    model {acc['model_brier']}  vs market {acc['market_brier']}")
    print(f"  observed margin sd {acc['observed_margin_sd']} (assumed {acc['assumed_margin_sd']}), "
          f"total sd {acc['observed_total_sd']} (assumed {acc['assumed_total_sd']})")


def cmd_board(a):
    games = db.load_games(a.league)
    board = build_board(a.league, build_engine(a.league, games), games,
                        odds_api.get_odds(a.league), min_ev=a.min_ev)
    if board["odds_error"]:
        print(f"[!] {board['odds_error']}")
    for c in board["games"]:
        p = c["prediction"]
        print(f"{c['away_name']:>28} @ {c['home_name']:<28} "
              f"proj {p['away_score']:.0f}-{p['home_score']:.0f}  "
              f"fair spread {p['fair_home_spread']:+}  home win {pct(p['home_win_prob'])}")
    if board["value_bets"]:
        print("\nValue bets:")
        for o in board["value_bets"]:
            line = "" if o["line"] is None else f" {o['line']:+}" if o["market"] == "spread" else f" {o['line']}"
            flag = "  (check news)" if o["caution"] else ""
            print(f"  {o['game']:<50} {o['selection']}{line} {o['price']:+} @ {o['book']}  "
                  f"model {pct(o['model_prob'])} vs mkt {pct(o['market_prob'])}  EV {pct(o['ev'])}{flag}")


def cmd_ratings(a):
    eng = build_engine(a.league, db.load_games(a.league))
    for i, r in enumerate(eng.rankings()[: a.top], 1):
        print(f"{i:>3}. {r['team']:<24} Elo {r['elo']}  ({r['pts_vs_avg']:+} pts vs avg)")


def cmd_serve(a):
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=a.port, reload=a.reload)


def main():
    ap = argparse.ArgumentParser(description="Football probability toolkit")
    sub = ap.add_subparsers(required=True)

    p = sub.add_parser("refresh", help="download schedules, scores and historical lines")
    p.add_argument("league", choices=["nfl", "cfb"])
    p.add_argument("--seasons", help="cfb only: e.g. 2015-2026 or 2024,2025")
    p.set_defaults(fn=cmd_refresh)

    p = sub.add_parser("backtest", help="test the model against historical closing lines")
    p.add_argument("league", choices=["nfl", "cfb"])
    p.add_argument("--start", type=int)
    p.add_argument("--min-ev", type=float, default=0.02)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_backtest)

    p = sub.add_parser("board", help="this week's projections and value bets")
    p.add_argument("league", choices=["nfl", "cfb"])
    p.add_argument("--min-ev", type=float, default=0.03)
    p.set_defaults(fn=cmd_board)

    p = sub.add_parser("ratings", help="current power ratings")
    p.add_argument("league", choices=["nfl", "cfb"])
    p.add_argument("--top", type=int, default=32)
    p.set_defaults(fn=cmd_ratings)

    p = sub.add_parser("serve", help="run the web dashboard")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(fn=cmd_serve)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
