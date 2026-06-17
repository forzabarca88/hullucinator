# AGENTS.md — Development Context for Hullucinator

This file captures architectural decisions, known issues, and conventions to ensure consistency across future changes.


## Core Principles

- After every change, review and if required update the `README.md` and `AGENTS.md` file.
- After every change, evaluate if tests need to be updated and ensure they are run before considering the task complete.


## Architecture Overview

Hullucinator is a **FastAPI service with a web interface** that orchestrates LLM calls to generate complete e-books from a user prompt. The pipeline is linear and runs as a background task:

```
POST /api/books/create → (background) generate_summary → generate_outline → generate_chapters → review
```

### Components

| Module | Responsibility | Key Details |
|--------|---------------|-------------|
| `app/main.py` | FastAPI app & HTTP endpoints | Defines all API + web UI endpoints. Creates `AIClient`, optional `ReviewerClient`, and `Orchestrator` as module-level singletons. Configured via environment variables. **Config persistence** — loads from `~/.hullucinator_data/data/config.json` on startup, saves on changes (no API keys). Background task support via `asyncio.create_task()`. Serves static web UI. AI config endpoints (`GET/POST /api/config`, `GET /api/models`). Review trigger (`POST /api/books/{id}/review`). Writer + reviewer config in one endpoint. |
| `app/schemas.py` | Data models | `BookState` Pydantic model: `id`, `title`, `prompt`, `tags` (List[str]), `length` (str), `status`, `summary`, `outline`, `chapters`, `chapter_summaries` (Dict[str,str]), `metadata`, `review` (Dict — latest turn result), `review_history` (List[Dict] — full audit trail), `review_max_turns` (int, default 2), `progress` (Dict). `BookCreateRequest` for API input includes `review_max_turns`. `AIConfig` for persisted config: `endpoint_url`, `model_name`, `reviewer_endpoint_url`, `reviewer_model_name`, `review_max_turns`. |
| `app/storage.py` | Persistence | JSON files in `~/.hullucinator_data/data/books/`. Uses the user's home directory (`Path.home()`) for cross-platform compatibility. `list_books()` returns all books sorted by modification time. `EXPORTS_DIR` shared with exporter. **Config persistence** — `save_config()` and `load_config()` read/write `~/.hullucinator_data/data/config.json` (endpoint URLs, model names, review settings). API keys are **never persisted** for security. |
| `app/ai_client.py` | LLM API client | Talks to OpenAI-compatible `/v1/chat/completions`. Retries 2x on 429/500/503 or empty responses. Uses **persistent** `httpx.AsyncClient`. Uses **async** `await asyncio.sleep()`. Runtime-reconfigurable endpoint, model, and API key via properties. `list_models()` fetches available models from `/v1/models`. **`ReviewerClient`** — dedicated client for review/correction tasks, can use different endpoint/model than main `AIClient` while sharing the same HTTP connection and auth headers. |
| `app/orchestrator.py` | Pipeline coordinator | 5 async methods (`generate_summary`, `generate_outline`, `generate_chapters`, `review_book`, `validate_book`). Each step saves state to disk. **Enforced status transitions** prevent data inconsistencies. Progress tracking updated at each step. Improved outline parser. **Tags and length** guide LLM prompts throughout the pipeline. **Chapter continuity** — each chapter receives cumulative context via condensed chapter summaries. **Iterative review loop** — `review_book()` runs critique → correct → re-critique until approved or `review_max_turns` reached. Uses separate `reviewer_client` if configured. Full audit trail in `book_state.review_history`. Fuzzy chapter title matching for issue-to-chapter mapping. |
| `app/exporter.py` | EPUB/PDF export | EPUB: full CSS styling, markdown→HTML conversion, TOC, drop caps, **genre tags as EPUB subjects**. PDF: plain text with configurable font paths (env var `PDF_FONT_DIR`), fallback to Helvetica, **tags on title page**. Uses absolute `EXPORTS_DIR` from storage. **New: review metadata** included in exports (score, verdict, corrections on title page). |
| `static/css/styles.css` | Styles | All CSS: CSS variables, resets, layout components, cards, forms, badges, progress bars, modal, review section, settings panel, toast notifications, responsive breakpoints. |
| `static/js/ui.js` | Shared utilities | Core helpers: `apiFetch()` (error handling), `toast()` notifications, `esc()` HTML escaping, `statusBadge()` renderer, progress polling (`startPolling`/`stopPolling`). |
| `static/js/app.js` | Main application | Book creation form (tags input, length/turns selectors), library view with book cards, detail modal (summary, outline, chapters, review section with per-turn history), EPUB/PDF download links, retry/review actions. |
| `static/js/settings.js` | Settings panel | Writer config (endpoint, model dropdown with fetch button, API key), reviewer config (endpoint, model dropdown with fetch button), global max review turns, config persistence. Model fetch buttons call `/api/models` (writer) or `/api/reviewer/models` (reviewer). |
| `static/index.html` | HTML skeleton | Clean semantic HTML structure only — no inline CSS/JS. Links to `css/styles.css` and JS modules (`ui.js`, `app.js`, `settings.js`). Contains: header with ⚙️ button, create form (title, prompt, tags input, length/turns selectors), library card, detail modal, settings panel (writer/reviewer config groups). |

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_ENDPOINT_URL` | `http://192.168.0.40:1234` | Writer LLM API endpoint |
| `AI_MODEL_NAME` | `qwen3.6-27b` | Writer model name |
| `AI_API_KEY` | *(empty)* | Bearer token |
| `REVIEWER_ENDPOINT_URL` | *(empty)* | Reviewer LLM endpoint (empty = use writer's) |
| `REVIEWER_MODEL_NAME` | *(empty)* | Reviewer model (empty = use writer's) |
| `HULLUCINATOR_HOST` | `0.0.0.0` | Bind address |
| `HULLUCINATOR_PORT` | `8000` | Port |
| `PDF_FONT_DIR` | `/usr/share/fonts/truetype/dejavu` | PDF font directory |
| `LOG_LEVEL` | `INFO` | Logging level |

**Config Persistence:** AI settings (endpoint URLs, model names, max review turns) are persisted to `~/.hullucinator_data/data/config.json` and loaded on server startup. This survives restarts. **API keys are never persisted** — they must come from environment variables or runtime updates via the GUI/API.

**Runtime Configuration:** AI settings can be changed at runtime via the GUI Settings panel or the `/api/config` endpoint. Changes take effect immediately for all subsequent generation tasks.

## Resolved Issues

The following issues from the original codebase have been fixed:

1. ✅ **Hardcoded AI Configuration** — Now uses environment variables + runtime GUI config
2. ✅ **Blocking `time.sleep()`** — Replaced with `await asyncio.sleep()`
3. ✅ **No Background Task Support** — Added `asyncio.create_task()` with task registry + progress polling
4. ✅ **Relative Path in Storage** — Uses absolute path from project root
5. ✅ **PDF Font Paths Hardcoded** — Configurable via `PDF_FONT_DIR` env var, with Helvetica fallback
6. ✅ **Data Inconsistency** — Enforced status transitions via `_transition()` function
7. ✅ **No `requirements.txt`** — Added both `pyproject.toml` and `requirements.txt`
8. ✅ **DEBUG Print** — Removed; replaced with structured logging
9. ✅ **Export Directory** — Uses absolute path from project root
10. ✅ **Outline Parser Fragility** — Improved with better regex patterns and fallback handling
11. ✅ **No Chapter Continuity** — Each chapter now receives cumulative context via condensed summaries of prior chapters
12. ✅ **No Quality Review** — Post-completion professional critic review with automatic corrections
13. ✅ **No Model Discovery** — GUI fetches available models from the LLM provider
14. ✅ **No Config Persistence** — AI settings saved to `~/.hullucinator_data/data/config.json` on changes, loaded on startup. API keys never persisted.
15. ✅ **No Separate Reviewer Config** — Optional `REVIEWER_ENDPOINT_URL`/`REVIEWER_MODEL_NAME` env vars + GUI settings. ReviewerClient shares HTTP connection but uses different endpoint/model.
16. ✅ **No Iterative Review Loop** — `review_book()` runs critique → correct → re-critique until approved or `review_max_turns` reached. Full per-turn audit trail in `review_history`.
17. ✅ **Create Form Max Turns Not Synced** — Create form's `maxTurns` select now syncs with persisted config on page load and after config save, so the default matches the user's saved preference.

## Remaining Technical Debt

### 1. No Test Suite
Priority areas for testing:
1. `orchestrator._parse_outline()` — various JSON and text formats
2. `orchestrator._parse_critique()` — parsing critic review responses
3. `orchestrator._match_chapter_title()` — fuzzy chapter title matching
4. `exporter.markdown_to_html()` — edge cases in markdown conversion
5. `storage` — round-trip save/load fidelity
6. `ai_client` — retry behavior and error handling (mock the HTTP layer)

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
- **Status transitions:** Enforced via `_transition()` — see `VALID_TRANSITIONS` dict in orchestrator
- **Book IDs:** UUID4 strings (generated at creation time)
- **Storage format:** One JSON file per book in `~/.hullucinator_data/data/books/`, named `{id}.json`
- **Export format:** EPUB and PDF files written to `~/.hullucinator_data/exports/` directory, named `{book_id}.{ext}`
- **Chapter storage:** Dict mapping chapter title (string) → chapter content (string)
- **Chapter summaries:** Dict mapping chapter title (string) → one-paragraph summary (string). Generated after each chapter for continuity context.
- **Progress tracking:** `progress` dict with `current_step`, `total_chapters`, `chapters_completed`, `percentage`
- **API prefix:** All API endpoints use `/api/` prefix; web UI served at `/`
- **Logging:** Structured logging via Python `logging` module; configurable via `LOG_LEVEL`
- **Tags:** List of genre/theme strings (e.g. `comedy`, `dark fantasy`, `biography`). Guided by user input, injected into all LLM prompts. Stored in `BookState.tags`. Default: empty list.
- **Book length:** One of `short_story`, `novella`, `novel`, `epic`. Controls chapter count (`LENGTH_CHAPTER_COUNT`) and word count (`LENGTH_WORD_COUNT`) in orchestrator prompts. Default: `novel` (8–15 chapters, 20,000–50,000 words).
- **Review audit:** `BookState.review` dict (latest turn result) with `turn` (int), `critique` (raw LLM response), `issues` (list of identified problems), `overall_score` (0-10), `verdict` (`needs_revision` | `ready`), `corrections` (list of applied fixes), `reviewed` (bool). `BookState.review_history` — list of all turn dicts providing full iteration audit trail. `BookState.review_max_turns` — maximum critique→correct iterations (default 2, settable per-book).
- **Reviewer config:** Optional separate endpoint/model for review tasks. Configured via `REVIEWER_ENDPOINT_URL`/`REVIEWER_MODEL_NAME` env vars, GUI settings panel, or `POST /api/config`. Empty values mean reviewer uses the same endpoint/model as the writer.
- **Config persistence:** `~/.hullucinator_data/data/config.json` stores `endpoint_url`, `model_name`, `reviewer_endpoint_url`, `reviewer_model_name`, `review_max_turns`. Loaded on startup, saved on config changes. API keys are **never persisted**.

## Chapter Continuity Design

Each chapter generation follows this context strategy:

1. **Book summary** — Overall direction and themes
2. **Full outline** — Structural awareness of all chapters
3. **Condensed chapter summaries** — One-paragraph summaries of all previously generated chapters, in order

This approach provides narrative continuity without consuming excessive tokens from full chapter text. After each chapter is generated, a concise summary is created and stored in `chapter_summaries` for use by subsequent chapters.

## Review Design

The review process runs automatically after chapter generation (or can be triggered manually via `POST /api/books/{id}/review`):

1. **Critique:** Full book (summary + outline + all chapters) sent to the reviewer LLM acting as professional critic. Uses `reviewer_client` if configured (different endpoint/model), otherwise falls back to main `ai_client`.
2. **Issue Detection:** Critic identifies plot holes, character inconsistencies, pacing issues, continuity errors, tone inconsistencies, and unresolved threads. Returns JSON with `issues`, `overall_score` (0-10), and `verdict` (`needs_revision` | `ready`).
3. **Iterative Correction Loop:** For each issue, the affected chapter is re-revisioned with full context from the rest of the book (summary + outline + prior chapter summaries). After all corrections in a turn, the reviewer re-evaluates. This repeats until the book passes review (score ≥ 7, verdict = `ready`) or `review_max_turns` is reached.
4. **Audit Trail:** Each turn's critique, issues, score, verdict, and corrections are appended to `book_state.review_history`. The latest turn is also kept in `book_state.review` for backward compatibility.
5. **Max Turns:** Default 2 turns. Configurable per-book (`BookCreateRequest.review_max_turns`) or globally (GUI settings, `POST /api/config`). If max turns is reached without passing, the book is marked as `reviewed` with a `max_turns_reached` flag.
6. **Export:** Review metadata (score, verdict, corrections count) included in EPUB/PDF title pages.

## Adding Features

When extending the system, follow these patterns:

- **New generation steps:** Add a method to `Orchestrator`, add to `VALID_TRANSITIONS`, call it from `_run_generation_pipeline`, and persist state via `save_book`.
- **New export formats:** Add a function in `exporter.py` following the existing pattern (takes `book_id`, `title`, `chapters`, `tags`, `output_dir`, `review`). Use absolute `EXPORTS_DIR` from `storage`.
- **New endpoints:** Define in `main.py` under `/api/` prefix. Use `load_book()` for lookup + `validate_book()` before processing.
- **Web UI changes:** The web UI is split into focused files:
  - `static/css/styles.css` — all styles (CSS variables, components, responsive)
  - `static/js/ui.js` — shared utilities (`apiFetch`, `toast`, `esc`, `statusBadge`, polling)
  - `static/js/app.js` — main app logic (create form, library, detail modal, review section)
  - `static/js/settings.js` — settings panel (writer/reviewer config, model fetch, persistence)
  - `static/index.html` — clean HTML skeleton only (links CSS/JS, defines DOM structure)
- **Tags/length in prompts:** When adding new orchestrator methods, always inject `book_state.tags` and `book_state.length` into the LLM prompts so the generation stays consistent with user intent.
- **AI config changes:** Use `ai_client.update_config()` for runtime updates. The `AIClient` uses mutable properties for endpoint, model, and API key. `ReviewerClient` has its own `update_config()` for reviewer-specific settings. Config is persisted via `save_config()` in storage.
- **Reviewer config:** Reviewer settings (endpoint, model) are optional. Empty values mean the reviewer uses the same endpoint/model as the writer. Configure via `REVIEWER_ENDPOINT_URL`/`REVIEWER_MODEL_NAME` env vars, GUI settings panel, or `POST /api/config`.
