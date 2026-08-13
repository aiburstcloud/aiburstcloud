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

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.state import CostStore

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class BurstMode(str, Enum):
    EDGE_FIRST = "edge_burst"  # local baseline, cloud overflow
    CLOUD_FIRST = "cloud_burst"  # cloud baseline, local for sensitive


class SensitivityLevel(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"


class BackendStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class RouterConfig(BaseModel):
    # Burst mode
    burst_mode: BurstMode = Field(
        default_factory=lambda: BurstMode(os.getenv("BURST_MODE", "edge_burst"))
    )

    # Local backend (Orin / Ollama / any local vLLM)
    local_url: str = Field(
        default_factory=lambda: os.getenv("LOCAL_URL", "http://localhost:11434")
    )
    local_model: str = Field(default_factory=lambda: os.getenv("LOCAL_MODEL", "qwen3.5-35b-a3b"))
    local_max_queue: int = int(os.getenv("LOCAL_MAX_QUEUE", "5"))
    local_latency_threshold_ms: float = float(os.getenv("LOCAL_LATENCY_THRESHOLD_MS", "2000"))

    # Cloud backend (RunPod / Modal / any serverless vLLM)
    cloud_url: str = Field(default_factory=lambda: os.getenv("CLOUD_URL", ""))
    cloud_model: str = Field(
        default_factory=lambda: os.getenv("CLOUD_MODEL", "Qwen/Qwen3.5-35B-A3B-AWQ")
    )
    cloud_api_key: str = Field(default_factory=lambda: os.getenv("CLOUD_API_KEY", ""))
    cloud_max_queue: int = int(os.getenv("CLOUD_MAX_QUEUE", "50"))
    cloud_latency_threshold_ms: float = float(os.getenv("CLOUD_LATENCY_THRESHOLD_MS", "5000"))

    # Cost controls
    daily_cloud_budget_usd: float = float(os.getenv("DAILY_CLOUD_BUDGET_USD", "5.00"))
    cloud_cost_per_1k_tokens: float = float(os.getenv("CLOUD_COST_PER_1K_TOKENS", "0.002"))

    # Persistent state (budget survives restarts; shared across workers).
    # Set to ":memory:" for an ephemeral per-process budget.
    state_db_path: str = Field(
        default_factory=lambda: os.getenv("STATE_DB_PATH", "aiburstcloud.db")
    )

    # Sensitivity keywords — force routing to local in both modes
    sensitive_keywords: list[str] = Field(
        default_factory=lambda: [
            kw.strip()
            for kw in os.getenv(
                "SENSITIVE_KEYWORDS",
                "ais,mmsi,imo,vessel,maritime,sigint,intelligence,classified,"
                "geoint,icd203,satellite,sentinel,umbra,sar,ads-b,icao,aircraft,track,"
                "pii,ssn,hipaa,phi,secret,top secret,noforn",
            ).split(",")
            if kw.strip()
        ]
    )


# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------


class BackendMetrics:
    def __init__(self, name: str):
        self.name = name
        self.active_requests: int = 0
        self.total_requests: int = 0
        self.total_tokens: int = 0
        self.total_latency_ms: float = 0.0
        self.last_health_check: float = 0.0
        self.status: BackendStatus = BackendStatus.HEALTHY
        self.errors_consecutive: int = 0

    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "active_requests": self.active_requests,
            "total_requests": self.total_requests,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "total_tokens": self.total_tokens,
        }


class CostTracker:
    """Budget accounting backed by a persistent, shared CostStore.

    The store survives restarts and is shared by all processes pointed at
    the same STATE_DB_PATH, so the daily cloud budget is enforced globally
    rather than per-process (a restart no longer resets today's spend).
    """

    def __init__(self, daily_budget: float, store: CostStore | None = None):
        self.daily_budget = daily_budget
        self.store = store if store is not None else CostStore(":memory:")

    def record_cloud_usage(self, tokens: int, cost_per_1k: float) -> None:
        self.store.add_cloud_usage(tokens, (tokens / 1000) * cost_per_1k)

    def record_local_usage(self, tokens: int) -> None:
        self.store.add_local_usage(tokens)

    @property
    def today_spend(self) -> float:
        return self.store.snapshot().today_spend

    @property
    def total_tokens_cloud(self) -> int:
        return self.store.snapshot().total_tokens_cloud

    @property
    def total_tokens_local(self) -> int:
        return self.store.snapshot().total_tokens_local

    @property
    def budget_remaining(self) -> float:
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
# HTTP proxy
# ---------------------------------------------------------------------------


async def proxy_to_backend(
    client: httpx.AsyncClient,
    url: str,
    model: str,
    payload: dict[str, Any],
    api_key: str | None = None,
    stream: bool = False,
) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {**payload, "model": model}

    # Ollama uses /api/chat, vLLM uses /v1/chat/completions
    # Detect by URL pattern
    if ":11434" in url and "/v1" not in url:
        endpoint = f"{url}/v1/chat/completions"
    else:
        endpoint = f"{url}/v1/chat/completions"

    if stream:
        req = client.build_request("POST", endpoint, json=payload, headers=headers)
        return await client.send(req, stream=True)
    else:
        return await client.post(endpoint, json=payload, headers=headers, timeout=120.0)


# ---------------------------------------------------------------------------
# Health checker
# ---------------------------------------------------------------------------


async def health_check_loop(
    client: httpx.AsyncClient,
    config: RouterConfig,
    local_metrics: BackendMetrics,
    cloud_metrics: BackendMetrics,
) -> None:
    while True:
        for _name, url, api_key, metrics in [
            ("local", config.local_url, None, local_metrics),
            ("cloud", config.cloud_url, config.cloud_api_key, cloud_metrics),
        ]:
            if not url:
                continue
            try:
                headers = {}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                # Try OpenAI /v1/models first, fall back to Ollama /api/tags
                check_url = f"{url}/v1/models"
                if ":11434" in url:
                    check_url = f"{url}/api/tags"
                r = await client.get(check_url, headers=headers, timeout=8.0)
                if r.status_code == 200:
                    metrics.status = BackendStatus.HEALTHY
                    metrics.errors_consecutive = 0
                else:
                    metrics.errors_consecutive += 1
            except Exception:
                metrics.errors_consecutive += 1

            if metrics.errors_consecutive >= 3:
                metrics.status = BackendStatus.DOWN
            elif metrics.errors_consecutive >= 1:
                metrics.status = BackendStatus.DEGRADED
            metrics.last_health_check = time.time()

        await asyncio.sleep(15)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

config = RouterConfig()
local_metrics = BackendMetrics("local")
cloud_metrics = BackendMetrics("cloud")
cost_tracker = CostTracker(
    daily_budget=config.daily_cloud_budget_usd,
    store=CostStore(config.state_db_path),
)


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
    task = asyncio.create_task(health_check_loop(client, config, local_metrics, cloud_metrics))
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

    if decision.backend == "local":
        metrics = local_metrics
        url = config.local_url
        model = config.local_model
        api_key = None
    else:
        metrics = cloud_metrics
        url = config.cloud_url
        model = config.cloud_model
        api_key = config.cloud_api_key or None

    metrics.active_requests += 1

    try:
        if stream:
            response = await proxy_to_backend(client, url, model, payload, api_key, stream=True)

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
            response = await proxy_to_backend(client, url, model, payload, api_key, stream=False)
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
        failover_backend = "cloud" if decision.backend == "local" else "local"
        if sensitivity != SensitivityLevel.SENSITIVE or failover_backend == "local":
            logger.warning(
                "failover",
                extra={"request_id": request_id, "from": decision.backend, "to": failover_backend},
            )
            try:
                is_cloud = failover_backend == "cloud"
                fo_url = config.cloud_url if is_cloud else config.local_url
                fo_model = config.cloud_model if is_cloud else config.local_model
                fo_key = (config.cloud_api_key or None) if is_cloud else None

                response = await proxy_to_backend(
                    client, fo_url, fo_model, payload, fo_key, stream=stream
                )
                if stream:
                    return StreamingResponse(
                        response.aiter_bytes(),
                        media_type="text/event-stream",
                        headers={
                            "X-Request-ID": request_id,
                            "X-Burst-Backend": failover_backend,
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
