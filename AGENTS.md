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

**Book creation, retry, and manual review endpoints must validate API credentials before queuing.** The `_check_configured_and_connected()` function performs a live test request to the LLM provider's models endpoint. This prevents books from being queued when the API key is missing or invalid, avoiding wasted background tasks that would fail later. The basic `_check_configured()` function (checks endpoint, model, and API key presence) is used for read-only endpoints like `/api/config` and `/api/health`.

## Content Security Policy

**Never load external resources via CDN.** The app enforces a strict CSP that blocks all cross-origin requests. All fonts, stylesheets, and scripts must be self-hosted. After any frontend change, verify no CSP violations in the browser console.

**TTS exception:** The CSP `default-src` allows `https:` for HuggingFace model downloads (data fetch, not script execution). `script-src` includes `'unsafe-eval'`, `'wasm-unsafe-eval'`, and `blob:` to allow kokoro-js's dynamic blob imports for ONNX Runtime WASM. COOP/COEP headers enable Cross-Origin Isolation for SharedArrayBuffer support.

## Text-to-Speech Architecture

Browser-based TTS uses `kokoro-js` (self-hosted at `static/js/vendor/kokoro.web.js`) running in a Web Worker (`static/js/tts-worker.js`). Main-thread playback managed by `static/js/tts-manager.js` (exposed as global `bookTTS`). Progress persists via `localStorage`. Backend endpoint `GET /api/books/{id}/tts-text` serves markdown-stripped chapter text. TTS is optional — failure never blocks reading.

COEP is set to `credentialless` to enable Cross-Origin Isolation, unlocking `SharedArrayBuffer` and multi-threaded WASM inference. ONNX Runtime WASM binaries (`ort-wasm-simd-threaded.jsep.mjs` and `.wasm`) are self-hosted in `static/js/vendor/` and referenced via `wasmPaths` in the worker. HuggingFace model weights are fetched with CORS, which is compatible with `credentialless`.

**TTS model lifecycle:** The worker keeps the Kokoro model loaded across `stop()` calls for instant replay. `init` is idempotent — repeated calls return `ready` immediately without reloading. The manager's `stop()` clears queues but preserves `isInitialized`. Only `destroy()` terminates the worker and releases WASM memory.

**TTS audio cache:** Synthesized audio is stored in IndexedDB (`hullucinator_tts_cache`) keyed by `audio:{bookId}:{chapterIndex}:{sentenceIndex}`. Cache persists across page loads. `playChapter` checks cache before synthesizing. `clearCache(bookId)` purges all entries for a deleted book.

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
- **Web UI changes:** Follow the split-file structure (config → utilities → renderers → tts-manager → app → settings → bootstrap). Load shared config before initializing any component.
- **Config changes:** All defaults flow from the shared config. Frontend and backend must stay in sync.
- **TTS changes:** Worker code in `tts-worker.js`, main-thread in `tts-manager.js`. CSS in `styles.css` section 17. Controls rendered in `renderers.js`, wired in `app.js`.
