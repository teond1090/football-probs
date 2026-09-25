"""Betting math: odds conversions, vig removal, expected value, Kelly sizing."""
import math


def american_to_decimal(odds: float) -> float:
    return 1 + odds / 100 if odds > 0 else 1 + 100 / abs(odds)


def implied_prob(odds: float) -> float:
    """Break-even probability for a price, vig included."""
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def prob_to_american(p: float) -> int:
    """Fair (no-vig) American price for a probability."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    if p > 0.5:
        return round(-100 * p / (1 - p))
    return round(100 * (1 - p) / p)


def devig(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Remove the book's margin from a two-way market (multiplicative method)."""
    a, b = implied_prob(odds_a), implied_prob(odds_b)
    total = a + b
    return a / total, b / total


def expected_value(p: float, odds: float) -> float:
    """Expected profit per 1 unit staked. 0.05 = +5% EV."""
    return p * (american_to_decimal(odds) - 1) - (1 - p)


def kelly_fraction(p: float, odds: float, fraction: float = 0.25) -> float:
    """Share of bankroll to stake. Defaults to quarter-Kelly because model probabilities are noisy."""
    b = american_to_decimal(odds) - 1
    full = (b * p - (1 - p)) / b
    return max(0.0, full) * fraction


def profit(stake: float, odds: float, result: str) -> float:
    if result == "win":
        return stake * (american_to_decimal(odds) - 1)
    if result == "loss":
        return -stake
    return 0.0


def normal_cdf(x: float, mu: float = 0.0, sd: float = 1.0) -> float:
    return 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))


# --- Converting a projected margin / total into bet probabilities ------------------------------
# Football outcomes are roughly normal around the projection. The standard deviations live in
# the league params and can be checked against real residuals with the backtest.

def win_prob(home_margin: float, sd: float) -> float:
    return 1 - normal_cdf(0, home_margin, sd)


def cover_prob(home_margin: float, home_spread: float, sd: float) -> float:
    """P(home covers). Home covers when margin + home_spread > 0 (e.g. -3.5 needs a 4+ pt win)."""
    return 1 - normal_cdf(-home_spread, home_margin, sd)


def over_prob(total: float, line: float, sd: float) -> float:
    return 1 - normal_cdf(line, total, sd)
