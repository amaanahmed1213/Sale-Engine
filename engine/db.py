"""SQLite price history. One row per product per day it was seen."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    uid TEXT PRIMARY KEY, source TEXT, brand TEXT, title TEXT, url TEXT, image TEXT,
    first_seen TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS prices (
    uid TEXT, day TEXT, price REAL, original REAL,
    PRIMARY KEY (uid, day)
);
CREATE TABLE IF NOT EXISTS watchlist (
    url TEXT PRIMARY KEY, target REAL, note TEXT, added TEXT
);
CREATE TABLE IF NOT EXISTS codes (
    brand TEXT, code TEXT, pct INTEGER, confidence INTEGER, sources TEXT, url TEXT,
    newest TEXT, first_found TEXT, PRIMARY KEY (brand, code)
);
CREATE TABLE IF NOT EXISTS alerted (
    uid TEXT, price REAL, day TEXT, PRIMARY KEY (uid, price)
);
"""


class DB:
    def __init__(self, path: str | Path = "prices.db"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # ── history ──────────────────────────────────────────────
    def record(self, item: Listing, day: str | None = None) -> None:
        day = day or date.today().isoformat()
        self.conn.execute(
            """INSERT INTO products VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(uid) DO UPDATE SET last_seen=excluded.last_seen,
               title=excluded.title, image=excluded.image""",
            (item.uid, item.source, item.brand_key or item.brand, item.title, item.url,
             item.image, day, day),
        )
        # keep the lowest price seen that day
        self.conn.execute(
            """INSERT INTO prices VALUES (?,?,?,?)
               ON CONFLICT(uid, day) DO UPDATE SET price=MIN(price, excluded.price),
               original=COALESCE(excluded.original, original)""",
            (item.uid, day, item.price, item.original),
        )
        self.conn.commit()

    def history(self, uid: str, days: int = 120) -> list[sqlite3.Row]:
        since = (date.today() - timedelta(days=days)).isoformat()
        return self.conn.execute(
            "SELECT day, price, original FROM prices WHERE uid=? AND day>=? ORDER BY day",
            (uid, since),
        ).fetchall()

    def stats(self, uid: str, days: int = 120) -> dict:
        rows = self.history(uid, days)
        # exclude today so "is this the lowest ever" compares against the past
        past = [r["price"] for r in rows if r["day"] != date.today().isoformat()]
        return {
            "n_days": len(rows),
            "low": min(past) if past else None,
            "high": max(past) if past else None,
            "median": sorted(past)[len(past) // 2] if past else None,
        }

    # ── watchlist ────────────────────────────────────────────
    def watch(self, url: str, target: float, note: str = "") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO watchlist VALUES (?,?,?,?)",
            (url, target, note, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def unwatch(self, url: str) -> None:
        self.conn.execute("DELETE FROM watchlist WHERE url=?", (url,))
        self.conn.commit()

    def watchlist(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM watchlist ORDER BY added").fetchall()

    # ── discount codes ───────────────────────────────────────
    def save_codes(self, ranked: list[dict]) -> list[dict]:
        """Upsert codes; returns the ones we've never seen before."""
        new = []
        today = date.today().isoformat()
        for c in ranked:
            exists = self.conn.execute("SELECT 1 FROM codes WHERE brand=? AND code=?",
                                       (c["brand"], c["code"])).fetchone()
            if not exists:
                new.append(c)
            self.conn.execute(
                """INSERT INTO codes VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(brand, code) DO UPDATE SET pct=COALESCE(excluded.pct, pct),
                   confidence=excluded.confidence, sources=excluded.sources, url=excluded.url,
                   newest=excluded.newest""",
                (c["brand"], c["code"], c["pct"], c["confidence"], ", ".join(c["sources"]),
                 c["urls"][0], c["newest"].date().isoformat(), today))
        self.conn.commit()
        return new

    def best_codes(self, min_conf: int = 40, max_age: int = 21) -> dict[str, dict]:
        """Best live code per brand (highest % among confident, recent ones)."""
        since = (date.today() - timedelta(days=max_age)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM codes WHERE confidence>=? AND newest>=? ORDER BY COALESCE(pct,0) DESC, confidence DESC",
            (min_conf, since)).fetchall()
        best = {}
        for r in rows:
            best.setdefault(r["brand"], dict(r))
        return best

    # ── alert de-dupe (don't ping twice for the same price) ──
    def already_alerted(self, uid: str, price: float) -> bool:
        return bool(self.conn.execute(
            "SELECT 1 FROM alerted WHERE uid=? AND price<=?", (uid, price)).fetchone())

    def mark_alerted(self, uid: str, price: float) -> None:
        self.conn.execute("INSERT OR IGNORE INTO alerted VALUES (?,?,?)",
                          (uid, price, date.today().isoformat()))
        self.conn.commit()
