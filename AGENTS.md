# AGENTS.md — Development Context for Hullucinator

This file captures architectural decisions, known issues, and conventions to ensure consistency across future changes.


## Core Principles

After every change, review and if required update the `README.md` and `AGENTS.md` file.


## Architecture Overview

Hullucinator is a **FastAPI service with a web interface** that orchestrates LLM calls to generate complete e-books from a user prompt. The pipeline is linear and runs as a background task:

```
POST /api/books/create → (background) generate_summary → generate_outline → generate_chapters → review
```

### Components

| Module | Responsibility | Key Details |
|--------|---------------|-------------|
| `app/main.py` | FastAPI app & HTTP endpoints | Defines all API + web UI endpoints. Creates `AIClient` and `Orchestrator` as module-level singletons. Configured via environment variables. Background task support via `asyncio.create_task()`. Serves static web UI. **New: AI config endpoints** (`GET/POST /api/config`, `GET /api/models`). **New: review trigger** (`POST /api/books/{id}/review`). |
| `app/schemas.py` | Data models | `BookState` Pydantic model: `id`, `title`, `prompt`, `tags` (List[str]), `length` (str), `status`, `summary`, `outline`, `chapters`, `chapter_summaries` (Dict[str,str]), `metadata`, `review` (Dict), `progress` (Dict). `BookCreateRequest` for API input. |
| `app/storage.py` | Persistence | JSON files in `data/books/`. Uses **absolute path** from project root. `list_books()` returns all books sorted by modification time. `EXPORTS_DIR` shared with exporter. |
| `app/ai_client.py` | LLM API client | Talks to OpenAI-compatible `/v1/chat/completions`. Retries 2x on 429/500/503 or empty responses. Uses **persistent** `httpx.AsyncClient`. Uses **async** `await asyncio.sleep()`. **New: runtime-reconfigurable** endpoint, model, and API key via properties. **New: `list_models()`** fetches available models from `/v1/models`. |
| `app/orchestrator.py` | Pipeline coordinator | 4 async methods + `validate_book`. Each step saves state to disk. **Enforced status transitions** prevent data inconsistencies. Progress tracking updated at each step. Improved outline parser. **Tags and length** guide LLM prompts throughout the pipeline. **New: chapter continuity** — each chapter receives cumulative context via condensed chapter summaries. **New: post-completion review** — professional critic reviews the book, identifies issues, and corrects them. Full audit trail in `book_state.review`. |
| `app/exporter.py` | EPUB/PDF export | EPUB: full CSS styling, markdown→HTML conversion, TOC, drop caps, **genre tags as EPUB subjects**. PDF: plain text with configurable font paths (env var `PDF_FONT_DIR`), fallback to Helvetica, **tags on title page**. Uses absolute `EXPORTS_DIR` from storage. **New: review metadata** included in exports (score, verdict, corrections on title page). |
| `static/index.html` | Web interface | Polished dark-themed SPA with book creation form (title, prompt, **tags**, **length** selector), library view with tag/length badges, progress polling, detail modal, EPUB/PDF downloads. **New: Settings panel** for runtime AI configuration (endpoint URL, API key, model selector with live model list). **New: review section** in detail modal showing critique, score, verdict, and correction audit trail. |

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_ENDPOINT_URL` | `http://192.168.0.40:1234` | LLM API endpoint |
| `AI_MODEL_NAME` | `qwen3.6-27b` | Model name |
| `AI_API_KEY` | *(empty)* | Bearer token |
| `HULLUCINATOR_HOST` | `0.0.0.0` | Bind address |
| `HULLUCINATOR_PORT` | `8000` | Port |
| `PDF_FONT_DIR` | `/usr/share/fonts/truetype/dejavu` | PDF font directory |
| `LOG_LEVEL` | `INFO` | Logging level |

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
Exported files in `exports/` accumulate without cleanup. Consider a configurable retention policy or periodic cleanup.

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
- **Storage format:** One JSON file per book in `data/books/`, named `{id}.json`
- **Export format:** EPUB and PDF files written to `exports/` directory, named `{book_id}.{ext}`
- **Chapter storage:** Dict mapping chapter title (string) → chapter content (string)
- **Chapter summaries:** Dict mapping chapter title (string) → one-paragraph summary (string). Generated after each chapter for continuity context.
- **Progress tracking:** `progress` dict with `current_step`, `total_chapters`, `chapters_completed`, `percentage`
- **API prefix:** All API endpoints use `/api/` prefix; web UI served at `/`
- **Logging:** Structured logging via Python `logging` module; configurable via `LOG_LEVEL`
- **Tags:** List of genre/theme strings (e.g. `comedy`, `dark fantasy`, `biography`). Guided by user input, injected into all LLM prompts. Stored in `BookState.tags`. Default: empty list.
- **Book length:** One of `short_story`, `novella`, `novel`, `epic`. Controls chapter count (`LENGTH_CHAPTER_COUNT`) and word count (`LENGTH_WORD_COUNT`) in orchestrator prompts. Default: `novel` (8–15 chapters, 20,000–50,000 words).
- **Review audit:** `BookState.review` dict with `critique` (raw LLM response), `issues` (list of identified problems), `overall_score` (0-10), `verdict` (`needs_revision` | `ready`), `corrections` (list of applied fixes), `reviewed` (bool).

## Chapter Continuity Design

Each chapter generation follows this context strategy:

1. **Book summary** — Overall direction and themes
2. **Full outline** — Structural awareness of all chapters
3. **Condensed chapter summaries** — One-paragraph summaries of all previously generated chapters, in order

This approach provides narrative continuity without consuming excessive tokens from full chapter text. After each chapter is generated, a concise summary is created and stored in `chapter_summaries` for use by subsequent chapters.

## Review Design

The review process runs automatically after chapter generation:

1. **Critique:** Full book (summary + outline + all chapters) sent to LLM acting as professional critic
2. **Issue Detection:** Critic identifies plot holes, character inconsistencies, pacing issues, continuity errors, tone inconsistencies, and unresolved threads
3. **Correction Loop:** For each issue, the affected chapter is re-revisioned with context from the rest of the book
4. **Audit Trail:** Full critique text, issues list, and corrections are stored in `book_state.review`
5. **Export:** Review metadata (score, verdict, corrections count) included in EPUB/PDF title pages

## Adding Features

When extending the system, follow these patterns:

- **New generation steps:** Add a method to `Orchestrator`, add to `VALID_TRANSITIONS`, call it from `_run_generation_pipeline`, and persist state via `save_book`.
- **New export formats:** Add a function in `exporter.py` following the existing pattern (takes `book_id`, `title`, `chapters`, `tags`, `output_dir`, `review`). Use absolute `EXPORTS_DIR` from `storage`.
- **New endpoints:** Define in `main.py` under `/api/` prefix. Use `load_book()` for lookup + `validate_book()` before processing.
- **Web UI changes:** Edit `static/index.html`. The JS uses `apiFetch()` helper for all API calls.
- **Tags/length in prompts:** When adding new orchestrator methods, always inject `book_state.tags` and `book_state.length` into the LLM prompts so the generation stays consistent with user intent.
- **AI config changes:** Use `ai_client.update_config()` for runtime updates. The `AIClient` uses mutable properties for endpoint, model, and API key.
