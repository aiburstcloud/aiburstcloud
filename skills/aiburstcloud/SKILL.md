---
name: aiburstcloud
description: Dual-mode cloud burst LLM router. Route inference between local GPU and
  cloud with automatic failover, data sovereignty, and cost controls. Manage and query
  your AI Burst Cloud instance.
version: 0.1.0
homepage: https://aiburstcloud.com
when: When user mentions 'burst routing', 'cloud burst', 'local inference', 'LLM routing',
  'aiburstcloud', 'AI Burst Cloud', 'inference routing', 'edge burst', or wants to
  route requests between local and cloud LLM backends
examples:
  - start aiburstcloud router
  - check my aiburstcloud health status
  - switch burst mode to cloud_burst
  - show my cloud spend today
  - route this request locally for privacy
  - set daily cloud budget to $10
metadata:
  openclaw:
    emoji: "\u26A1"
    os:
      - darwin
      - linux
    primaryEnv: CLOUD_API_KEY
    requires:
      anyBins:
        - python3
        - python
      bins:
        - curl
      env:
        - LOCAL_URL
    install:
      - name: aiburstcloud
        type: uv
        package: "git+https://github.com/aiburstcloud/aiburstcloud.git"
---

# AI Burst Cloud Skill

You are managing an AI Burst Cloud instance — a dual-mode cloud burst LLM router that routes inference between local GPUs and cloud backends.

## Setup

If AI Burst Cloud is not installed, install it:

```bash
pip install git+https://github.com/aiburstcloud/aiburstcloud.git
```

Or with the one-line installer:

```bash
curl -fsSL https://raw.githubusercontent.com/aiburstcloud/aiburstcloud/main/install.sh | bash
```

## Configuration

AI Burst Cloud is configured via environment variables. The config file is at `~/.aiburstcloud/.env` or in the working directory `.env`.

Required variables:
- `BURST_MODE` — `edge_burst` (local primary, cloud overflow) or `cloud_burst` (cloud primary, local for sensitive data). Default: `edge_burst`
- `LOCAL_URL` — Local inference endpoint (e.g., `http://localhost:11434` for Ollama)
- `LOCAL_MODEL` — Model name for local backend
- `CLOUD_URL` — Cloud inference endpoint (RunPod, Modal, any OpenAI-compatible)
- `CLOUD_MODEL` — Model name for cloud backend
- `CLOUD_API_KEY` — Bearer token for cloud endpoint
- `DAILY_CLOUD_BUDGET_USD` — Max daily cloud spend (default: `5.00`)

## Starting the Router

Start with defaults:
```bash
aiburstcloud
```

Start with specific options:
```bash
aiburstcloud --port 9000 --burst-mode cloud_burst
```

Start with Docker:
```bash
cd /path/to/aiburstcloud && docker compose up -d
```

The router listens on `http://localhost:8000` by default.

## Checking Status

Check health and routing status:
```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

This returns:
- Backend status (local and cloud: healthy/unhealthy)
- Active queue depths
- Current burst mode
- Daily cloud spend and remaining budget
- Latency metrics

## Checking Metrics

Get Prometheus-compatible metrics:
```bash
curl -s http://localhost:8000/metrics
```

## Sending Requests

AI Burst Cloud exposes an OpenAI-compatible API. Send requests to it like any OpenAI endpoint:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "burst-auto", "messages": [{"role": "user", "content": "Hello!"}]}'
```

## Per-Request Mode Override

Override the burst mode for a single request using the `X-Burst-Mode` header:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Burst-Mode: cloud_burst" \
  -d '{"model": "burst-auto", "messages": [{"role": "user", "content": "Hello!"}]}'
```

## Response Headers

Every response includes routing metadata:
- `X-Burst-Backend` — Which backend handled the request (`local` or `cloud`)
- `X-Burst-Mode` — Active burst mode
- `X-Burst-Reason` — Why that backend was chosen
- `X-Burst-Sensitivity` — Detected sensitivity level (`public` or `sensitive`)

## Switching Modes

To switch between edge-first and cloud-first:

```bash
# Set environment variable and restart
export BURST_MODE=cloud_burst
aiburstcloud
```

Or update the `.env` file and restart.

## Listing Models

```bash
curl -s http://localhost:8000/v1/models | python3 -m json.tool
```

## Troubleshooting

1. **Router won't start**: Check that `LOCAL_URL` points to a running Ollama/vLLM instance
2. **Cloud requests failing**: Verify `CLOUD_URL` and `CLOUD_API_KEY` are set correctly
3. **Everything routing locally**: Check if daily budget is exhausted via `/health`
4. **Sensitive data going to cloud**: Check `SENSITIVE_KEYWORDS` env var or add keywords

## Links

- GitHub: https://github.com/aiburstcloud/aiburstcloud
- Website: https://aiburstcloud.com
- Issues: https://github.com/aiburstcloud/aiburstcloud/issues
