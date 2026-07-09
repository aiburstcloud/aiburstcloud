# Contributing to AI Burst Cloud

Contributions are welcome. This guide covers everything you need to get a change from idea to merged PR.

## Development setup

```bash
git clone https://github.com/aiburstcloud/aiburstcloud.git
cd aiburstcloud
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with your local/cloud endpoints
aiburstcloud
```

## Running tests

```bash
python -m pytest tests/ -v
```

The tests cover the routing decision engine, sensitivity classifier, cost tracker, and observability endpoints. They run offline — no live backends needed.

## Making changes

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
5. Run the tests: `python -m pytest tests/`
6. Run the audit: `./scripts/audit.sh`
7. Submit a pull request

## Repo audit

Before submitting a PR, run the audit script to check consistency:

```bash
./scripts/audit.sh
```

This validates version sync, env var documentation, dependency consistency, install method docs, skill/policy validity, and repo links. Exits `0` on success, `1` on failure. The same script runs in CI on every PR.

## Areas we'd love help with

- **New backend integrations** — adapters for Groq, Cerebras, AWS Bedrock, etc.
- **Advanced sensitivity classifiers** — NLP-based PII/PHI detection beyond keyword matching
- **Dashboard UI** — web interface for routing analytics, cost tracking, and mode switching
- **Helm chart** — Kubernetes deployment
- **Tests** — expand unit and integration test coverage
- **Documentation** — tutorials, integration guides, architecture deep-dives

## Code style

- Keep it simple. No abstractions for one-time operations.
- Follow existing patterns in `router.py`.
- No type stubs, docstrings, or comments unless the logic isn't self-evident.

## Reporting issues

- **Bugs and feature requests** — use the [issue templates](https://github.com/aiburstcloud/aiburstcloud/issues/new/choose)
- **Security vulnerabilities** — do not open a public issue; see [SECURITY.md](SECURITY.md)

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be kind.
