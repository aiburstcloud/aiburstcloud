"""Unit tests for backend adapters."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.backends import OpenAIBackend, create_backends
from app.models import BackendMetrics, BackendStatus, RouterConfig

# ---------------------------------------------------------------------------
# OpenAIBackend
# ---------------------------------------------------------------------------


class TestOpenAIBackend:
    def test_init_sets_fields(self) -> None:
        b = OpenAIBackend(url="http://localhost:11434", model="llama3", name="local")
        assert b.name == "local"
        assert b.url == "http://localhost:11434"
        assert b.model == "llama3"
        assert b.api_key is None
        assert b.health_path == "/v1/models"
        assert isinstance(b.metrics, BackendMetrics)
        assert b.metrics.name == "local"

    def test_custom_health_path(self) -> None:
        b = OpenAIBackend(url="http://localhost:11434", model="llama3", health_path="/api/tags")
        assert b.health_path == "/api/tags"

    @pytest.mark.anyio
    async def test_health_check_uses_configured_path(self) -> None:
        b = OpenAIBackend(
            url="http://localhost:11434",
            model="llama3",
            name="local",
            health_path="/api/tags",
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = httpx.Response(200)

        result = await b.health_check(mock_client)

        assert result is True
        mock_client.get.assert_called_once_with(
            "http://localhost:11434/api/tags", headers={}, timeout=8.0
        )

    @pytest.mark.anyio
    async def test_health_check_v1_models_with_auth(self) -> None:
        b = OpenAIBackend(url="http://cloud:8000", model="qwen", api_key="sk-123", name="cloud")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = httpx.Response(200)

        result = await b.health_check(mock_client)

        assert result is True
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "http://cloud:8000/v1/models"
        assert call_args[1]["headers"]["Authorization"] == "Bearer sk-123"

    @pytest.mark.anyio
    async def test_health_check_returns_false_on_error(self) -> None:
        b = OpenAIBackend(url="http://localhost:11434", model="llama3", name="local")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.ConnectError("refused")

        result = await b.health_check(mock_client)
        assert result is False

    @pytest.mark.anyio
    async def test_health_check_returns_false_on_non_200(self) -> None:
        b = OpenAIBackend(url="http://localhost:11434", model="llama3", name="local")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = httpx.Response(503)

        result = await b.health_check(mock_client)
        assert result is False

    @pytest.mark.anyio
    async def test_send_calls_completions_endpoint(self) -> None:
        b = OpenAIBackend(url="http://localhost:11434", model="llama3", name="local")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = httpx.Response(200, json={"choices": []})

        payload = {"messages": [{"role": "user", "content": "hi"}]}
        await b.send(mock_client, payload, stream=False)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:11434/v1/chat/completions"
        assert call_args[1]["json"]["model"] == "llama3"
        assert "Authorization" not in call_args[1]["headers"]

    @pytest.mark.anyio
    async def test_send_includes_auth_header(self) -> None:
        b = OpenAIBackend(url="http://cloud:8000", model="qwen", api_key="sk-abc", name="cloud")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = httpx.Response(200, json={})

        payload = {"messages": [{"role": "user", "content": "hi"}]}
        await b.send(mock_client, payload, stream=False)

        call_args = mock_client.post.call_args
        assert call_args[1]["headers"]["Authorization"] == "Bearer sk-abc"

    @pytest.mark.anyio
    async def test_send_groq_endpoint(self) -> None:
        b = OpenAIBackend(
            url="https://api.groq.com/openai",
            model="llama-3.3-70b-versatile",
            api_key="gsk-test",
            name="cloud",
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = httpx.Response(200, json={})

        payload = {"messages": [{"role": "user", "content": "hi"}]}
        await b.send(mock_client, payload, stream=False)

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.groq.com/openai/v1/chat/completions"
        assert call_args[1]["json"]["model"] == "llama-3.3-70b-versatile"
        assert call_args[1]["headers"]["Authorization"] == "Bearer gsk-test"


# ---------------------------------------------------------------------------
# create_backends factory
# ---------------------------------------------------------------------------


class TestCreateBackends:
    def test_ollama_provider_uses_api_tags_health(self) -> None:
        config = RouterConfig(
            local_url="http://localhost:11434",
            local_model="llama3",
            cloud_url="http://cloud:8000",
            cloud_model="qwen",
        )
        env = {"LOCAL_PROVIDER": "ollama", "CLOUD_PROVIDER": "generic"}
        with patch.dict("os.environ", env, clear=False):
            local, cloud = create_backends(config)

        assert isinstance(local, OpenAIBackend)
        assert local.health_path == "/api/tags"
        assert local.name == "local"

    def test_vllm_provider_uses_v1_models_health(self) -> None:
        config = RouterConfig(
            local_url="http://localhost:8080",
            local_model="llama3",
            cloud_url="http://cloud:8000",
            cloud_model="qwen",
        )
        env = {"LOCAL_PROVIDER": "vllm", "CLOUD_PROVIDER": "generic"}
        with patch.dict("os.environ", env, clear=False):
            local, _cloud = create_backends(config)

        assert isinstance(local, OpenAIBackend)
        assert local.health_path == "/v1/models"
        assert local.name == "local"

    def test_groq_provider_creates_correct_backend(self) -> None:
        config = RouterConfig(
            local_url="http://localhost:11434",
            local_model="llama3",
            cloud_url="",
            cloud_model="",
        )
        env = {
            "LOCAL_PROVIDER": "ollama",
            "CLOUD_PROVIDER": "groq",
            "GROQ_API_KEY": "gsk-test-key",
            "GROQ_MODEL": "mixtral-8x7b-32768",
        }
        with patch.dict("os.environ", env, clear=False):
            _local, cloud = create_backends(config)

        assert isinstance(cloud, OpenAIBackend)
        assert cloud.url == "https://api.groq.com/openai"
        assert cloud.api_key == "gsk-test-key"
        assert cloud.model == "mixtral-8x7b-32768"

    def test_generic_cloud_uses_config_values(self) -> None:
        config = RouterConfig(
            local_url="http://localhost:11434",
            local_model="llama3",
            cloud_url="http://runpod:8000",
            cloud_model="qwen-72b",
            cloud_api_key="rp-key",
        )
        env = {"LOCAL_PROVIDER": "ollama", "CLOUD_PROVIDER": "generic"}
        with patch.dict("os.environ", env, clear=False):
            _local, cloud = create_backends(config)

        assert cloud.url == "http://runpod:8000"
        assert cloud.model == "qwen-72b"

    def test_together_provider_creates_correct_backend(self) -> None:
        config = RouterConfig()
        env = {"CLOUD_PROVIDER": "together", "TOGETHER_API_KEY": "sk-together"}
        with patch.dict("os.environ", env, clear=False):
            _local, cloud = create_backends(config)
        assert cloud.url == "https://api.together.xyz"
        assert cloud.model == "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
        assert cloud.api_key == "sk-together"

    def test_openrouter_provider_creates_correct_backend(self) -> None:
        config = RouterConfig()
        env = {"CLOUD_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "sk-or"}
        with patch.dict("os.environ", env, clear=False):
            _local, cloud = create_backends(config)
        assert cloud.url == "https://openrouter.ai/api"
        assert cloud.model == "anthropic/claude-3.5-sonnet"
        assert cloud.api_key == "sk-or"

    def test_cerebras_provider_creates_correct_backend(self) -> None:
        config = RouterConfig()
        env = {"CLOUD_PROVIDER": "cerebras", "CEREBRAS_API_KEY": "sk-cb"}
        with patch.dict("os.environ", env, clear=False):
            _local, cloud = create_backends(config)
        assert cloud.url == "https://api.cerebras.ai"
        assert cloud.model == "llama3.1-70b"
        assert cloud.api_key == "sk-cb"

    def test_each_backend_has_independent_metrics(self) -> None:
        config = RouterConfig(
            local_url="http://localhost:11434",
            local_model="llama3",
            cloud_url="http://cloud:8000",
            cloud_model="qwen",
        )
        env = {"LOCAL_PROVIDER": "ollama", "CLOUD_PROVIDER": "generic"}
        with patch.dict("os.environ", env, clear=False):
            local, cloud = create_backends(config)

        local.metrics.total_requests = 10
        assert cloud.metrics.total_requests == 0

    def test_health_status_starts_healthy(self) -> None:
        config = RouterConfig(
            local_url="http://localhost:11434",
            local_model="llama3",
            cloud_url="http://cloud:8000",
            cloud_model="qwen",
        )
        env = {"LOCAL_PROVIDER": "ollama", "CLOUD_PROVIDER": "generic"}
        with patch.dict("os.environ", env, clear=False):
            local, cloud = create_backends(config)

        assert local.metrics.status == BackendStatus.HEALTHY
        assert cloud.metrics.status == BackendStatus.HEALTHY

    def test_missing_groq_key_logs_warning(self) -> None:
        config = RouterConfig(
            local_url="http://localhost:11434",
            local_model="llama3",
            cloud_url="",
            cloud_model="",
        )
        env = {"LOCAL_PROVIDER": "ollama", "CLOUD_PROVIDER": "groq", "GROQ_API_KEY": ""}
        with (
            patch.dict("os.environ", env, clear=False),
            patch("app.backends.logger") as mock_logger,
        ):
            _local, cloud = create_backends(config)

        mock_logger.warning.assert_called_once()
        assert "GROQ_API_KEY" in mock_logger.warning.call_args[0][0]
        assert cloud.api_key == ""
