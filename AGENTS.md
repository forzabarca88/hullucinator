# AGENTS.md — Development Context for Hullucinator

## What This Is

A FastAPI application with a web interface that orchestrates LLM calls to generate complete e-books from a user prompt. Pipeline: create → summary → outline → chapters → review → export.

## Core Principles

- After every change, update `README.md` and `AGENTS.md` if needed.
- Keep `AGENTS.md` file minimal — only critical guardrails and architectural principles. Documentation should be minimal because any code written should be self documenting in terms of code readability.
- `README.md` should only contain information useful to users who may wish to implement or use the application.
- After every change, run the full test suite prior to considering the task complete.
- **Follow software engineering best practices** and minimise future technical debt at all times.

## Content Security Policy

**Never load external resources via CDN.** The app enforces a strict CSP that blocks all cross-origin requests. All fonts, stylesheets, and scripts must be self-hosted. After any frontend change, verify no CSP violations in the browser console.

## Testing

- **Never touch the real data directory during testing.** Tests must use `tmp_path` or `set_test_dirs(tmp_path)` to isolate from production data.
- Run tests with: `.venv/bin/pytest -x -q`
- The venv has no `pip` — use `uv` for package management.
- Async tests use `asyncio_mode = "auto"` (configured in `pyproject.toml`).
- When adding tests that write to disk or modify shared state, use appropriate isolation fixtures.

## Extending the System

- **New generation steps:** Add to the appropriate module. Add allowed transitions to the status module. Add a wrapping method to the orchestrator for status transitions and persistence.
- **New export formats:** Add to the exporter module following existing patterns.
- **New endpoints:** Define in the routes module under `/api/`. Use existing lookup and validation helpers.
- **Web UI changes:** Follow the split-file structure (config → utilities → renderers → app → settings → bootstrap). Load shared config before initializing any component.
- **Config changes:** All defaults flow from the shared config. Frontend and backend must stay in sync.
