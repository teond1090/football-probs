# Football Probabilities

[![tests](https://github.com/teond1090/football-probs/actions/workflows/tests.yml/badge.svg)](https://github.com/teond1090/football-probs/actions/workflows/tests.yml)

NFL and college football win, spread and total probabilities: a weekly picks page with
confidence tiers, live sportsbook comparisons to flag positive-EV bets, a matchup calculator,
team rating histories, a walk-forward backtester and a bet tracker.

> **Reality check:** sportsbooks are very good at this. At -110 you need a 52.4% hit rate just to
> break even, and this model's spread picks have historically landed around 51-53%. The app shows
> every pick type's real track record right next to the picks, so you can judge for yourself.
> This is for entertainment and research. Bet only what you can afford to lose.
> Problem gambling help: **1-800-GAMBLER**.

## Features

| Tab | What it does |
| --- | --- |
| **Weekly picks** | Every game of the week: projected score, straight-up winner, spread pick, total pick and moneyline value, with a confidence tier (Best / Lean / Check news / Pass). Past weeks are auto-graded, and each tier's all-time and last-5-season record is shown at the top. CSV export. |
| **Live odds** | Pulls every US sportsbook's lines, finds the best price for each bet, and flags bets whose expected value clears your threshold, with fractional-Kelly stake sizing. |
| **Ratings** | Power rankings with offense/defense ratings and current starting QB. Click a team for its rating-history chart, recent results against the spread, and upcoming games. |
| **Matchup** | Project any hypothetical game (home or neutral site) with fair spread/total/moneyline and alternate-line tables. Includes an odds calculator (break-even %, EV, Kelly) and a vig remover. |
| **Backtest** | Replays history game by game against closing lines: ROI by market and season, model vs. market accuracy, and win-probability calibration. |
| **My bets** | Log bets from the picks or odds pages, settle them, and track profit, ROI and a cumulative profit chart. |

## Setup

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt     # macOS/Linux: .venv/bin/python
copy .env.example .env                                      # optional: add API keys
.venv\Scripts\python cli.py refresh nfl
.venv\Scripts\python cli.py serve                           # http://localhost:8000
```

NFL data comes from [nflverse](https://github.com/nflverse/nfldata) and needs no key: schedules,
scores, closing lines, starting QBs and rest days back to 1999. Weekly picks work out of the box.

| Optional key | Unlocks | Get it (free) |
| --- | --- | --- |
| `ODDS_API_KEY` | Live odds tab (line shopping across books) | https://the-odds-api.com |
| `CFBD_API_KEY` | College football | https://collegefootballdata.com/key |

Data refreshes automatically when the server starts if it's older than 12 hours
(`AUTO_REFRESH_HOURS`, 0 disables).

On Windows you can also just double-click **`start.bat`**.

### Deploy a 24/7 public site (Render)

1. Sign in at https://render.com with GitHub.
2. **New + → Blueprint**, pick this repo. Render reads [`render.yaml`](render.yaml): an always-on web
   service plus a 1 GB disk so tracked bets and data survive restarts.
3. Paste your `ODDS_API_KEY` / `CFBD_API_KEY` when asked (optional), then **Apply**.
4. Your site is live at `https://<service-name>.onrender.com`. Every push to `master` redeploys it.

The site refreshes its data every 6 hours. Public-facing refresh buttons have cooldowns so
visitors can't burn through API quotas.

### Command line

```bash
python cli.py picks nfl                   # this week's picks in the terminal
python cli.py board nfl                   # live odds + value bets
python cli.py ratings cfb --top 25
python cli.py backtest nfl --start 2010 --min-ev 0.03
python cli.py tune nfl --save             # re-fit model parameters to the latest data
python -m unittest                        # tests
```

## How the model works

1. **Ratings** (`app/models/ratings.py`) replay every game in date order.
   - **Elo** with a margin-of-victory multiplier and home-field advantage gives a projected **margin**.
   - **Offense/defense points ratings** give a projected **total**.
   - Ratings regress toward average each offseason.
2. **Situational adjustments** (NFL):
   - **Backup QB:** if a team's regular starter this season isn't starting, it loses points.
   - **Rest:** a team with more days off gets points per extra day (bye weeks, Thursday games).
3. **Probabilities:** actual results are roughly normal around the projection (NFL SD is about
   13.6 points), which turns projections into P(win), P(cover) at any spread, and P(over) at any total.
4. **Tuning** (`app/tune.py`) fits the parameters on older seasons and checks them on recent seasons
   the tuner never saw.
5. **Pick tiers** (`app/picks.py`) are based on how far the model's number is from the market's:

   | Tier | Spread | Total | Why |
   | --- | --- | --- | --- |
   | Best | 3-6 pts off | - | The range where the model has historically done best |
   | Lean | 2-3 pts | 3-6 pts | Mild disagreement |
   | Check news | 6+ pts | 6+ pts | Huge gaps usually mean the model is missing news (injury, QB change) |
   | Pass | < 2 pts | < 3 pts | Model agrees with the line |

   Every week's picks use only ratings from before that week's first kickoff, so historical records are honest.

## Current results (NFL, graded against closing lines)

| Pick type | 2002-2025 | 2021-2025 |
| --- | --- | --- |
| Winner (straight up) | 64.9% | 64.2% |
| Spread, Best tier | 51.8% | 51.6% |
| Spread, Lean tier | 52.7% | 47.7% |
| Totals, Lean tier | 50.2% | 49.0% |

Closing lines are still slightly more accurate than the model (2021-2025 average margin error 10.15
points vs. the market's 9.76). **Don't treat any tier as a money-maker until its live record says so.**

## Roadmap

- [ ] Opening-line data: bet early, before lines move toward the closing number
- [ ] Closing line value (CLV) tracking for logged bets, the best early sign of a real edge
- [ ] Injury feed beyond QBs (key skill players, offensive line)
- [ ] Preseason priors from roster continuity and recruiting (college)
- [ ] Player props from nflverse play-by-play
- [ ] Scheduled odds snapshots + alerts when a value bet appears

## License

MIT. See [LICENSE](LICENSE).
