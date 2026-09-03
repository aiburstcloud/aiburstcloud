"""Tests for the dashboard page and its data endpoint.

The page is served from disk and fetches everything over HTTP, so these tests
cover the shell, the JSON contract it depends on, and the decision ring buffer.
No network access or live backends required.
"""

import re
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.router import (
    DASHBOARD_HTML,
    BurstMode,
    RouteDecision,
    SensitivityLevel,
    app,
    recent_decisions,
    record_decision,
)

client = TestClient(app)


def make_decision(**overrides):
    defaults = dict(
        backend="local",
        burst_mode=BurstMode.EDGE_FIRST,
        reason="local_available",
        sensitivity=SensitivityLevel.PUBLIC,
        primary_queue_depth=0,
        budget_remaining_usd=5.0,
    )
    defaults.update(overrides)
    return RouteDecision(**defaults)


class TestDashboardPage:
    def test_serves_html(self):
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "AI Burst Cloud" in r.text

    def test_page_is_self_contained(self):
        """No CDN, font, or analytics fetches — the router must work air-gapped."""
        html = DASHBOARD_HTML.read_text(encoding="utf-8")
        assert not re.search(r"(src|href)\s*=\s*[\"']https?://", html)
        assert "//cdn" not in html


class TestDashboardData:
    def test_reports_health_limits_and_decisions(self):
        r = client.get("/dashboard/data")
        assert r.status_code == 200
        body = r.json()
        assert {"status", "burst_mode", "local", "cloud", "cost", "limits", "decisions"} <= (
            body.keys()
        )

    def test_backends_include_model_names(self):
        body = client.get("/dashboard/data").json()
        assert body["local"]["model"]
        assert "model" in body["cloud"]

    def test_limits_cover_every_meter_the_page_draws(self):
        body = client.get("/dashboard/data").json()
        assert {
            "local_max_queue",
            "local_latency_threshold_ms",
            "cloud_max_queue",
            "cloud_latency_threshold_ms",
            "daily_cloud_budget_usd",
        } == body["limits"].keys()

    def test_health_contract_is_unchanged(self):
        """/dashboard/data adds keys; /health itself must stay as it was."""
        assert client.get("/health").json().keys() == {
            "status",
            "burst_mode",
            "local",
            "cloud",
            "cost",
        }


class TestRecentDecisions:
    def test_newest_first_and_capped(self):
        recent_decisions.clear()
        for i in range(recent_decisions.maxlen + 10):
            recent_decisions.appendleft({"reason": f"r{i}"})
        assert len(recent_decisions) == recent_decisions.maxlen
        assert recent_decisions[0]["reason"] == f"r{recent_decisions.maxlen + 9}"

    def test_decisions_surface_in_the_payload(self):
        recent_decisions.clear()
        record_decision("local", "sensitive_data_local_only", make_decision())
        decisions = client.get("/dashboard/data").json()["decisions"]
        assert decisions[0]["reason"] == "sensitive_data_local_only"
        assert decisions[0]["backend"] == "local"
        recent_decisions.clear()

    def test_timestamp_is_utc_iso_so_the_page_can_localize_it(self):
        """The page renders `at` with toLocaleTimeString, which needs a real
        timezone-aware ISO string — a bare "%H:%M:%S" would show as UTC."""
        recent_decisions.clear()
        record_decision("cloud", "cloud_available", make_decision())
        at = client.get("/dashboard/data").json()["decisions"][0]["at"]
        parsed = datetime.fromisoformat(at)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)
        recent_decisions.clear()

    def test_records_the_backend_that_served_not_only_the_first_choice(self):
        """A runtime failover must appear, or the log misreports who served."""
        recent_decisions.clear()
        decision = make_decision()
        record_decision(decision.backend, decision.reason, decision)
        record_decision("cloud", "local_unreachable_failover_to_cloud", decision)
        rows = client.get("/dashboard/data").json()["decisions"]
        assert rows[0]["backend"] == "cloud"
        assert "failover" in rows[0]["reason"]
        assert rows[1]["backend"] == "local"
        recent_decisions.clear()
