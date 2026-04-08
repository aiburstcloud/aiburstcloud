# AI Burst Cloud

**Dual-mode cloud burst LLM router.** Route inference between local GPUs and cloud serverless backends with automatic failover, data sovereignty controls, and cost management.

[aiburstcloud.com](https://aiburstcloud.com)

## Install

**One line:**

```bash
curl -fsSL https://raw.githubusercontent.com/aiburstcloud/aiburstcloud/main/install.sh | bash
```

**Or pip:**

```bash
pip install git+https://github.com/aiburstcloud/aiburstcloud.git
```

**Then run:**

```bash
aiburstcloud
```

**OpenClaw / NemoClaw skill:**

```bash
openclaw skills install aiburstcloud
```

Or copy the `skills/aiburstcloud/` directory into your OpenClaw skills folder. Works with NemoClaw sandboxing out of the box (network policy included).

## Two burst modes

### Edge-first burst (`edge_burst`)

Local GPU handles baseline traffic. Cloud bursts only when local is overloaded or down.

```
User -> [AI Burst Cloud] -> Local GPU (primary, free)
                         \-> Cloud GPU (burst when queue > 5)
```

**Best for:** Cost optimization. Data stays local by default. Cloud is the safety valve.

### Cloud-first burst (`cloud_burst`)

Cloud handles everything for maximum speed and scale. Sensitive requests automatically "burst down" to local/on-prem GPU.

```
User -> [AI Burst Cloud] -> Cloud GPU (primary, fast)
                         \-> Local GPU (sensitive data only)
```

**Best for:** Performance-first teams that need sovereignty-on-demand for regulated data.

## Three-axis routing engine

| Axis | Logic | Applies to |
|------|-------|------------|
| **Data sovereignty** | Sensitive keywords detected -> always local | Both modes |
| **Cost minimization** | Daily cloud budget cap -> local when exhausted | Both modes |
| **Latency optimization** | Primary overloaded -> burst to secondary | Both modes |

## Quick start

### With pip

```bash
# Install
pip install git+https://github.com/aiburstcloud/aiburstcloud.git

# Set your cloud endpoint (optional — works local-only out of the box)
export CLOUD_URL=https://api.runpod.ai/v2/your-endpoint-id/openai
export CLOUD_API_KEY=your_api_key_here

# Start
aiburstcloud
```

### With Docker

```bash
git clone https://github.com/aiburstcloud/aiburstcloud.git
cd aiburstcloud
cp .env.example .env
# Edit .env with your cloud endpoint and API key
docker compose up -d
```

### Test it

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "burst-auto",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## CLI options

```bash
aiburstcloud                            # start on 0.0.0.0:8000
aiburstcloud --port 9000                # custom port
aiburstcloud --burst-mode cloud_burst   # override burst mode
aiburstcloud --workers 4                # multiple workers
aiburstcloud --version                  # show version
```

## Switch modes

Set `BURST_MODE` in your environment:

```bash
# Edge-first (default)
BURST_MODE=edge_burst aiburstcloud

# Cloud-first
BURST_MODE=cloud_burst aiburstcloud
```

Or override per-request with a header:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "X-Burst-Mode: cloud_burst" \
  -H "Content-Type: application/json" \
  -d '{"model": "burst-auto", "messages": [{"role": "user", "content": "Hello!"}]}'
```

## Response headers

Every response includes routing metadata:

| Header | Example | Description |
|--------|---------|-------------|
| `X-Burst-Backend` | `local` | Which backend handled the request |
| `X-Burst-Mode` | `edge_burst` | Active burst mode |
| `X-Burst-Reason` | `local_overloaded_burst_to_cloud` | Why that backend was chosen |
| `X-Burst-Sensitivity` | `public` | Detected sensitivity level |

## Observability

- `GET /health` — backend status, queue depths, cost tracking
- `GET /metrics` — Prometheus-compatible plaintext metrics
- `GET /v1/models` — OpenAI-compatible model listing

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BURST_MODE` | `edge_burst` | `edge_burst` or `cloud_burst` |
| `LOCAL_URL` | `http://localhost:11434` | Ollama / local vLLM endpoint |
| `LOCAL_MODEL` | `qwen3.5-35b-a3b` | Model name for local backend |
| `LOCAL_MAX_QUEUE` | `5` | Max concurrent local requests before burst |
| `LOCAL_LATENCY_THRESHOLD_MS` | `2000` | Avg latency trigger for burst |
| `CLOUD_URL` | — | vLLM endpoint (RunPod / Modal / any) |
| `CLOUD_MODEL` | `Qwen/Qwen3.5-35B-A3B-AWQ` | Model name for cloud backend |
| `CLOUD_API_KEY` | — | Bearer token for cloud endpoint |
| `CLOUD_MAX_QUEUE` | `50` | Max concurrent cloud requests (cloud_burst mode) |
| `CLOUD_LATENCY_THRESHOLD_MS` | `5000` | Avg latency trigger (cloud_burst mode) |
| `DAILY_CLOUD_BUDGET_USD` | `5.00` | Max daily cloud spend before cutoff |
| `CLOUD_COST_PER_1K_TOKENS` | `0.002` | Estimated cost per 1K tokens |
| `SENSITIVE_KEYWORDS` | *(see code)* | Comma-separated keywords forcing local routing |

## Compatible backends

**Local:** Ollama, vLLM, llama.cpp (OpenAI-compatible mode), LM Studio, LocalAI

**Cloud:** RunPod Serverless, Modal, Google Cloud Run GPU, any OpenAI-compatible vLLM endpoint

## OpenClaw / NemoClaw Skill

AI Burst Cloud ships as an OpenClaw skill. Install it with:

```bash
openclaw skills install aiburstcloud
```

Or manually copy `skills/aiburstcloud/` into any of these directories:
- `<workspace>/skills/`
- `~/.openclaw/skills/`
- `~/.agents/skills/`

The skill lets your AI agent manage the burst router: start/stop, check health, switch modes, monitor spend, and send routed requests.

**NemoClaw compatible:** Includes a deny-by-default network policy at `skills/aiburstcloud/nemoclaw/network-policy.yaml`. Local inference is always allowed. Cloud provider egress requires operator approval.

## Contributing

### Repo audit

Before submitting a PR, run the audit script to check consistency across the project:

```bash
./scripts/audit.sh
```

This validates:
- Version numbers match across `pyproject.toml`, `app/__init__.py`, and `skills/aiburstcloud/SKILL.md`
- All environment variables in code are documented in README and `.env.example`
- Dependencies are in sync between `pyproject.toml` and `requirements.txt`
- All install methods are documented (pip, curl, Docker, OpenClaw)
- Dockerfile, OpenClaw skill, and NemoClaw network policy are valid
- All repository links point to `aiburstcloud/aiburstcloud`

The script exits `0` on success and `1` if any check fails.

## License

MIT — see [LICENSE](LICENSE)
