"""API smoke tests against a small synthetic database (no network)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["AUTO_REFRESH_HOURS"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db  # noqa: E402


def synthetic_games():
    teams = ["AAA", "BBB", "CCC", "DDD"]
    rows = []
    for season in (2020, 2021, 2022, 2023, 2024):
        for week in range(1, 7):
            for i in range(0, 4, 2):
                home, away = teams[(i + week) % 4], teams[(i + week + 1) % 4]
                played = not (season == 2024 and week >= 5)
                rows.append({
                    "league": "nfl", "game_id": f"{season}_{week}_{home}_{away}", "season": season,
                    "week": week, "season_type": "regular", "game_date": f"{season}-09-{week + 9:02d}T13:00",
                    "home": home, "away": away,
                    "home_score": 20 + (week * 3 + i) % 11 if played else None,
                    "away_score": 17 + (week * 5 + i) % 9 if played else None,
                    "neutral": 0, "home_spread": -2.5, "total_line": 41.5,
                    "home_ml": -140, "away_ml": 120, "home_qb": f"{home} QB", "away_qb": f"{away} QB",
                    "home_rest": 7, "away_rest": 7,
                })
    return rows


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        data_dir = Path(cls.tmp.name)
        cls.patches = [
            mock.patch.object(config, "DATA_DIR", data_dir),
            mock.patch.object(db, "DATA_DIR", data_dir),
            mock.patch.object(db, "DB_PATH", data_dir / "test.db"),
        ]
        for p in cls.patches:
            p.start()
        db.upsert_games(synthetic_games())
        from app.main import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def test_picks_default_week_is_first_unplayed(self):
        r = self.client.get("/api/picks/nfl").json()
        self.assertEqual(r["week"]["id"], "2024-regular-5")
        self.assertEqual(len(r["picks"]), 2)
        self.assertTrue(all(not p["completed"] for p in r["picks"]))
        self.assertIn("spread", r["picks"][0])

    def test_past_week_is_graded(self):
        r = self.client.get("/api/picks/nfl?week=2023-regular-3").json()
        self.assertTrue(all(p["spread"]["result"] in ("win", "loss", "push") for p in r["picks"]))
        self.assertIn("winner", r["week_record"])

    def test_csv_export(self):
        r = self.client.get("/api/picks/nfl/csv?week=2023-regular-3")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.text.strip().splitlines()), 3)

    def test_matchup_and_team(self):
        m = self.client.get("/api/matchup/nfl?home=AAA&away=BBB").json()
        covers = [s["home_cover"] for s in m["alt_spreads"]]
        self.assertEqual(covers, sorted(covers))  # easier lines cover more often
        t = self.client.get("/api/team/nfl/AAA").json()
        self.assertEqual(t["team"], "AAA")
        self.assertTrue(t["games"])

    def test_bet_tracker_roundtrip(self):
        bet = {"league": "nfl", "game": "BBB @ AAA", "market": "spread", "selection": "AAA",
               "line": -2.5, "price": -110, "stake": 11, "model_prob": 0.56}
        bid = self.client.post("/api/bets", json=bet).json()["id"]
        self.client.patch(f"/api/bets/{bid}", json={"result": "win"})
        s = self.client.get("/api/bets").json()["summary"]
        self.assertAlmostEqual(s["profit"], 10.0)
        self.client.delete(f"/api/bets/{bid}")


if __name__ == "__main__":
    unittest.main()
