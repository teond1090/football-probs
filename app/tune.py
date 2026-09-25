"""Parameter tuning by coordinate descent.

Fits on older seasons ("train") and reports accuracy on recent seasons the tuner never saw
("test"), so improvements are real rather than overfit. Objective: mean absolute error of
the projected margin (Elo params) and projected total (points params).
"""
import math
from dataclasses import replace

from .models.ratings import LeagueParams, RatingEngine, is_completed

MARGIN_GRID = {
    "k": [12, 16, 20, 24, 28, 32],
    "hfa_elo": [20, 30, 40, 50, 60, 70, 80],
    "regress": [0.15, 0.25, 1 / 3, 0.4, 0.5, 0.6],
    "qb_penalty": [0, 1, 2, 3, 4, 5, 6],
    "rest_pts": [0, 0.1, 0.2, 0.3, 0.4, 0.5],
}
TOTAL_GRID = {
    "pts_k": [0.02, 0.04, 0.06, 0.08, 0.1, 0.12],
    "pts_regress": [0.15, 0.25, 0.35, 0.45, 0.6],
}


def evaluate(games: list[dict], p: LeagueParams, lo: int, hi: int) -> dict:
    eng = RatingEngine(p)
    m_err, t_err, m_res, t_res, mk_m, mk_t = [], [], [], [], [], []
    for g in games:
        if not is_completed(g):
            continue
        if g["season"] > hi:
            break
        pred = eng.update(g)
        if g["season"] < lo:
            continue
        margin = g["home_score"] - g["away_score"]
        total = g["home_score"] + g["away_score"]
        m_res.append(margin - pred.home_margin)
        t_res.append(total - pred.total)
        m_err.append(abs(m_res[-1]))
        t_err.append(abs(t_res[-1]))
        if g["home_spread"] is not None:
            mk_m.append(abs(margin + g["home_spread"]))
        if g["total_line"] is not None:
            mk_t.append(abs(total - g["total_line"]))

    def mean(xs):
        return sum(xs) / len(xs) if xs else float("nan")

    def sd(xs):
        m = mean(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / max(len(xs) - 1, 1))

    return {
        "margin_mae": mean(m_err), "total_mae": mean(t_err),
        "market_margin_mae": mean(mk_m), "market_total_mae": mean(mk_t),
        "margin_sd": sd(m_res), "total_sd": sd(t_res), "games": len(m_err),
    }


def tune(games: list[dict], base: LeagueParams, train: tuple[int, int], passes: int = 2,
         log=print) -> LeagueParams:
    p = base
    for grid, metric in ((MARGIN_GRID, "margin_mae"), (TOTAL_GRID, "total_mae")):
        best = evaluate(games, p, *train)[metric]
        for n in range(passes):
            improved = False
            for name, values in grid.items():
                for v in values:
                    if v == getattr(p, name):
                        continue
                    trial = replace(p, **{name: v})
                    score = evaluate(games, trial, *train)[metric]
                    if score < best - 1e-4:
                        best, p, improved = score, trial, True
            log(f"  pass {n + 1} {metric}: {best:.4f}  ({', '.join(f'{k}={getattr(p, k):g}' for k in grid)})")
            if not improved:
                break
    fit = evaluate(games, p, *train)
    return replace(p, margin_sd=round(fit["margin_sd"], 2), total_sd=round(fit["total_sd"], 2))
