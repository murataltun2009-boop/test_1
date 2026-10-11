"""
SQLite kayit katmani.

Sinyal gecisleri ve her gecisin tam indikator anlik goruntusu burada saklanir.
Arayuzdeki "Veritabanini Sifirla" butonu reset() cagirir.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Any, Optional

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,          -- kayit zamani (ISO, yerel)
    symbol          TEXT    NOT NULL,
    timeframe       TEXT    NOT NULL,
    candle_open_time INTEGER NOT NULL,         -- sinyalin olustugu bar
    signal          TEXT    NOT NULL,          -- GÜÇLÜ AL / AL / ...
    previous_signal TEXT,                      -- onceki sinyal (yoksa NULL)
    composite       REAL    NOT NULL,
    price           REAL    NOT NULL,
    osc_score       REAL    NOT NULL,
    ma_score        REAL    NOT NULL,
    osc_buy         INTEGER NOT NULL,
    osc_sell        INTEGER NOT NULL,
    osc_neutral     INTEGER NOT NULL,
    ma_buy          INTEGER NOT NULL,
    ma_sell         INTEGER NOT NULL,
    ma_neutral      INTEGER NOT NULL,
    details_json    TEXT    NOT NULL           -- tum indikator degerleri
);

CREATE INDEX IF NOT EXISTS ix_tf_time  ON signal_events (timeframe, created_at);
CREATE INDEX IF NOT EXISTS ix_created  ON signal_events (created_at);

CREATE TABLE IF NOT EXISTS app_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    level       TEXT NOT NULL,
    category    TEXT NOT NULL,
    message     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_log_created ON app_log (created_at);
"""

TABLES = ("signal_events", "app_log")


class SignalStore:
    """Thread-safe SQLite sarmalayicisi."""

    def __init__(self, path: str = config.DB_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self.init_schema()

    # ------------------------------------------------------------------
    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------
    def record_signal(self, symbol: str, timeframe: str, candle_open_time: int,
                      signal: str, previous_signal: Optional[str],
                      composite: float, price: float,
                      osc_score: float, ma_score: float,
                      osc_counts: dict, ma_counts: dict,
                      details: list[dict[str, Any]]) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        payload = json.dumps(details, ensure_ascii=False)
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO signal_events (
                    created_at, symbol, timeframe, candle_open_time,
                    signal, previous_signal, composite, price,
                    osc_score, ma_score,
                    osc_buy, osc_sell, osc_neutral,
                    ma_buy, ma_sell, ma_neutral,
                    details_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (created_at, symbol, timeframe, candle_open_time,
                 signal, previous_signal, composite, price,
                 osc_score, ma_score,
                 osc_counts.get(1, 0), osc_counts.get(-1, 0), osc_counts.get(0, 0),
                 ma_counts.get(1, 0), ma_counts.get(-1, 0), ma_counts.get(0, 0),
                 payload),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    # ------------------------------------------------------------------
    def log(self, level: str, category: str, message: str) -> None:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "INSERT INTO app_log (created_at, level, category, message) VALUES (?,?,?,?)",
                (created_at, level, category, message),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    def count_signals(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM signal_events").fetchone()[0])

    def count_logs(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM app_log").fetchone()[0])

    def recent_logs(self, limit: int = 60) -> list[sqlite3.Row]:
        """
        Web arayuzu sayfayi her acildiginda son log satirlarini gosterir;
        aksi halde log paneli uygulama yeniden baslatilana kadar bos kalir.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM app_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return list(reversed(rows))       # kronolojik

    def recent_signals(self, limit: int = 200) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM signal_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    def stats_by_timeframe(self) -> dict[str, dict[str, int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT timeframe, signal, COUNT(*) AS n "
                "FROM signal_events GROUP BY timeframe, signal"
            ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["timeframe"], {})[r["signal"]] = r["n"]
        return out

    # ------------------------------------------------------------------
    def reset(self) -> dict[str, int]:
        """Tum tablolari bosaltir ve dosyayi sikistirir."""
        removed: dict[str, int] = {}
        with self._lock:
            for table in TABLES:
                n = int(self._conn.execute(
                    f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                self._conn.execute(f"DELETE FROM {table}")
                removed[table] = n
            self._conn.commit()
            try:
                self._conn.execute("VACUUM")
            except sqlite3.OperationalError:
                # VACUUM, aktif bir transaction icinde calismaz
                pass
            self._conn.commit()
        return removed

    # ------------------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
                self._conn.close()
            except Exception:      # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    def disk_size_kb(self) -> int:
        import os
        try:
            return os.path.getsize(self.path) // 1024
        except OSError:
            return 0