"""Walk-forward backtest against historical closing lines.

The model only ever sees games played *before* the one it is betting, exactly as it would live.
Closing lines are the sharpest lines of the week, so this is a tough (honest) benchmark:
profiting against closing lines is strong evidence of a real edge.
"""
import math
from collections import defaultdict

from . import odds_math
from .models.ratings import PARAMS, RatingEngine

DEFAULT_JUICE = -110


def _new_bucket():
    return {"bets": 0, "wins": 0, "losses": 0, "pushes": 0, "units": 0.0}


def _settle(bucket: dict, won: bool | None, price: int) -> None:
    bucket["bets"] += 1
    if won is None:
        bucket["pushes"] += 1
    elif won:
        bucket["wins"] += 1
        bucket["units"] += odds_math.american_to_decimal(price) - 1
    else:
        bucket["losses"] += 1
        bucket["units"] -= 1


def _pick(p_a: float, price_a: int, p_b: float, price_b: int, min_ev: float):
    """Bet the side with the higher EV if it clears the threshold. Returns 'a', 'b' or None."""
    ev_a = odds_math.expected_value(p_a, price_a)
    ev_b = odds_math.expected_value(p_b, price_b)
    if max(ev_a, ev_b) < min_ev:
        return None
    return "a" if ev_a >= ev_b else "b"


def _finish(b: dict) -> dict:
    decided = b["wins"] + b["losses"]
    return {
        **b,
        "units": round(b["units"], 2),
        "win_pct": round(b["wins"] / decided, 4) if decided else None,
        "roi": round(b["units"] / b["bets"], 4) if b["bets"] else None,
    }


def run_backtest(league: str, games: list[dict], start_season: int, min_ev: float = 0.02) -> dict:
    eng = RatingEngine(PARAMS[league])
    markets = defaultdict(_new_bucket)
    by_season = defaultdict(lambda: defaultdict(_new_bucket))
    err = defaultdict(list)       # absolute errors: model vs market as predictors
    brier = defaultdict(list)
    calib = defaultdict(lambda: [0, 0.0, 0])   # bucket -> [n, sum_p, wins]

    for g in games:
        if g["home_score"] is None or g["away_score"] is None:
            continue
        pred = eng.update(g)  # prediction made before this game's result is learned
        if g["season"] < start_season:
            continue

        margin = g["home_score"] - g["away_score"]
        total = g["home_score"] + g["away_score"]
        season = g["season"]
        err["model_margin"].append(abs(margin - pred.home_margin))
        err["model_total"].append(abs(total - pred.total))
        err["margin_resid"].append(margin - pred.home_margin)
        err["total_resid"].append(total - pred.total)

        # Moneyline
        if margin != 0:
            p = pred.home_win_prob
            home_won = margin > 0
            brier["model"].append((p - home_won) ** 2)
            bucket = min(int(p * 10), 9)
            calib[bucket][0] += 1
            calib[bucket][1] += p
            calib[bucket][2] += home_won
            if g["home_ml"] and g["away_ml"]:
                mp, _ = odds_math.devig(g["home_ml"], g["away_ml"])
                brier["market"].append((mp - home_won) ** 2)
                side = _pick(p, g["home_ml"], 1 - p, g["away_ml"], min_ev)
                if side:
                    price = g["home_ml"] if side == "a" else g["away_ml"]
                    won = home_won if side == "a" else not home_won
                    _settle(markets["moneyline"], won, price)
                    _settle(by_season[season]["moneyline"], won, price)

        # Spread
        if g["home_spread"] is not None:
            err["market_margin"].append(abs(margin + g["home_spread"]))
            hp = g["home_spread_odds"] or DEFAULT_JUICE
            ap = g["away_spread_odds"] or DEFAULT_JUICE
            p = pred.home_cover_prob(g["home_spread"])
            side = _pick(p, hp, 1 - p, ap, min_ev)
            if side:
                cover = margin + g["home_spread"]
                won = None if cover == 0 else (cover > 0) == (side == "a")
                price = hp if side == "a" else ap
                _settle(markets["spread"], won, price)
                _settle(by_season[season]["spread"], won, price)

        # Total
        if g["total_line"] is not None:
            err["market_total"].append(abs(total - g["total_line"]))
            op = g["over_odds"] or DEFAULT_JUICE
            up = g["under_odds"] or DEFAULT_JUICE
            p = pred.over_prob(g["total_line"])
            side = _pick(p, op, 1 - p, up, min_ev)
            if side:
                diff = total - g["total_line"]
                won = None if diff == 0 else (diff > 0) == (side == "a")
                price = op if side == "a" else up
                _settle(markets["total"], won, price)
                _settle(by_season[season]["total"], won, price)

    def avg(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    def sd(xs):
        if len(xs) < 2:
            return None
        m = sum(xs) / len(xs)
        return round(math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)), 2)

    return {
        "league": league,
        "start_season": start_season,
        "min_ev": min_ev,
        "games_evaluated": len(err["model_margin"]),
        "markets": {k: _finish(v) for k, v in markets.items()},
        "by_season": {
            s: {k: _finish(v) for k, v in m.items()} for s, m in sorted(by_season.items())
        },
        "accuracy": {
            "model_margin_mae": avg(err["model_margin"]),
            "market_margin_mae": avg(err["market_margin"]),
            "model_total_mae": avg(err["model_total"]),
            "market_total_mae": avg(err["market_total"]),
            "model_brier": avg(brier["model"]),
            "market_brier": avg(brier["market"]),
            "observed_margin_sd": sd(err["margin_resid"]),
            "observed_total_sd": sd(err["total_resid"]),
            "assumed_margin_sd": PARAMS[league].margin_sd,
            "assumed_total_sd": PARAMS[league].total_sd,
        },
        "calibration": [
            {"bucket": f"{b * 10}-{b * 10 + 10}%", "games": n,
             "predicted": round(sp / n, 3), "actual": round(w / n, 3)}
            for b, (n, sp, w) in sorted(calib.items()) if n
        ],
    }
