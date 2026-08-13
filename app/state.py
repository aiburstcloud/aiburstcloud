"""
Persistent shared state for AI Burst Cloud.

Inspired by the shared-context design in DeLM (arXiv:2606.10662): routing
state that must be authoritative — the daily cloud budget — lives in a
shared store that every worker reads and writes, instead of in per-process
memory. This makes the budget survive restarts and be enforced across
multiple uvicorn workers or router replicas sharing the same file.

SQLite is used as the substrate: a single-row table updated with atomic
`SET x = x + ?` statements, WAL journaling for concurrent readers, and a
busy timeout so writers queue instead of failing. Set STATE_DB_PATH to
`:memory:` to opt out of persistence (each process then keeps its own
ephemeral budget, matching the pre-0.2 behavior).
"""

import sqlite3
import threading
from datetime import datetime, timezone


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class CostStore:
    """Single-row SQLite store for cloud spend and token counters.

    All mutations are atomic in-database increments, so any number of
    processes pointed at the same path see one consistent budget. Reads
    apply the UTC day rollover before returning, which keeps `today_spend`
    correct even if no request arrives for days.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10.0)
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=10000")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cost_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    today_date TEXT NOT NULL,
                    today_spend REAL NOT NULL,
                    total_tokens_cloud INTEGER NOT NULL,
                    total_tokens_local INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO cost_state VALUES (1, ?, 0, 0, 0)",
                (_utc_today(),),
            )

    def _rollover(self) -> None:
        today = _utc_today()
        self._conn.execute(
            "UPDATE cost_state SET today_spend = 0, today_date = ? WHERE today_date != ?",
            (today, today),
        )

    def add_cloud_usage(self, tokens: int, cost_usd: float) -> None:
        with self._lock, self._conn:
            self._rollover()
            self._conn.execute(
                "UPDATE cost_state SET today_spend = today_spend + ?,"
                " total_tokens_cloud = total_tokens_cloud + ?",
                (cost_usd, tokens),
            )

    def add_local_usage(self, tokens: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE cost_state SET total_tokens_local = total_tokens_local + ?",
                (tokens,),
            )

    def snapshot(self) -> "CostSnapshot":
        with self._lock, self._conn:
            self._rollover()
            row = self._conn.execute(
                "SELECT today_date, today_spend, total_tokens_cloud, total_tokens_local"
                " FROM cost_state WHERE id = 1"
            ).fetchone()
        return CostSnapshot(
            today_date=row[0],
            today_spend=row[1],
            total_tokens_cloud=row[2],
            total_tokens_local=row[3],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class CostSnapshot:
    """Point-in-time read of the cost state."""

    def __init__(
        self,
        today_date: str,
        today_spend: float,
        total_tokens_cloud: int,
        total_tokens_local: int,
    ):
        self.today_date = today_date
        self.today_spend = today_spend
        self.total_tokens_cloud = total_tokens_cloud
        self.total_tokens_local = total_tokens_local
