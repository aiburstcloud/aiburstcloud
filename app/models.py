"""Shared models for AI Burst Cloud — used by both router and backends."""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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
