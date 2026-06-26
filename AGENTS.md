# AGENTS.md — Development Context for Hullucinator

## What This Is

A FastAPI application with a web interface that orchestrates LLM calls to generate complete e-books from a user prompt. Pipeline: create → summary → outline → chapters → review → export.

## Core Principles

- After every change, update `README.md` and `AGENTS.md` if needed.
- Keep `AGENTS.md` file minimal — only critical guardrails and architectural principles. Documentation should be minimal because any code written should be self documenting in terms of code readability.
- `README.md` should only contain information useful to users who may wish to implement or use the application.
- After every change, run the full test suite prior to considering the task complete.
- **Follow software engineering best practices** and minimise future technical debt at all times.

## Credential Validation

**Book creation, retry, and manual review endpoints must validate API credentials before queuing.** The `_check_configured_and_connected()` function checks endpoint URL and model name, then sends a lightweight test request to the LLM provider's models endpoint to verify connectivity and credentials. This prevents books from being queued when the API key is missing or invalid, avoiding wasted background tasks that would fail later. The test request itself is the sole credential validator — it succeeds for endpoints that don't require API keys, and fails naturally when credentials are invalid. The basic `_check_configured()` function (checks endpoint URL and model name only, does not require API key) is used for read-only endpoints like `/api/config` and `/api/health`.

## Content Security Policy

**Never load external resources via CDN.** The app enforces a strict CSP that blocks all cross-origin requests. All fonts, stylesheets, and scripts must be self-hosted. After any frontend change, verify no CSP violations in the browser console.

## Testing

- **Never touch the real data directory during testing.** Tests must use `tmp_path` or `set_test_dirs(tmp_path)` to isolate from production data.
- Run tests with: `.venv/bin/pytest -x -q`
- The venv has no `pip` — use `uv` for package management.
- Async tests use `asyncio_mode = "auto"` (configured in `pyproject.toml`).
- When adding tests that write to disk or modify shared state, use appropriate isolation fixtures.

## Shared Configuration

**All tunable parameters flow from `app/config.py`.** This includes temperatures, system prompts, validation thresholds, concurrency limits, and UI settings. Never hardcode values in other modules — always reference the shared config. The frontend reads the same config via `GET /api/config-schema` to stay in sync.

Config sub-models:
- `GenerationConfig` — temperatures, system prompts, min chapter chars
- `ReviewConfig` — max turns, pass/fail scores, word thresholds, chunk size
- `ClientConfig` — retry counts, timeouts, jitter
- `ConcurrencyConfig` — max simultaneous generations
- `ValidationConfig` — validation thresholds
- `UISchema` — polling intervals, input limits

## Extending the System

- **New generation steps:** Add to the appropriate module. Add allowed transitions to the status module. Add a wrapping method to the orchestrator for status transitions and persistence.
- **New export formats:** Add to the exporter module following existing patterns.
- **New endpoints:** Define in the routes module under `/api/`. Use existing lookup and validation helpers.
- **Web UI changes:** Follow the split-file structure (config → utilities → renderers → app → settings → bootstrap). Load shared config before initializing any component.
- **Config changes:** All defaults flow from the shared config. Frontend and backend must stay in sync.
