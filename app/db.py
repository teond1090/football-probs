import sqlite3
from contextlib import contextmanager

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    league           TEXT NOT NULL,          -- 'nfl' | 'cfb'
    game_id          TEXT NOT NULL,
    season           INTEGER NOT NULL,
    week             INTEGER,
    season_type      TEXT,                   -- 'regular' | 'postseason'
    game_date        TEXT,                   -- ISO date/datetime (UTC for cfb)
    home             TEXT NOT NULL,
    away             TEXT NOT NULL,
    home_score       INTEGER,                -- NULL until played
    away_score       INTEGER,
    neutral          INTEGER DEFAULT 0,
    home_div         TEXT,                   -- cfb classification: fbs / fcs / ii / iii
    away_div         TEXT,
    -- closing-ish market lines (betting convention: home_spread -3.5 = home favored by 3.5)
    home_spread      REAL,
    total_line       REAL,
    home_ml          INTEGER,
    away_ml          INTEGER,
    home_spread_odds INTEGER,
    away_spread_odds INTEGER,
    over_odds        INTEGER,
    under_odds       INTEGER,
    PRIMARY KEY (league, game_id)
);
CREATE INDEX IF NOT EXISTS idx_games_date ON games (league, game_date);

CREATE TABLE IF NOT EXISTS odds_cache (
    league     TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    remaining  TEXT,
    payload    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    league      TEXT NOT NULL,
    game        TEXT NOT NULL,
    market      TEXT NOT NULL,               -- moneyline | spread | total
    selection   TEXT NOT NULL,
    line        REAL,
    price       INTEGER NOT NULL,            -- American odds
    stake       REAL NOT NULL,
    model_prob  REAL,
    book        TEXT,
    result      TEXT NOT NULL DEFAULT 'pending',  -- pending | win | loss | push
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

GAME_COLUMNS = [
    "league", "game_id", "season", "week", "season_type", "game_date", "home", "away",
    "home_score", "away_score", "neutral", "home_div", "away_div", "home_spread",
    "total_line", "home_ml", "away_ml", "home_spread_odds", "away_spread_odds",
    "over_odds", "under_odds",
]


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_games(rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = ", ".join(GAME_COLUMNS)
    placeholders = ", ".join(f":{c}" for c in GAME_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in GAME_COLUMNS[2:])
    sql = (
        f"INSERT INTO games ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT (league, game_id) DO UPDATE SET {updates}"
    )
    normalized = [{c: r.get(c) for c in GAME_COLUMNS} for r in rows]
    with connect() as conn:
        conn.executemany(sql, normalized)
    return len(normalized)


def load_games(league: str) -> list[dict]:
    """All games for a league in chronological order."""
    with connect() as conn:
        cur = conn.execute(
            "SELECT * FROM games WHERE league = ? ORDER BY game_date, game_id", (league,)
        )
        return [dict(r) for r in cur.fetchall()]


def set_meta(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_meta(key: str) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
