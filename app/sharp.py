"""Sharp-book value finder.

Pinnacle takes the biggest bets in the world at the smallest margin, so its prices (with the
margin removed) are the best available estimate of each outcome's true probability. Any other
book paying more than that fair price, at the same line, is a positive-expected-value bet.
This does not use the app's own model at all.

When Pinnacle hasn't posted a market, LowVig/BetOnline (low-margin, fairly sharp) stand in,
and the result is labeled as the weaker source.
"""
from datetime import datetime, timezone

from . import odds_math

SHARP_PRIMARY = "pinnacle"
SHARP_FALLBACK = ("lowvig", "betonlineag")
MARKET_NAMES = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}
MAX_SHARP_HOLD = 0.08      # ignore sharp markets with an unusually big margin (stale/odd)
VERIFY_EV = 0.10           # edges this large are usually a stale line: flag, don't trust


def filter_books(events: list[dict], allowed: set[str] | None, keep: set[str] = frozenset()) -> list[dict]:
    """Drop bookmakers the user can't bet at (sharp books in `keep` stay for pricing)."""
    if not allowed:
        return events
    ok = allowed | set(keep)
    return [{**e, "bookmakers": [b for b in e.get("bookmakers", []) if b["key"] in ok]} for e in events]


def _fair_lines(book: dict) -> dict[tuple, float]:
    """(market, outcome name, point) -> vig-free probability for one book's two-way markets."""
    out = {}
    for m in book.get("markets", []):
        outs = m.get("outcomes", [])
        if len(outs) != 2 or m["key"] not in MARKET_NAMES:
            continue
        a, b = outs
        if a.get("point") is not None and b.get("point") is not None and m["key"] == "totals" and a["point"] != b["point"]:
            continue
        hold = odds_math.implied_prob(a["price"]) + odds_math.implied_prob(b["price"]) - 1
        if hold > MAX_SHARP_HOLD:
            continue
        pa, pb = odds_math.devig(a["price"], b["price"])
        out[(m["key"], a["name"], a.get("point"))] = pa
        out[(m["key"], b["name"], b.get("point"))] = pb
    return out


def sharp_fair(event: dict) -> tuple[dict[tuple, float], str | None]:
    books = {b["key"]: b for b in event.get("bookmakers", [])}
    if SHARP_PRIMARY in books:
        fair = _fair_lines(books[SHARP_PRIMARY])
        if fair:
            return fair, "Pinnacle"
    # Fallback: average of the low-margin books that have the same line
    tables = [_fair_lines(books[k]) for k in SHARP_FALLBACK if k in books]
    tables = [t for t in tables if t]
    if not tables:
        return {}, None
    keys = set().union(*tables)
    fair = {k: sum(t[k] for t in tables if k in t) / sum(1 for t in tables if k in t) for k in keys}
    return fair, "LowVig/BetOnline"


def find_value(events: list[dict], allowed: set[str] | None = None, min_ev: float = 0.01,
               kelly: float = 0.25, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    sharp_keys = {SHARP_PRIMARY, *SHARP_FALLBACK}
    events = filter_books(events, allowed, keep=sharp_keys)
    bets: dict[tuple, dict] = {}
    games = covered = 0

    for ev in events:
        kick = ev.get("commence_time")
        if kick and datetime.fromisoformat(kick.replace("Z", "+00:00")) <= now:
            continue    # in-play prices move too fast to compare
        games += 1
        fair, source = sharp_fair(ev)
        if not fair:
            continue
        covered += 1
        game = f"{ev['away_team']} @ {ev['home_team']}"
        for book in ev.get("bookmakers", []):
            key = book["key"]
            if key in sharp_keys and (allowed is None or key not in allowed):
                continue    # pricing source only, unless the user can bet there
            if source == "Pinnacle" and key == SHARP_PRIMARY:
                continue
            for m in book.get("markets", []):
                if m["key"] not in MARKET_NAMES:
                    continue
                for o in m.get("outcomes", []):
                    fk = (m["key"], o["name"], o.get("point"))
                    p = fair.get(fk)
                    if p is None:
                        continue
                    ev_pct = odds_math.expected_value(p, o["price"])
                    if ev_pct < min_ev:
                        continue
                    bk = (ev["id"], fk)
                    cand = {
                        "event_id": ev["id"], "game": game, "kickoff": kick,
                        "home": ev["home_team"], "away": ev["away_team"],
                        "market": MARKET_NAMES[m["key"]], "selection": o["name"], "line": o.get("point"),
                        "price": o["price"], "book": book.get("title", key), "book_key": key,
                        "fair_prob": round(p, 4), "fair_price": odds_math.prob_to_american(p),
                        "ev": round(ev_pct, 4),
                        "kelly": round(odds_math.kelly_fraction(p, o["price"], kelly), 4),
                        "sharp": source, "verify": ev_pct >= VERIFY_EV,
                        "also": [],
                    }
                    if bk not in bets:
                        bets[bk] = cand
                    elif ev_pct > bets[bk]["ev"]:
                        cand["also"] = bets[bk]["also"] + [f"{bets[bk]['book']} {bets[bk]['price']:+d}"]
                        bets[bk] = cand
                    else:
                        bets[bk]["also"].append(f"{book.get('title', key)} {o['price']:+d}")

    found = sorted(bets.values(), key=lambda b: -b["ev"])
    return {"bets": found, "games": games, "games_with_sharp": covered}


def books_seen(events: list[dict]) -> list[dict]:
    seen = {}
    for e in events:
        for b in e.get("bookmakers", []):
            seen[b["key"]] = b.get("title", b["key"])
    return [{"key": k, "title": t} for k, t in sorted(seen.items(), key=lambda kv: kv[1].lower())]
