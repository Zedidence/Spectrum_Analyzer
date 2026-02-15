"""
SQLite signal database for persistent signal storage.

Stores all detected signals with frequency, power, bandwidth,
timestamps, hit count, and user-assigned classification/notes.

Thread-safe: uses a dedicated connection per call (SQLite handles
file-level locking). All operations are synchronous and fast.
"""

import sqlite3
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Schema version for future migrations
SCHEMA_VERSION = 1

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    center_freq REAL NOT NULL,
    peak_freq REAL NOT NULL,
    bandwidth REAL NOT NULL,
    peak_power REAL NOT NULL,
    avg_power REAL NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    hit_count INTEGER DEFAULT 1,
    classification TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    active INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_signals_freq ON signals(center_freq);
CREATE INDEX IF NOT EXISTS idx_signals_active ON signals(active);
CREATE INDEX IF NOT EXISTS idx_signals_last_seen ON signals(last_seen);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class SignalDatabase:
    """
    Persistent signal storage using SQLite.

    Signals are upserted by frequency proximity — if a new detection
    is within `match_bandwidth_hz` of an existing entry, the existing
    entry is updated rather than creating a duplicate.
    """

    def __init__(self, db_path="data/signals.db", match_bandwidth_hz=50e3):
        """
        Args:
            db_path: Path to SQLite database file
            match_bandwidth_hz: Frequency tolerance for matching signals
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._match_bw = match_bandwidth_hz

        self._init_db()
        logger.info("Signal database initialized: %s", self._db_path)

    def _get_conn(self):
        """Get a new connection (thread-safe pattern)."""
        conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        """Create tables if they don't exist."""
        conn = self._get_conn()
        try:
            conn.executescript(CREATE_SQL)
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_signal(self, center_freq, peak_freq, bandwidth,
                      peak_power, avg_power, hit_count=1):
        """
        Insert or update a signal in the database.

        If a signal exists within match_bandwidth_hz of center_freq,
        updates it. Otherwise inserts a new entry.

        Returns:
            signal id (int)
        """
        now = time.time()
        conn = self._get_conn()
        try:
            # Try to find existing signal near this frequency
            row = conn.execute(
                "SELECT id, hit_count, peak_power FROM signals "
                "WHERE ABS(center_freq - ?) < ? AND active = 1 "
                "ORDER BY ABS(center_freq - ?) LIMIT 1",
                (center_freq, self._match_bw, center_freq),
            ).fetchone()

            if row:
                # Update existing
                sig_id = row['id']
                new_peak = max(row['peak_power'], peak_power)
                conn.execute(
                    "UPDATE signals SET "
                    "center_freq=?, peak_freq=?, bandwidth=?, "
                    "peak_power=?, avg_power=?, last_seen=?, "
                    "hit_count=hit_count+?, active=1 "
                    "WHERE id=?",
                    (center_freq, peak_freq, bandwidth,
                     new_peak, avg_power, now, hit_count, sig_id),
                )
            else:
                # Insert new
                cursor = conn.execute(
                    "INSERT INTO signals "
                    "(center_freq, peak_freq, bandwidth, peak_power, avg_power, "
                    "first_seen, last_seen, hit_count, active) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (center_freq, peak_freq, bandwidth,
                     peak_power, avg_power, now, now, hit_count),
                )
                sig_id = cursor.lastrowid

            conn.commit()
            return sig_id
        finally:
            conn.close()

    def mark_lost(self, center_freq):
        """Mark a signal as inactive (lost)."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE signals SET active=0 WHERE "
                "ABS(center_freq - ?) < ? AND active=1",
                (center_freq, self._match_bw),
            )
            conn.commit()
        finally:
            conn.close()

    def get_signals(self, active_only=False, limit=100, offset=0,
                    freq_min=None, freq_max=None):
        """
        Query signals from the database.

        Args:
            active_only: Only return currently active signals
            limit: Max results
            offset: Pagination offset
            freq_min: Minimum frequency filter (Hz)
            freq_max: Maximum frequency filter (Hz)

        Returns:
            List of dicts
        """
        conn = self._get_conn()
        try:
            conditions = []
            params = []

            if active_only:
                conditions.append("active = 1")
            if freq_min is not None:
                conditions.append("center_freq >= ?")
                params.append(freq_min)
            if freq_max is not None:
                conditions.append("center_freq <= ?")
                params.append(freq_max)

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            query = (
                f"SELECT * FROM signals {where} "
                f"ORDER BY last_seen DESC LIMIT ? OFFSET ?"
            )
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_signal(self, signal_id):
        """Get a single signal by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM signals WHERE id=?", (signal_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def classify_signal(self, signal_id, classification, notes=""):
        """Set classification and notes for a signal."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE signals SET classification=?, notes=? WHERE id=?",
                (classification, notes, signal_id),
            )
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def delete_signal(self, signal_id):
        """Delete a signal from the database."""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM signals WHERE id=?", (signal_id,))
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def get_stats(self):
        """Return database statistics."""
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM signals WHERE active=1"
            ).fetchone()[0]
            return {
                'total_signals': total,
                'active_signals': active,
                'db_path': str(self._db_path),
            }
        finally:
            conn.close()

    def clear_all(self):
        """Delete all signals from the database."""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM signals")
            conn.commit()
        finally:
            conn.close()
