"""Unit tests for the routing engine in app/router.py.

Covers the pure decision logic (sensitivity classifier, cost tracker,
dual-mode route decisions) and the observability endpoints. No network
access or live backends required.
"""

from fastapi.testclient import TestClient

from app.router import (
    BackendMetrics,
    BackendStatus,
    BurstMode,
    CostTracker,
    RouterConfig,
    SensitivityLevel,
    app,
    classify_sensitivity,
    decide_route,
)

KEYWORDS = ["ssn", "hipaa", "classified", "top secret"]


def make_metrics(name, active=0, status=BackendStatus.HEALTHY, avg_latency_ms=0.0):
    m = BackendMetrics(name)
    m.active_requests = active
    m.status = status
    if avg_latency_ms:
        m.total_requests = 1
        m.total_latency_ms = avg_latency_ms
    return m


def make_config(**overrides):
    defaults = dict(
        burst_mode=BurstMode.EDGE_FIRST,
        local_max_queue=5,
        local_latency_threshold_ms=2000.0,
        cloud_max_queue=50,
        cloud_latency_threshold_ms=5000.0,
        daily_cloud_budget_usd=5.0,
    )
    defaults.update(overrides)
    return RouterConfig(**defaults)


def make_tracker(budget=5.0, spent=0.0):
    tracker = CostTracker(daily_budget=budget)
    if spent:
        # 1k tokens at $spent/1k = $spent
        tracker.record_cloud_usage(1000, spent)
    return tracker


# ---------------------------------------------------------------------------
# Sensitivity classifier
# ---------------------------------------------------------------------------


class TestClassifySensitivity:
    def test_no_keywords_is_public(self):
        messages = [{"role": "user", "content": "What's the weather like?"}]
        assert classify_sensitivity(messages, KEYWORDS) == SensitivityLevel.PUBLIC

    def test_one_keyword_is_internal(self):
        messages = [{"role": "user", "content": "Summarize our HIPAA policy"}]
        assert classify_sensitivity(messages, KEYWORDS) == SensitivityLevel.INTERNAL

    def test_two_keywords_is_sensitive(self):
        messages = [{"role": "user", "content": "This classified doc has an SSN"}]
        assert classify_sensitivity(messages, KEYWORDS) == SensitivityLevel.SENSITIVE

    def test_matching_is_case_insensitive(self):
        messages = [{"role": "user", "content": "TOP SECRET // CLASSIFIED"}]
        assert classify_sensitivity(messages, KEYWORDS) == SensitivityLevel.SENSITIVE

    def test_keywords_counted_across_messages(self):
        messages = [
            {"role": "user", "content": "look up this ssn"},
            {"role": "assistant", "content": "that may be hipaa data"},
        ]
        assert classify_sensitivity(messages, KEYWORDS) == SensitivityLevel.SENSITIVE

    def test_non_string_content_is_ignored(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "ssn hipaa"}]},
            {"role": "user", "content": None},
        ]
        assert classify_sensitivity(messages, KEYWORDS) == SensitivityLevel.PUBLIC


# ---------------------------------------------------------------------------
# Cost tracker
# ---------------------------------------------------------------------------


class TestCostTracker:
    def test_cloud_usage_accumulates_spend(self):
        tracker = CostTracker(daily_budget=5.0)
        tracker.record_cloud_usage(2000, cost_per_1k=0.002)
        assert tracker.today_spend == 0.004
        assert tracker.total_tokens_cloud == 2000

    def test_budget_remaining_and_exhausted(self):
        tracker = CostTracker(daily_budget=1.0)
        assert tracker.budget_remaining == 1.0
        assert not tracker.budget_exhausted
        tracker.record_cloud_usage(1000, cost_per_1k=1.0)  # spend the full $1
        assert tracker.budget_remaining == 0.0
        assert tracker.budget_exhausted

    def test_remaining_never_negative(self):
        tracker = CostTracker(daily_budget=1.0)
        tracker.record_cloud_usage(5000, cost_per_1k=1.0)  # $5 spend on $1 budget
        assert tracker.budget_remaining == 0.0

    def test_spend_resets_on_new_day(self):
        tracker = CostTracker(daily_budget=1.0)
        tracker.record_cloud_usage(1000, cost_per_1k=1.0)
        assert tracker.budget_exhausted
        tracker.today_date = "1999-01-01"  # simulate UTC day rollover
        assert not tracker.budget_exhausted
        assert tracker.today_spend == 0.0

    def test_local_usage_does_not_touch_budget(self):
        tracker = CostTracker(daily_budget=1.0)
        tracker.record_local_usage(10_000)
        assert tracker.today_spend == 0.0
        assert tracker.total_tokens_local == 10_000


# ---------------------------------------------------------------------------
# Backend metrics
# ---------------------------------------------------------------------------


class TestBackendMetrics:
    def test_avg_latency_zero_when_no_requests(self):
        assert BackendMetrics("local").avg_latency_ms == 0.0

    def test_avg_latency_is_mean_over_requests(self):
        m = BackendMetrics("local")
        m.total_requests = 4
        m.total_latency_ms = 1000.0
        assert m.avg_latency_ms == 250.0


# ---------------------------------------------------------------------------
# Route decisions — edge_first mode
# ---------------------------------------------------------------------------


class TestEdgeFirstRouting:
    def test_idle_routes_to_local(self):
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local"),
            make_metrics("cloud"),
            make_tracker(),
            make_config(),
        )
        assert decision.backend == "local"
        assert decision.reason == "local_available"

    def test_sensitive_always_local_even_when_overloaded(self):
        decision = decide_route(
            SensitivityLevel.SENSITIVE,
            make_metrics("local", active=99),
            make_metrics("cloud"),
            make_tracker(),
            make_config(),
        )
        assert decision.backend == "local"
        assert decision.reason == "sensitive_data_local_only"

    def test_budget_exhausted_blocks_cloud_burst(self):
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local", active=99),  # would otherwise burst
            make_metrics("cloud"),
            make_tracker(budget=1.0, spent=1.0),
            make_config(),
        )
        assert decision.backend == "local"
        assert decision.reason == "daily_cloud_budget_exhausted"

    def test_local_down_fails_over_to_cloud(self):
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local", status=BackendStatus.DOWN),
            make_metrics("cloud"),
            make_tracker(),
            make_config(),
        )
        assert decision.backend == "cloud"
        assert decision.reason == "local_down_failover_to_cloud"

    def test_queue_depth_triggers_cloud_burst_for_public(self):
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local", active=5),  # at local_max_queue
            make_metrics("cloud"),
            make_tracker(),
            make_config(),
        )
        assert decision.backend == "cloud"
        assert decision.reason == "local_overloaded_burst_to_cloud"

    def test_latency_triggers_cloud_burst_for_public(self):
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local", avg_latency_ms=3000.0),  # over 2000ms threshold
            make_metrics("cloud"),
            make_tracker(),
            make_config(),
        )
        assert decision.backend == "cloud"
        assert decision.reason == "local_overloaded_burst_to_cloud"

    def test_internal_data_never_bursts_to_cloud(self):
        decision = decide_route(
            SensitivityLevel.INTERNAL,
            make_metrics("local", active=5),
            make_metrics("cloud"),
            make_tracker(),
            make_config(),
        )
        assert decision.backend == "local"

    def test_no_burst_when_cloud_is_down(self):
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local", active=5),
            make_metrics("cloud", status=BackendStatus.DOWN),
            make_tracker(),
            make_config(),
        )
        assert decision.backend == "local"


# ---------------------------------------------------------------------------
# Route decisions — cloud_first mode
# ---------------------------------------------------------------------------


class TestCloudFirstRouting:
    def test_idle_routes_to_cloud(self):
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local"),
            make_metrics("cloud"),
            make_tracker(),
            make_config(burst_mode=BurstMode.CLOUD_FIRST),
        )
        assert decision.backend == "cloud"
        assert decision.reason == "cloud_available"

    def test_sensitive_bursts_down_to_local(self):
        decision = decide_route(
            SensitivityLevel.SENSITIVE,
            make_metrics("local"),
            make_metrics("cloud"),
            make_tracker(),
            make_config(burst_mode=BurstMode.CLOUD_FIRST),
        )
        assert decision.backend == "local"
        assert decision.reason == "sensitive_data_local_only"

    def test_budget_exhausted_falls_back_to_local(self):
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local"),
            make_metrics("cloud"),
            make_tracker(budget=1.0, spent=1.0),
            make_config(burst_mode=BurstMode.CLOUD_FIRST),
        )
        assert decision.backend == "local"
        assert decision.reason == "daily_cloud_budget_exhausted"

    def test_cloud_down_fails_over_to_local(self):
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local"),
            make_metrics("cloud", status=BackendStatus.DOWN),
            make_tracker(),
            make_config(burst_mode=BurstMode.CLOUD_FIRST),
        )
        assert decision.backend == "local"
        assert decision.reason == "cloud_down_failover_to_local"

    def test_overload_bursts_down_to_local_even_for_internal(self):
        decision = decide_route(
            SensitivityLevel.INTERNAL,
            make_metrics("local"),
            make_metrics("cloud", active=50),  # at cloud_max_queue
            make_tracker(),
            make_config(burst_mode=BurstMode.CLOUD_FIRST),
        )
        assert decision.backend == "local"
        assert decision.reason == "cloud_overloaded_burst_to_local"


# ---------------------------------------------------------------------------
# Concurrency safety — per-request mode override must not mutate global state
# ---------------------------------------------------------------------------


class TestModeOverrideConcurrency:
    def test_override_does_not_mutate_config(self):
        """decide_route with burst_mode_override leaves config unchanged."""
        cfg = make_config(burst_mode=BurstMode.EDGE_FIRST)
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local"),
            make_metrics("cloud"),
            make_tracker(),
            cfg,
            burst_mode_override=BurstMode.CLOUD_FIRST,
        )
        assert decision.backend == "cloud"
        assert decision.burst_mode == BurstMode.CLOUD_FIRST
        assert cfg.burst_mode == BurstMode.EDGE_FIRST

    def test_none_override_uses_config_default(self):
        cfg = make_config(burst_mode=BurstMode.EDGE_FIRST)
        decision = decide_route(
            SensitivityLevel.PUBLIC,
            make_metrics("local"),
            make_metrics("cloud"),
            make_tracker(),
            cfg,
            burst_mode_override=None,
        )
        assert decision.backend == "local"
        assert decision.burst_mode == BurstMode.EDGE_FIRST


# ---------------------------------------------------------------------------
# Observability endpoints
# ---------------------------------------------------------------------------

client = TestClient(app)


class TestEndpoints:
    def test_models_lists_burst_auto(self):
        r = client.get("/v1/models")
        assert r.status_code == 200
        assert r.json()["data"][0]["id"] == "burst-auto"

    def test_health_reports_backends_and_cost(self):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["burst_mode"] in [m.value for m in BurstMode]
        assert {"local", "cloud", "cost"} <= body.keys()

    def test_metrics_exposes_prometheus_format(self):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]
        assert "# TYPE aiburstcloud_requests_total counter" in r.text
        assert "# HELP aiburstcloud_cloud_budget_remaining_usd" in r.text
        assert 'aiburstcloud_requests_total{backend="local"}' in r.text
