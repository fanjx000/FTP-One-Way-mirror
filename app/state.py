"""SQLite store of what has already been synced (per job, per relative path).

Its only purpose is to make repeated runs cheap and to survive FTP servers that
report timestamps in local time or do not support MFMT: if the local file has the
same size+mtime as the last successful upload, it is skipped without a round trip.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Dict, Iterable, NamedTuple, Optional


class StateRow(NamedTuple):
    local_size: int
    local_mtime: float
    remote_size: int
    remote_mtime: float
    last_sync: float


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (
    job_id       TEXT NOT NULL,
    rel          TEXT NOT NULL,
    local_size   INTEGER NOT NULL,
    local_mtime  REAL NOT NULL,
    remote_size  INTEGER NOT NULL,
    remote_mtime REAL NOT NULL,
    last_sync    REAL NOT NULL,
    PRIMARY KEY (job_id, rel)
);
CREATE INDEX IF NOT EXISTS idx_job ON sync_state(job_id);
CREATE TABLE IF NOT EXISTS job_log (
    job_id     TEXT NOT NULL,
    last_run   REAL NOT NULL,
    last_result TEXT,
    PRIMARY KEY (job_id)
);
"""


class StateDB:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def load(self, job_id: str) -> Dict[str, StateRow]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT rel, local_size, local_mtime, remote_size, remote_mtime, last_sync "
                "FROM sync_state WHERE job_id=?", (job_id,))
            return {r[0]: StateRow(int(r[1]), float(r[2]), int(r[3]), float(r[4]), float(r[5]))
                    for r in cur.fetchall()}

    def record(self, job_id: str, rel: str, local_size: int, local_mtime: float,
               remote_size: int, remote_mtime: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sync_state "
                "(job_id, rel, local_size, local_mtime, remote_size, remote_mtime, last_sync) "
                "VALUES (?,?,?,?,?,?,?)",
                (job_id, rel, int(local_size), float(local_mtime), int(remote_size),
                 float(remote_mtime), time.time()))
            self._conn.commit()

    def record_many(self, items: Iterable[tuple]) -> None:
        rows = [(j, r, int(ls), float(lm), int(rs), float(rm), time.time())
                for (j, r, ls, lm, rs, rm) in items]
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO sync_state "
                "(job_id, rel, local_size, local_mtime, remote_size, remote_mtime, last_sync) "
                "VALUES (?,?,?,?,?,?,?)", rows)
            self._conn.commit()

    def forget(self, job_id: str, rels: Iterable[str]) -> None:
        rels = list(rels)
        if not rels:
            return
        with self._lock:
            self._conn.executemany(
                "DELETE FROM sync_state WHERE job_id=? AND rel=?",
                [(job_id, r) for r in rels])
            self._conn.commit()

    def mark_run(self, job_id: str, result: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO job_log (job_id, last_run, last_result) VALUES (?,?,?)",
                (job_id, time.time(), result))
            self._conn.commit()

    def last_run(self, job_id: str) -> Optional[float]:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_run FROM job_log WHERE job_id=?", (job_id,)).fetchone()
            return float(row[0]) if row else None
