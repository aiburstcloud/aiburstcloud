# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in AI Burst Cloud, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, email the details to the maintainers or use [GitHub's private vulnerability reporting](https://github.com/aiburstcloud/aiburstcloud/security/advisories/new).

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 48 hours and aim to release a fix within 7 days for critical issues.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Security Design

AI Burst Cloud is designed with security in mind:

- **Sensitive data stays local.** The sensitivity classifier routes flagged requests to your local GPU, never to cloud backends.
- **No data storage.** AI Burst Cloud is a pass-through router. It does not log, store, or cache request/response content.
- **No telemetry.** No data is sent to AI Burst Cloud maintainers or any third party.
- **API keys are never logged.** Cloud API keys are used for authentication only and are not included in logs or metrics.
- **NemoClaw compatible.** Ships with a deny-by-default network policy for sandboxed deployments.

## Dependencies

We keep dependencies minimal (FastAPI, uvicorn, httpx, pydantic) and pin minimum versions in `pyproject.toml`. Run `pip audit` to check for known vulnerabilities in installed packages.
