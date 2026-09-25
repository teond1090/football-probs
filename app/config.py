import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """Minimal .env loader so we don't need python-dotenv."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()

# Where the SQLite database and tuned parameters live. Hosts with a persistent disk
# (e.g. Render) point this at the mounted disk.
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
DB_PATH = DATA_DIR / "football.db"

# https://the-odds-api.com  (free tier: 500 requests/month) - live sportsbook lines
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
# https://collegefootballdata.com/key  (free) - college schedules, scores, historical lines
CFBD_API_KEY = os.getenv("CFBD_API_KEY", "")

# How long to reuse a live-odds response before spending another API request.
ODDS_CACHE_MINUTES = int(os.getenv("ODDS_CACHE_MINUTES", "15"))
# Sportsbook regions to shop (us = major US books; add us2 for more books, e.g. "us,us2").
# Each extra region multiplies the API credits a refresh costs.
ODDS_REGIONS = os.getenv("ODDS_REGIONS", "us")
# Specific books to pull instead of whole regions. Every 10 books cost the same as one region,
# so this gets Pinnacle (the sharp price) plus the main US books for 3 credits a refresh.
# Set to empty to use ODDS_REGIONS instead.
ODDS_BOOKMAKERS = os.getenv(
    "ODDS_BOOKMAKERS",
    "pinnacle,lowvig,betonlineag,draftkings,fanduel,betmgm,williamhill_us,betrivers,espnbet,fanatics",
)
# While the server runs, re-download schedules/scores/lines once they are older than this
# (checked on start and hourly). 0 = never.
AUTO_REFRESH_HOURS = float(os.getenv("AUTO_REFRESH_HOURS", "12"))
# Public-site guards so visitors can't burn through API quotas:
# minimum minutes between data refreshes, and between forced live-odds refreshes.
REFRESH_COOLDOWN_MINUTES = float(os.getenv("REFRESH_COOLDOWN_MINUTES", "10"))
ODDS_FORCE_COOLDOWN_MINUTES = float(os.getenv("ODDS_FORCE_COOLDOWN_MINUTES", "5"))


def current_season(today: date | None = None) -> int:
    """Football seasons start in late summer; Jan/Feb games belong to the prior season."""
    today = today or date.today()
    return today.year if today.month >= 8 else today.year - 1
