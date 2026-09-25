import unittest
from datetime import datetime, timezone

from app.sharp import filter_books, find_value, sharp_fair

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


def book(key, title, h2h=None, spread=None, total=None):
    markets = []
    if h2h:
        markets.append({"key": "h2h", "outcomes": [{"name": "Home", "price": h2h[0]}, {"name": "Away", "price": h2h[1]}]})
    if spread:
        pt, hp, ap = spread
        markets.append({"key": "spreads", "outcomes": [{"name": "Home", "price": hp, "point": pt},
                                                       {"name": "Away", "price": ap, "point": -pt}]})
    if total:
        pt, op, up = total
        markets.append({"key": "totals", "outcomes": [{"name": "Over", "price": op, "point": pt},
                                                      {"name": "Under", "price": up, "point": pt}]})
    return {"key": key, "title": title, "markets": markets}


def event(*books, kickoff="2026-09-27T17:00:00Z"):
    return {"id": "e1", "home_team": "Home", "away_team": "Away", "commence_time": kickoff, "bookmakers": list(books)}


class SharpTest(unittest.TestCase):
    def test_flags_soft_book_beating_pinnacle(self):
        ev = event(book("pinnacle", "Pinnacle", h2h=(-150, 140)),
                   book("draftkings", "DraftKings", h2h=(-160, 160)))
        r = find_value([ev], now=NOW)
        self.assertEqual(len(r["bets"]), 1)
        b = r["bets"][0]
        self.assertEqual((b["selection"], b["book"], b["sharp"]), ("Away", "DraftKings", "Pinnacle"))
        self.assertGreater(b["ev"], 0.05)

    def test_no_value_when_soft_book_is_worse(self):
        ev = event(book("pinnacle", "Pinnacle", h2h=(-150, 140)),
                   book("fanduel", "FanDuel", h2h=(-170, 135)))
        self.assertEqual(find_value([ev], now=NOW)["bets"], [])

    def test_lines_must_match_exactly(self):
        ev = event(book("pinnacle", "Pinnacle", spread=(-3.0, -110, -110)),
                   book("draftkings", "DraftKings", spread=(-2.5, +120, -140)))
        self.assertEqual(find_value([ev], now=NOW)["bets"], [])

    def test_fallback_sharp_source(self):
        ev = event(book("lowvig", "LowVig", total=(44.5, -105, -105)),
                   book("betmgm", "BetMGM", total=(44.5, +110, -130)))
        fair, source = sharp_fair(ev)
        self.assertEqual(source, "LowVig/BetOnline")
        bets = find_value([ev], now=NOW)["bets"]
        self.assertEqual(bets[0]["selection"], "Over")

    def test_started_games_are_skipped(self):
        ev = event(book("pinnacle", "Pinnacle", h2h=(-150, 140)), book("draftkings", "DraftKings", h2h=(-160, 160)),
                   kickoff="2026-09-24T17:00:00Z")
        self.assertEqual(find_value([ev], now=NOW)["games"], 0)

    def test_book_filter(self):
        ev = event(book("pinnacle", "Pinnacle", h2h=(-150, 140)),
                   book("draftkings", "DraftKings", h2h=(-160, 160)),
                   book("fanduel", "FanDuel", h2h=(-160, 165)))
        r = find_value([ev], allowed={"draftkings"}, now=NOW)
        self.assertEqual({b["book"] for b in r["bets"]}, {"DraftKings"})
        kept = filter_books([ev], {"draftkings"}, keep={"pinnacle"})[0]["bookmakers"]
        self.assertEqual({b["key"] for b in kept}, {"pinnacle", "draftkings"})

    def test_best_book_wins_and_others_listed(self):
        ev = event(book("pinnacle", "Pinnacle", h2h=(-150, 140)),
                   book("draftkings", "DraftKings", h2h=(-160, 160)),
                   book("fanduel", "FanDuel", h2h=(-160, 165)))
        b = find_value([ev], now=NOW)["bets"][0]
        self.assertEqual(b["book"], "FanDuel")
        self.assertEqual(b["also"], ["DraftKings +160"])


if __name__ == "__main__":
    unittest.main()
