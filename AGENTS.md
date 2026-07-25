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
- `ToolConfig` — web grounding toggle (Wikipedia + web search during generation)

## Extending the System

- **New generation steps:** Add to the appropriate module. Add allowed transitions to the status module. Add a wrapping method to the orchestrator for status transitions and persistence.
- **New export formats:** Add to the exporter module following existing patterns.
- **New endpoints:** Define in the routes module under `/api/`. Use existing lookup and validation helpers.
- **Web UI changes:** Follow the split-file structure (config → utilities → renderers → app → settings → bootstrap). Load shared config before initializing any component.
- **Config changes:** All defaults flow from the shared config. Frontend and backend must stay in sync.

## Book Resumption

**Books interrupted by server shutdown automatically resume on restart.** The `lifespan` startup hook scans all stored books for non-terminal statuses (`pending`, `summary_generated`, `outline_generated`, `in_progress`, `reviewing`) and queues them for resume. Manual resume is available via `POST /api/books/{book_id}/resume`. Resume preserves all already-generated content (chapters, summaries, outline) and continues only from the point of interruption.

## Cover Image Architecture

**Cover images are stored in `~/.hullucinator_data/covers/` with format-preserving extensions.** The `cover_image` field on `BookState` stores a relative path (e.g., `covers/{book_id}.png`). Supported formats: PNG, JPEG, WebP. The `save_cover_image()` function preserves the original file extension so MIME type detection works correctly in EPUB export and cover serving.

**Retry preserves cover images.** When retrying a book via `POST /api/books/{book_id}/retry`, the cover image file is copied to the new book's cover path (renamed with the new book ID) and the old cover file is deleted. The new book's `cover_image` field is updated to reference the copied file.

**EPUB export uses proper MIME type mapping.** The suffix-to-MIME mapping supports `.png` → `image/png`, `.jpg/.jpeg` → `image/jpeg`, `.webp` → `image/webp`, `.gif` → `image/gif`.

## Web Grounding

**Web grounding enables factual research during generation and review.** When `allow_web_grounding` is enabled in config, the generation and review pipelines use tool calling to query Wikipedia and DuckDuckGo for factual information. Tool calling falls back gracefully to regular completion when the endpoint doesn't support it.

**Shared module architecture.** `_is_web_grounding_enabled()` and `_generate_with_optional_tools()` live in `app/web_grounding.py` and are imported by both `generation.py` and `review.py`. The `WebGroundingClient` protocol type (in `web_grounding.py`) provides consistent typing for clients that support tool calling.

**Persistent HTTP client.** Tool calls (Wikipedia, web search) use a module-level persistent `httpx.AsyncClient` in `app/tools.py` to avoid connection overhead per call. The client is closed during application shutdown via `close_tool_client()`.

## Tool Calling

**Shared helpers eliminate duplication.** `execute_tool_calls` and `generate_completion_with_tools` logic is extracted to module-level helpers (`_execute_tool_calls_helper`, `_generate_completion_with_tools_helper`) in `app/ai_client.py`. Both `AIClient` and `ReviewerClient` delegate to these shared helpers, differing only in log prefixes.
