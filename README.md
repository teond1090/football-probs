# Football Probabilities

NFL + college football win/cover/total probabilities, compared against live sportsbook prices
to flag positive-expected-value bets. Includes a walk-forward backtester and a bet tracker.

> **Reality check:** sportsbooks are good at this. At -110 you need a 52.4% hit rate just to break
> even. Use the backtest and the bet tracker to prove an edge exists before staking real money,
> and only bet what you can afford to lose.

## Setup

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # then add your API keys
```

| Key | Needed for | Get it |
| --- | --- | --- |
| `ODDS_API_KEY` | Live sportsbook lines (value bets) | https://the-odds-api.com (free: 500 req/mo) |
| `CFBD_API_KEY` | College data | https://collegefootballdata.com/key (free) |

NFL history comes from [nflverse](https://github.com/nflverse/nfldata) and needs no key.

## Usage

```bash
.venv\Scripts\python cli.py refresh nfl          # download 1999-present games + closing lines
.venv\Scripts\python cli.py refresh cfb          # first run: last ~10 seasons
.venv\Scripts\python cli.py serve                # dashboard at http://localhost:8000
```

CLI extras: `backtest nfl --start 2010 --min-ev 0.03`, `board nfl`, `ratings cfb --top 25`.
Run tests with `.venv\Scripts\python -m unittest`.

## How it works

1. **Ratings** (`app/models/ratings.py`) - replays every game in date order.
   - Elo with margin-of-victory adjustment and home-field advantage gives a **projected margin**.
   - Offense/defense points ratings give a **projected total**.
   - Ratings regress toward average each offseason.
2. **Probabilities** - actual results are roughly normal around the projections
   (NFL SD ~13.5 pts margin / ~13.7 total), which converts projections into P(win),
   P(cover at any spread) and P(over at any total).
3. **Value finder** (`app/edges.py`) - for every book's moneyline, spread and total:
   removes the vig to get the market's probability, takes the best available price (line
   shopping), and computes EV and a fractional-Kelly stake. Edges of 10%+ get a "check news"
   flag, because a gap that large usually means the model is missing an injury or QB change.
4. **Backtest** (`app/backtest.py`) - bets history against closing lines using only
   information available before each game. Also compares model and market accuracy directly.

## Baseline results (NFL, 2006-2025, bet when EV >= 2%)

| Market | Win % | ROI |
| --- | --- | --- |
| Spread | 51.0% | ~0% |
| Total | 49.8% | -2.9% |
| Moneyline | - | -2.9% |

The closing line is still more accurate than this model (margin MAE 10.25 vs 10.54).
**This is the baseline to beat.** Don't bet real money until the backtest is clearly positive.

## Roadmap

Ideas most likely to improve accuracy, roughly in order:

- [ ] **QB adjustment** - starting QB changes are the biggest thing Elo misses (nflverse has QB data).
- [ ] **Blend with the market** - start from the opening line and adjust, instead of predicting from scratch.
- [ ] **Preseason priors** - use last season's ratings + recruiting/returning production (CFBD) instead of flat regression.
- [ ] **Rest / travel / weather / dome** features.
- [ ] **Tune parameters** (K, HFA, regression) by minimizing backtest error.
- [ ] **Closing line value (CLV)** tracking - record the closing line for tracked bets; beating the close is the best early signal of a real edge.
- [ ] **Player props** (phase 2) - player usage/efficiency projections from nflverse play-by-play + Odds API player markets.
- [ ] **Scheduled refresh** of data and odds.
