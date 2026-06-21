# AGENTS.md — Development Context for Hullucinator

This file captures architectural decisions, known issues, and conventions to ensure consistency across future changes.


## Core Principles

- After every change, review and if required update the `README.md` and `AGENTS.md` file.
- After every change, evaluate if tests need to be updated and ensure they are run before considering the task complete.

## Content Security Policy (CSP)

**CRITICAL: Never load external resources (fonts, stylesheets, scripts) via CDN.** The app enforces a strict CSP (`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'`) that blocks all cross-origin requests. This has caused repeated failures when adding Google Fonts `<link>` tags — the browser blocks both the stylesheet AND the font files it references.

**Always self-host:**
- **Fonts:** Download TTF/WOFF2 files and place in `static/fonts/`. Use `@font-face` declarations in `static/css/styles.css` with `url('/static/fonts/...')` paths. Never use `<link>` to `fonts.googleapis.com`.
- **Third-party scripts:** If a feature requires an external library, bundle it locally in `static/js/` or install via npm and import.
- **Images/icons:** Keep in `static/` subdirectories. The CSP allows `img-src 'self' data:` so inline data URIs work for small icons.

**When adding new CSS:** If you need external styles (e.g., a UI framework), inline the critical CSS or self-host the stylesheet. The `style-src` directive allows `'unsafe-inline'` for `<style>` blocks but blocks external `<link>` stylesheets.

**Verify before committing:** After any frontend change, check the browser console for CSP violations. Any `"violates the following Content Security Policy directive"` error means the change won't work in production.

## Testing

**CRITICAL: Never delete or modify `~/.hullucinator_data` during testing.**

Tests must be fully isolated from the user's real data directory:

- **`tests/test_storage.py`** — Uses `set_test_dirs(tmp_path)` via an `autouse` fixture to redirect all storage paths (BOOKS_DIR, CONFIG_FILE, EXPORTS_DIR) to a temporary directory. Calls `reset_to_defaults()` after each test.
- **`tests/test_api.py`** — Uses `_isolate_api_tests` fixture (autouse) that redirects all storage paths (BOOKS_DIR, CONFIG_FILE, EXPORTS_DIR) to `tmp_path` via `set_test_dirs()`, resets AI client config, resets `_generation_semaphore` for clean event loop, and restores paths to real defaults on teardown. This prevents tests from touching production data. **Validation tests:** long prompts (>5000 chars). **Retry endpoint tests:** creates new book, preserves fields, handles nonexistent book.
- **`tests/test_export.py`** — Passes `tmp_path` as `output_dir` to export functions, avoiding the real EXPORTS_DIR. Tests markdown→HTML conversion and EPUB/PDF export.
- **`tests/test_orchestrator.py`** — Uses mocks for AI client; never touches disk. Tests outline parsing, critique parsing, chapter title matching, and status transitions.
- **`tests/test_parsing.py`** — Tests `parse_outline()` (JSON, code fences, numbered/bulleted lists, prose), `parse_critique()` (JSON, code fences, text fallback), `match_chapter_title()` (exact, normalized, substring, fuzzy Jaccard), `_normalize_title()`.
- **`tests/test_schemas.py`** — Tests `BookCreateRequest` and `BookState` validation (title/prompt constraints, review_max_turns bounds), `AIConfig` defaults and constraints, and schema↔shared config sync.
- **`tests/test_config.py`** — Tests `SharedConfig` structure (`lengths`, `statuses`, `review`, `client`, `ui` sub-models), field constraints, and derivation correctness.
- **`tests/test_concurrency.py`** — Tests semaphore-based concurrency limiting (`_get_semaphore()`, acquire/release, blocking).
- **`tests/test_frontend.py`** — Static analysis of frontend files: CSP compliance (no CDN resources), JS module integrity, HTML structure.

When adding new tests:
- If the test writes to disk (books, config, exports), use `tmp_path` fixture or `set_test_dirs(tmp_path)`.
- If the test modifies shared state (AI client config, reviewer_client), add cleanup in an `autouse` fixture.
- Always verify tests pass in isolation AND as part of the full suite.

**Running Tests:** The project uses a `.venv` virtual environment (not `venv`). System `python3` does not have pytest installed. Always run tests using the venv binary:

```
.venv/bin/pytest -x -q
```

This ensures all project dependencies (pytest, httpx, etc.) are available.

**Pytest Configuration:** `asyncio_mode = "auto"` is set in `pyproject.toml` under `[tool.pytest.ini_options]`. No separate `pytest.ini` file — single source of truth in `pyproject.toml`.

**Python/Pip:** The venv does **not** have `pip` installed (no `pip` or `python3 -m pip` in `.venv/bin/`), and the system `pip3` is unavailable. Always use `uv` for package management:

```
uv pip install <package>          # install into current venv
uv pip install <package> --system # install system-wide
uv pip list                       # list installed packages
```

Never attempt `pip install` or `python3 -m pip` — both will fail.


## Architecture Overview

Hullucinator is a **FastAPI service with a web interface** that orchestrates LLM calls to generate complete e-books from a user prompt. The pipeline is linear and runs as a background task:

```
POST /api/books/create → (background) generate_summary → generate_outline → generate_chapters → review
```

### Components

| Module | Responsibility | Key Details |
|--------|---------------|-------------|
| `app/config.py` | Shared configuration — single source of truth | `SharedConfig` Pydantic model with `LengthConfig`, `StatusConfig`, `ReviewConfig` (includes `fail_score`), `ClientConfig`, `UISchema` sub-models. `get_default_shared_config()` returns the default instance. Served to frontend via `GET /api/config-schema`. All backend modules derive defaults from this config. |
| `app/main.py` | Application bootstrap | FastAPI app creation, lifespan context, middleware setup (`app/middleware.py`), router inclusion (`app/routes.py`), static file mounting, singleton instantiation (`AIClient`, `ReviewerClient`, `Orchestrator`). Config persistence via `load_config()` on startup, saves on changes. **Lazy semaphore** — `_generation_semaphore` created on first use via `_get_semaphore()` to handle event loop changes between test runs. CLI entry point. **No endpoint logic** — all routes delegated to `app/routes.py`. |
| `app/middleware.py` | Middleware definitions | CORS middleware (configurable origins, methods, headers). Security headers (X-Content-Type-Options, X-Frame-Options, X-XSS-Protection). No-cache headers for API responses. `setup_middleware(app)` function registers all middleware. |
| `app/routes.py` | API endpoint definitions | `create_router()` factory function accepts dependencies (ai_client, reviewer_client, orchestrator, server_config, etc.). All `/api/` endpoints organized by resource: config (`GET/POST /api/config`, `GET /api/config-schema`), models (`GET /api/models`, `GET /api/reviewer/models`), books (`POST /api/books/create`, `GET /api/books`, `GET /api/books/{id}`, `DELETE /api/books/{id}`, `POST /api/books/{id}/review`, `POST /api/books/{id}/retry`, `GET /api/books/{id}/export/epub`, `GET /api/books/{id}/export/pdf`). Background task management via `asyncio.create_task()`. |
| `app/schemas.py` | Data models | `BookState` Pydantic model: `id`, `title` (min 1 char, max 200 chars), `prompt` (min 1 char, no upper limit), `tags` (List[str]), `length` (str), `status` (required), `summary`, `outline`, `chapters`, `chapter_summaries` (Dict[str,str]), `metadata`, `review` (Dict — latest turn result), `review_history` (List[Dict] — full audit trail), `review_max_turns` (int, default from shared config), `skip_review` (bool, default False), `progress` (Dict). `BookCreateRequest` for API input mirrors BookState fields. `AIConfig` for persisted config: `endpoint_url`, `model_name`, `reviewer_endpoint_url`, `reviewer_model_name`, `review_max_turns`, `review_word_threshold` (int, default from shared config), `review_chunk_size` (int, default from shared config). **All defaults imported from `app/config.py` shared config.** |
| `app/storage.py` | Persistence | JSON files in `~/.hullucinator_data/data/books/`. Uses the user's home directory (`Path.home()`) for cross-platform compatibility. `list_books()` returns all books sorted by modification time. `delete_book()` removes a book's JSON file from disk. `EXPORTS_DIR` shared with exporter. **Config persistence** — `save_config()` and `load_config()` read/write `~/.hullucinator_data/data/config.json` (endpoint URLs, model names, review settings). Both `api_key` and `reviewer_api_key` are **stripped before persistence** for security. |
| `app/ai_client.py` | LLM API client | Talks to OpenAI-compatible `/v1/chat/completions`. Retries configurable (max_retries, base_wait, backoff, jitter from shared config). Uses **persistent** `httpx.AsyncClient`. Uses **async** `await asyncio.sleep()`. Runtime-reconfigurable endpoint, model, and API key via properties. `list_models()` fetches available models from `/v1/models`. **Shared retry logic:** `_retry_request(client, url, payload, headers, max_retries, log_prefix, error_prefix)` module-level helper used by both `AIClient.generate_completion()` and `ReviewerClient.generate_completion()`. Eliminates ~80 lines of duplicated retry/backoff code. **`ReviewerClient`** — dedicated client for review/correction tasks, can use different endpoint/model/API key than main `AIClient` while sharing the same HTTP connection. Has its own `_api_key`, `_rebuild_headers()`, `get_config()`, and `update_config()` methods. **Module-level helpers:** `_extract_content()` (module-level function, not static method), `_parse_models_response()`, `_build_api_url()` shared between `AIClient` and `ReviewerClient`. |
| `app/status.py` | Status transition management | `VALID_TRANSITIONS` dict defines allowed status transitions. `_transition()` enforces valid transitions. `is_terminal_status()` and `get_allowed_transitions()` helpers. Imported by `orchestrator.py`, `generation.py`, `review.py`. |
| `app/parsing.py` | LLM response parsing | `parse_outline()` handles JSON, code fences, numbered lists, chapter prefix formats. `parse_critique()` handles JSON and text fallback formats. `match_chapter_title()` fuzzy matching with exact, normalized, substring, and Jaccard similarity. `_normalize_title()` removes punctuation, preserves spaces. Imports `_extract_content` from `app.ai_client`. |
| `app/generation.py` | Book generation pipeline | `generate_summary()`, `generate_outline()`, `generate_chapters()` methods. Uses `LENGTH_CHAPTER_COUNT`/`LENGTH_WORD_COUNT` derived from shared config. Uses `_update_progress()` helper. Chapter continuity via cumulative chapter summaries. |
| `app/review.py` | Review pipeline | `review_book()` orchestrates full or chunked review. `_full_review()` for books under threshold. `_chunked_review()` for books exceeding `review_word_threshold` or with >10 chapters. `_build_review_text()`, `_build_revision_context()`, `_record_review_turn()` helpers. Uses `REVIEW_PASS_SCORE` from shared config. |
| `app/validators.py` | Validation helpers | `validate_create_request()` validates book creation input. `validate_book_state()` checks book content completeness. `validate_ai_config()` validates AI config constraints. `max_title_length` exported for frontend use. |
| `app/orchestrator.py` | Pipeline coordinator (slim) | 152-line coordinator that delegates to specialized modules. Imports `VALID_TRANSITIONS`, `_transition` from `app.status`; `parse_outline`, `parse_critique`, `match_chapter_title` from `app.parsing`; `generate_summary`, `generate_outline`, `generate_chapters` from `app.generation`; `review_book` from `app.review`. Contains 5 async methods (`generate_summary`, `generate_outline`, `generate_chapters`, `review_book`, `validate_book`) that wrap delegated functions with status transitions, progress tracking, and disk persistence via `save_book`. Re-exports key functions (`_parse_outline`, `_parse_critique`, `_match_chapter_title`, `_normalize_title`) for backward compatibility with tests. |
| `app/exporter.py` | EPUB/PDF export | EPUB: full CSS styling, markdown→HTML conversion, TOC, drop caps, **genre tags as EPUB subjects**. PDF: plain text with configurable font paths (env var `PDF_FONT_DIR`), fallback to Helvetica, **tags on title page**. Uses absolute `EXPORTS_DIR` from storage. **New: review metadata** included in exports (score, verdict, corrections on title page). |
| `static/js/config.js` | Shared config — frontend | Loads `SHARED_CONFIG` from `GET /api/config-schema` via `loadSharedConfig()`. Provides `renderLengthSelect()`, `renderMaxTurnsSelect()`, `getStatusLabel()`, `getStatusCssClass()`, `isTerminalStatus()`, `isActiveStatus()` helpers. Loaded before other scripts in `index.html`. |
| `static/css/styles.css` | Styles | All CSS: CSS variables, resets, layout components, cards, forms, badges, progress bars, modal, review section, settings panel, toast notifications, delete button styling, responsive breakpoints. |
| `static/js/ui.js` | Shared utilities | Core helpers: `apiFetch()` (error handling), `toast()` notifications, `esc()` HTML escaping, progress polling (`startPolling`/`stopPolling`), library auto-refresh. **Rendering functions removed:** `statusBadge()` migrated to `renderers.js`. |
| `static/js/renderers.js` | UI rendering utilities | Generates HTML fragments for the book library and detail modal. `statusBadge()` — renders status label with CSS class (uses `config.js` helpers). `buildBookCardHtml()` — renders library card HTML (title, status, tags, length, prompt, progress bar). `renderDetail()` — renders full detail modal content (settings, status, progress, summary, outline, chapters, review section, action buttons). `buildReviewSection()` — renders review results (score, verdict, critique, corrections, iteration history). Depends on `config.js` (SHARED_CONFIG, getStatusLabel, getStatusCssClass) and `ui.js` (esc). |
| `static/js/app.js` | Main application | Book creation form (tags input, length/turns selectors populated from `SHARED_CONFIG`, live prompt character counter), library view with book cards, detail modal (summary, outline, chapters, review section with per-turn history), EPUB/PDF download links, retry/review/delete actions. **Rendering functions removed:** `buildBookCardHtml`, `renderDetail`, `buildReviewSection` migrated to `renderers.js`. Calls `renderDetail()` from `renderers.js` for modal content. **Client-side validation:** title/prompt must be non-empty before submission; integer fields use `isNaN` guards with safe defaults; `skip_review` always sent explicitly. **Retry behavior:** when retrying a failed book, the old failed entry is deleted after the new book is queued. **Delete:** delete button on library cards (appears on hover) and in detail modal actions. Confirmation dialog before deletion. |
| `static/js/settings.js` | Settings panel | Writer config (endpoint, model dropdown with fetch button, API key), reviewer config (endpoint, API key, model dropdown with fetch button), global max review turns, review word threshold, chunk size, config persistence. Model fetch buttons call `/api/models` (writer) or `/api/reviewer/models` (reviewer). Setup wizard (first-time config) shares the same fields. Dropdowns populated from `SHARED_CONFIG`. |
| `static/js/boot.js` | Bootstrapper | Called after all other scripts have loaded. Calls `loadSharedConfig()` then `initApp()` and `initSettings()`. Replaces inline `<script>` in `index.html` for CSP compliance. |
| `static/index.html` | HTML skeleton | Clean semantic HTML structure only — no inline CSS/JS. Links to `css/styles.css` and JS modules (`config.js`, `ui.js`, `renderers.js`, `app.js`, `settings.js`, `boot.js`). Contains: header with ⚙️ button, create form (title, prompt with character counter, tags input, length/turns selectors), library card, detail modal, settings panel (writer/reviewer config groups with API key + review threshold inputs), setup wizard (first-time config with all fields). |

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_ENDPOINT_URL` | `http://192.168.0.40:1234` | Writer LLM API endpoint |
| `AI_MODEL_NAME` | `qwen3.6-27b` | Writer model name |
| `AI_API_KEY` | *(empty)* | Bearer token |
| `REVIEWER_ENDPOINT_URL` | *(empty)* | Reviewer LLM endpoint (empty = use writer's) |
| `REVIEWER_MODEL_NAME` | *(empty)* | Reviewer model (empty = use writer's) |
| `REVIEWER_API_KEY` | *(empty)* | Reviewer Bearer token (empty = use writer's) |
| `HULLUCINATOR_HOST` | `0.0.0.0` | Bind address |
| `HULLUCINATOR_PORT` | `8000` | Port |
| `PDF_FONT_DIR` | `/usr/share/fonts/truetype/dejavu` | PDF font directory |
| `LOG_LEVEL` | `INFO` | Logging level |

**Config Persistence:** AI settings (endpoint URLs, model names, max review turns, review thresholds) are persisted to `~/.hullucinator_data/data/config.json` and loaded on server startup. This survives restarts. **API keys are never persisted** — they must come from environment variables or runtime updates via the GUI/API. Both writer and reviewer API keys are stripped before saving.

**Runtime Configuration:** AI settings can be changed at runtime via the GUI Settings panel or the `/api/config` endpoint. Changes take effect immediately for all subsequent generation tasks.

## Remaining Technical Debt

### 1. Test coverage gaps
The project has 126 tests across 9 test files. Remaining gaps:
1. `exporter.markdown_to_html()` — edge cases in markdown conversion (some coverage in `test_export.py` but could be more thorough)
2. `storage` — round-trip save/load fidelity (covered in `test_storage.py`)
3. `ai_client` — retry behavior and error handling (mock the HTTP layer) — not yet tested
4. `app/middleware.py` — CORS and security headers verification — not yet tested
5. `app/routes.py` — endpoint-level integration tests beyond `test_api.py`

### 2. No Rate Limiting
The API has no rate limiting. For production deployments, consider adding `slowapi` or similar.

### 3. Export Cleanup
Exported files in `~/.hullucinator_data/exports/` accumulate without cleanup. Consider a configurable retention policy or periodic cleanup.

### 4. Concurrency Limits
No limit on concurrent background tasks. For high-traffic deployments, consider a task queue (Celery, RQ) with worker limits.

### 5. No Authentication
The API is open. For production, add authentication (API keys, OAuth, etc.).

### 6. Review Token Budget
The review step sends the entire book to the LLM, which can be expensive for long books. Consider summarization-based review for epics.

## Conventions

- **Status values:** `pending`, `summary_generated`, `outline_generated`, `in_progress`, `completed`, `reviewing`, `reviewed`, `failed`
- **Status transitions:** Enforced via `_transition()` — see `VALID_TRANSITIONS` dict in `app/status.py`
- **Book IDs:** UUID4 strings (generated at creation time)
- **Storage format:** One JSON file per book in `~/.hullucinator_data/data/books/`, named `{id}.json`
- **Export format:** EPUB and PDF files written to `~/.hullucinator_data/exports/` directory, named `{book_id}.{ext}`
- **Chapter storage:** Dict mapping chapter title (string) → chapter content (string)
- **Chapter summaries:** Dict mapping chapter title (string) → one-paragraph summary (string). Generated after each chapter for continuity context.
- **Progress tracking:** `progress` dict with `current_step`, `total_chapters`, `chapters_completed`, `percentage`
- **API prefix:** All API endpoints use `/api/` prefix; web UI served at `/`
- **Logging:** Structured logging via Python `logging` module; configurable via `LOG_LEVEL`
- **Tags:** List of genre/theme strings (e.g. `comedy`, `dark fantasy`, `biography`). Guided by user input, injected into all LLM prompts. Stored in `BookState.tags`. Default: empty list.
- **Book length:** One of `short_story`, `novella`, `novel`, `epic`. Controls chapter count (`LENGTH_CHAPTER_COUNT`) and word count (`LENGTH_WORD_COUNT`) in generation prompts. Default: `novel` (8–15 chapters, 20,000–50,000 words).
- **Review audit:** `BookState.review` dict (latest turn result) with `turn` (int), `critique` (raw LLM response), `issues` (list of identified problems), `overall_score` (0-10), `verdict` (`needs_revision` | `ready`), `corrections` (list of applied fixes), `reviewed` (bool). `BookState.review_history` — list of all turn dicts providing full iteration audit trail. `BookState.review_max_turns` — maximum critique→correct iterations (default 2, settable per-book).
- **Reviewer config:** Optional separate endpoint/model/API key for review tasks. Configured via `REVIEWER_ENDPOINT_URL`/`REVIEWER_MODEL_NAME`/`REVIEWER_API_KEY` env vars, GUI settings panel, or `POST /api/config`. Empty values mean reviewer uses the same setting as the writer. Review thresholds (`review_word_threshold`, `review_chunk_size`) are configurable via GUI and persisted.
- **Config persistence:** `~/.hullucinator_data/data/config.json` stores `endpoint_url`, `model_name`, `reviewer_endpoint_url`, `reviewer_model_name`, `review_max_turns`, `review_word_threshold`, `review_chunk_size`. Loaded on startup, saved on config changes. API keys (both `api_key` and `reviewer_api_key`) are **never persisted**.

## Chapter Continuity Design

Each chapter generation in `app/generation.py` follows this context strategy:

1. **Book summary** — Overall direction and themes
2. **Full outline** — Structural awareness of all chapters
3. **Condensed chapter summaries** — One-paragraph summaries of all previously generated chapters, in order

This approach provides narrative continuity without consuming excessive tokens from full chapter text. After each chapter is generated, a concise summary is created and stored in `chapter_summaries` for use by subsequent chapters.

## Review Design

The review process runs automatically after chapter generation (or can be triggered manually via `POST /api/books/{id}/review`). Implemented in `app/review.py`, delegated by `app/orchestrator.py`:

1. **Critique:** Full book (summary + outline + all chapters) sent to the reviewer LLM acting as professional critic. Uses `reviewer_client` if configured (different endpoint/model), otherwise falls back to main `ai_client`.
2. **Issue Detection:** Critic identifies plot holes, character inconsistencies, pacing issues, continuity errors, tone inconsistencies, and unresolved threads. Returns JSON with `issues`, `overall_score` (0-10), and `verdict` (`needs_revision` | `ready`).
3. **Iterative Correction Loop:** For each issue, the affected chapter is re-revisioned with full context from the rest of the book (summary + outline + prior chapter summaries). After all corrections in a turn, the reviewer re-evaluates. This repeats until the book passes review (score ≥ 7, verdict = `ready`) or `review_max_turns` is reached.
4. **Audit Trail:** Each turn's critique, issues, score, verdict, and corrections are appended to `book_state.review_history`. The latest turn is also kept in `book_state.review` for backward compatibility.
5. **Max Turns:** Default 2 turns. Configurable per-book (`BookCreateRequest.review_max_turns`) or globally (GUI settings, `POST /api/config`). If max turns is reached without passing, the book is marked as `reviewed` with a `max_turns_reached` flag.
6. **Chunked Review:** For books exceeding `review_word_threshold` words (default 30,000) or with >10 chapters, `app/review.py` uses chunked review instead of sending the entire book to the LLM. Chapters are split into batches of `review_chunk_size` (default 5) to avoid context window overflow. Each chunk is reviewed independently with context from the summary, outline, and other chapter summaries. Results are aggregated and corrections applied across all chunks. Thresholds are configurable via GUI settings and persisted in `AIConfig`.
7. **Export:** Review metadata (score, verdict, corrections count) included in EPUB/PDF title pages.

## Adding Features

When extending the system, follow these patterns:

- **New generation steps:** Add a function to the appropriate module (`app/generation.py` for generation, `app/review.py` for review). Add to `VALID_TRANSITIONS` in `app/status.py`. Add a wrapping method to `Orchestrator` for status transitions + persistence.
- **New export formats:** Add a function in `exporter.py` following the existing pattern (takes `book_id`, `title`, `chapters`, `tags`, `output_dir`, `review`). Use absolute `EXPORTS_DIR` from `storage`.
- **New endpoints:** Define in `app/routes.py` under `/api/` prefix. Use `load_book()` for lookup + `validate_book()` before processing. `app/main.py` only handles app bootstrap, middleware, and router inclusion.
- **Web UI changes:** The web UI is split into focused files:
  - `static/css/styles.css` — all styles (CSS variables, components, responsive)
  - `static/js/config.js` — shared config loader and renderer helpers (`SHARED_CONFIG`, `renderLengthSelect`, `renderMaxTurnsSelect`, `getStatusLabel`, `getStatusCssClass`, `isTerminalStatus`, `isActiveStatus`)
  - `static/js/ui.js` — shared utilities (`apiFetch`, `toast`, `esc`, polling)
  - `static/js/renderers.js` — UI rendering functions (`statusBadge`, `buildBookCardHtml`, `renderDetail`, `buildReviewSection`)
  - `static/js/app.js` — main app logic (create form, library, detail modal, actions)
  - `static/js/settings.js` — settings panel (writer/reviewer config, model fetch, persistence)
  - `static/js/boot.js` — bootstrapper (loads shared config, then initializes app and settings)
  - `static/index.html` — clean HTML skeleton only (links CSS/JS, defines DOM structure)
- **Tags/length in prompts:** When adding new orchestrator methods, always inject `book_state.tags` and `book_state.length` into the LLM prompts so the generation stays consistent with user intent.
- **AI config changes:** Use `ai_client.update_config()` for runtime updates. The `AIClient` uses mutable properties for endpoint, model, and API key. `ReviewerClient` has its own `update_config()` for reviewer-specific settings. Config is persisted via `save_config()` in storage.
- **Reviewer config:** Reviewer settings (endpoint, model) are optional. Empty values mean the reviewer uses the same endpoint/model as the writer. Configure via `REVIEWER_ENDPOINT_URL`/`REVIEWER_MODEL_NAME` env vars, GUI settings panel, or `POST /api/config`.
