"""Line shopping for picks: find the best line + price across every sportsbook for each pick.

"Best" means highest expected value using the calibrated probability *at that book's line*,
so a book offering DEN +3 -115 can beat another's DEN +2.5 -105.
"""
from . import odds_math
from .data.teams import match_team
from .picks import fair


def _event_pick(league: str, event: dict, picks: list[dict], known: set[str]) -> dict | None:
    home = match_team(league, event["home_team"], known)
    away = match_team(league, event["away_team"], known)
    if not home or not away:
        return None
    return next((p for p in picks if {p["home"], p["away"]} == {home, away} and not p["completed"]), None)


def _better(new: dict, old: dict | None) -> bool:
    return old is None or (new["fair_ev"], new["price"]) > (old["fair_ev"], old["price"])


def attach_best_odds(league: str, picks: list[dict], events: list[dict], cal: dict, known: set[str]) -> int:
    """Adds pick[market]["best"] (and pick["best_ml"]) in place. Returns games matched."""
    matched = 0
    for ev in events:
        p = _event_pick(league, ev, picks, known)
        if p is None:
            continue
        matched += 1
        m = p["model"]
        home_name = ev["home_team"]
        # the odds feed's name for each of our teams
        name_of = {p["home"]: home_name, p["away"]: ev["away_team"]}
        sp, tp = p.get("spread"), p.get("total")
        best_sp = best_tp = None
        best_ml: dict[str, dict] = {}

        for book in ev.get("bookmakers", []):
            title = book.get("title", book.get("key"))
            for mk in book.get("markets", []):
                for o in mk.get("outcomes", []):
                    price, point = o.get("price"), o.get("point")
                    if price is None:
                        continue
                    if mk["key"] == "spreads" and sp and point is not None and o["name"] == name_of[sp["team"]]:
                        # probability our side covers at this book's line
                        if sp["team"] == p["home"]:
                            raw = odds_math.cover_prob(m["home_margin"], point, m["margin_sd"])
                        else:
                            raw = 1 - odds_math.cover_prob(m["home_margin"], -point, m["margin_sd"])
                        f = 0.5 if sp["tier"] == "caution" else fair(raw, cal["spread"]["k"])
                        offer = {"line": point, "price": price, "book": title, "fair_prob": round(f, 4),
                                 "fair_ev": round(odds_math.expected_value(f, price), 4)}
                        if _better(offer, best_sp):
                            best_sp = offer
                    elif mk["key"] == "totals" and tp and point is not None and o["name"].lower() == tp["side"].lower():
                        over = odds_math.over_prob(m["total"], point, m["total_sd"])
                        raw = over if tp["side"] == "Over" else 1 - over
                        f = 0.5 if tp["tier"] == "caution" else fair(raw, cal["total"]["k"])
                        offer = {"line": point, "price": price, "book": title, "fair_prob": round(f, 4),
                                 "fair_ev": round(odds_math.expected_value(f, price), 4)}
                        if _better(offer, best_tp):
                            best_tp = offer
                    elif mk["key"] == "h2h":
                        team = p["home"] if o["name"] == home_name else p["away"]
                        if team not in best_ml or price > best_ml[team]["price"]:
                            best_ml[team] = {"price": price, "book": title}

        if best_sp:
            sp["best"] = best_sp
        if best_tp:
            tp["best"] = best_tp
        if best_ml:
            p["best_ml"] = best_ml
    return matched
