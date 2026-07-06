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

CREATE TABLE IF NOT EXISTS no_data_dates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    etf_id INTEGER NOT NULL REFERENCES etfs(id),
    date DATE NOT NULL,
    UNIQUE(etf_id, date)
);

CREATE TABLE IF NOT EXISTS daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    etf_id INTEGER NOT NULL REFERENCES etfs(id),
    date DATE NOT NULL,
    report_text TEXT NOT NULL,
    UNIQUE(etf_id, date)
);

CREATE TABLE IF NOT EXISTS user_preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS etf_returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    etf_id INTEGER NOT NULL REFERENCES etfs(id),
    date DATE NOT NULL,
    close_price REAL NOT NULL,
    daily_return_pct REAL,
    UNIQUE(etf_id, date)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_etf_date ON snapshots(etf_id, date);
CREATE INDEX IF NOT EXISTS idx_holdings_snapshot ON holdings(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_no_data_etf_date ON no_data_dates(etf_id, date);
CREATE INDEX IF NOT EXISTS idx_daily_reports_etf_date ON daily_reports(etf_id, date);
CREATE INDEX IF NOT EXISTS idx_etf_returns_etf_date ON etf_returns(etf_id, date DESC);
"""

# (id, name, ticker, url, backfill_from, yf_ticker, benchmark)
DEFAULT_ETFS = [
    (1, "TIME 글로벌AI인공지능액티브", "456600", "https://timeetf.co.kr/m11_view.php?idx=6", "2023-05-16", "456600.KS", 0),
    (2, "TIME 미국나스닥100액티브", "426030", "https://timeetf.co.kr/m11_view.php?idx=2", "2022-05-11", "426030.KS", 0),
    (3, "TIME 코스피액티브", "385720", "https://timeetf.co.kr/m11_view.php?idx=11", "2021-05-25", "385720.KS", 0),
    (4, "iShares A.I. Innovation and Tech Active ETF", "BAI",
     "https://www.ishares.com/us/products/339081/ishares-a-i-innovation-and-tech-active-etf/1467271812596.ajax?tab=holdings&fileType=csv",
     "2024-10-21", "BAI", 0),
    (5, "Roundhill Generative AI & Technology ETF", "CHAT",
     "roundhill://CHAT", "2023-05-18", "CHAT", 0),
    (6, "WisdomTree AI & Innovation Fund", "WTAI",
     "wisdomtree://WTAI", "2026-05-28", "WTAI", 0),
    (7, "Vanguard S&P 500 ETF", "VOO",
     "yfinance://VOO", "2026-05-28", "VOO", 1),
    (8, "Invesco QQQ Trust", "QQQ",
     "yfinance://QQQ", "2026-05-28", "QQQ", 1),
    (9, "iShares Semiconductor ETF", "SOXX",
     "yfinance://SOXX", "2025-01-02", "SOXX", 1),
    (10, "VistaShares Artificial Intelligence Supercycle ETF", "AIS",
     "vistashares://AIS", "2026-06-22", "AIS", 0),
    (11, "LG QRAFT AI-Powered U.S. Large Cap Core ETF", "LQAI",
     "qraft://LQAI", "2026-07-04", "LQAI", 0),
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
        # Migrations
        for col, default in [
            ("backfill_from", "'2023-05-16'"),
            ("yf_ticker", "NULL"),
            ("benchmark", "0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE etfs ADD COLUMN {col} DATE DEFAULT {default}")
            except Exception:
                pass
        for etf_id, name, ticker, url, backfill_from, yf_ticker, benchmark in DEFAULT_ETFS:
            conn.execute(
                """INSERT INTO etfs (id, name, ticker, url, backfill_from, yf_ticker, benchmark)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       name = excluded.name, ticker = excluded.ticker,
                       url = excluded.url, backfill_from = excluded.backfill_from,
                       yf_ticker = excluded.yf_ticker, benchmark = excluded.benchmark""",
                (etf_id, name, ticker, url, backfill_from, yf_ticker, benchmark),
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
        # ON CONFLICT DO UPDATE avoids deleting the existing row (which would cascade-fail on holdings FK)
        conn.execute(
            """INSERT INTO snapshots (etf_id, date, aum_100m) VALUES (?, ?, ?)
               ON CONFLICT(etf_id, date) DO UPDATE SET aum_100m = excluded.aum_100m""",
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


def save_no_data_date(etf_id: int, date: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO no_data_dates (etf_id, date) VALUES (?, ?)",
            (etf_id, date),
        )


def save_daily_report(etf_id: int, date: str, text: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_reports (etf_id, date, report_text) VALUES (?, ?, ?)",
            (etf_id, date, text),
        )


def get_latest_daily_report(etf_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM daily_reports WHERE etf_id = ? ORDER BY date DESC LIMIT 1",
            (etf_id,),
        ).fetchone()


def save_preference(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_preferences (key, value) VALUES (?, ?)",
            (key, value),
        )


def get_preference(key: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM user_preferences WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def get_known_dates(etf_id: int) -> set:
    """Returns all dates that have been checked: either have a snapshot or confirmed no data."""
    with get_conn() as conn:
        snap_dates = {r["date"] for r in conn.execute(
            "SELECT date FROM snapshots WHERE etf_id = ?", (etf_id,)
        ).fetchall()}
        no_data = {r["date"] for r in conn.execute(
            "SELECT date FROM no_data_dates WHERE etf_id = ?", (etf_id,)
        ).fetchall()}
    return snap_dates | no_data


# ── Returns ──────────────────────────────────────────────────────────────────

def save_returns(etf_id: int, returns_list: list[dict]):
    with get_conn() as conn:
        for r in returns_list:
            conn.execute(
                """INSERT INTO etf_returns (etf_id, date, close_price, daily_return_pct)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(etf_id, date) DO UPDATE SET
                       close_price = excluded.close_price,
                       daily_return_pct = excluded.daily_return_pct""",
                (etf_id, r["date"], r["close_price"], r["daily_return_pct"]),
            )


def get_returns(etf_id: int, days: int = 30) -> list:
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM etf_returns
               WHERE etf_id = ? ORDER BY date DESC LIMIT ?""",
            (etf_id, days),
        ).fetchall()


def get_latest_return(etf_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM etf_returns WHERE etf_id = ? ORDER BY date DESC LIMIT 1",
            (etf_id,),
        ).fetchone()


def get_returns_range(etf_id: int, start_date: str, end_date: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM etf_returns
               WHERE etf_id = ? AND date BETWEEN ? AND ?
               ORDER BY date""",
            (etf_id, start_date, end_date),
        ).fetchall()


def get_latest_snapshot_date(etf_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT date FROM snapshots WHERE etf_id = ? ORDER BY date DESC LIMIT 1",
            (etf_id,),
        ).fetchone()
    return row["date"] if row else None


def delete_no_data_date(etf_id: int, date_str: str):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM no_data_dates WHERE etf_id = ? AND date = ?",
            (etf_id, date_str),
        )
