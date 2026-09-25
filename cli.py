"""Command-line entry point.

    python cli.py refresh nfl
    python cli.py refresh cfb --seasons 2015-2026
    python cli.py backtest nfl --start 2010 --min-ev 0.03
    python cli.py board nfl
    python cli.py ratings cfb
    python cli.py picks nfl
    python cli.py tune nfl --save
    python cli.py serve
"""
import argparse
import json

from app import db
from app.backtest import run_backtest
from app.data import odds_api
from app.edges import build_board
from app.main import refresh_league
from app.models.ratings import PARAMS, build_engine, save_params
from app.picks import compute_all_picks
from app.tune import evaluate, tune


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


def cmd_picks(a):
    games = db.load_games(a.league)
    all_picks, starts, _ = compute_all_picks(a.league, games)
    keys = sorted(all_picks, key=lambda k: (starts[k], k))
    latest = max(k[0] for k in keys)
    key = next((k for k in keys if k[0] == latest and any(not p["completed"] for p in all_picks[k])), keys[-1])
    print(f"{a.league.upper()} {key[0]} {key[1]} week {key[2]}\n")
    order = {"best": 0, "lean": 1, "caution": 2, "pass": 3}
    for p in sorted(all_picks[key], key=lambda p: order[p["best_tier"]]):
        sp, tp = p.get("spread"), p.get("total")
        parts = [f"{p['away']:>16} @ {p['home']:<16} winner {p['winner']['team']} ({pct(p['winner']['prob'])})"]
        if sp:
            parts.append(f"ATS {sp['team']} {sp['line']:+g} [{sp['tier']}]")
        if tp:
            parts.append(f"{tp['side']} {tp['line']:g} [{tp['tier']}]")
        print("  ".join(parts))
        for n in p["notes"]:
            print(f"{'':>20}note: {n}")


def cmd_tune(a):
    games = db.load_games(a.league)
    seasons = sorted({g["season"] for g in games if g["home_score"] is not None})
    train = (seasons[0] + 3, seasons[-1] - a.holdout)
    test = (seasons[-1] - a.holdout + 1, seasons[-1])
    print(f"Tuning {a.league.upper()} on {train[0]}-{train[1]}, checking on {test[0]}-{test[1]}...")
    before = PARAMS[a.league]
    after = tune(games, before, train)
    for name, p in (("current", before), ("tuned", after)):
        r = evaluate(games, p, *test)
        print(f"  {name:<8} margin MAE {r['margin_mae']:.3f}  total MAE {r['total_mae']:.3f}  "
              f"(market {r['market_margin_mae']:.3f} / {r['market_total_mae']:.3f})")
    if a.save:
        save_params(after)
        print("Saved - restart the server to use the new parameters.")
    else:
        print("Run again with --save to use these parameters.")


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

    p = sub.add_parser("picks", help="this week's picks with confidence tiers")
    p.add_argument("league", choices=["nfl", "cfb"])
    p.set_defaults(fn=cmd_picks)

    p = sub.add_parser("tune", help="fit model parameters to your data")
    p.add_argument("league", choices=["nfl", "cfb"])
    p.add_argument("--holdout", type=int, default=5, help="recent seasons held out for checking")
    p.add_argument("--save", action="store_true")
    p.set_defaults(fn=cmd_tune)

    p = sub.add_parser("serve", help="run the web dashboard")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(fn=cmd_serve)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
