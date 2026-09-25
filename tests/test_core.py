import unittest

from app import odds_math as om
from app.backtest import run_backtest
from app.models.ratings import NFL, RatingEngine


class OddsMathTest(unittest.TestCase):
    def test_implied_prob(self):
        self.assertAlmostEqual(om.implied_prob(-110), 0.5238, places=4)
        self.assertAlmostEqual(om.implied_prob(+150), 0.4, places=4)

    def test_devig_sums_to_one(self):
        a, b = om.devig(-110, -110)
        self.assertAlmostEqual(a, 0.5)
        self.assertAlmostEqual(a + b, 1.0)

    def test_expected_value(self):
        self.assertAlmostEqual(om.expected_value(0.5, +100), 0.0)
        self.assertLess(om.expected_value(0.5, -110), 0)
        self.assertGreater(om.expected_value(0.55, -110), 0)

    def test_kelly(self):
        self.assertEqual(om.kelly_fraction(0.45, -110), 0.0)
        # full Kelly at 55% and -110 is ~5.5%; quarter Kelly ~1.4%
        self.assertAlmostEqual(om.kelly_fraction(0.55, -110, 1.0), 0.055, places=3)

    def test_prob_to_american_roundtrip(self):
        for odds in (-250, -110, +100, +180):
            self.assertAlmostEqual(om.prob_to_american(om.implied_prob(odds)), odds, delta=1)

    def test_cover_prob(self):
        # Projected home by 3 vs a -3 spread = coin flip
        self.assertAlmostEqual(om.cover_prob(3, -3, 13.5), 0.5)
        self.assertGreater(om.cover_prob(7, -3, 13.5), 0.5)
        self.assertLess(om.cover_prob(0, -3, 13.5), 0.5)

    def test_profit(self):
        self.assertAlmostEqual(om.profit(110, -110, "win"), 100)
        self.assertEqual(om.profit(50, +200, "loss"), -50)
        self.assertEqual(om.profit(50, +200, "push"), 0)


def game(season, home, away, hs, as_, **kw):
    return {"season": season, "home": home, "away": away, "home_score": hs, "away_score": as_,
            "neutral": 0, "home_div": None, "away_div": None, "home_spread": None, "total_line": None,
            "home_ml": None, "away_ml": None, "home_spread_odds": None, "away_spread_odds": None,
            "over_odds": None, "under_odds": None, **kw}


class RatingsTest(unittest.TestCase):
    def test_home_field_advantage(self):
        pred = RatingEngine(NFL).predict(game(2024, "A", "B", None, None))
        self.assertAlmostEqual(pred.home_margin, NFL.hfa_pts)
        self.assertGreater(pred.home_win_prob, 0.5)

    def test_neutral_site_is_even(self):
        pred = RatingEngine(NFL).predict(game(2024, "A", "B", None, None, neutral=1))
        self.assertAlmostEqual(pred.home_win_prob, 0.5)

    def test_winner_gains_rating(self):
        eng = RatingEngine(NFL)
        eng.update(game(2024, "A", "B", 35, 10))
        self.assertGreater(eng.elo["A"], 1500)
        self.assertLess(eng.elo["B"], 1500)
        self.assertAlmostEqual(eng.elo["A"] + eng.elo["B"], 3000)

    def test_offseason_regression(self):
        eng = RatingEngine(NFL)
        for _ in range(5):
            eng.update(game(2024, "A", "B", 35, 10))
        before = eng.elo["A"]
        eng.predict(game(2025, "A", "B", None, None))
        self.assertLess(eng.elo["A"], before)
        self.assertGreater(eng.elo["A"], 1500)

    def test_high_scoring_team_raises_total(self):
        eng = RatingEngine(NFL)
        base = eng.predict(game(2024, "A", "B", None, None)).total
        for _ in range(8):
            eng.update(game(2024, "A", "C", 45, 38))
        self.assertGreater(eng.predict(game(2024, "A", "B", None, None)).total, base)


class BacktestTest(unittest.TestCase):
    def test_runs_and_settles(self):
        games = [game(2020 + i // 10, "A", "B", 24 + i % 7, 20, home_spread=-3.0, total_line=44.5,
                      home_ml=-150, away_ml=130) for i in range(40)]
        r = run_backtest("nfl", games, start_season=2021, min_ev=0.0)
        self.assertEqual(r["games_evaluated"], 30)
        for m in r["markets"].values():
            self.assertEqual(m["bets"], m["wins"] + m["losses"] + m["pushes"])


if __name__ == "__main__":
    unittest.main()
