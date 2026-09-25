"""Team rating model.

Two ratings are tracked per team and updated after every game, in date order:

* Elo (with margin-of-victory multiplier, FiveThirtyEight-style) -> projected point margin,
  used for moneyline and spread probabilities.
* Offense / defense points ratings (points above/below league average) -> projected total,
  used for over/under probabilities.

Ratings regress toward each team's baseline at the start of every season.
"""
import math
from dataclasses import dataclass, field

from .. import odds_math


@dataclass(frozen=True)
class LeagueParams:
    name: str
    k: float                 # Elo learning rate
    hfa_elo: float           # home-field advantage in Elo points
    regress: float           # fraction of Elo pulled back to baseline each offseason
    margin_sd: float         # std dev of actual margin around projection
    total_sd: float          # std dev of actual total around projection
    init_avg_pts: float      # starting league-average points per team per game
    pts_k: float             # learning rate for offense/defense ratings
    pts_regress: float       # offseason regression for offense/defense ratings
    mean_elo: float = 1500.0
    lower_div_elo: float = 1500.0   # starting Elo for non-FBS teams (college only)
    lower_div_pts: float = 0.0      # starting off/def rating for non-FBS teams
    elo_per_point: float = 25.0

    @property
    def hfa_pts(self) -> float:
        return self.hfa_elo / self.elo_per_point


NFL = LeagueParams(
    "nfl", k=20, hfa_elo=40, regress=1 / 3, margin_sd=13.5, total_sd=13.7,
    init_avg_pts=21.0, pts_k=0.06, pts_regress=0.35,
)
CFB = LeagueParams(
    "cfb", k=25, hfa_elo=65, regress=0.35, margin_sd=16.5, total_sd=16.0,
    init_avg_pts=27.0, pts_k=0.08, pts_regress=0.35,
    lower_div_elo=1150, lower_div_pts=-8.0,
)
PARAMS = {"nfl": NFL, "cfb": CFB}


@dataclass
class Prediction:
    home_margin: float   # projected home points minus away points
    total: float         # projected combined points
    home_elo: float
    away_elo: float
    margin_sd: float
    total_sd: float

    @property
    def home_score(self) -> float:
        return (self.total + self.home_margin) / 2

    @property
    def away_score(self) -> float:
        return (self.total - self.home_margin) / 2

    @property
    def home_win_prob(self) -> float:
        return odds_math.win_prob(self.home_margin, self.margin_sd)

    def home_cover_prob(self, home_spread: float) -> float:
        return odds_math.cover_prob(self.home_margin, home_spread, self.margin_sd)

    def over_prob(self, line: float) -> float:
        return odds_math.over_prob(self.total, line, self.total_sd)

    def as_dict(self) -> dict:
        p = self.home_win_prob
        return {
            "home_margin": round(self.home_margin, 1),
            "total": round(self.total, 1),
            "home_score": round(self.home_score, 1),
            "away_score": round(self.away_score, 1),
            "home_win_prob": round(p, 4),
            "fair_home_spread": round(-self.home_margin * 2) / 2,  # nearest half point
            "fair_home_ml": odds_math.prob_to_american(p),
            "fair_away_ml": odds_math.prob_to_american(1 - p),
            "home_elo": round(self.home_elo),
            "away_elo": round(self.away_elo),
        }


def _is_lower_div(div: str | None) -> bool:
    return div is not None and div.lower() != "fbs"


@dataclass
class RatingEngine:
    p: LeagueParams
    elo: dict = field(default_factory=dict)
    off: dict = field(default_factory=dict)
    dfn: dict = field(default_factory=dict)   # positive = better defense (allows fewer points)
    base_elo: dict = field(default_factory=dict)
    base_pts: dict = field(default_factory=dict)
    avg_pts: float = 0.0
    season: int | None = None
    games_processed: int = 0

    def __post_init__(self):
        self.avg_pts = self.avg_pts or self.p.init_avg_pts

    # -- bookkeeping ---------------------------------------------------------------------------
    def _ensure(self, team: str, div: str | None) -> None:
        if team in self.elo:
            return
        lower = _is_lower_div(div)
        self.base_elo[team] = self.p.lower_div_elo if lower else self.p.mean_elo
        self.base_pts[team] = self.p.lower_div_pts if lower else 0.0
        self.elo[team] = self.base_elo[team]
        self.off[team] = self.base_pts[team]
        self.dfn[team] = self.base_pts[team]

    def _roll_season(self, season: int) -> None:
        if self.season is not None and season > self.season:
            for t in self.elo:
                self.elo[t] += (self.base_elo[t] - self.elo[t]) * self.p.regress
                self.off[t] += (self.base_pts[t] - self.off[t]) * self.p.pts_regress
                self.dfn[t] += (self.base_pts[t] - self.dfn[t]) * self.p.pts_regress
        if self.season is None or season > self.season:
            self.season = season

    def _hfa(self, g: dict) -> float:
        return 0.0 if g.get("neutral") else 1.0

    # -- core ----------------------------------------------------------------------------------
    def predict(self, g: dict) -> Prediction:
        """g needs: home, away, season, neutral; optionally home_div / away_div."""
        self._roll_season(g["season"])
        h, a = g["home"], g["away"]
        self._ensure(h, g.get("home_div"))
        self._ensure(a, g.get("away_div"))
        home = self._hfa(g)

        elo_diff = self.elo[h] - self.elo[a] + home * self.p.hfa_elo
        margin = elo_diff / self.p.elo_per_point

        home_pts = self.avg_pts + self.off[h] - self.dfn[a] + home * self.p.hfa_pts / 2
        away_pts = self.avg_pts + self.off[a] - self.dfn[h] - home * self.p.hfa_pts / 2
        return Prediction(
            home_margin=margin,
            total=max(home_pts + away_pts, 0.0),
            home_elo=self.elo[h],
            away_elo=self.elo[a],
            margin_sd=self.p.margin_sd,
            total_sd=self.p.total_sd,
        )

    def update(self, g: dict) -> Prediction:
        """Predict a completed game, then learn from its result. Returns the pre-game prediction."""
        pred = self.predict(g)
        h, a = g["home"], g["away"]
        hs, as_ = g["home_score"], g["away_score"]
        home = self._hfa(g)

        # Elo with margin-of-victory multiplier (dampened when the favorite wins big)
        margin = hs - as_
        elo_diff = self.elo[h] - self.elo[a] + home * self.p.hfa_elo
        expected = 1 / (1 + 10 ** (-elo_diff / 400))
        result = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        if margin != 0:
            winner_diff = elo_diff if margin > 0 else -elo_diff
            mult = math.log(abs(margin) + 1) * 2.2 / (winner_diff * 0.001 + 2.2)
        else:
            mult = 1.0
        shift = self.p.k * mult * (result - expected)
        self.elo[h] += shift
        self.elo[a] -= shift

        # Offense / defense points ratings
        exp_h = self.avg_pts + self.off[h] - self.dfn[a] + home * self.p.hfa_pts / 2
        exp_a = self.avg_pts + self.off[a] - self.dfn[h] - home * self.p.hfa_pts / 2
        err_h, err_a = hs - exp_h, as_ - exp_a
        k = self.p.pts_k
        self.off[h] += k * err_h
        self.dfn[a] -= k * err_h
        self.off[a] += k * err_a
        self.dfn[h] -= k * err_a
        self.avg_pts += 0.01 * ((hs + as_) / 2 - self.avg_pts)

        self.games_processed += 1
        return pred

    def rankings(self, teams: set[str] | None = None) -> list[dict]:
        rows = [
            {
                "team": t,
                "elo": round(e),
                "off": round(self.off[t], 1),
                "def": round(self.dfn[t], 1),
                "pts_vs_avg": round((e - self.p.mean_elo) / self.p.elo_per_point, 1),
            }
            for t, e in self.elo.items()
            if teams is None or t in teams
        ]
        return sorted(rows, key=lambda r: r["elo"], reverse=True)


def build_engine(league: str, games: list[dict]) -> RatingEngine:
    """Replay every completed game in order to get current ratings."""
    eng = RatingEngine(PARAMS[league])
    for g in games:
        if g["home_score"] is not None and g["away_score"] is not None:
            eng.update(g)
    return eng
