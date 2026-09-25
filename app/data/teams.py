"""Team-name matching between data sources (The Odds API uses full names)."""

NFL_FULL_NAMES = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}

# Relocated franchises keep one continuous rating history.
NFL_LEGACY_CODES = {"OAK": "LV", "SD": "LAC", "STL": "LA"}


def nfl_code(code: str) -> str:
    return NFL_LEGACY_CODES.get(code, code)


def match_team(league: str, odds_api_name: str, known: set[str]) -> str | None:
    if league == "nfl":
        return NFL_FULL_NAMES.get(odds_api_name)
    # College: Odds API says "Texas A&M Aggies", CFBD says "Texas A&M".
    # Take the longest known school name that prefixes the full name.
    if odds_api_name in known:
        return odds_api_name
    candidates = [t for t in known if odds_api_name.startswith(t + " ")]
    return max(candidates, key=len) if candidates else None
