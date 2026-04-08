---
name: aiburstcloud
description: Manage AI Burst Cloud — the dual-mode cloud burst LLM router. Start/stop the server, check health and cloud spend, switch burst modes, send test requests, view routing logs. Use when user mentions aiburstcloud, burst routing, inference routing, or cloud spend.
argument-hint: "[start|stop|health|spend|mode|test|logs] [args...]"
allowed-tools: Bash(aiburstcloud *) Bash(curl *) Bash(pip install *) Bash(docker compose *) Bash(ps aux *) Bash(kill *) Bash(lsof *) Read Write Grep
---

# AI Burst Cloud Manager

You are managing an AI Burst Cloud instance — a dual-mode LLM router that routes inference between local GPUs and cloud backends based on privacy, cost, and capacity.

## Commands

Handle user requests based on the argument passed (available via `$0`):

### start — Start the router

Check if already running first:
```bash
lsof -i :8000 -t 2>/dev/null
```

If not running, start it:
```bash
aiburstcloud
```

With options:
```bash
aiburstcloud --port $1 --burst-mode $2
```

If aiburstcloud is not installed:
```bash
pip install git+https://github.com/aiburstcloud/aiburstcloud.git
```

### stop — Stop the router

```bash
kill $(lsof -i :8000 -t) 2>/dev/null && echo "Stopped" || echo "Not running"
```

### health — Check health and backend status

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Report: backend status (local/cloud), queue depths, latency, and whether both backends are healthy.

### spend — Check cloud spend and budget

```bash
curl -s http://localhost:8000/health | python3 -c "
import sys, json
h = json.load(sys.stdin)
c = h.get('cost', {})
print(f\"Budget:    \${c.get('daily_budget_usd', 0):.2f}/day\")
print(f\"Spent:     \${c.get('spent_today_usd', 0):.2f}\")
print(f\"Remaining: \${c.get('remaining_usd', 0):.2f}\")
print(f\"Cloud reqs: {c.get('requests_to_cloud_today', 0)}\")
"
```

### mode — Show or switch burst mode

Show current mode:
```bash
curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin).get('burst_mode','unknown'))"
```

To switch modes, the user must update the `BURST_MODE` environment variable and restart. Guide them:
1. Set `BURST_MODE=edge_burst` or `BURST_MODE=cloud_burst`
2. Restart the router

### test — Send a test request

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "burst-auto", "messages": [{"role": "user", "content": "Hello, this is a test request."}]}' | python3 -m json.tool
```

Check the response headers for routing info:
```bash
curl -si http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "burst-auto", "messages": [{"role": "user", "content": "Hello"}]}' 2>&1 | grep -i "x-burst"
```

Send a sensitive request (should force local routing):
```bash
curl -si http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "burst-auto", "messages": [{"role": "user", "content": "Analyze this classified SIGINT report."}]}' 2>&1 | grep -i "x-burst"
```

Override mode per-request:
```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Burst-Mode: cloud_burst" \
  -d '{"model": "burst-auto", "messages": [{"role": "user", "content": "Hello"}]}' | python3 -m json.tool
```

### logs — View metrics

```bash
curl -s http://localhost:8000/metrics
```

### models — List available models

```bash
curl -s http://localhost:8000/v1/models | python3 -m json.tool
```

## Dynamic Status

Current server status: !`curl -s http://localhost:8000/health 2>/dev/null | python3 -c "import sys,json; h=json.load(sys.stdin); print(f\"{h.get('burst_mode','?')} | local:{h['backends']['local']['status']} cloud:{h['backends']['cloud']['status']} | spent:\${h['cost']['spent_today_usd']:.2f}/\${h['cost']['daily_budget_usd']:.2f}\")" 2>/dev/null || echo "not running"`

## Response Headers

Every routed request returns these headers — always check them:
- `X-Burst-Backend` — which backend handled it (local/cloud)
- `X-Burst-Mode` — active burst mode
- `X-Burst-Reason` — why that backend was chosen
- `X-Burst-Sensitivity` — detected sensitivity level

## Troubleshooting

- **Port in use**: `lsof -i :8000` to find what's using it
- **Cloud requests failing**: Check `CLOUD_URL` and `CLOUD_API_KEY` env vars
- **Everything routing locally**: Budget may be exhausted — check `/health`
- **Sensitive data going to cloud**: Add keywords to `SENSITIVE_KEYWORDS` env var

## Links

- Repo: https://github.com/aiburstcloud/aiburstcloud
- Docs: https://aiburstcloud.com
