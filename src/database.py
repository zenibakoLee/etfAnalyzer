import os
import sqlite3
from contextlib import contextmanager
from src.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS etfs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    ticker TEXT,
    url TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    added_at DATE DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    etf_id INTEGER NOT NULL REFERENCES etfs(id),
    date DATE NOT NULL,
    aum_100m REAL,
    UNIQUE(etf_id, date)
);

CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    ticker_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    valuation_krw BIGINT NOT NULL,
    weight_pct REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    etf_id INTEGER NOT NULL REFERENCES etfs(id),
    date DATE NOT NULL,
    insight_text TEXT NOT NULL,
    UNIQUE(etf_id, date)
);

CREATE TABLE IF NOT EXISTS market_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL UNIQUE,
    headline_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_snapshots_etf_date ON snapshots(etf_id, date);
CREATE INDEX IF NOT EXISTS idx_holdings_snapshot ON holdings(snapshot_id);
"""

DEFAULT_ETFS = [
    (1, "TIME 글로벌AI인공지능액티브", "456600", "https://timeetf.co.kr/m11_view.php?idx=6"),
]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for etf_id, name, ticker, url in DEFAULT_ETFS:
            conn.execute(
                "INSERT OR IGNORE INTO etfs (id, name, ticker, url) VALUES (?, ?, ?, ?)",
                (etf_id, name, ticker, url),
            )


def get_all_etfs():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM etfs WHERE active = 1 ORDER BY id").fetchall()


def get_snapshot(etf_id: int, date: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM snapshots WHERE etf_id = ? AND date = ?",
            (etf_id, date),
        ).fetchone()


def get_prev_snapshot(etf_id: int, before_date: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM snapshots WHERE etf_id = ? AND date < ? ORDER BY date DESC LIMIT 1",
            (etf_id, before_date),
        ).fetchone()


def save_snapshot(etf_id: int, date: str, aum_100m, holdings_list: list):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO snapshots (etf_id, date, aum_100m) VALUES (?, ?, ?)",
            (etf_id, date, aum_100m),
        )
        snap = conn.execute(
            "SELECT id FROM snapshots WHERE etf_id = ? AND date = ?",
            (etf_id, date),
        ).fetchone()
        snapshot_id = snap["id"]
        conn.execute("DELETE FROM holdings WHERE snapshot_id = ?", (snapshot_id,))
        conn.executemany(
            """INSERT INTO holdings
               (snapshot_id, ticker_code, stock_name, quantity, valuation_krw, weight_pct)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    snapshot_id,
                    h["ticker_code"],
                    h["stock_name"],
                    h["quantity"],
                    h["valuation_krw"],
                    h["weight_pct"],
                )
                for h in holdings_list
            ],
        )


def get_holdings(snapshot_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM holdings WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchall()


def get_all_snapshots(etf_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM snapshots WHERE etf_id = ? ORDER BY date",
            (etf_id,),
        ).fetchall()


def save_insight(etf_id: int, date: str, text: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO insights (etf_id, date, insight_text) VALUES (?, ?, ?)",
            (etf_id, date, text),
        )


def get_latest_insight(etf_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM insights WHERE etf_id = ? ORDER BY date DESC LIMIT 1",
            (etf_id,),
        ).fetchone()


def save_market_insight(date: str, text: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO market_insights (date, headline_text) VALUES (?, ?)",
            (date, text),
        )


def get_latest_market_insight():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM market_insights ORDER BY date DESC LIMIT 1"
        ).fetchone()
