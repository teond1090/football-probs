"""Weekly picks: the side the model favors in every game, graded once games finish.

Picks for a week are made from ratings frozen at the start of that week, so past weeks show
exactly what the app would have recommended at the time, and the record is honest.
"""
from collections import defaultdict

from . import odds_math
from .models.ratings import PARAMS, NFL, LeagueParams, RatingEngine, is_completed

DEFAULT_JUICE = -110

# Confidence tiers by how far the model's number is from the market's (NFL points; college
# thresholds scale up with its bigger score variance). Chosen from NFL history 2006-2025:
#   spread edge < 2 pts  -> ~50% ATS (coin flip)            -> pass
#   spread edge 2-3 pts  -> ~51%                             -> lean
#   spread edge 3-6 pts  -> ~53-55% (where the model has shown signal) -> best
#   edge 6+ pts          -> back to ~50%: the market usually knows something the model doesn't
#                           (injury, QB news, weather)       -> caution
#   totals               -> no historical edge at any size, so never better than lean
# The Weekly Picks page shows each tier's actual record so these claims stay honest.
TIER_ORDER = {"best": 0, "lean": 1, "caution": 2, "pass": 3}


def tier_for(market: str, edge_pts: float, scale: float = 1.0) -> str:
    e = edge_pts / scale
    if e >= 6:
        return "caution"
    if market == "spread":
        return "best" if e >= 3 else "lean" if e >= 2 else "pass"
    return "lean" if e >= 3 else "pass"


def week_key(g: dict) -> tuple:
    return (g["season"], g.get("season_type") or "regular", g.get("week") or 0)


def week_label(key: tuple) -> str:
    _, stype, week = key
    return f"Week {week}" if stype == "regular" else f"Postseason {week}"


def _grade(won: bool | None) -> str | None:
    return None if won is None else "win" if won else "loss"


def make_pick(g: dict, pred, done: bool, scale: float = 1.0) -> dict:
    h, a = g["home"], g["away"]
    margin = g["home_score"] - g["away_score"] if done else None
    total = g["home_score"] + g["away_score"] if done else None
    p_home = pred.home_win_prob

    pick = {
        "game_id": g["game_id"], "kickoff": g["game_date"], "home": h, "away": a,
        "neutral": bool(g.get("neutral")), "home_qb": g.get("home_qb"), "away_qb": g.get("away_qb"),
        "completed": done, "home_score": g["home_score"], "away_score": g["away_score"],
        "proj_home": round(pred.home_score, 1), "proj_away": round(pred.away_score, 1),
        "home_win_prob": round(p_home, 4), "notes": pred.notes,
        "market_home_spread": g.get("home_spread"), "market_total": g.get("total_line"),
        "market_home_ml": g.get("home_ml"), "market_away_ml": g.get("away_ml"),
        # raw projection, so probabilities can be recomputed at any line a sportsbook offers
        "model": {"home_margin": round(pred.home_margin, 3), "total": round(pred.total, 3),
                  "margin_sd": pred.margin_sd, "total_sd": pred.total_sd},
    }

    # Straight-up winner
    home_fav = p_home >= 0.5
    pick["winner"] = {
        "team": h if home_fav else a,
        "prob": round(max(p_home, 1 - p_home), 4),
        "result": None if not done or margin == 0 else _grade((margin > 0) == home_fav),
    }

    # Against the spread
    hs = g.get("home_spread")
    if hs is not None:
        ph = pred.home_cover_prob(hs)
        home_side = ph >= 0.5
        prob = ph if home_side else 1 - ph
        price = (g.get("home_spread_odds") if home_side else g.get("away_spread_odds")) or DEFAULT_JUICE
        result = None
        if done:
            cover = margin + hs
            result = "push" if cover == 0 else _grade((cover > 0) == home_side)
        edge = abs(pred.home_margin + hs)
        pick["spread"] = {
            "team": h if home_side else a, "line": hs if home_side else -hs, "price": price,
            "prob": round(prob, 4), "ev": round(odds_math.expected_value(prob, price), 4),
            "edge_pts": round(edge, 1), "tier": tier_for("spread", edge, scale), "result": result,
        }

    # Over / under
    tl = g.get("total_line")
    if tl is not None:
        po = pred.over_prob(tl)
        over = po >= 0.5
        prob = po if over else 1 - po
        price = (g.get("over_odds") if over else g.get("under_odds")) or DEFAULT_JUICE
        result = None
        if done:
            diff = total - tl
            result = "push" if diff == 0 else _grade((diff > 0) == over)
        edge = abs(pred.total - tl)
        pick["total"] = {
            "side": "Over" if over else "Under", "line": tl, "price": price,
            "prob": round(prob, 4), "ev": round(odds_math.expected_value(prob, price), 4),
            "edge_pts": round(edge, 1), "tier": tier_for("total", edge, scale), "result": result,
        }

    # Moneyline: only when the price is better than the model's fair odds
    hml, aml = g.get("home_ml"), g.get("away_ml")
    if hml and aml:
        options = [(h, hml, p_home, True), (a, aml, 1 - p_home, False)]
        team, price, prob, is_home = max(options, key=lambda o: odds_math.expected_value(o[2], o[1]))
        ev = odds_math.expected_value(prob, price)
        if ev > 0:
            pick["moneyline"] = {
                "team": team, "price": price, "prob": round(prob, 4), "ev": round(ev, 4),
                "result": None if not done or margin == 0 else _grade((margin > 0) == is_home),
            }

    tiers = [pick[m]["tier"] for m in ("spread", "total") if m in pick]
    pick["best_tier"] = min(tiers, key=TIER_ORDER.get) if tiers else "pass"
    pick["confidence"] = max((pick[m]["edge_pts"] for m in ("spread", "total")
                              if m in pick and pick[m]["tier"] == pick["best_tier"]), default=0)
    return pick


def compute_all_picks(league: str, games: list[dict], params: LeagueParams | None = None):
    """Replays history week by week. Returns ({week_key: [picks]}, {week_key: first kickoff}, engine)."""
    eng = RatingEngine(params or PARAMS[league])
    scale = eng.p.margin_sd / NFL.margin_sd
    weeks: dict[tuple, list[dict]] = defaultdict(list)
    for g in games:
        weeks[week_key(g)].append(g)
    starts = {k: min(g["game_date"] or "" for g in wk) for k, wk in weeks.items()}

    out = {}
    for key in sorted(weeks, key=lambda k: (starts[k], k)):
        wk = weeks[key]
        preds = [(g, eng.predict(g)) for g in wk]   # all picks use start-of-week ratings
        out[key] = [make_pick(g, pred, is_completed(g), scale) for g, pred in preds]
        for g, _ in preds:
            if is_completed(g):
                eng.update(g)
    return out, starts, eng


def _bucket():
    return {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0}


def _add(b: dict, bet: dict) -> None:
    r = bet["result"]
    if r == "win":
        b["wins"] += 1
        b["units"] += odds_math.american_to_decimal(bet.get("price", DEFAULT_JUICE)) - 1
    elif r == "loss":
        b["losses"] += 1
        b["units"] -= 1
    elif r == "push":
        b["pushes"] += 1


def _finish(b: dict) -> dict:
    n = b["wins"] + b["losses"]
    bets = n + b["pushes"]
    return {**b, "units": round(b["units"], 2),
            "win_pct": round(b["wins"] / n, 4) if n else None,
            "roi": round(b["units"] / bets, 4) if bets else None}


def record(picks: list[dict]) -> dict:
    """Record by market and tier for a set of graded picks."""
    out = defaultdict(_bucket)
    for p in picks:
        if not p["completed"]:
            continue
        if p["winner"]["result"]:
            _add(out["winner"], {**p["winner"], "price": 100})
        for m in ("spread", "total"):
            if m in p and p[m]["result"]:
                _add(out[f"{m}:{p[m]['tier']}"], p[m])
                if p[m]["tier"] in ("best", "lean"):
                    _add(out[f"{m}:all_picks"], p[m])
        if "moneyline" in p and p["moneyline"]["result"]:
            _add(out["moneyline"], p["moneyline"])
    return {k: _finish(v) for k, v in sorted(out.items())}


BEST_BETS_PER_WEEK = 5


def best_bets(picks: list[dict], limit: int = BEST_BETS_PER_WEEK) -> list[dict]:
    """The week's shortlist: Best-tier spread picks, biggest model edge first.

    Totals and moneylines are left out on purpose: neither has shown a historical edge.
    """
    best = [p for p in picks if p.get("spread", {}).get("tier") == "best"]
    best.sort(key=lambda p: -p["spread"]["edge_pts"])
    return [{**p["spread"], "game_id": p["game_id"], "home": p["home"], "away": p["away"],
             "kickoff": p["kickoff"], "completed": p["completed"],
             "home_score": p["home_score"], "away_score": p["away_score"]}
            for p in best[:limit]]


def best_bets_record(weeks: list[list[dict]]) -> dict:
    b = _bucket()
    for picks in weeks:
        for bet in best_bets(picks):
            if bet["result"]:
                _add(b, bet)
    return _finish(b)


# --- Calibration --------------------------------------------------------------------------------
# The raw model is overconfident: it may say a spread pick covers 63% of the time when picks
# like it have historically covered ~52%. We learn a shrink factor per market from graded
# history:  fair = 0.5 + k * (raw - 0.5),  fitted by least squares on past outcomes.
# k = 1 means the raw numbers were right; k = 0 means they carried no information.

CAL_MARKETS = ("spread", "total", "winner")


def _market_prob(p: dict, team: str) -> float | None:
    """The sportsbooks' vig-free win probability for a team, if moneylines are known."""
    hml, aml = p.get("market_home_ml"), p.get("market_away_ml")
    if not hml or not aml:
        return None
    ph, pa = odds_math.devig(hml, aml)
    return ph if team == p["home"] else pa


def _fit_ml_blend(weeks: list[list[dict]]) -> dict:
    """How much the model should move the market's win probability: fair = q + w * (model - q).

    Least squares on past outcomes. w = 0 means the market already knows everything the model does.
    """
    num = den = 0.0
    n = 0
    for picks in weeks:
        for p in picks:
            w = p["winner"]
            if not p["completed"] or w["result"] not in ("win", "loss"):
                continue
            q = _market_prob(p, w["team"])
            if q is None:
                continue
            d = w["prob"] - q
            num += ((1.0 if w["result"] == "win" else 0.0) - q) * d
            den += d * d
            n += 1
    return {"w": round(max(0.0, min(1.0, num / den)), 3) if den else 0.0, "n": n}


def ml_fair_prob(p: dict, team: str, cal: dict) -> float:
    """Fair win probability for a moneyline bet: the market's, nudged by the model."""
    model = p["home_win_prob"] if team == p["home"] else 1 - p["home_win_prob"]
    q = _market_prob(p, team)
    if q is None:
        return fair(model, cal["winner"]["k"])
    return min(0.99, max(0.01, q + cal["ml_blend"]["w"] * (model - q)))


def fit_calibration(weeks: list[list[dict]]) -> dict:
    sums = {m: [0.0, 0.0, 0] for m in CAL_MARKETS}   # sum (y-.5)(p-.5), sum (p-.5)^2, n
    for picks in weeks:
        for p in picks:
            for m in CAL_MARKETS:
                x = p.get(m)
                if not x or x.get("result") not in ("win", "loss"):
                    continue
                d = x["prob"] - 0.5
                y = 1.0 if x["result"] == "win" else 0.0
                sums[m][0] += (y - 0.5) * d
                sums[m][1] += d * d
                sums[m][2] += 1
    cal = {m: {"k": round(max(0.0, min(1.5, a / b)), 3) if b else 1.0, "n": n}
           for m, (a, b, n) in sums.items()}
    cal["ml_blend"] = _fit_ml_blend(weeks)
    return cal


def fair(prob: float, k: float) -> float:
    return min(0.99, max(0.01, 0.5 + k * (prob - 0.5)))


def apply_calibration(picks: list[dict], cal: dict) -> None:
    """Adds fair_prob (and fair EV) next to every raw model probability, in place."""
    for p in picks:
        for m in CAL_MARKETS:
            x = p.get(m)
            if x:
                # "Check news" picks (model 6+ pts off the market) have historically hit ~50%:
                # the market knew something the model didn't, so they get no edge.
                raw_fair = 0.5 if x.get("tier") == "caution" else fair(x["prob"], cal[m]["k"])
                x["fair_prob"] = round(raw_fair, 4)
                if "price" in x:
                    x["fair_ev"] = round(odds_math.expected_value(x["fair_prob"], x["price"]), 4)
        ml = p.get("moneyline")
        if ml:
            ml["fair_prob"] = round(ml_fair_prob(p, ml["team"], cal), 4)
            ml["fair_ev"] = round(odds_math.expected_value(ml["fair_prob"], ml["price"]), 4)
