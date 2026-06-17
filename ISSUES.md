# ISSUES.md — Hullucinator Code Review

Comprehensive critical review of the Hullucinator codebase. Issues are categorized by severity.

---

## Critical

### C1. `app/__init__.py` is missing
**File:** `app/` directory
**Impact:** The `app` package has no `__init__.py`. While Python 3.3+ supports implicit namespace packages, this breaks with `setuptools.packages.find` (which requires explicit packages) and can cause import issues in some deployment contexts (e.g., `pip install .`, Docker).
**Fix:** Create an empty `app/__init__.py`.

### C2. Version mismatch between `pyproject.toml` and `main.py`
**File:** `pyproject.toml` vs `app/main.py`
**Impact:** `pyproject.toml` declares `version = "1.0.0"` but `app/main.py` declares `version="1.2.0"` on the FastAPI app and `"%(prog)s 1.2.0"` on the CLI. This inconsistency causes confusion in `--version` output, API docs, and package metadata.
**Fix:** Sync both to the same version number (recommended: `1.2.0` since that reflects current feature set).

### C3. `global` statements in `main.py` for mutable state
**File:** `app/main.py` — `update_ai_config` function
**Impact:** The `update_ai_config` endpoint uses `global configured, reviewer_client, _persisted` to mutate module-level state. This pattern is fragile: it doesn't work cleanly with module reloading, can cause subtle bugs in long-running servers, and makes testing harder (the `_reset_config` fixture has to manually reset each global).
**Fix:** Replace module-level globals with a mutable config object (e.g., a `ServerConfig` dataclass or simple dict wrapper) that is passed or referenced by all components.

### C4. `list_available_models` temporarily mutates shared `ai_client` state
**File:** `app/main.py` — `list_available_models` endpoint
**Impact:** The endpoint temporarily overwrites `ai_client.endpoint_url` and `ai_client.api_key` to use query-parameter values, then restores them in a `finally` block. This is **not thread-safe**: if two concurrent requests arrive, one can overwrite the other's values, causing incorrect endpoint usage or leaking API keys between requests.
**Fix:** Create a temporary `AIClient` for the fetch, or use `_client.get()` directly with a custom URL/headers without mutating the shared client.

---

## High

### H1. No concurrency limit on background tasks
**File:** `app/main.py` — `_active_tasks` dict
**Impact:** Users can queue unlimited books simultaneously. Each book generation makes multiple sequential LLM calls (summary + outline + N chapters + N summaries + review turns). With 15 chapters and 2 review turns, that's ~35+ HTTP calls per book. 10 concurrent books = 350+ in-flight requests, causing memory exhaustion and LLM provider rate limits.
**Fix:** Add a `Semaphore` or bounded `asyncio.Queue` to limit concurrent generation tasks (e.g., max 3-5 concurrent books).

### H2. No CORS middleware configured
**File:** `app/main.py`
**Impact:** If the web UI is served from a different origin (e.g., behind a reverse proxy, CDN, or separate frontend deployment), all API calls will be blocked by the browser's CORS policy. The app works fine when served directly by FastAPI, but is unusable in any split-deployment scenario.
**Fix:** Add `CORSMiddleware` to the FastAPI app:
```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

### H3. Review runs automatically with no way to skip
**File:** `app/main.py` — `_run_generation_pipeline`
**Impact:** The generation pipeline unconditionally calls `review_book()` after chapters complete. Users who want a quick draft without review have no way to opt out. The create form's `review_max_turns` selector implies review is optional, but the pipeline always runs it.
**Fix:** Add a `skip_review` flag to `BookCreateRequest` and conditionally call `review_book()` only when requested.

### H4. `_parse_critique` fallback regex is fragile
**File:** `app/orchestrator.py` — `_parse_critique` method
**Impact:** When the reviewer LLM doesn't return valid JSON, the fallback regex parser attempts to extract issues from free-form text. The regex patterns (`(?:issue|problem|finding)\s*#?\s*\d+`) are brittle and may:
- Miss issues described in non-standard formats
- Produce false positives from unrelated text
- Fail to parse chapter names, issue types, or descriptions correctly
This means review corrections may be incomplete or incorrect.
**Fix:** Add a stronger system prompt enforcing JSON output. Consider adding a "re-prompt" step where the LLM is asked to reformat its critique as JSON if the first attempt fails.

### H5. `_match_chapter_title` uses naive character overlap scoring
**File:** `app/orchestrator.py` — `_match_chapter_title` method
**Impact:** The fuzzy matching algorithm uses simple character overlap ratio, which fails for semantically equivalent but textually different titles:
- "Chapter One: The Start" vs "Chapter 1: The Beginning" → low score
- "The Beginning" vs "Chapter 1: The Beginning" → works (substring match)
- "Ch. 1: Start" vs "Chapter 1: The Start" → may fail
This means review corrections may be applied to wrong chapters or skipped entirely.
**Fix:** Use a proper fuzzy matching library (e.g., `python-Levenshtein` or `thefuzz`) or add token-based comparison.

### H6. `markdown_to_html` is a basic regex converter
**File:** `app/exporter.py` — `markdown_to_html` function
**Impact:** The EPUB export uses a hand-rolled regex-based markdown-to-HTML converter that:
- Does not handle nested formatting (**bold inside *italic***)
- Does not handle blockquotes (`> text`)
- Does not handle links (`[text](url)`)
- Does not handle images (`![alt](url)`)
- Does not handle code blocks (``` ... ```)
- Does not handle strikethrough (`~~text~~`)
Since LLMs frequently produce rich markdown, EPUB exports will have missing or incorrect formatting.
**Fix:** Use a proper markdown parser library (e.g., `python-markdown` or `mistune`) instead of regex.

### H7. PDF export strips all markdown formatting
**File:** `app/exporter.py` — `export_to_pdf` function
**Impact:** The PDF export strips markdown syntax (`**bold**` → `bold`, `*italic*` → `italic`, headings → plain text) rather than rendering it. The resulting PDF has no visual distinction between headings, bold, italic, and body text — it's essentially a plain-text dump. This contradicts the README claim of "rich exports."
**Fix:** Use the markdown-to-HTML converter for PDF content, then render HTML to PDF using a library like `weasyprint` or `xhtml2pdf`. Alternatively, add proper formatting to the FPDF output (detect bold/italic/heading markers and apply corresponding font styles).

---

## Medium

### M1. `_resolve_static_dir` `importlib.resources` call is broken
**File:** `app/main.py` — `_resolve_static_dir` function
**Impact:** `resources.files("static")` tries to import a Python package named `"static"`, but `static/` is a directory of HTML/CSS/JS files, not a Python package. This always raises `ImportError` and falls through to the source-tree path. The installed-package path is dead code.
**Fix:** Remove the `importlib.resources` branch. For installed packages, use `importlib.resources.files("app") / "static"` since `static` is declared as package data in `pyproject.toml`.

### M2. `Dockerfile` has hardcoded local defaults
**File:** `Dockerfile`
**Impact:** The Dockerfile sets `ENV AI_ENDPOINT_URL=http://192.168.0.40:1234` and `ENV AI_MODEL_NAME=qwen3.6-27b`. These are the developer's local Ollama instance defaults. Anyone building and running the Docker image will have these baked in, which is confusing and potentially a security concern (exposing internal network addresses).
**Fix:** Remove the hardcoded defaults from the Dockerfile. Users should configure via the setup wizard or `.env` file.

### M3. `ReviewerClient` doesn't support `model_override`
**File:** `app/ai_client.py` — `ReviewerClient.generate_completion`
**Impact:** `AIClient.generate_completion` accepts a `model_override` parameter, but `ReviewerClient.generate_completion` does not. This means the reviewer can't be dynamically switched to a different model for a specific call.
**Fix:** Add `model_override` parameter to `ReviewerClient.generate_completion` for consistency.

### M4. Review text can exceed LLM context window
**File:** `app/orchestrator.py` — `review_book` method
**Impact:** The review step sends the **entire book** (summary + outline + all chapter content + prior review history) to the LLM in a single prompt. For epic-length books (15-25 chapters, 50,000+ words), this can easily exceed the context window of many models, causing truncation or errors.
**Fix:** Implement chunked review: send chapters in batches (e.g., 5 at a time) and aggregate results. Or use a summarization step to condense the book before review.

### M5. No input validation on title/prompt length
**File:** `app/schemas.py` — `BookCreateRequest`
**Impact:** The schema accepts unlimited-length strings for `title` and `prompt`. Extremely long inputs (e.g., pasting an entire novel as a prompt) could cause:
- LLM API errors (input too large)
- Excessive token usage and cost
- Slow generation times
**Fix:** Add `Field(max_length=...)` constraints: title ≤ 200 chars, prompt ≤ 5000 chars.

### M6. `review_max_turns` has no upper bound validation
**File:** `app/schemas.py` — `BookCreateRequest` and `AIConfig`
**Impact:** The schema accepts any integer for `review_max_turns`. A user could set `review_max_turns: 100` via the API, causing 100 rounds of critique→correct→re-critique, which is wasteful and expensive. The web UI limits to 1-5 via the `<select>`, but the API has no guard.
**Fix:** Add `Field(ge=1, le=10)` validation to `review_max_turns` fields.

### M7. `settings.js` — `saveConfig` sends `null` for empty fields, can't clear values
**File:** `static/js/settings.js` — `saveConfig` function
**Impact:** When the user leaves the reviewer endpoint or model field blank in the settings panel, the JS sends `null`. The server's `update_ai_config` treats `None` fields as "don't change this value." This means users **cannot clear** a previously-set reviewer endpoint/model from the GUI — the old value persists.
**Fix:** Send empty string `""` instead of `null` for cleared fields, or change the server to treat `null` as "clear this field."

### M8. `conftest.py` — `_ensure_dirs` removes `config.json` before every test
**File:** `tests/conftest.py`
**Impact:** The `autouse` fixture deletes `data/config.json` before every test. This means tests that depend on persisted config state (e.g., testing restart behavior) can't work. The `_reset_config` fixture in `test_api.py` tries to compensate by resetting module-level state, but there's a timing issue: the config file is deleted before the test runs, and the module-level `_persisted` variable may still reference the old config.
**Fix:** Only clean up config in tests that explicitly need it, or use a separate test data directory.

### M9. `pyproject.toml` includes `static*` in setuptools packages
**File:** `pyproject.toml` — `[tool.setuptools.packages.find]`
**Impact:** `include = ["app*", "static*"]` tells setuptools to treat `static/` as a Python package. Since `static/` contains no Python files and no `__init__.py`, this can cause packaging warnings or errors. The `static` directory should be included as package data under `app`, not as its own package.
**Fix:** Remove `"static*"` from `include` and ensure `static/` files are included via `[tool.setuptools.package-data]` under `app`.

### M10. `ebooklib` UID collision in EPUB export
**File:** `app/exporter.py` — `export_to_epub` function
**Impact:** The EPUB stylesheet is assigned `uid=book_id` (the book's UUID), but the book identifier is also set to `book_id` via `book.set_identifier(book_id)`. Having the same UID for both the book-level identifier and a content item violates the EPUB specification and can cause validation failures in EPUB readers.
**Fix:** Use a distinct UID for the stylesheet, e.g., `uid="style_css"`.

---

## Low

### L1. `AIClient` timeout hardcoded to 1800 seconds
**File:** `app/ai_client.py` — `__init__`
**Impact:** The HTTP client timeout is hardcoded to 30 minutes. For very large completions (epic books with 25 chapters), individual chapter generation could approach this limit. Should be configurable via environment variable.
**Fix:** Add `AI_TIMEOUT` environment variable with a reasonable default.

### L2. Retry backoff uses fixed multipliers without jitter
**File:** `app/ai_client.py` — `generate_completion`
**Impact:** Retry delays use `10 * (attempt + 1)` and `15 * (attempt + 1)` — fixed linear multipliers. Without random jitter, concurrent retries from multiple tasks can thunder-herd, all retrying at the same time.
**Fix:** Add random jitter: `wait = base_delay * (attempt + 1) * (0.5 + random.random())`.

### L3. `_MINIMAL_INDEX` fallback HTML is bloated
**File:** `app/main.py`
**Impact:** The inline fallback HTML is over 2KB of embedded CSS/JS. In normal operation (when `static/index.html` exists), this code is never used. It adds unnecessary bulk to `main.py`.
**Fix:** Remove the fallback or reduce it to a minimal "static files not found" message.

### L4. No Content Security Policy (CSP) headers
**File:** `app/main.py`
**Impact:** The app doesn't set CSP headers. While the inline fallback HTML contains `<script>` tags, the normal UI loads external JS files. Without CSP, the app is more vulnerable to XSS attacks if any endpoint is compromised.
**Fix:** Add a `SecurityHeadersMiddleware` or `CORSMiddleware` with CSP configuration.

### L5. `esc()` in `ui.js` creates DOM elements for every call
**File:** `static/js/ui.js`
**Impact:** The `esc()` function creates a new DOM element, sets `textContent`, and reads `innerHTML` for every string it escapes. For large book content (tens of thousands of characters), this is significantly slower than a regex-based approach.
**Fix:** Use a simple regex: `return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');`

### L6. `loadBooks` re-renders entire library list on every call
**File:** `static/js/app.js` — `loadBooks` function
**Impact:** Every time `loadBooks()` is called (on page load, after create, during polling), it rebuilds the entire DOM for all book cards. This causes unnecessary DOM thrashing, especially with many books.
**Fix:** Use keyed reconciliation: compare existing cards with new data and only update changed cards.

### L7. `startPolling` doesn't debounce rapid modal opens
**File:** `static/js/ui.js` — `startPolling` function
**Impact:** If a user rapidly clicks on multiple book cards to open detail modals, each click starts a new 3-second polling interval. While `stopPolling()` clears the previous interval, the async callback from the old interval may still fire after the new one starts, causing stale updates.
**Fix:** Add a debounce or ensure the polling callback checks that `pollingBookId` still matches before updating.

### L8. `fpdf2` import path inconsistency
**File:** `app/exporter.py` — `from fpdf.fpdf import FPDF`
**Impact:** The import `from fpdf.fpdf import FPDF` works with `fpdf2` because fpdf2 maintains backward compatibility with the original fpdf import path. However, this is fragile — a future fpdf2 version may change the import path. The `requirements.txt` specifies `fpdf2>=2.0.0`.
**Fix:** Use the canonical fpdf2 import: `from fpdf import FPDF`.

### L9. No test coverage for orchestrator logic
**File:** `tests/`
**Impact:** The test suite covers storage (save/load) and API endpoints, but has **no tests** for:
- `orchestrator._parse_outline()` — critical for handling varied LLM output formats
- `orchestrator._parse_critique()` — critical for review correctness
- `orchestrator._match_chapter_title()` — critical for review-to-chapter mapping
- `orchestrator._generate_chapter()` — prompt construction
- `exporter.markdown_to_html()` — edge cases in markdown conversion
These are the most complex and bug-prone parts of the codebase.
**Fix:** Add unit tests for all orchestrator parsing/matching methods and exporter markdown conversion.

### L10. No test for export functionality
**File:** `tests/`
**Impact:** There are no tests for `export_to_epub()` or `export_to_pdf()`. Export failures (e.g., invalid EPUB structure, PDF font errors) would go undetected.
**Fix:** Add tests that generate a minimal book and verify EPUB/PDF export produces valid files.

---

## Observations (Not Bugs, But Worth Noting)

### O1. `data/` and `exports/` are gitignored but contain production data
The `.gitignore` excludes `data/` and `exports/`, which is correct. However, the `data/config.json` contains the user's AI endpoint and model configuration. If a user deploys by copying the project directory (e.g., `rsync`), they may accidentally copy config with sensitive endpoint URLs. Consider documenting this.

### O2. Export files accumulate without cleanup
Exported EPUB/PDF files in `exports/` are never cleaned up. Over time, this consumes disk space. Consider a configurable retention policy or periodic cleanup.

### O3. Review token budget for long books
The review step sends the entire book to the LLM, which can be very expensive for epic-length books (50,000+ words). Consider a summarization-based review approach for long books.

### O4. No authentication or authorization
The API is completely open. Anyone with network access can create books, read all books, modify config, and trigger reviews. For production deployments behind a public-facing network, add authentication.

---

## Summary

| Severity | Count | Key Items |
|----------|-------|-----------|
| Critical | 4 | Missing `__init__.py`, version mismatch, `global` state, race condition in model listing |
| High | 7 | No concurrency limit, no CORS, mandatory review, fragile critique parser, weak fuzzy matching, basic markdown→HTML, PDF strips formatting |
| Medium | 10 | Broken `importlib.resources`, hardcoded Docker defaults, no `model_override` for reviewer, context window overflow, no input validation, can't clear reviewer config, test config cleanup, setuptools package config, EPUB UID collision |
| Low | 10 | Hardcoded timeout, no jitter, bloated fallback, no CSP, slow `esc()`, DOM thrashing, polling race, fpdf import, missing orchestrator tests, missing export tests |

**Total: 31 issues identified.**

Recommended priority: Address C1-C4 first (they affect correctness and reliability), then H1-H7 (they affect user experience and data integrity), then M1-M10 (improvements), and finally L1-L10 (polish).
