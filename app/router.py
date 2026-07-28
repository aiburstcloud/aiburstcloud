"""
AI Burst Cloud Router
---------------------
Dual-mode cloud burst LLM routing engine.

Mode 1 — EDGE FIRST (default: "edge_burst")
  Local GPU handles baseline. Cloud bursts when overloaded.
  Best for: cost optimization, data sovereignty by default.

Mode 2 — CLOUD FIRST ("cloud_burst")
  Cloud handles everything for speed/scale. Sensitive requests
  "burst down" to local/on-prem GPU for security.
  Best for: max throughput, sovereignty-on-demand.

Exposes an OpenAI-compatible /v1/chat/completions endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.backends import Backend, create_backends
from app.models import (
    BackendMetrics,
    BackendStatus,
    BurstMode,
    RouterConfig,
    SensitivityLevel,
)


class CostTracker:
    def __init__(self, daily_budget: float):
        self.daily_budget = daily_budget
        self.today_spend: float = 0.0
        self.today_date: str = ""
        self.total_tokens_cloud: int = 0
        self.total_tokens_local: int = 0

    def check_and_reset(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self.today_date:
            self.today_spend = 0.0
            self.today_date = today

    def record_cloud_usage(self, tokens: int, cost_per_1k: float) -> None:
        self.check_and_reset()
        cost = (tokens / 1000) * cost_per_1k
        self.today_spend += cost
        self.total_tokens_cloud += tokens

    def record_local_usage(self, tokens: int) -> None:
        self.total_tokens_local += tokens

    @property
    def budget_remaining(self) -> float:
        self.check_and_reset()
        return max(0.0, self.daily_budget - self.today_spend)

    @property
    def budget_exhausted(self) -> bool:
        return self.budget_remaining <= 0.0


# ---------------------------------------------------------------------------
# Sensitivity classifier
# ---------------------------------------------------------------------------


def classify_sensitivity(messages: list[dict[str, Any]], keywords: list[str]) -> SensitivityLevel:
    text = " ".join(
        msg.get("content", "") for msg in messages if isinstance(msg.get("content"), str)
    ).lower()

    hits = sum(1 for kw in keywords if kw in text)

    if hits >= 2:
        return SensitivityLevel.SENSITIVE
    elif hits == 1:
        return SensitivityLevel.INTERNAL
    return SensitivityLevel.PUBLIC


# ---------------------------------------------------------------------------
# Route decision engine — dual mode
# ---------------------------------------------------------------------------


class RouteDecision(BaseModel):
    backend: str  # "local" or "cloud"
    reason: str
    burst_mode: BurstMode
    sensitivity: SensitivityLevel
    primary_queue_depth: int
    budget_remaining_usd: float


def decide_route(
    sensitivity: SensitivityLevel,
    local_metrics: BackendMetrics,
    cloud_metrics: BackendMetrics,
    cost_tracker: CostTracker,
    config: RouterConfig,
    burst_mode_override: BurstMode | None = None,
) -> RouteDecision:
    """
    Dual-mode routing:

    EDGE_FIRST:  local is primary, cloud is burst overflow
    CLOUD_FIRST: cloud is primary, local is security fallback

    In BOTH modes, SENSITIVE data always routes to local.
    """
    mode = burst_mode_override if burst_mode_override is not None else config.burst_mode

    if mode == BurstMode.EDGE_FIRST:
        primary, overflow = "local", "cloud"
        primary_metrics = local_metrics
        overflow_metrics = cloud_metrics
        max_queue = config.local_max_queue
        latency_threshold = config.local_latency_threshold_ms
    else:
        primary, overflow = "cloud", "local"
        primary_metrics = cloud_metrics
        overflow_metrics = local_metrics
        max_queue = config.cloud_max_queue
        latency_threshold = config.cloud_latency_threshold_ms

    queue_depth = primary_metrics.active_requests
    budget_remaining = cost_tracker.budget_remaining

    def _decision(backend: str, reason: str) -> RouteDecision:
        return RouteDecision(
            backend=backend,
            reason=reason,
            burst_mode=mode,
            sensitivity=sensitivity,
            primary_queue_depth=queue_depth,
            budget_remaining_usd=budget_remaining,
        )

    # ----- AXIS 1: Data sovereignty (always wins) -----
    if sensitivity == SensitivityLevel.SENSITIVE:
        return _decision("local", "sensitive_data_local_only")

    # ----- AXIS 2: Cost gate (cloud budget) -----
    # In edge_first: if budget gone, stay local (no burst)
    # In cloud_first: if budget gone, fall back to local for everything
    if cost_tracker.budget_exhausted:
        return _decision("local", "daily_cloud_budget_exhausted")

    # ----- AXIS 3: Primary backend health -----
    if primary_metrics.status == BackendStatus.DOWN:
        if sensitivity != SensitivityLevel.SENSITIVE:
            return _decision(overflow, f"{primary}_down_failover_to_{overflow}")
        return _decision("local", f"{primary}_down_but_sensitive_queuing_local")

    # ----- AXIS 3: Latency / queue depth triggers burst -----
    primary_overloaded = (
        primary_metrics.active_requests >= max_queue
        or primary_metrics.avg_latency_ms > latency_threshold
    )

    # In cloud_first mode, "overflow" is local — always safe
    # In edge_first mode, "overflow" is cloud — only for PUBLIC
    if (
        primary_overloaded
        and overflow_metrics.status != BackendStatus.DOWN
        and (mode == BurstMode.CLOUD_FIRST or sensitivity == SensitivityLevel.PUBLIC)
    ):
        return _decision(overflow, f"{primary}_overloaded_burst_to_{overflow}")

    # ----- Default: use primary -----
    return _decision(primary, f"{primary}_available")


# ---------------------------------------------------------------------------
# Health checker
# ---------------------------------------------------------------------------


async def health_check_loop(
    client: httpx.AsyncClient,
    backends: list[Backend],
) -> None:
    while True:
        for backend in backends:
            healthy = await backend.health_check(client)
            if healthy:
                backend.metrics.status = BackendStatus.HEALTHY
                backend.metrics.errors_consecutive = 0
            else:
                backend.metrics.errors_consecutive += 1

            if backend.metrics.errors_consecutive >= 3:
                backend.metrics.status = BackendStatus.DOWN
            elif backend.metrics.errors_consecutive >= 1:
                backend.metrics.status = BackendStatus.DEGRADED
            backend.metrics.last_health_check = time.time()

        await asyncio.sleep(15)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

config = RouterConfig()
local_backend, cloud_backend = create_backends(config)
local_metrics = local_backend.metrics
cloud_metrics = cloud_backend.metrics
cost_tracker = CostTracker(daily_budget=config.daily_cloud_budget_usd)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "request_id",
            "backend",
            "mode",
            "reason",
            "sensitivity",
            "queue_depth",
            "budget_remaining_usd",
        ):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


logger = logging.getLogger("aiburstcloud")
_handler = logging.StreamHandler()
_handler.setFormatter(JSONFormatter())
logger.handlers = [_handler]
logger.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    client = httpx.AsyncClient()
    app.state.client = client
    task = asyncio.create_task(health_check_loop(client, [local_backend, cloud_backend]))
    logger.info(f"AI Burst Cloud starting in {config.burst_mode.value} mode")
    yield
    task.cancel()
    await client.aclose()


app = FastAPI(
    title="AI Burst Cloud",
    description="Dual-mode cloud burst LLM router — edge-first or cloud-first",
    version="0.1.1",
    lifespan=lifespan,
)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    payload = await request.json()
    messages = payload.get("messages", [])
    stream = payload.get("stream", False)

    # Resolve per-request mode override without mutating shared state
    mode_override_header = request.headers.get("X-Burst-Mode")
    burst_mode_override: BurstMode | None = None
    if mode_override_header and mode_override_header in [m.value for m in BurstMode]:
        burst_mode_override = BurstMode(mode_override_header)

    sensitivity = classify_sensitivity(messages, config.sensitive_keywords)

    decision = decide_route(
        sensitivity=sensitivity,
        local_metrics=local_metrics,
        cloud_metrics=cloud_metrics,
        cost_tracker=cost_tracker,
        config=config,
        burst_mode_override=burst_mode_override,
    )

    logger.info(
        "route_decision",
        extra={
            "request_id": request_id,
            "backend": decision.backend,
            "mode": decision.burst_mode.value,
            "reason": decision.reason,
            "sensitivity": decision.sensitivity.value,
            "queue_depth": decision.primary_queue_depth,
            "budget_remaining_usd": decision.budget_remaining_usd,
        },
    )

    client: httpx.AsyncClient = request.app.state.client
    start = time.monotonic()

    backend = local_backend if decision.backend == "local" else cloud_backend
    metrics = backend.metrics

    metrics.active_requests += 1

    try:
        if stream:
            response = await backend.send(client, payload, stream=True)

            async def stream_and_track() -> AsyncGenerator[bytes, None]:
                total_tokens = 0
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                        if b'"content"' in chunk:
                            total_tokens += 1
                finally:
                    elapsed = (time.monotonic() - start) * 1000
                    metrics.active_requests -= 1
                    metrics.total_requests += 1
                    metrics.total_latency_ms += elapsed
                    metrics.total_tokens += total_tokens
                    if decision.backend == "cloud":
                        cost_tracker.record_cloud_usage(
                            total_tokens, config.cloud_cost_per_1k_tokens
                        )
                    else:
                        cost_tracker.record_local_usage(total_tokens)
                    await response.aclose()

            return StreamingResponse(
                stream_and_track(),
                media_type="text/event-stream",
                headers={
                    "X-Request-ID": request_id,
                    "X-Burst-Backend": decision.backend,
                    "X-Burst-Mode": decision.burst_mode.value,
                    "X-Burst-Reason": decision.reason,
                    "X-Burst-Sensitivity": decision.sensitivity,
                },
            )
        else:
            response = await backend.send(client, payload, stream=False)
            elapsed = (time.monotonic() - start) * 1000
            metrics.active_requests -= 1
            metrics.total_requests += 1
            metrics.total_latency_ms += elapsed

            data = response.json()
            total_tokens = data.get("usage", {}).get("total_tokens", 0)
            metrics.total_tokens += total_tokens

            if decision.backend == "cloud":
                cost_tracker.record_cloud_usage(total_tokens, config.cloud_cost_per_1k_tokens)
            else:
                cost_tracker.record_local_usage(total_tokens)

            data["_burst"] = {
                "request_id": request_id,
                "backend": decision.backend,
                "mode": decision.burst_mode.value,
                "reason": decision.reason,
                "sensitivity": decision.sensitivity,
                "latency_ms": round(elapsed, 1),
                "daily_cloud_spend_usd": round(cost_tracker.today_spend, 4),
            }
            return data

    except httpx.ConnectError:
        metrics.active_requests -= 1
        metrics.errors_consecutive += 1

        # Failover logic
        failover = cloud_backend if decision.backend == "local" else local_backend
        if sensitivity != SensitivityLevel.SENSITIVE or failover.name == "local":
            logger.warning(
                "failover",
                extra={"request_id": request_id, "from": decision.backend, "to": failover.name},
            )
            try:
                response = await failover.send(client, payload, stream=stream)
                if stream:
                    return StreamingResponse(
                        response.aiter_bytes(),
                        media_type="text/event-stream",
                        headers={
                            "X-Request-ID": request_id,
                            "X-Burst-Backend": failover.name,
                            "X-Burst-Reason": "failover",
                        },
                    )
                return response.json()
            except Exception as e:
                raise HTTPException(
                    status_code=502, detail=f"All backends unreachable: {e}"
                ) from e

        raise HTTPException(status_code=502, detail="Backend unreachable") from None

    except Exception as e:
        metrics.active_requests -= 1
        logger.error(
            "request_failed",
            extra={"request_id": request_id},
            exc_info=e,
        )
        raise HTTPException(status_code=500, detail=str(e)) from e


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {"id": "burst-auto", "object": "model", "owned_by": "aiburstcloud"},
        ],
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "burst_mode": config.burst_mode.value,
        "local": local_metrics.to_dict(),
        "cloud": cloud_metrics.to_dict(),
        "cost": {
            "today_spend_usd": round(cost_tracker.today_spend, 4),
            "budget_remaining_usd": round(cost_tracker.budget_remaining, 4),
            "total_tokens_local": cost_tracker.total_tokens_local,
            "total_tokens_cloud": cost_tracker.total_tokens_cloud,
        },
    }


@app.get("/metrics")
async def metrics() -> Response:
    lines = [
        "# HELP aiburstcloud_burst_mode Active burst mode (1 = active)",
        "# TYPE aiburstcloud_burst_mode gauge",
        f'aiburstcloud_burst_mode{{mode="{config.burst_mode.value}"}} 1',
        "# HELP aiburstcloud_requests_total Total requests handled per backend",
        "# TYPE aiburstcloud_requests_total counter",
        f'aiburstcloud_requests_total{{backend="local"}} {local_metrics.total_requests}',
        f'aiburstcloud_requests_total{{backend="cloud"}} {cloud_metrics.total_requests}',
        "# HELP aiburstcloud_active_requests Current in-flight requests per backend",
        "# TYPE aiburstcloud_active_requests gauge",
        f'aiburstcloud_active_requests{{backend="local"}} {local_metrics.active_requests}',
        f'aiburstcloud_active_requests{{backend="cloud"}} {cloud_metrics.active_requests}',
        "# HELP aiburstcloud_tokens_total Total tokens processed per backend",
        "# TYPE aiburstcloud_tokens_total counter",
        f'aiburstcloud_tokens_total{{backend="local"}} {local_metrics.total_tokens}',
        f'aiburstcloud_tokens_total{{backend="cloud"}} {cloud_metrics.total_tokens}',
        "# HELP aiburstcloud_cloud_spend_today_usd Cloud spend for current UTC day",
        "# TYPE aiburstcloud_cloud_spend_today_usd gauge",
        f"aiburstcloud_cloud_spend_today_usd {cost_tracker.today_spend:.4f}",
        "# HELP aiburstcloud_cloud_budget_remaining_usd Remaining daily cloud budget",
        "# TYPE aiburstcloud_cloud_budget_remaining_usd gauge",
        f"aiburstcloud_cloud_budget_remaining_usd {cost_tracker.budget_remaining:.4f}",
    ]
    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4",
    )
