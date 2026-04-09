# Changelog

All notable changes to AI Burst Cloud will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-04-09

### Added
- Dual-mode cloud burst routing engine (`edge_burst` and `cloud_burst`)
- Three-axis decision engine: data sovereignty, cost minimization, latency optimization
- OpenAI-compatible `/v1/chat/completions` API
- Per-request mode override via `X-Burst-Mode` header
- Routing metadata in response headers (`X-Burst-Backend`, `X-Burst-Reason`, `X-Burst-Sensitivity`)
- Daily cloud budget cap with automatic local fallback
- Sensitive keyword classifier for data sovereignty enforcement
- Health endpoint (`/health`) with backend status, queue depths, and cost tracking
- Prometheus-compatible metrics endpoint (`/metrics`)
- Model listing endpoint (`/v1/models`)
- Automatic health checking and failover
- Streaming support
- CLI entry point: `aiburstcloud` command with `--port`, `--burst-mode`, `--workers` flags
- `python -m app` support
- One-line curl installer (`install.sh`)
- pip installable from GitHub
- Docker and Docker Compose support
- OpenClaw skill with full frontmatter and install spec
- NemoClaw network policy (deny-by-default egress)
- Claude Code skill with auto-discovery
- Repo audit script (`scripts/audit.sh`)
- GitHub issue templates (bug, feature, backend integration)
- PR template with audit checklist
