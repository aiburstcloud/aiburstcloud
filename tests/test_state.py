"""Tests for the persistent shared cost state (app/state.py).

Verifies the properties the in-memory tracker lacked: spend survives a
process restart, and multiple workers/replicas pointed at the same file
enforce one shared budget.
"""

import sqlite3

from app.router import CostTracker
from app.state import CostStore


class TestPersistence:
    def test_spend_survives_restart(self, tmp_path):
        db = str(tmp_path / "state.db")

        store = CostStore(db)
        store.add_cloud_usage(2000, 0.004)
        store.close()

        # A new store on the same path — simulating a router restart —
        # must see the spend instead of starting from zero.
        reopened = CostStore(db)
        snap = reopened.snapshot()
        assert snap.today_spend == 0.004
        assert snap.total_tokens_cloud == 2000
        reopened.close()

    def test_budget_enforced_across_restart(self, tmp_path):
        db = str(tmp_path / "state.db")

        tracker = CostTracker(daily_budget=1.0, store=CostStore(db))
        tracker.record_cloud_usage(1000, cost_per_1k=1.0)
        assert tracker.budget_exhausted
        tracker.store.close()

        restarted = CostTracker(daily_budget=1.0, store=CostStore(db))
        assert restarted.budget_exhausted
        restarted.store.close()


class TestSharedBudget:
    def test_two_workers_share_one_budget(self, tmp_path):
        db = str(tmp_path / "state.db")
        worker_a = CostTracker(daily_budget=1.0, store=CostStore(db))
        worker_b = CostTracker(daily_budget=1.0, store=CostStore(db))

        worker_a.record_cloud_usage(600, cost_per_1k=1.0)  # $0.60
        worker_b.record_cloud_usage(600, cost_per_1k=1.0)  # $0.60 → $1.20 total

        assert worker_a.budget_exhausted
        assert worker_b.budget_exhausted
        assert worker_a.today_spend == worker_b.today_spend == 1.2

        worker_a.store.close()
        worker_b.store.close()

    def test_token_counters_accumulate_across_stores(self, tmp_path):
        db = str(tmp_path / "state.db")
        a, b = CostStore(db), CostStore(db)
        a.add_local_usage(100)
        b.add_local_usage(250)
        a.add_cloud_usage(40, 0.0001)
        snap = b.snapshot()
        assert snap.total_tokens_local == 350
        assert snap.total_tokens_cloud == 40
        a.close()
        b.close()


class TestDayRollover:
    def test_rollover_resets_spend_but_keeps_lifetime_tokens(self, tmp_path):
        db = str(tmp_path / "state.db")
        store = CostStore(db)
        store.add_cloud_usage(5000, 2.5)

        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE cost_state SET today_date = '1999-01-01'")

        snap = store.snapshot()
        assert snap.today_spend == 0.0
        assert snap.total_tokens_cloud == 5000  # lifetime counter unaffected
        store.close()


class TestEphemeralMode:
    def test_memory_store_is_per_process(self):
        # ":memory:" opts out of persistence — two stores are independent.
        a, b = CostStore(":memory:"), CostStore(":memory:")
        a.add_cloud_usage(1000, 0.5)
        assert a.snapshot().today_spend == 0.5
        assert b.snapshot().today_spend == 0.0
        a.close()
        b.close()
