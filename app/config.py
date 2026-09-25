import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "football.db"


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

# https://the-odds-api.com  (free tier: 500 requests/month) - live sportsbook lines
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
# https://collegefootballdata.com/key  (free) - college schedules, scores, historical lines
CFBD_API_KEY = os.getenv("CFBD_API_KEY", "")

# How long to reuse a live-odds response before spending another API request.
ODDS_CACHE_MINUTES = int(os.getenv("ODDS_CACHE_MINUTES", "15"))
# Re-download schedules/scores/lines on server start when older than this (0 = never).
AUTO_REFRESH_HOURS = float(os.getenv("AUTO_REFRESH_HOURS", "12"))


def current_season(today: date | None = None) -> int:
    """Football seasons start in late summer; Jan/Feb games belong to the prior season."""
    today = today or date.today()
    return today.year if today.month >= 8 else today.year - 1
