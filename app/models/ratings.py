"""Team rating model.

Two ratings are tracked per team and updated after every game, in date order:

* Elo (with margin-of-victory multiplier, FiveThirtyEight-style) -> projected point margin,
  used for moneyline and spread probabilities.
* Offense / defense points ratings (points above/below league average) -> projected total,
  used for over/under probabilities.

On top of the ratings, each game gets situational adjustments (when the data has them):

* Backup quarterback: the team's regular starter this season isn't starting.
* Rest: difference in days since each team's last game (bye weeks, Thursday games).

Ratings regress toward each team's baseline at the start of every season.
"""
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field, fields, replace

from .. import odds_math
from ..config import DATA_DIR


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
    qb_penalty: float = 0.0         # points lost when a backup QB starts
    rest_pts: float = 0.0           # points per day of rest advantage
    rest_cap: int = 7               # max rest difference that counts (days)

    @property
    def hfa_pts(self) -> float:
        return self.hfa_elo / self.elo_per_point


# Defaults below were chosen with `python cli.py tune <league>` (fit on older seasons,
# checked on recent ones). Re-tuning writes data/params_<league>.json, which overrides these.
NFL = LeagueParams(
    "nfl", k=20, hfa_elo=50, regress=0.5, margin_sd=13.6, total_sd=13.7,
    init_avg_pts=21.0, pts_k=0.04, pts_regress=0.35, qb_penalty=2.0, rest_pts=0.2,
)
CFB = LeagueParams(
    "cfb", k=25, hfa_elo=65, regress=0.35, margin_sd=16.5, total_sd=16.0,
    init_avg_pts=27.0, pts_k=0.08, pts_regress=0.35,
    lower_div_elo=1150, lower_div_pts=-8.0,
)
DEFAULTS = {"nfl": NFL, "cfb": CFB}
TUNABLE = {f.name for f in fields(LeagueParams)} - {"name", "mean_elo", "elo_per_point"}


def params_path(league: str):
    return DATA_DIR / f"params_{league}.json"


def load_params(league: str) -> LeagueParams:
    base = DEFAULTS[league]
    path = params_path(league)
    if path.exists():
        overrides = {k: v for k, v in json.loads(path.read_text()).items() if k in TUNABLE}
        return replace(base, **overrides)
    return base


def save_params(p: LeagueParams) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in asdict(p).items() if k in TUNABLE}
    params_path(p.name).write_text(json.dumps(data, indent=2))


class _Params(dict):
    """PARAMS[league] always reflects the latest tuned values."""
    def __getitem__(self, league):
        return load_params(league)


PARAMS = _Params(DEFAULTS)


@dataclass
class Prediction:
    home_margin: float   # projected home points minus away points
    total: float         # projected combined points
    home_elo: float
    away_elo: float
    margin_sd: float
    total_sd: float
    notes: list = field(default_factory=list)   # situational adjustments applied

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
            "notes": self.notes,
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
    starters: dict = field(default_factory=dict)   # team -> recent starting QBs this season
    history: dict = field(default_factory=dict)    # team -> [(date, elo)] after each game
    avg_pts: float = 0.0
    season: int | None = None
    games_processed: int = 0
    track_history: bool = False

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
            self.starters.clear()
        if self.season is None or season > self.season:
            self.season = season

    def _hfa(self, g: dict) -> float:
        return 0.0 if g.get("neutral") else 1.0

    def regular_starter(self, team: str) -> str | None:
        """Most common starter over the team's last 4 games this season (needs 2+ starts)."""
        recent = self.starters.get(team, [])[-4:]
        if len(recent) < 2:
            return None
        counts = Counter(recent)
        top = max(counts.values())
        # ties go to whoever started most recently
        return next(qb for qb in reversed(recent) if counts[qb] == top)

    def _adjustments(self, g: dict) -> tuple[float, float, float, list[str]]:
        """Returns (home margin adj, home points adj, away points adj, notes)."""
        margin_adj, home_pts_adj, away_pts_adj, notes = 0.0, 0.0, 0.0, []
        if self.p.qb_penalty:
            for side, sign in (("home", 1), ("away", -1)):
                qb, team = g.get(f"{side}_qb"), g[side]
                regular = self.regular_starter(team)
                if qb and regular and qb != regular:
                    margin_adj -= sign * self.p.qb_penalty
                    if side == "home":
                        home_pts_adj -= self.p.qb_penalty / 2
                    else:
                        away_pts_adj -= self.p.qb_penalty / 2
                    notes.append(f"{team}: {qb} starting instead of {regular} "
                                 f"(-{self.p.qb_penalty:g} pts)")
        hr, ar = g.get("home_rest"), g.get("away_rest")
        if self.p.rest_pts and hr is not None and ar is not None and hr != ar:
            diff = max(-self.p.rest_cap, min(self.p.rest_cap, hr - ar))
            margin_adj += diff * self.p.rest_pts
            rested = g["home"] if diff > 0 else g["away"]
            notes.append(f"{rested} +{abs(diff)} day{'s' if abs(diff) != 1 else ''} rest ({abs(diff) * self.p.rest_pts:+.1f} pts)")
        return margin_adj, home_pts_adj, away_pts_adj, notes

    def _elo_diff(self, g: dict, margin_adj: float) -> float:
        return (self.elo[g["home"]] - self.elo[g["away"]] + self._hfa(g) * self.p.hfa_elo
                + margin_adj * self.p.elo_per_point)

    # -- core ----------------------------------------------------------------------------------
    def predict(self, g: dict) -> Prediction:
        """g needs: home, away, season, neutral; optional home_div/away_div, *_qb, *_rest."""
        self._roll_season(g["season"])
        h, a = g["home"], g["away"]
        self._ensure(h, g.get("home_div"))
        self._ensure(a, g.get("away_div"))
        home = self._hfa(g)
        margin_adj, hp_adj, ap_adj, notes = self._adjustments(g)

        margin = self._elo_diff(g, margin_adj) / self.p.elo_per_point
        home_pts = self.avg_pts + self.off[h] - self.dfn[a] + home * self.p.hfa_pts / 2 + hp_adj
        away_pts = self.avg_pts + self.off[a] - self.dfn[h] - home * self.p.hfa_pts / 2 + ap_adj
        return Prediction(
            home_margin=margin,
            total=max(home_pts + away_pts, 0.0),
            home_elo=self.elo[h],
            away_elo=self.elo[a],
            margin_sd=self.p.margin_sd,
            total_sd=self.p.total_sd,
            notes=notes,
        )

    def update(self, g: dict, pred: Prediction | None = None) -> Prediction:
        """Learn from a completed game. Returns the pre-game prediction."""
        pred = pred or self.predict(g)
        h, a = g["home"], g["away"]
        hs, as_ = g["home_score"], g["away_score"]
        home = self._hfa(g)
        margin_adj, hp_adj, ap_adj, _ = self._adjustments(g)

        # Elo with margin-of-victory multiplier (dampened when the favorite wins big).
        # Situational adjustments are part of the expectation, so a team isn't
        # over-penalized for losing with its backup QB.
        margin = hs - as_
        elo_diff = self._elo_diff(g, margin_adj)
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
        exp_h = self.avg_pts + self.off[h] - self.dfn[a] + home * self.p.hfa_pts / 2 + hp_adj
        exp_a = self.avg_pts + self.off[a] - self.dfn[h] - home * self.p.hfa_pts / 2 + ap_adj
        err_h, err_a = hs - exp_h, as_ - exp_a
        k = self.p.pts_k
        self.off[h] += k * err_h
        self.dfn[a] -= k * err_h
        self.off[a] += k * err_a
        self.dfn[h] -= k * err_a
        self.avg_pts += 0.01 * ((hs + as_) / 2 - self.avg_pts)

        for side in ("home", "away"):
            if g.get(f"{side}_qb"):
                self.starters.setdefault(g[side], []).append(g[f"{side}_qb"])
        if self.track_history:
            day = (g.get("game_date") or "")[:10]
            self.history.setdefault(h, []).append((day, round(self.elo[h])))
            self.history.setdefault(a, []).append((day, round(self.elo[a])))

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
                "qb": self.regular_starter(t) or (self.starters.get(t) or [None])[-1],
            }
            for t, e in self.elo.items()
            if teams is None or t in teams
        ]
        return sorted(rows, key=lambda r: r["elo"], reverse=True)


def is_completed(g: dict) -> bool:
    return g["home_score"] is not None and g["away_score"] is not None


def build_engine(league: str, games: list[dict], params: LeagueParams | None = None,
                 track_history: bool = False) -> RatingEngine:
    """Replay every completed game in order to get current ratings."""
    eng = RatingEngine(params or PARAMS[league], track_history=track_history)
    for g in games:
        if is_completed(g):
            eng.update(g)
    return eng
