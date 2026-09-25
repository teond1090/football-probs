import unittest

from app import odds_math
from app.best_odds import attach_best_odds
from app.parlays import combine, legs_for_week, suggestions, to_american
from app.picks import apply_calibration, fair, fit_calibration

CAL = {"spread": {"k": 0.2, "n": 1}, "total": {"k": 0.0, "n": 1},
       "winner": {"k": 1.0, "n": 1}, "ml_blend": {"w": 0.0, "n": 1}}


def pick(gid, home, away, home_margin=3.0, spread_team=None, line=-1.5, tier="best", done=False):
    spread_team = spread_team or home
    return {
        "game_id": gid, "home": home, "away": away, "kickoff": "2026-09-27T13:00", "completed": done,
        "home_score": None, "away_score": None, "home_win_prob": 0.6,
        "market_home_ml": -150, "market_away_ml": 130, "market_home_spread": -1.5, "market_total": 44.5,
        "model": {"home_margin": home_margin, "total": 45.0, "margin_sd": 13.5, "total_sd": 13.5},
        "winner": {"team": home, "prob": 0.6, "result": None},
        "spread": {"team": spread_team, "line": line, "price": -110, "prob": 0.58, "tier": tier,
                   "edge_pts": 4.5, "result": None},
        "total": {"side": "Over", "line": 44.5, "price": -110, "prob": 0.52, "tier": "pass", "result": None},
    }


class CalibrationTest(unittest.TestCase):
    def test_fair_shrinks_toward_half(self):
        self.assertAlmostEqual(fair(0.7, 0.25), 0.55)
        self.assertAlmostEqual(fair(0.7, 0.0), 0.5)

    def test_fit_recovers_no_signal(self):
        # picks claim 60% but win exactly half the time -> k ~ 0
        weeks = [[{"spread": {"prob": 0.6, "result": r}, "completed": True,
                   "winner": {"result": None}} for r in ("win", "loss") * 50]]
        self.assertEqual(fit_calibration(weeks)["spread"]["k"], 0.0)

    def test_caution_picks_get_no_edge(self):
        p = pick("g1", "AAA", "BBB", tier="caution")
        apply_calibration([p], CAL)
        self.assertEqual(p["spread"]["fair_prob"], 0.5)

    def test_moneyline_anchored_to_market_when_w_zero(self):
        p = pick("g1", "AAA", "BBB")
        apply_calibration([p], CAL)
        legs = legs_for_week([p], CAL)
        ml = next(l for l in legs if l["market"] == "moneyline")
        home_no_vig, _ = odds_math.devig(-150, 130)
        self.assertAlmostEqual(ml["prob"], round(home_no_vig, 4))


class BestOddsTest(unittest.TestCase):
    def test_picks_best_line_and_price_across_books(self):
        p = pick("g1", "AAA", "BBB", home_margin=-1.0, spread_team="BBB", line=1.5)
        apply_calibration([p], CAL)
        event = {"home_team": "AAA", "away_team": "BBB", "bookmakers": [
            {"title": "Book1", "markets": [{"key": "spreads", "outcomes": [
                {"name": "AAA", "price": -110, "point": -1.5}, {"name": "BBB", "price": -110, "point": 1.5}]}]},
            {"title": "Book2", "markets": [{"key": "spreads", "outcomes": [
                {"name": "AAA", "price": -110, "point": -2.5}, {"name": "BBB", "price": -110, "point": 2.5}]},
                {"key": "h2h", "outcomes": [{"name": "AAA", "price": -140}, {"name": "BBB", "price": 125}]}]},
        ]}
        n = attach_best_odds("cfb", [p], [event], CAL, {"AAA", "BBB"})
        self.assertEqual(n, 1)
        self.assertEqual(p["spread"]["best"]["book"], "Book2")   # +2.5 beats +1.5 at the same price
        self.assertEqual(p["spread"]["best"]["line"], 2.5)
        self.assertEqual(p["best_ml"]["BBB"], {"price": 125, "book": "Book2"})


class ParlayTest(unittest.TestCase):
    def test_combine_math(self):
        legs = [{"prob": 0.5, "decimal": odds_math.american_to_decimal(-110)} for _ in range(2)]
        c = combine(legs)
        self.assertEqual(c["price"], 264)             # standard 2-team parlay payout
        self.assertAlmostEqual(c["prob"], 0.25)
        self.assertLess(c["ev"], 0)

    def test_to_american(self):
        self.assertEqual(to_american(2.0), 100)
        self.assertEqual(to_american(1.5), -200)

    def test_suggestions_never_combine_same_game(self):
        picks = [pick(f"g{i}", f"H{i}", f"A{i}") for i in range(4)]
        apply_calibration(picks, CAL)
        legs = legs_for_week(picks, CAL)
        s = suggestions(legs, picks)
        for key, val in s.items():
            for c in (val if isinstance(val, list) else [val]):
                if c:
                    ids = [l["game_id"] for l in c["legs"]]
                    self.assertEqual(len(ids), len(set(ids)), key)


if __name__ == "__main__":
    unittest.main()
