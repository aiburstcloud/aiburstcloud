"""
Backend adapters for AI Burst Cloud.

Each backend encapsulates connection info, request proxying, and health checking.
The router dispatches to backends via the Backend protocol.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol

import httpx

from app.models import BackendMetrics, RouterConfig

logger = logging.getLogger("aiburstcloud")


class Backend(Protocol):
    name: str
    metrics: BackendMetrics

    async def send(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        stream: bool = False,
    ) -> httpx.Response: ...

    async def health_check(self, client: httpx.AsyncClient) -> bool: ...


class OpenAIBackend:
    """Generic OpenAI-compatible backend. Covers Ollama, vLLM, Groq, Cerebras, etc."""

    def __init__(
        self,
        url: str,
        model: str,
        name: str = "cloud",
        api_key: str | None = None,
        health_path: str = "/v1/models",
    ) -> None:
        self.name = name
        self.url = url
        self.model = model
        self.api_key = api_key
        self.health_path = health_path
        self.metrics = BackendMetrics(name)

    async def send(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        stream: bool = False,
    ) -> httpx.Response:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        endpoint = f"{self.url}/v1/chat/completions"
        payload = {**payload, "model": self.model}

        if stream:
            req = client.build_request("POST", endpoint, json=payload, headers=headers)
            return await client.send(req, stream=True)
        return await client.post(endpoint, json=payload, headers=headers, timeout=120.0)

    async def health_check(self, client: httpx.AsyncClient) -> bool:
        try:
            headers: dict[str, str] = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            r = await client.get(f"{self.url}{self.health_path}", headers=headers, timeout=8.0)
            return r.status_code == 200
        except Exception:
            return False


CLOUD_PROVIDERS: dict[str, dict[str, str]] = {
    "groq": {
        "url": "https://api.groq.com/openai",
        "default_model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
    },
    "together": {
        "url": "https://api.together.xyz",
        "default_model": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "key_env": "TOGETHER_API_KEY",
        "model_env": "TOGETHER_MODEL",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api",
        "default_model": "anthropic/claude-3.5-sonnet",
        "key_env": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_MODEL",
    },
    "cerebras": {
        "url": "https://api.cerebras.ai",
        "default_model": "llama3.1-70b",
        "key_env": "CEREBRAS_API_KEY",
        "model_env": "CEREBRAS_MODEL",
    },
}


def _create_provider_backend(provider_name: str, provider_cfg: dict[str, str]) -> Backend:
    """Create a backend from a named provider config."""
    api_key = os.getenv(provider_cfg["key_env"], "")
    model = os.getenv(provider_cfg["model_env"], provider_cfg["default_model"])

    if not api_key:
        logger.warning(
            f"CLOUD_PROVIDER={provider_name} but {provider_cfg['key_env']} is empty — "
            f"cloud backend will fail health checks until configured"
        )

    return OpenAIBackend(
        url=provider_cfg["url"],
        model=model,
        name="cloud",
        api_key=api_key,
    )


def create_backends(config: RouterConfig) -> tuple[Backend, Backend]:
    """Create local and cloud backend instances from config."""
    local_provider = os.getenv("LOCAL_PROVIDER", "ollama")
    health_path = "/api/tags" if local_provider == "ollama" else "/v1/models"

    local: Backend = OpenAIBackend(
        url=config.local_url,
        model=config.local_model,
        name="local",
        health_path=health_path,
    )

    cloud_provider = os.getenv("CLOUD_PROVIDER", "generic")

    if cloud_provider in CLOUD_PROVIDERS:
        cloud = _create_provider_backend(cloud_provider, CLOUD_PROVIDERS[cloud_provider])
    else:
        cloud = OpenAIBackend(
            url=config.cloud_url,
            model=config.cloud_model,
            name="cloud",
            api_key=config.cloud_api_key or None,
        )

    return local, cloud
