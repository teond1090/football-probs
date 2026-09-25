"""Parlay math and suggestions.

A parlay pays the product of its legs' decimal odds and wins only if every leg wins. Legs from
the same game are never combined (they're correlated, and books price same-game parlays
differently). All probabilities are the calibrated "fair" ones, not the raw model's.
"""
from itertools import combinations
from math import prod

from . import odds_math
from .picks import best_bets, ml_fair_prob

MAX_CANDIDATES = 20       # per ranking; keeps combinations fast even for 70-game college weeks
MIN_LEG_PRICE = -500      # heavier favorites add almost nothing to a parlay's payout
MIN_PARLAY_PRICE = 100    # suggestions must pay at least even money


def to_american(decimal: float) -> int:
    return round((decimal - 1) * 100) if decimal >= 2 else round(-100 / (decimal - 1))


def legs_for_week(picks: list[dict], cal: dict) -> list[dict]:
    legs = []
    for p in picks:
        if p["completed"]:
            continue
        game = f"{p['away']} @ {p['home']}"
        base = {"game_id": p["game_id"], "game": game, "kickoff": p["kickoff"]}

        sp = p.get("spread")
        if sp:
            b = sp.get("best") or {"line": sp["line"], "price": sp["price"], "book": None,
                                   "fair_prob": sp["fair_prob"]}
            legs.append({**base, "market": "spread", "label": f"{sp['team']} {b['line']:+g}",
                         "team": sp["team"], "line": b["line"], "price": b["price"], "book": b["book"],
                         "prob": b["fair_prob"], "tier": sp["tier"]})
        tp = p.get("total")
        if tp:
            b = tp.get("best") or {"line": tp["line"], "price": tp["price"], "book": None,
                                   "fair_prob": tp["fair_prob"]}
            legs.append({**base, "market": "total", "label": f"{tp['side']} {b['line']:g}",
                         "team": None, "line": b["line"], "price": b["price"], "book": b["book"],
                         "prob": b["fair_prob"], "tier": tp["tier"]})

        # Moneyline on the model's winner, at the best available price
        w = p["winner"]
        live = (p.get("best_ml") or {}).get(w["team"])
        consensus = p["market_home_ml"] if w["team"] == p["home"] else p["market_away_ml"]
        price = live["price"] if live else consensus
        if price:
            legs.append({**base, "market": "moneyline", "label": f"{w['team']} ML", "team": w["team"],
                         "line": None, "price": price, "book": live["book"] if live else None,
                         "prob": round(ml_fair_prob(p, w["team"], cal), 4), "tier": None})

    for i, leg in enumerate(legs):
        leg["id"] = i
        leg["decimal"] = round(odds_math.american_to_decimal(leg["price"]), 4)
        leg["ev"] = round(odds_math.expected_value(leg["prob"], leg["price"]), 4)
    return legs


def combine(legs: list[dict]) -> dict:
    p = prod(leg["prob"] for leg in legs)
    d = prod(leg["decimal"] for leg in legs)
    return {
        "legs": legs, "size": len(legs), "prob": round(p, 4), "decimal": round(d, 3),
        "price": to_american(d), "ev": round(p * d - 1, 4),
        "fair_price": odds_math.prob_to_american(p),
    }


def _combos(cands: list[dict], sizes=(2, 3)):
    for n in sizes:
        for c in combinations(cands, n):
            if len({leg["game_id"] for leg in c}) == n:
                yield combine(list(c))


def suggestions(legs: list[dict], picks: list[dict]) -> dict:
    usable = [l for l in legs if l["price"] >= MIN_LEG_PRICE and l["tier"] != "caution"]
    by_prob = sorted(usable, key=lambda l: -l["prob"])[:MAX_CANDIDATES]
    by_ev = sorted(usable, key=lambda l: -l["ev"])[:MAX_CANDIDATES]
    cands = list({l["id"]: l for l in by_prob + by_ev}.values())
    combos = list(_combos(cands))

    out = {}
    # Most likely to hit, among parlays that pay at least even money (2 legs) / +200 (3 legs)
    for n, min_price in ((2, 100), (3, 200)):
        pool = [c for c in combos if c["size"] == n and c["price"] >= min_price]
        out[f"safest_{n}"] = max(pool, key=lambda c: c["prob"]) if pool else None
    out["best_value"] = sorted((c for c in combos if c["price"] >= MIN_PARLAY_PRICE),
                               key=lambda c: -c["ev"])[:3]

    # The week's best bets, parlayed
    bb_ids = [b["game_id"] for b in best_bets(picks)]
    bb_legs = [next(l for l in legs if l["game_id"] == gid and l["market"] == "spread")
               for gid in bb_ids if any(l["game_id"] == gid and l["market"] == "spread" for l in legs)]
    out["best_bets_2"] = combine(bb_legs[:2]) if len(bb_legs) >= 2 else None
    out["best_bets_3"] = combine(bb_legs[:3]) if len(bb_legs) >= 3 else None
    return out


def best_bets_parlay_history(weeks: list[list[dict]], n: int) -> dict:
    """Record of parlaying each week's top-n best bets (pushes drop out of the parlay)."""
    wins = losses = pushes = 0
    units = 0.0
    for picks in weeks:
        bets = [b for b in best_bets(picks)[:n] if b["completed"]]
        if len(bets) < n:
            continue
        if any(b["result"] == "loss" for b in bets):
            losses += 1
            units -= 1
            continue
        live = [b for b in bets if b["result"] == "win"]
        if not live:
            pushes += 1
            continue
        wins += 1
        units += prod(odds_math.american_to_decimal(b["price"]) for b in live) - 1
    played = wins + losses
    return {"wins": wins, "losses": losses, "pushes": pushes, "units": round(units, 2),
            "win_pct": round(wins / played, 4) if played else None,
            "roi": round(units / (played + pushes), 4) if played + pushes else None}
