"""Build the betting board: model projections vs. live sportsbook prices."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean

from . import odds_math
from .config import current_season
from .data.teams import match_team
from .models.ratings import NFL, Prediction, RatingEngine
from .picks import fair as shrink

# A model that disagrees with the market this much is usually missing information
# (injury, QB change, weather) rather than finding value: NFL points, scaled for college.
CAUTION_POINTS = 6.0


def _day(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def _find_scheduled(upcoming: list[dict], home: str, away: str, when: str | None) -> dict | None:
    target = _day(when)
    for g in upcoming:
        if {g["home"], g["away"]} != {home, away}:
            continue
        d = _day(g["game_date"])
        if target is None or d is None or abs((d - target).days) <= 1:
            return g
    return None


def _outcome(market_key: str, o: dict, pred: Prediction, home_name: str):
    """Map an Odds API outcome to (market, side, point, model probability)."""
    point = o.get("point")
    if market_key == "h2h":
        p = pred.home_win_prob
        return ("moneyline", "home", None, p) if o["name"] == home_name else ("moneyline", "away", None, 1 - p)
    if market_key == "spreads":
        if o["name"] == home_name:
            return "spread", "home", point, pred.home_cover_prob(point)
        # away +3.5 covers when home margin < 3.5
        return "spread", "away", point, 1 - pred.home_cover_prob(-point)
    if market_key == "totals":
        p = pred.over_prob(point)
        return ("total", "over", point, p) if o["name"].lower() == "over" else ("total", "under", point, 1 - p)
    return None


def _realistic(market: str, side: str, point, raw: float, market_p: float, pred: Prediction,
               cal: dict | None) -> tuple[float, bool]:
    """(calibrated probability, caution flag) for one offer. Without calibration, raw is used."""
    scale = pred.margin_sd / NFL.margin_sd
    if market == "spread":
        home_line = point if side == "home" else -point
        caution = abs(pred.home_margin + home_line) >= CAUTION_POINTS * scale
    elif market == "total":
        caution = abs(pred.total - point) >= CAUTION_POINTS * scale
    else:
        caution = False
    if cal is None:
        return raw, caution
    if market == "moneyline":
        return market_p + cal["ml_blend"]["w"] * (raw - market_p), caution
    if caution:
        return 0.5, caution
    return shrink(raw, cal[market]["k"]), caution


def collect_offers(event: dict, pred: Prediction, min_ev: float, kelly: float,
                   cal: dict | None = None) -> list[dict]:
    home_name, away_name = event["home_team"], event["away_team"]
    best: dict[tuple, dict] = {}
    fair: dict[tuple, list[float]] = defaultdict(list)
    books: dict[tuple, int] = defaultdict(int)

    for book in event.get("bookmakers", []):
        for m in book.get("markets", []):
            outs = m.get("outcomes", [])
            if len(outs) != 2:
                continue
            no_vig = odds_math.devig(outs[0]["price"], outs[1]["price"])
            for o, market_p in zip(outs, no_vig):
                parsed = _outcome(m["key"], o, pred, home_name)
                if parsed is None:
                    continue
                market, side, point, model_p = parsed
                key = (market, side, point)
                fair[key].append(market_p)
                books[key] += 1
                if key not in best or o["price"] > best[key]["price"]:
                    label = {"home": home_name, "away": away_name}.get(side, side.title())
                    best[key] = {
                        "market": market, "side": side, "selection": label, "line": point,
                        "price": o["price"], "book": book.get("title", book.get("key")),
                        "model_prob": model_p,
                    }

    offers = []
    for key, off in best.items():
        raw = off["model_prob"]
        market_p = mean(fair[key])
        p, caution = _realistic(off["market"], off["side"], off["line"], raw, market_p, pred, cal)
        ev = odds_math.expected_value(p, off["price"])
        edge = p - market_p
        offers.append({
            **off,
            "model_prob": round(p, 4),
            "raw_prob": round(raw, 4),
            "market_prob": round(market_p, 4),
            "books": books[key],
            "edge": round(edge, 4),
            "ev": round(ev, 4),
            "kelly": round(odds_math.kelly_fraction(p, off["price"], kelly), 4),
            "value": ev >= min_ev and not caution,
            "caution": caution,
        })
    order = {"moneyline": 0, "spread": 1, "total": 2}
    return sorted(offers, key=lambda o: (order[o["market"]], o["side"], o["line"] or 0))


def build_board(
    league: str, engine: RatingEngine, games: list[dict], odds: dict,
    min_ev: float = 0.03, kelly: float = 0.25, cal: dict | None = None,
) -> dict:
    season = current_season()
    upcoming = [g for g in games if g["home_score"] is None]
    known = {t for g in games if g["season"] >= season - 1 for t in (g["home"], g["away"])}
    cards, unmatched = [], []

    if odds.get("events"):
        for ev in odds["events"]:
            home = match_team(league, ev["home_team"], known)
            away = match_team(league, ev["away_team"], known)
            if not home or not away:
                unmatched.append(f"{ev['away_team']} @ {ev['home_team']}")
                continue
            sched = _find_scheduled(upcoming, home, away, ev.get("commence_time"))
            g = {
                "home": home, "away": away, "season": season,
                "neutral": sched["neutral"] if sched else 0,
                "home_div": sched["home_div"] if sched else None,
                "away_div": sched["away_div"] if sched else None,
            }
            pred = engine.predict(g)
            cards.append({
                "home": home, "away": away,
                "home_name": ev["home_team"], "away_name": ev["away_team"],
                "kickoff": ev.get("commence_time"), "neutral": bool(g["neutral"]),
                "prediction": pred.as_dict(),
                "offers": collect_offers(ev, pred, min_ev, kelly, cal),
            })
    else:
        today = date.today()
        future = [g for g in upcoming if (_day(g["game_date"]) or today) >= today]
        horizon = today + timedelta(days=8)
        window = [g for g in future if (_day(g["game_date"]) or today) <= horizon] or future[:16]
        for g in window:
            cards.append({
                "home": g["home"], "away": g["away"],
                "home_name": g["home"], "away_name": g["away"],
                "kickoff": g["game_date"], "neutral": bool(g["neutral"]),
                "prediction": engine.predict(g).as_dict(),
                "offers": [],
            })

    cards.sort(key=lambda c: c["kickoff"] or "")
    value = [
        {**o, "game": f"{c['away_name']} @ {c['home_name']}", "kickoff": c["kickoff"]}
        for c in cards for o in c["offers"] if o["value"]
    ]
    value.sort(key=lambda o: o["ev"], reverse=True)
    return {
        "league": league,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "odds_fetched_at": odds.get("fetched_at"),
        "odds_remaining": odds.get("remaining"),
        "odds_error": odds.get("error"),
        "games": cards,
        "value_bets": value,
        "unmatched": unmatched,
    }
