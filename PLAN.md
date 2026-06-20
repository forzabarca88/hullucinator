# Hullucinator Refactoring Plan

A comprehensive plan to address code fragility, duplicated logic, config drift, test quality, and modularity.

---

## 1. Duplicated Code — Consolidation

### 1.1 `_extract_content()` — duplicated between `orchestrator.py` and `ai_client.py`

**Where:**
- `app/ai_client.py` — `AIClient._extract_content()` (static method, ~6 lines)
- `app/orchestrator.py` — module-level `_extract_content()` (module function, identical logic)

**Problem:** Two copies of the same content-extraction logic. The orchestrator re-implements it instead of importing from `AIClient`. This means any fix (e.g., handling a new response format) must be applied in two places.

**Action:** Import `_extract_content` from `ai_client` in `orchestrator.py`. Delete the module-level copy from `orchestrator.py`. All call sites in `orchestrator.py` already use `_extract_content()` so this is a simple import swap.

---

### 1.2 `_parse_models_response()` logic — duplicated 3×

**Where:**
- `app/ai_client.py` — `AIClient.list_models()` (inline, ~15 lines)
- `app/ai_client.py` — `ReviewerClient.list_models()` (identical inline copy, ~15 lines)
- `app/main.py` — `_parse_models_response()` (standalone function, same logic)

**Problem:** The same JSON-parsing logic (handle `data` key, list response, error response, dict keys) is copy-pasted in three places. Any change to model-listing behavior requires editing three files.

**Action:** Extract to a standalone function `_parse_models_response(result)` in `app/ai_client.py`. Have both `AIClient.list_models()` and `ReviewerClient.list_models()` call it. Remove the copy from `main.py` and import the function instead.

---

### 1.3 `/v1` suffix URL construction — duplicated 6×

**Where:**
- `AIClient.list_models()` — `url = f"{self._endpoint_url}/models" if self._endpoint_url.endswith('/v1') else ...`
- `AIClient.generate_completion()` — same pattern for `/chat/completions`
- `ReviewerClient.list_models()` — same pattern
- `ReviewerClient.generate_completion()` — same pattern
- `main.py` `list_reviewer_models()` — same pattern (inline, not using client)

**Problem:** The URL construction logic (append `/v1` suffix unless endpoint already ends with `/v1`) is copy-pasted everywhere. A change to the URL scheme (e.g., supporting `/openai/` prefix variants) requires editing 6 locations.

**Action:** Create a module-level helper `_build_api_url(endpoint, path_suffix)` in `app/ai_client.py`:
```python
def _build_api_url(endpoint: str, path_suffix: str) -> str:
    base = endpoint.rstrip('/')
    if base.endswith('/v1'):
        return f"{base}/{path_suffix}"
    return f"{base}/v1/{path_suffix}"
```
Replace all inline URL construction in both `AIClient` and `ReviewerClient` with calls to this helper. In `main.py`, import and use it for the reviewer models endpoint.

---

### 1.4 Review text building — duplicated between `review_book()` and `_chunked_review()`

**Where:** `app/orchestrator.py` — both methods contain identical blocks for building the review prompt text:
- `review_text = f"Book: {book_state.title}\nGenre: {tags_str}\n\n"`
- `review_text += f"Summary:\n{book_state.summary}\n\n"`
- `review_text += "Outline:\n" + "\n".join(...)`
- Chapter separator: `f"\n{'='*60}\nChapter {idx}: {title}\n{'='*60}\n{content}"`
- Prior review history injection block
- Critique system prompt string

**Problem:** The review prompt construction is copy-pasted between the full-book review and chunked review paths. Any improvement to the review prompt (e.g., adding genre-specific critique criteria) requires editing both methods.

**Action:** Extract `_build_review_text(book_state, chapters, turn_num)` as a module-level helper in `orchestrator.py`. Both `review_book()` and `_chunked_review()` call it. For chunked review, pass only the chunk's chapters; for full review, pass all chapters.

---

### 1.5 Revision context building — duplicated between `review_book()` and `_chunked_review()`

**Where:** Both methods contain identical blocks for building the revision prompt:
- Prior chapter summaries collection (iterating `book_state.outline` and `book_state.chapter_summaries`)
- Revision system prompt string
- Revision user prompt template

**Problem:** Same duplication risk as review text building.

**Action:** Extract `_build_revision_context(book_state, chapter_title)` as a module-level helper that returns `(system_prompt, user_prompt)` tuple. Both methods call it.

---

### 1.6 Review turn recording — duplicated between `review_book()` and `_chunked_review()`

**Where:** Both methods contain identical blocks for recording review results:
- `turn_record` dict construction
- `book_state.review_history.append(turn_record)`
- `book_state.review = turn_record`
- `save_book(book_state.id, book_state)`

**Problem:** The audit trail recording logic is copy-pasted. Any change to the review history schema requires editing both methods.

**Action:** Extract `_record_review_turn(book_state, turn_record)` as a module-level helper. Both methods call it.

---

### 1.7 Progress update pattern — repeated throughout `orchestrator.py`

**Where:** Nearly every method in `orchestrator.py` updates `book_state.progress` with the same pattern:
```python
book_state.progress["current_step"] = "..."
book_state.progress["percentage"] = N
save_book(book_state.id, book_state)
```

**Problem:** ~15 occurrences of this three-line pattern. Any change to progress tracking (e.g., adding elapsed time, tokens used) requires editing every occurrence.

**Action:** Extract `_update_progress(book_state, step, percentage)` helper that updates the progress dict and saves. Replace all inline progress updates with calls to this helper.

---

### 1.8 Status text mapping — duplicated between backend and frontend

**Where:**
- `static/js/ui.js` — `statusBadge()` has a `textMap` dict mapping status keys to display labels
- `static/css/styles.css` — CSS classes like `.status-pending`, `.status-completed`, etc.
- Backend: status values used in `VALID_TRANSITIONS`, `orchestrator.py`, and `schemas.py` comments

**Problem:** The mapping of internal status keys (`summary_generated`, `outline_generated`, etc.) to human-readable labels exists in JS but not in a shared place. Adding a new status requires updating Python, JS, and CSS separately.

**Action:** See Section 2 (Shared Config). Status mappings should live in the shared config and be consumed by both frontend and backend.

---

### 1.9 Length option definitions — duplicated between backend and frontend

**Where:**
- `app/orchestrator.py` — `LENGTH_CHAPTER_COUNT` and `LENGTH_WORD_COUNT` dicts
- `static/index.html` — `<select id="bookLength">` options with human-readable descriptions
- `static/index.html` — `<select id="maxTurns">` options with descriptions

**Problem:** The valid values and their human-readable descriptions exist in both Python and HTML. Adding a new length tier (e.g., `mega_epic`) requires updating both.

**Action:** See Section 2 (Shared Config). Length definitions should be in shared config.

---

### 1.10 Retry logic — duplicated between `app.js` and `main.py`

**Where:**
- `static/js/app.js` — `retryBook()` function reconstructs a `BookCreateRequest` from the old book's fields
- `app/main.py` — `_run_generation_pipeline()` runs the full pipeline

**Problem:** The frontend retry logic manually reconstructs the create request. If the `BookCreateRequest` schema changes (new fields, renamed fields), the frontend retry breaks silently.

**Action:** Add a `POST /api/books/{id}/retry` endpoint that loads the book, constructs a new `BookCreateRequest` from its fields, and calls the same creation logic as `/api/books/create`. The frontend simply calls this endpoint instead of reconstructing the request manually.

---

## 2. Shared Configuration — Eliminate Config Drift

### 2.1 Current State of Config Drift

The following values are hardcoded in multiple files with no single source of truth:

| Value | Python locations | JS/HTML locations |
|-------|------------------|-------------------|
| `review_max_turns` default (2) | `schemas.py`, `main.py`, `orchestrator.py` | `settings.js` (×3), `app.js`, `index.html` (×2) |
| `review_word_threshold` default (30000) | `schemas.py`, `orchestrator.py` | `settings.js` (×3), `index.html` (×2) |
| `review_chunk_size` default (5) | `schemas.py`, `orchestrator.py` | `settings.js` (×3), `index.html` (×2) |
| Valid lengths (`short_story`, `novella`, `novel`, `epic`) | `schemas.py` (comment), `orchestrator.py` | `index.html` (select options) |
| Length → chapter count mapping | `orchestrator.py` (`LENGTH_CHAPTER_COUNT`) | `index.html` (option text) |
| Length → word count mapping | `orchestrator.py` (`LENGTH_WORD_COUNT`) | `index.html` (option text) |
| Valid statuses | `orchestrator.py` (`VALID_TRANSITIONS`) | `ui.js` (`statusBadge` textMap), `css` (status classes) |
| Review score thresholds (7 = pass) | `orchestrator.py` (hardcoded `>= 7`) | `app.js` (`buildReviewSection` scoreClass) |
| Polling interval (3s) | — | `ui.js` (`startPolling`, hardcoded `3000`) |
| Library polling interval (10s) | — | `ui.js` (`LIBRARY_POLL_INTERVAL`, hardcoded `10000`) |
| Max retries (2) | `ai_client.py` (default param) | — |
| Retry backoff (10s, 15s) | `ai_client.py` (hardcoded) | — |

### 2.2 Proposed Solution: Shared Config Endpoint

**Create `app/config.py`** — a new module that defines all shared configuration as a single Pydantic model:

```python
"""
Shared configuration — the single source of truth for all tunable parameters.
Served to the frontend via GET /api/config-schema.
"""
from pydantic import BaseModel, Field
from typing import Dict, List, Literal

class LengthConfig(BaseModel):
    key: str                    # "short_story", "novella", "novel", "epic"
    label: str                  # human-readable: "Short Story"
    chapter_range: str          # "1", "3-5", "8-15", "15-25"
    word_range: str             # "1,000-7,500", "7,500-20,000", etc.

class StatusConfig(BaseModel):
    key: str                    # "pending", "summary_generated", etc.
    label: str                  # display label: "pending", "summary", etc.
    css_class: str              # "status-pending", "status-summary_generated", etc.
    is_terminal: bool           # True for completed, reviewed, failed
    is_active: bool             # True for statuses that trigger polling

class ReviewConfig(BaseModel):
    max_turns_default: int = Field(default=2, ge=1, le=10)
    max_turns_range: tuple = (1, 10)
    word_threshold_default: int = Field(default=30_000, ge=1_000)
    chunk_size_default: int = Field(default=5, ge=1, le=20)
    pass_score: int = 7         # score threshold for "ready" verdict
    turn_options: List[dict]    # [{value: 1, label: "1 turn — quick"}, ...]

class ClientConfig(BaseModel):
    max_retries: int = 2
    retry_base_wait: float = 10.0  # seconds
    retry_status_wait: float = 15.0
    empty_response_wait: float = 10.0
    jitter_factor: float = 0.5     # random multiplier range
    http_timeout: float = 1800.0   # seconds (30 min)

class UISchema(BaseModel):
    polling_interval_ms: int = 3000
    library_polling_interval_ms: int = 10000
    prompt_warn_threshold: int = 10000  # characters before warning
    title_max_length: int = 200

class SharedConfig(BaseModel):
    lengths: List[LengthConfig]
    statuses: List[StatusConfig]
    review: ReviewConfig
    client: ClientConfig
    ui: UISchema
```

**Default config** — `app/config.py` exports a `DEFAULT_SHARED_CONFIG` instance with all sensible defaults. This is:
1. Imported by `orchestrator.py` (replaces `LENGTH_CHAPTER_COUNT`, `LENGTH_WORD_COUNT`, `REVIEW_WORD_THRESHOLD`, `REVIEW_CHUNK_SIZE`)
2. Imported by `ai_client.py` (replaces hardcoded retry/backoff values)
3. Imported by `main.py` and served via a new endpoint `GET /api/config-schema`

**Frontend consumption** — `static/js/config.js` (new file):
```javascript
// Loaded once on boot, populated from GET /api/config-schema
let SHARED_CONFIG = null;

async function loadSharedConfig() {
  SHARED_CONFIG = await apiFetch('/config-schema');
}
```

All JS files that currently hardcode config values import from `SHARED_CONFIG`:
- `settings.js` reads defaults from `SHARED_CONFIG.review` and `SHARED_CONFIG.ui`
- `app.js` reads length options, status mappings, review thresholds from `SHARED_CONFIG`
- `ui.js` reads polling intervals from `SHARED_CONFIG.ui`

**HTML generation** — `static/js/config.js` provides helper functions:
```javascript
function renderLengthSelect(selectEl) {
  selectEl.innerHTML = SHARED_CONFIG.lengths.map(l =>
    `<option value="${l.key}">${l.label} (${l.chapter_range} chapters, ${l.word_range} words)</option>`
  ).join('');
}

function renderMaxTurnsSelect(selectEl) {
  selectEl.innerHTML = SHARED_CONFIG.review.turn_options.map(o =>
    `<option value="${o.value}" ${o.default ? 'selected' : ''}>${o.label}</option>`
  ).join('');
}
```

**Impact on existing files:**

| File | Changes |
|------|---------|
| `app/config.py` | **NEW** — defines `SharedConfig`, `DEFAULT_SHARED_CONFIG` |
| `app/schemas.py` | Remove default values from `review_max_turns`, `review_word_threshold`, `review_chunk_size` fields; import defaults from `config.py` |
| `app/orchestrator.py` | Replace `LENGTH_CHAPTER_COUNT`, `LENGTH_WORD_COUNT`, `REVIEW_WORD_THRESHOLD`, `REVIEW_CHUNK_SIZE` with imports from `config.py`. Replace `>= 7` score threshold with `shared_config.review.pass_score` |
| `app/ai_client.py` | Replace hardcoded retry/backoff values with `shared_config.client`. Replace `AI_TIMEOUT` env var with config value (env var becomes optional override) |
| `app/main.py` | Add `GET /api/config-schema` endpoint that returns `DEFAULT_SHARED_CONFIG.model_dump()`. Import shared config for server-side defaults |
| `static/js/config.js` | **NEW** — `SHARED_CONFIG` singleton, `loadSharedConfig()`, renderer helpers |
| `static/js/ui.js` | Replace hardcoded `statusBadge` textMap with `SHARED_CONFIG.statuses`. Replace polling interval constants with `SHARED_CONFIG.ui` |
| `static/js/settings.js` | Replace hardcoded defaults (`|| 2`, `|| 30000`, `|| 5`) with `SHARED_CONFIG.review` values |
| `static/js/app.js` | Replace hardcoded review score threshold (`score >= 7`) with `SHARED_CONFIG.review.pass_score` |
| `static/index.html` | Remove hardcoded `<option>` values from `<select id="bookLength">` and `<select id="maxTurns">`; mark them as `data-config-source="lengths"` and `data-config-source="turn_options"` for dynamic population |
| `static/js/boot.js` | Call `await loadSharedConfig()` before `initApp()` and `initSettings()` |
| `static/css/styles.css` | No change needed (CSS classes are structural, not config) |

---

## 3. Test Suite — Audit and Remediation

### 3.1 Current Test Inventory

| File | Tests | Purpose |
|------|-------|---------|
| `test_storage.py` | 9 tests | Round-trip save/load for books and config |
| `test_api.py` | 16 tests | HTTP endpoint behavior |
| `test_export.py` | 18 tests | EPUB/PDF export, markdown→HTML |
| `test_orchestrator.py` | 18 tests | Parsing, matching, transitions |
| `test_frontend.py` | 3 tests | CSP compliance, API path consistency |
| `conftest.py` | Fixtures | Test isolation, config reset |

### 3.2 Tests to REMOVE

**`test_orchestrator.py::TestParseOutline::test_empty_input`**
- Tests that empty input returns `["Chapter 1", "Chapter 2", "Chapter 3"]` default
- **Why remove:** This tests a fallback that should never be reached in production (the LLM always returns something). It validates a safety net, not business logic. If the parser ever returns this default, the outline generation step should fail loudly instead of proceeding with generic chapter titles.
- **Replace with:** A test that verifies `_parse_outline()` raises a clear error when no parseable content is found, rather than silently returning generic defaults.

**`test_orchestrator.py::TestParseOutline::test_prose_with_chapters`**
- Tests that prose text with chapter references is parsed
- **Why remove:** The assertion `assert len(result) >= 3` is too vague — it doesn't verify that the right titles were extracted. It passes even if the parser returns garbage as long as there are 3+ items.
- **Replace with:** A test with exact expected output: `assert result == ["Chapter 1: The Setup - Introduce the main character and setting", ...]`

**`test_orchestrator.py::TestParseCritique::test_text_fallback_score_extraction`**
- Tests regex-based score extraction from free-form text
- **Why remove:** This tests the regex pattern itself, not business logic. The regex is an implementation detail that will change as LLM output formats evolve. Testing the regex is fragile and provides no confidence in actual behavior.
- **Replace with:** An integration-style test that sends a realistic LLM response through the full `_parse_critique()` pipeline and asserts the final parsed structure.

**`test_orchestrator.py::TestParseCritique::test_text_fallback_issues`**
- Same problem as above — tests regex pattern matching on structured text
- **Why remove:** Tests implementation detail (regex) rather than business outcome (correct issue extraction)

**`test_orchestrator.py::TestMatchChapterTitle::test_normalized_exact_match`**
- Tests that `"chapter 1: the beginning"` matches `"Chapter 1: The Beginning!"`
- **Why remove:** This is a subset of `test_exact_match`. If exact normalized matching works, case/punctuation normalization is implicitly tested.
- **Keep** `test_exact_match` which already covers this implicitly.

**`test_orchestrator.py::TestMatchChapterTitle::test_substring_match`**
- Tests that `"The Beginning"` matches `"Chapter 1: The Long Beginning"`
- **Why keep but modify:** This tests a real matching strategy. However, the assertion should verify the exact matched title, not just that a match exists.
- **Modify:** `assert result == "Chapter 1: The Long Beginning"` (exact assertion)

**`test_api.py::TestBookEndpoints::test_create_book_missing_title`**
- Tests that empty title returns 422
- **Why remove:** This tests Pydantic's built-in validation (`Field(..., min_length=1)`), not any Hullucinator-specific logic. Pydantic guarantees this behavior.
- **Keep** the schema definition test in a unit test for `BookCreateRequest` instead.

**`test_api.py::TestBookEndpoints::test_create_book_missing_prompt`**
- Same as above — tests Pydantic's `Field(..., min_length=1)` validation
- **Why remove:** Same reason

**`test_api.py::TestBookEndpoints::test_create_book_invalid_review_max_turns`**
- Tests that `review_max_turns=0` and `review_max_turns=11` return 422
- **Why remove:** Tests Pydantic's `Field(..., ge=1, le=10)` constraint. Pydantic guarantees this.
- **Keep** the schema constraint test in a unit test for `BookCreateRequest` instead.

**`test_api.py::TestBookEndpoints::test_create_book_null_review_max_turns`**
- Tests that `review_max_turns=None` returns 422
- **Why remove:** Tests Pydantic's type coercion (None → rejected for int field). This is Pydantic behavior, not Hullucinator logic.

**`test_api.py::TestBookEndpoints::test_create_book_defaults`**
- Tests that omitted optional fields get schema defaults
- **Why remove:** Tests Pydantic's default value behavior. Trivially guaranteed by the schema definition.

**`test_api.py::TestBookEndpoints::test_create_book_invalid_length`**
- Tests that invalid length values are handled
- **Why modify:** The assertion `assert resp.status_code in (200, 400, 422)` accepts any of three status codes, making it effectively a no-op test. It doesn't verify any specific behavior.
- **Modify:** Add server-side validation for the `length` field in `BookCreateRequest` (Pydantic `Literal` type or custom validator) so the test can assert a specific 422 response.

**`test_export.py::TestMarkdownToHtml::test_combined_bold_italic`**
- Tests `***bold and italic***` parsing
- **Why remove:** The regex fallback parser doesn't handle combined bold+italic (`***text***`). The `markdown` library does, but this test doesn't specify which code path it's testing. It's testing an edge case that's either broken (regex) or delegated to a third-party library.
- **Replace with:** A test that explicitly verifies the `markdown` library handles this case when `HAS_MARKDOWN_LIB` is True, and documents that the regex fallback does not.

**`test_export.py::TestMarkdownToHtml::test_links`**
- Tests `[Google](https://google.com)` → `<a href="...">Google</a>`
- **Why remove:** The regex fallback parser has no link handling at all. This test only passes when `markdown` library is installed. It's testing a third-party library, not Hullucinator code.
- **Remove entirely** — link rendering is delegated to the `markdown` library.

**`test_export.py::TestMarkdownToHtml::test_blockquote`**
- Tests `> This is a quote` → `<blockquote>`
- **Why remove:** Same as links — the regex fallback doesn't handle blockquotes. Testing third-party library behavior.

**`test_export.py::TestMarkdownToHtml::test_html_escaping`**
- Tests `1 < 2 > 3` → `&lt;` and `&gt;`
- **Why remove:** The regex fallback escapes HTML, but the `markdown` library handles escaping internally. This test's behavior depends on which code path runs, making it non-deterministic.
- **Replace with:** A test that verifies HTML escaping works regardless of which parser is active, testing the output contract rather than the implementation.

**`test_api.py::TestWebUI::test_index_page`**
- Tests that `GET /` returns HTML containing "Hullucinator" and "setupOverlay"
- **Why modify:** This is a smoke test that's too fragile — it will break if the HTML content changes (e.g., renaming a div). It doesn't test meaningful behavior.
- **Modify:** Test that `GET /` returns status 200 with `Content-Type: text/html` and that the response body contains the `<script>` tags for `ui.js`, `app.js`, `settings.js`, `boot.js` (verifying the JS bundle loads correctly).

### 3.3 Tests to ADD

**Schema validation unit tests** (new file: `tests/test_schemas.py`):
```python
class TestBookCreateRequest:
    def test_requires_nonempty_title(self):
        """Pydantic rejects empty title."""
        with pytest.raises(ValidationError):
            BookCreateRequest(title="", prompt="test")

    def test_requires_nonempty_prompt(self):
        """Pydantic rejects empty prompt."""
        with pytest.raises(ValidationError):
            BookCreateRequest(title="Test", prompt="")

    def test_title_max_length(self):
        """Pydantic rejects titles exceeding 200 characters."""
        with pytest.raises(ValidationError):
            BookCreateRequest(title="A" * 201, prompt="test")

    def test_review_max_turns_range(self):
        """Pydantic enforces 1 <= review_max_turns <= 10."""
        with pytest.raises(ValidationError):
            BookCreateRequest(title="Test", prompt="test", review_max_turns=0)
        with pytest.raises(ValidationError):
            BookCreateRequest(title="Test", prompt="test", review_max_turns=11)

    def test_length_validation(self):
        """Pydantic enforces valid length values."""
        with pytest.raises(ValidationError):
            BookCreateRequest(title="Test", prompt="test", length="invalid")

    def test_defaults(self):
        """Omitted optional fields get correct defaults."""
        req = BookCreateRequest(title="Test", prompt="test")
        assert req.length == "novel"
        assert req.review_max_turns == 2
        assert req.skip_review is False
        assert req.tags == []
```

**Shared config tests** (new file: `tests/test_config.py`):
```python
class TestSharedConfig:
    def test_default_config_is_valid(self):
        """DEFAULT_SHARED_CONFIG passes validation."""
        config = get_default_shared_config()
        assert config.review.max_turns_default == 2
        assert config.review.word_threshold_default == 30_000
        assert config.review.chunk_size_default == 5
        assert config.review.pass_score == 7

    def test_config_endpoint_returns_schema(self):
        """GET /api/config-schema returns valid config."""
        # Tests the new endpoint

    def test_frontend_receives_config(self):
        """Frontend can load and use shared config."""
        # Tests that SHARED_CONFIG is populated after loadSharedConfig()
```

**Retry endpoint test** (add to `test_api.py`):
```python
class TestRetryEndpoint:
    async def test_retry_recreates_book(self, client):
        """POST /api/books/{id}/retry creates a new book from old fields."""
        # Creates a book, fails it, then retries — verifies new book has same fields

    async def test_retry_cancels_active_task(self, client):
        """Retry cancels any active generation task for the book."""
```

**Concurrency test** (new file: `tests/test_concurrency.py`):
```python
class TestConcurrency:
    async def test_semaphore_limits_concurrent_generations(self):
        """Verify that MAX_CONCURRENT_GENERATIONS limits parallel tasks."""
        # Creates multiple books simultaneously, verifies only N run at once

    async def test_delete_cancels_active_task(self, client):
        """Deleting a book in progress cancels its generation task."""
```

### 3.4 Test Infrastructure Improvements

**`conftest.py` — current problems:**
- `_reset_config` fixture references `server_config._persisted` which doesn't exist (the `ServerConfig` dataclass has `persisted` as a public attribute, not `_persisted`)
- The fixture is not `autouse` but the `test_api.py` fixture does its own reset, creating potential inconsistency

**Action:**
- Fix `_reset_config` to reference `server_config.persisted` (public attribute)
- Consolidate fixture logic: the `_isolate_api_tests` fixture in `test_api.py` already does comprehensive reset. The `_reset_config` fixture in `conftest.py` is redundant and buggy.
- Remove `_reset_config` from `conftest.py` entirely. Tests that need config reset should use the `test_api.py` fixture or import the reset logic directly.

**`test_export.py` — current problems:**
- Uses `sys.path.insert(0, ...)` to add project root to path. This is unnecessary when running pytest from the project root with proper `PYTHONPATH` or `pyproject.toml` configuration.
- Imports `ensure_exports_dir` from `app.storage` but never calls it (the export functions call it internally).

**Action:**
- Remove `sys.path.insert()` from all test files — pytest discovers the project root automatically.
- Remove unused `ensure_exports_dir` import from `test_export.py`.

---

## 4. Modularity — Restructure Files

### 4.1 `app/orchestrator.py` — Split into 4 modules

**Current state:** ~500 lines, contains:
- Status transition validation (`_transition`, `VALID_TRANSITIONS`)
- Parsing logic (`_parse_outline`, `_parse_critique`, `_match_chapter_title`, `_normalize_title`, `_extract_content`)
- Generation pipeline (`generate_summary`, `generate_outline`, `generate_chapters`, `_generate_chapter`, `_summarize_chapter`)
- Review pipeline (`review_book`, `_chunked_review`)
- Validation (`validate_book`)

**Proposed split:**

#### `app/status.py` — Status transition management
```python
"""Status transition validation for the book generation pipeline."""
VALID_TRANSITIONS: dict[str, list[str]] = { ... }

def _transition(book_state: BookState, new_status: str) -> None:
    """Transition book_state to new_status if valid, else raise ValueError."""
```
- Move `VALID_TRANSITIONS` and `_transition()` here
- All other modules import `_transition` from `app.status`

#### `app/parsing.py` — LLM response parsing
```python
"""Parsing utilities for LLM responses (outline, critique, chapter matching)."""
from app.ai_client import AIClient

def extract_content(result: dict) -> str:
    """Extract text content from LLM response (imported from AIClient)."""
    return AIClient._extract_content(result)

def parse_outline(outline_content: str) -> list[str]:
    """Parse chapter titles from LLM output."""
    # Current _parse_outline logic

def parse_critique(raw: str) -> dict:
    """Parse critique response from LLM."""
    # Current _parse_critique logic

def match_chapter_title(query: str, chapters: dict) -> str | None:
    """Fuzzy match a chapter title query against known chapters."""
    # Current _match_chapter_title logic

def normalize_title(title: str) -> str:
    """Normalize a chapter title for comparison."""
    # Current _normalize_title logic
```

#### `app/generation.py` — Book generation pipeline
```python
"""Book generation pipeline: summary → outline → chapters."""
from app.parsing import extract_content, parse_outline
from app.status import _transition

class BookGenerator:
    """Handles the summary → outline → chapters generation pipeline."""
    def __init__(self, ai_client: AIClient, shared_config):
        ...

    async def generate_summary(self, book_state: BookState) -> str: ...
    async def generate_outline(self, book_state: BookState) -> list[str]: ...
    async def generate_chapters(self, book_state: BookState) -> dict: ...
    async def _generate_chapter(self, book_state, idx, title, total) -> str: ...
    async def _summarize_chapter(self, content, title) -> str: ...
```

#### `app/review.py` — Review pipeline
```python
"""Iterative review pipeline: critique → correct → re-critique."""
from app.parsing import extract_content, parse_critique, match_chapter_title
from app.status import _transition

class BookReviewer:
    """Handles the review-correction loop."""
    def __init__(self, ai_client: AIClient, reviewer_client, shared_config):
        ...

    async def review_book(self, book_state: BookState, max_turns: int | None = None): ...
    async def _chunked_review(self, book_state, max_turns: int | None = None): ...
    def _build_review_text(self, book_state, chapters, turn_num) -> str: ...
    def _build_revision_context(self, book_state, chapter_title) -> tuple: ...
    def _record_review_turn(self, book_state, turn_record) -> None: ...
```

#### `app/orchestrator.py` — Slim coordinator
```python
"""Pipeline coordinator — delegates to specialized components."""
from app.generation import BookGenerator
from app.review import BookReviewer

class Orchestrator:
    """Thin coordinator that wires together generation and review components."""
    def __init__(self, ai_client: AIClient, reviewer_client: ReviewerClient | None = None):
        self._generator = BookGenerator(ai_client, shared_config)
        self._reviewer = BookReviewer(ai_client, reviewer_client, shared_config)

    async def generate_summary(self, book_state):
        return await self._generator.generate_summary(book_state)

    async def generate_outline(self, book_state):
        return await self._generator.generate_outline(book_state)

    async def generate_chapters(self, book_state):
        return await self._generator.generate_chapters(book_state)

    async def review_book(self, book_state, max_turns=None):
        return await self._reviewer.review_book(book_state, max_turns)

    def validate_book(self, book_state):
        # Current validate_book logic (short, self-contained)
```

### 4.2 `app/ai_client.py` — Consolidate retry logic

**Current state:** `generate_completion()` in both `AIClient` and `ReviewerClient` contains identical retry/backoff logic (~30 lines each).

**Action:** Extract retry logic into a reusable helper:

```python
# In app/ai_client.py
async def _retry_request(
    coro_factory,
    max_retries: int,
    retryable_statuses: tuple = (429, 500, 503),
    empty_retry: bool = True,
    status_wait: float = 15.0,
    error_wait: float = 10.0,
    client_name: str = "AIClient",
) -> Any:
    """Execute an async request with retry and exponential backoff + jitter."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            result = await coro_factory()
            # Check for empty response
            if empty_retry and not result and attempt < max_retries:
                wait = error_wait * (attempt + 1) * (0.5 + random.random())
                logger.warning("[%s] Empty response, retrying in %.1fs...", client_name, wait)
                await asyncio.sleep(wait)
                continue
            return result
        except httpx.HTTPStatusError as e:
            last_error = Exception(f"HTTP {e.response.status_code}: {e.response.text}")
            if e.response.status_code in retryable_statuses and attempt < max_retries:
                wait = status_wait * (attempt + 1) * (0.5 + random.random())
                logger.warning("[%s] Status %d, retrying in %.1fs...", client_name, e.response.status_code, wait)
                await asyncio.sleep(wait)
                continue
            raise last_error
        except Exception as e:
            last_error = Exception(str(e))
            if attempt < max_retries:
                wait = error_wait * (attempt + 1) * (0.5 + random.random())
                logger.warning("[%s] Error, retrying in %.1fs...", client_name, wait)
                await asyncio.sleep(wait)
                continue
            raise last_error
    raise last_error or Exception("Max retries exceeded")
```

Both `AIClient.generate_completion()` and `ReviewerClient.generate_completion()` become thin wrappers that construct the request coroutine and delegate to `_retry_request()`.

### 4.3 `app/main.py` — Split concerns

**Current state:** ~400 lines containing:
- Server configuration (`ServerConfig` dataclass, singleton instances)
- Lifespan management (startup/shutdown)
- Middleware (CORS, security headers, no-cache)
- Static file resolution
- Web UI routes
- API endpoints (config, models, books, export, delete)
- CLI entry point

**Proposed split:**

#### `app/middleware.py` — Middleware definitions
```python
"""HTTP middleware for security and caching."""
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    ...

def setup_middleware(app: FastAPI) -> None:
    """Register all middleware on the FastAPI app."""
    app.add_middleware(CORSMiddleware, ...)
    app.add_middleware(SecurityHeadersMiddleware)
```

#### `app/routes.py` — API endpoint definitions
```python
"""API endpoint handlers, organized by resource."""
from fastapi import APIRouter, HTTPException, BackgroundTasks

router = APIRouter(prefix="/api")

# Config endpoints
@router.get("/config")
async def get_ai_config(): ...

@router.post("/config")
async def update_ai_config(config: AIConfigUpdate): ...

@router.get("/config-schema")
async def get_config_schema(): ...

# Model endpoints
@router.get("/models")
async def list_available_models(...): ...

@router.get("/reviewer/models")
async def list_reviewer_models(...): ...

# Book endpoints
@router.post("/books/create")
async def create_book(...): ...

@router.get("/books")
async def list_all_books(): ...

@router.get("/books/{book_id}")
async def get_book_status(book_id: str): ...

@router.get("/books/{book_id}/validate")
async def validate_book(book_id: str): ...

@router.post("/books/{book_id}/review")
async def trigger_review(book_id: str, background_tasks: BackgroundTasks): ...

@router.post("/books/{book_id}/retry")
async def retry_book(book_id: str, background_tasks: BackgroundTasks): ...

@router.get("/books/{book_id}/export/{fmt}")
async def export_book(book_id: str, fmt: str): ...

@router.delete("/books/{book_id}")
async def delete_book_endpoint(book_id: str): ...

# Utility endpoints
@router.get("/health")
async def health_check(): ...
```

#### `app/main.py` — Slim application bootstrap
```python
"""Hullucinator — Application bootstrap and CLI entry point."""
from app.middleware import setup_middleware
from app.routes import router
from app.config import get_default_shared_config

app = FastAPI(title="Hullucinator", ...)
setup_middleware(app)
app.include_router(router)

# Web UI routes (kept in main.py since they're app-level)
@app.get("/", response_class=HTMLResponse)
async def web_index(): ...

# Static file serving (kept in main.py)
app.mount("/static", StaticFiles(...))

# CLI entry point
def main(): ...
```

### 4.4 Frontend JavaScript — Split concerns

**Current state:**
- `static/js/ui.js` — utilities (apiFetch, toast, esc, statusBadge, polling)
- `static/js/app.js` — main application (create form, library, detail modal, review, retry, delete)
- `static/js/settings.js` — settings panel and setup wizard
- `static/js/boot.js` — initialization

**Proposed additions:**

#### `static/js/config.js` — Shared config (Section 2.2)
- `SHARED_CONFIG` singleton
- `loadSharedConfig()` async function
- `renderLengthSelect()`, `renderMaxTurnsSelect()` helpers

#### `static/js/renderers.js` — UI rendering utilities
Extract from `app.js`:
- `buildBookCardHtml()` — book card HTML generation
- `renderDetail()` — detail modal HTML generation
- `buildReviewSection()` — review section HTML generation
- `statusBadge()` — move from `ui.js` to `renderers.js` (it's a rendering function, not a utility)

**Updated `static/js/ui.js`:**
Keep only true utilities: `apiFetch`, `toast`, `esc`, polling functions (`startPolling`, `stopPolling`, `startLibraryPolling`, `stopLibraryPolling`)

**Updated `static/js/app.js`:**
Import from `renderers.js` and `config.js`. Keep only interaction logic (event handlers, form submission, navigation).

**Updated `static/js/settings.js`:**
Import from `config.js`. Keep settings panel and setup wizard interaction logic.

**Updated `static/js/boot.js`:**
```javascript
await loadSharedConfig();
initApp();
initSettings();
```

---

## 5. Implementation Order

Changes should be implemented in this order to minimize risk:

### Phase 1: Foundation (no behavior changes)
1. **Create `app/config.py`** with `SharedConfig` model and `DEFAULT_SHARED_CONFIG`
2. **Create `static/js/config.js`** with `SHARED_CONFIG` singleton and loader
3. **Add `GET /api/config-schema`** endpoint to `app/main.py`
4. **Update `static/js/boot.js`** to load shared config before init
5. **Run full test suite** to verify nothing broke

### Phase 2: Consolidate duplicated code
6. **Import `_extract_content`** from `ai_client` in `orchestrator` (Section 1.1)
7. **Extract `_parse_models_response`** as standalone function (Section 1.2)
8. **Extract `_build_api_url`** helper (Section 1.3)
9. **Extract `_build_review_text`** helper (Section 1.4)
10. **Extract `_build_revision_context`** helper (Section 1.5)
11. **Extract `_record_review_turn`** helper (Section 1.6)
12. **Extract `_update_progress`** helper (Section 1.7)
13. **Run full test suite** after each change

### Phase 3: Migrate to shared config
14. **Migrate `orchestrator.py`** to use `shared_config` for length/review defaults (Section 2.2)
15. **Migrate `ai_client.py`** to use `shared_config.client` for retry/backoff values
16. **Migrate frontend JS** to use `SHARED_CONFIG` for all hardcoded values
17. **Migrate `index.html`** to use dynamic option rendering
18. **Run full test suite**

### Phase 4: Restructure modules
19. **Create `app/status.py`** and migrate transition logic (Section 4.1)
20. **Create `app/parsing.py`** and migrate parsing functions
21. **Create `app/generation.py`** and migrate generation pipeline
22. **Create `app/review.py`** and migrate review pipeline
23. **Slim `app/orchestrator.py`** to coordinator-only
24. **Create `app/middleware.py`** and migrate middleware (Section 4.3)
25. **Create `app/routes.py`** and migrate endpoints
26. **Slim `app/main.py`** to bootstrap only
27. **Extract retry logic** from `ai_client.py` (Section 4.2)
28. **Create `static/js/renderers.js`** and migrate rendering functions (Section 4.4)
29. **Run full test suite**

### Phase 5: Test remediation
30. **Remove identified tests** (Section 3.2)
31. **Add schema validation tests** (Section 3.3)
32. **Add shared config tests** (Section 3.3)
33. **Add retry endpoint test** (Section 3.3)
34. **Fix `conftest.py`** fixture bugs (Section 3.4)
35. **Clean up test imports** (remove `sys.path.insert`)
36. **Run full test suite**

### Phase 6: Documentation
37. **Update `AGENTS.md`** with new module structure and conventions
38. **Update `README.md`** with new architecture
39. **Add module docstrings** to all new files

---

## 6. Risk Assessment

| Change | Risk Level | Mitigation |
|--------|-----------|------------|
| Shared config | Medium | Thorough testing; config endpoint serves as integration test |
| Deduplication | Low | Import swaps preserve behavior; tests verify |
| Module splitting | Medium | Import chain verification; run full test suite after each split |
| Test removal | Low | Removed tests cover Pydantic behavior or regex internals |
| Test addition | Low | New tests are additive; don't break existing passing tests |
| Frontend JS restructuring | Medium | Visual regression testing; CSP compliance tests catch issues |

---

## 7. Expected Outcomes

After completing this plan:

1. **Zero duplicated code** — Every function, constant, and algorithm exists in exactly one place
2. **Single source of truth for config** — Frontend and backend read from the same config object; drift is impossible
3. **Focused test suite** — Tests verify business logic, not framework behavior or implementation details
4. **Clear module boundaries** — Each file has a single, well-defined responsibility
5. **Easier onboarding** — New contributors can understand any module in isolation
6. **Safer refactoring** — Changes to one area don't risk breaking unrelated areas
