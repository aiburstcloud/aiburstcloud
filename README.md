# AI Burst Cloud

[![GitHub stars](https://img.shields.io/github/stars/aiburstcloud/aiburstcloud?style=social)](https://github.com/aiburstcloud/aiburstcloud/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![GitHub issues](https://img.shields.io/github/issues/aiburstcloud/aiburstcloud)](https://github.com/aiburstcloud/aiburstcloud/issues)
[![GitHub last commit](https://img.shields.io/github/last-commit/aiburstcloud/aiburstcloud)](https://github.com/aiburstcloud/aiburstcloud/commits/main)

**Dual-mode cloud burst LLM router.** Route inference between local GPUs and cloud serverless backends with automatic failover, data sovereignty controls, and cost management.

[aiburstcloud.com](https://aiburstcloud.com)

<p align="center">
  <img src="https://raw.githubusercontent.com/aiburstcloud/docs/main/demo/aiburstcloud-demo.gif" alt="AI Burst Cloud demo" width="800">
</p>

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

**Claude Code skill:**

Clone the repo and the skill is auto-discovered:

```bash
git clone https://github.com/aiburstcloud/aiburstcloud.git
cd aiburstcloud
# Then in Claude Code:
# /aiburstcloud start
# /aiburstcloud health
# /aiburstcloud test
```

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

Contributions are welcome. Here's how to get started.

### Development setup

```bash
git clone https://github.com/aiburstcloud/aiburstcloud.git
cd aiburstcloud
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# Edit .env with your local/cloud endpoints
aiburstcloud
```

### Project structure

```
aiburstcloud/
  app/
    router.py          # Core routing engine and FastAPI app
    cli.py             # CLI entry point (aiburstcloud command)
    __main__.py        # python -m app support
    __init__.py        # Package version
  skills/
    aiburstcloud/
      SKILL.md         # OpenClaw skill definition
      nemoclaw/
        network-policy.yaml  # NemoClaw sandbox network policy
  scripts/
    audit.sh           # Repo consistency checker
  install.sh           # One-line curl installer
  pyproject.toml       # Package metadata and dependencies
  Dockerfile           # Container build
  docker-compose.yml   # Docker Compose orchestration
  .env.example         # Default environment variables
```

### Making changes

1. **Fork** the repo and create a branch from `main`
2. Make your changes
3. If you add a new environment variable, document it in:
   - `README.md` (environment variables table)
   - `.env.example`
   - `skills/aiburstcloud/SKILL.md` (if relevant to the skill)
4. If you change the version, update it in all three places:
   - `pyproject.toml`
   - `app/__init__.py`
   - `skills/aiburstcloud/SKILL.md`
5. Run the audit: `./scripts/audit.sh`
6. Submit a pull request

### Repo audit

Before submitting a PR, run the audit script to check consistency:

```bash
./scripts/audit.sh
```

This validates version sync, env var documentation, dependency consistency, install method docs, skill/policy validity, and repo links. Exits `0` on success, `1` on failure.

### Areas we'd love help with

- **New backend integrations** — adapters for Groq, Cerebras, AWS Bedrock, etc.
- **Advanced sensitivity classifiers** — NLP-based PII/PHI detection beyond keyword matching
- **Dashboard UI** — web interface for routing analytics, cost tracking, and mode switching
- **Helm chart** — Kubernetes deployment
- **Tests** — unit and integration test coverage
- **Documentation** — tutorials, integration guides, architecture deep-dives

### Code style

- Keep it simple. No abstractions for one-time operations.
- Follow existing patterns in `router.py`.
- No type stubs, docstrings, or comments unless the logic isn't self-evident.

## Support

If AI Burst Cloud helps you save on inference costs or keep sensitive data local, consider giving it a star. It helps others discover the project.

[![Star on GitHub](https://img.shields.io/github/stars/aiburstcloud/aiburstcloud?style=social)](https://github.com/aiburstcloud/aiburstcloud/stargazers)

## License

MIT — see [LICENSE](LICENSE)
