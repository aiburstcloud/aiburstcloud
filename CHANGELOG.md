# Changelog

All notable changes to AI Burst Cloud will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Persistent shared budget state (`app/state.py`): daily cloud spend and token counters now live in a SQLite store (`STATE_DB_PATH`, default `aiburstcloud.db`), so the budget survives restarts and is enforced across multiple uvicorn workers or router replicas sharing the file. Set `STATE_DB_PATH=:memory:` for the old ephemeral per-process behavior. Inspired by the shared-context design in DeLM (arXiv:2606.10662).
- Docker Compose named volume (`aiburstcloud-state`) so the budget survives container restarts

### Fixed
- Restarting the router no longer resets the daily cloud budget to zero, and `--workers N` no longer creates N independent budgets

## [0.1.1] - 2026-07-13

### Added
- Unit test suite for the routing engine (`tests/test_router.py`): sensitivity classifier, cost tracker, dual-mode route decisions, observability endpoints
- `pytest` runs in CI across Python 3.10–3.13
- `dev` optional dependency group (`pip install -e ".[dev]"`)
- CI status badge in README
- `CONTRIBUTING.md`
- Issue template `config.yml` (blank issues disabled, security policy and website links)

### Fixed
- `scripts/audit.sh` aborted on its first successful check: `((PASS++))` returns exit status 1 when the counter is 0, which `set -e` treats as a failure. This made the CI audit job fail even though every check passed.

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
