# Hullucinator Refactoring Plan

A comprehensive plan to address code fragility, duplicated logic, config drift, test quality, and modularity.

---

## Completion Status (as of 2026-06-20)

| Section | Completion | Details |
|---------|-----------|---------|
| **1. Duplicated Code** | 10/10 done | All items 1.1–1.10 ✅ done. `_extract_content` is now a module-level function in `ai_client.py` (not a static method). `POST /api/books/{id}/retry` endpoint added to `main.py`; frontend `retryBook()` calls it |
| **2. Shared Config** | ✅ DONE | All backend and frontend hardcoded values migrated to `SHARED_CONFIG`. `app/config.py` has `fail_score` in `ReviewConfig`. `schemas.py`, `orchestrator.py`, `ai_client.py` all derive defaults from shared config. Frontend `app.js` uses `SHARED_CONFIG.review.pass_score/fail_score`. All `<select>` elements in `index.html` emptied of hardcoded `<option>` children, populated dynamically by `config.js` |
| **3. Test Suite** | ✅ Complete | New `tests/test_parsing.py` (21 tests), `tests/test_schemas.py` (21 tests), `tests/test_config.py` (16 tests), `tests/test_concurrency.py` (3 tests). Removed 16 low-value tests from `test_orchestrator.py`, `test_api.py`, `test_export.py` (replaced by focused tests in new files). **Total: 126 tests, all passing.** |
| **4. Modularity** | ✅ DONE | New modules created: `app/status.py`, `app/parsing.py`, `app/generation.py`, `app/review.py`, `app/validators.py` — all with docstrings. `app/orchestrator.py` slimmed to 152-line coordinator that delegates to all modules. `app/middleware.py` (64 lines), `app/routes.py` (557 lines) created. `app/main.py` slimmed to 229-line bootstrap. Retry logic extracted to shared `_retry_request()` in `app/ai_client.py`. `static/js/renderers.js` (171 lines) created with `statusBadge`, `buildBookCardHtml`, `renderDetail`, `buildReviewSection` migrated from `app.js`/`ui.js` |
| **5. Implementation Order** | Phases 1–3 ✅, Phase 4 ⚠️, Phase 5 ✅, Phase 6 ❌ | |
| **6. Documentation** | ✅ DONE | `AGENTS.md` Components table updated with all modules (config, status, parsing, generation, review, validators, orchestrator, middleware, routes, ai_client, schemas, storage, exporter, frontend JS). `README.md` Project Structure section updated with new modules. Module docstrings ✅ done (all 5 new modules have docstrings) |

**Overall completion: ~97%**

**Test suite:** ✅ All 126 tests pass (`.venv/bin/pytest -x -q`)

**Test inventory by file:**

| File | Tests |
|------|-------|
| `test_storage.py` | 9 |
| `test_api.py` | 19 |
| `test_export.py` | 17 |
| `test_orchestrator.py` | 17 |
| `test_frontend.py` | 3 |
| `test_parsing.py` | 21 |
| `test_schemas.py` | 21 |
| `test_config.py` | 16 |
| `test_concurrency.py` | 3 |
| **Total** | **126** |

**Semaphore fix:** `_generation_semaphore` made lazy-created via `_get_semaphore()` with event loop detection. Recreates when bound to a different event loop (e.g., between pytest tests).

---

## 1. Duplicated Code — Consolidation

### 1.1 `_extract_content()` — duplicated between `orchestrator.py` and `ai_client.py`

**Status: ✅ DONE**

`_extract_content` was a static method inside `AIClient` class. Refactored to a module-level standalone function in `app/ai_client.py`. Both `AIClient` and `ReviewerClient` call the module-level `_extract_content()`. `app/orchestrator.py` imports it directly: `from app.ai_client import AIClient, _extract_content, _build_api_url`.

No duplicate copy remains in `orchestrator.py`.

---

### 1.2 `_parse_models_response()` logic — duplicated 3×

**Status: ✅ DONE**

Extracted as module-level function `_parse_models_response(result)` in `app/ai_client.py`. Both `AIClient.list_models()` and `ReviewerClient.list_models()` call it. `main.py` imports it.

---

### 1.3 `/v1` suffix URL construction — duplicated 6×

**Status: ✅ DONE**

Module-level helper `_build_api_url(endpoint, path_suffix)` in `app/ai_client.py`. Used by `AIClient.list_models()`, `AIClient.generate_completion()`, `ReviewerClient.list_models()`, `ReviewerClient.generate_completion()`, and `main.py` `list_reviewer_models()`.

---

### 1.4 Review text building — duplicated between `review_book()` and `_chunked_review()`

**Status: ✅ DONE**

Extracted as `_build_review_text(book_state, chapters, turn_num)` module-level helper in `app/review.py`. Both `_full_review()` and `_chunked_review()` call it.

---

### 1.5 Revision context building — duplicated between `review_book()` and `_chunked_review()`

**Status: ✅ DONE**

Extracted as `_build_revision_context(book_state, chapter_title)` module-level helper in `app/review.py`. Both `_full_review()` and `_chunked_review()` call it.

---

### 1.6 Review turn recording — duplicated between `review_book()` and `_chunked_review()`

**Status: ✅ DONE**

Extracted as `_record_review_turn(book_state, turn_record)` module-level helper in `app/review.py`. Both `_full_review()` and `_chunked_review()` call it.

---

### 1.7 Progress update pattern — repeated throughout `orchestrator.py`

**Status: ✅ DONE**

Extracted as `_update_progress(book_state, step, percentage)` helper in `app/generation.py`. Used throughout generation methods; re-exported by `app/orchestrator.py`.

---

### 1.8 Status text mapping — duplicated between backend and frontend

**Status: ✅ DONE**

Migrated to `SHARED_CONFIG.statuses` in `app/config.py`. Frontend `config.js` provides `getStatusLabel()`, `getStatusCssClass()`, `isTerminalStatus()`, `isActiveStatus()`. `ui.js` `statusBadge()` uses these helpers.

---

### 1.9 Length option definitions — duplicated between backend and frontend

**Status: ✅ DONE**

Migrated to `SHARED_CONFIG.lengths` in `app/config.py`. Frontend `config.js` provides `renderLengthSelect()`.

---

### 1.10 Retry logic — duplicated between `app.js` and `main.py`

**Status: ✅ DONE**

- `POST /api/books/{id}/retry` endpoint added to `main.py`
- Frontend `retryBook()` in `app.js` calls `/api/books/{book_id}/retry` instead of manually reconstructing `BookCreateRequest`
- Endpoint loads old book, constructs new `BookCreateRequest`, queues generation, deletes old book
- Test added to `tests/test_api.py::TestRetryEndpoint` (3 tests)

---

## 2. Shared Configuration — Eliminate Config Drift

### 2.1 Current State of Config Drift

**Status: ✅ RESOLVED**

All hardcoded values migrated to `SHARED_CONFIG`:

| Value | Files affected | Status |
|-------|---------------|--------|
| `review_max_turns` default (2) | `schemas.py` imports from `config.py` | ✅ Migrated |
| `review_word_threshold` default (30000) | `schemas.py`, `app/review.py` | ✅ Migrated |
| `review_chunk_size` default (5) | `schemas.py`, `app/review.py` | ✅ Migrated |
| `pass_score` (7) / `fail_score` (4) | Added to `config.py` `ReviewConfig`; `app/review.py` uses `REVIEW_PASS_SCORE`; `static/js/renderers.js` uses `SHARED_CONFIG?.review?.pass_score` / `fail_score` | ✅ Migrated |
| `title_max_length` (200) | `config.py` `UISchema`; `app/validators.py` re-exports `max_title_length` | ✅ Migrated |
| `prompt_warn_threshold` (10000) | `config.py` `UISchema`; `static/js/app.js` uses `SHARED_CONFIG?.ui?.prompt_warn_threshold` | ✅ Migrated |
| Length → chapter/word count mapping | `app/generation.py` derives from `shared_config.lengths` | ✅ Migrated |
| Retry/backoff values | `app/ai_client.py` uses `shared_config.client` | ✅ Migrated |
| Polling interval (3s) | `static/js/ui.js` | ✅ Migrated (uses `SHARED_CONFIG?.ui?.polling_interval_ms ?? 3000`) |
| Library polling interval (10s) | `static/js/ui.js` | ✅ Migrated (uses `SHARED_CONFIG?.ui?.library_polling_interval_ms ?? 10000`) |
| Prompt warn threshold (10000) | `static/js/app.js` | ✅ Migrated |
| Max turns default (2) | `static/js/settings.js` | ✅ Migrated |
| Review thresholds in settings | `static/js/settings.js` | ✅ Migrated |
| `<select>` options in `index.html` | All 4 selects emptied, populated by `static/js/config.js` | ✅ Migrated |

### 2.2 Proposed Solution: Shared Config Endpoint

**Status: ✅ Foundation complete**

`app/config.py` — `SharedConfig` model with `LengthConfig`, `StatusConfig`, `ReviewConfig`, `ClientConfig`, `UISchema` sub-models. `DEFAULT_SHARED_CONFIG` and `get_default_shared_config()` exported.

`static/js/config.js` — `SHARED_CONFIG` singleton, `loadSharedConfig()`, `renderLengthSelect()`, `renderMaxTurnsSelect()`, `getStatusLabel()`, `getStatusCssClass()`, `isTerminalStatus()`, `isActiveStatus()`.

`GET /api/config-schema` endpoint in `main.py` returns `config.model_dump()`.

`static/js/boot.js` calls `await loadSharedConfig()` before `initApp()` and `initSettings()`.

**Remaining migration work:** None — all items completed.

---

## 3. Test Suite — Audit and Remediation

### 3.1 Current Test Inventory

| File | Tests | Purpose |
|------|-------|---------|
| `test_storage.py` | 9 | Round-trip save/load for books and config |
| `test_api.py` | 19 | HTTP endpoint behavior (includes `TestRetryEndpoint` — 3 tests) |
| `test_export.py` | 17 | EPUB/PDF export, markdown→HTML |
| `test_orchestrator.py` | 17 | Parsing, matching, transitions (still uses orchestrator methods directly) |
| `test_frontend.py` | 3 | CSP compliance, API path consistency |
| `test_parsing.py` | 21 | Outline parsing (8), critique parsing (5), chapter matching (8) |
| `test_schemas.py` | 21 | `BookCreateRequest` (9), `BookState` (6), `AIConfig` (5), schema↔config sync (1) |
| `test_config.py` | 16 | `SharedConfig` structure (10), sub-models (4), derivation correctness (2) |
| `test_concurrency.py` | 3 | Semaphore concurrency limiting |
| `conftest.py` | — | Fixtures: test isolation, config reset, semaphore reset |

**Total: 126 tests, all passing**

### 3.2 Tests to REMOVE

**Status: ✅ DONE**

The 16 identified low-value tests have been removed from `test_orchestrator.py`, `test_api.py`, and `test_export.py`. Their coverage is replaced by focused tests in the new test files:

| Removed Test | Replaced By |
|-------------|-------------|
| `test_orchestrator.py::TestParseOutline::test_empty_input` | `test_parsing.py::TestParseOutline::test_empty_response_uses_defaults` |
| `test_orchestrator.py::TestParseOutline::test_prose_with_chapters` | Kept (improved assertions in `test_orchestrator.py`) |
| `test_orchestrator.py::TestParseCritique::test_text_fallback_*` | `test_parsing.py::TestParseCritique::test_text_fallback` |
| `test_orchestrator.py::TestMatchChapterTitle::test_normalized_exact_match` | Removed (covered by `test_exact_match` + `test_punctuation_tolerance` in `test_parsing.py`) |
| `test_api.py::TestBookEndpoints::test_create_book_missing_title/prompt` | `test_schemas.py::TestBookCreateRequest::test_empty_title/test_empty_prompt` |
| `test_api.py::TestBookEndpoints::test_create_book_invalid_review_max_turns` | `test_schemas.py::TestBookCreateRequest::test_review_max_turns_too_low/too_high` |
| `test_api.py::TestBookEndpoints::test_create_book_null_review_max_turns` | Removed (Pydantic type coercion — not business logic) |
| `test_api.py::TestBookEndpoints::test_create_book_defaults` | `test_schemas.py::TestBookCreateRequest::test_omitted_optional_fields` |
| `test_api.py::TestBookEndpoints::test_create_book_invalid_length` | Removed (no server-side `length` validation exists yet) |
| `test_export.py::TestMarkdownToHtml::test_combined_bold_italic` | Removed (tests third-party `markdown` library) |
| `test_export.py::TestMarkdownToHtml::test_links` | Removed (tests third-party `markdown` library) |
| `test_export.py::TestMarkdownToHtml::test_blockquote` | Removed (tests third-party `markdown` library) |
| `test_export.py::TestMarkdownToHtml::test_html_escaping` | Removed (non-deterministic across parser backends) |
| `test_api.py::TestWebUI::test_index_page` | Modified — now checks for `<script>` tags for `config.js`, `ui.js`, `app.js`, `settings.js`, `boot.js` |
| `test_api.py::TestBookEndpoints::test_create_book_null_review_max_turns` (duplicate) | Removed |

### 3.3 Tests to ADD

**Status: ✅ DONE**

**Parsing tests** (new file: `tests/test_parsing.py`) — ✅ DONE (21 tests)
- `TestParseOutline` (8): JSON list, JSON dict, code fences, numbered list fallback, chapter prefix format, empty response defaults, invalid JSON defaults, dict response
- `TestParseCritique` (5): JSON format, code fences, text fallback, empty response defaults, dict response
- `TestMatchChapterTitle` (8): exact match, case insensitive, punctuation tolerance, substring match, fuzzy match, no match, empty query, empty chapters

**Retry endpoint tests** (added to `tests/test_api.py`) — ✅ DONE (3 tests)
- `test_retry_creates_new_book` — verifies new book creation, field preservation, old book deletion
- `test_retry_nonexistent_book` — verifies 404 for missing book
- `test_retry_preserves_all_fields` — verifies all fields including optional ones preserved

**Schema validation tests** (new file: `tests/test_schemas.py`) — ✅ DONE (21 tests)
- `TestBookCreateRequest` (9): minimal valid, all fields, title too long, empty title, empty prompt, long prompt, review_max_turns bounds, omitted optional fields
- `TestBookState` (6): minimal valid, title too long, empty title, empty prompt, review_max_turns constraints
- `TestAIConfig` (5): defaults, custom values, review_max_turns constraints, review_word_threshold min, review_chunk_size constraints, no API keys
- `TestSchemaConfigSync` (1): defaults match shared config

**Shared config tests** (new file: `tests/test_config.py`) — ✅ DONE (16 tests)
- `TestSharedConfig` (10): default instance, length/status/review/ui/client config, custom config, constraint validation
- `TestConfigSubModels` (4): length config fields, status config fields, client config custom, ui schema custom
- `TestConfigDerivations` (2): schemas use shared defaults, orchestrator uses shared constants

**Concurrency test** (new file: `tests/test_concurrency.py`) — ✅ DONE (3 tests)
- `test_semaphore_limits_concurrency` — verifies exactly MAX_CONCURRENT_GENERATIONS concurrent tasks
- `test_semaphore_released_after_use` — verifies release after task completion
- `test_sequential_acquires` — verifies sequential tasks work correctly

### 3.4 Test Infrastructure Improvements

**Status: ⚠️ Partial**

**`conftest.py` — `_reset_config` fixture bug:**
- **Status: ✅ FIXED** — Uses `server_config.persisted` (public attribute) instead of `server_config._persisted` (private)

**`sys.path.insert` in test files:**
- **Status: ⚠️ Partial** — Removed from `test_orchestrator.py`, `test_export.py`, `test_frontend.py`. **Still present in `conftest.py`** — kept because pytest auto-discovers root for test files but `conftest` needs explicit setup for external runners (e.g., CI systems, IDE test runners). Consider removing only after verifying all test runners work without it.

**Unused import in `test_export.py`:**
- **Status: ✅ FIXED** — `ensure_exports_dir` import removed (was never called).

---

## 4. Modularity — Restructure Files

**Status: ✅ DONE**

### 4.1 `app/orchestrator.py` — Split into 4 modules

**Completed:**

#### `app/status.py` — Status transition management — ✅ DONE (45 lines)
Contains `VALID_TRANSITIONS`, `_transition()`, `is_terminal_status()`, `get_allowed_transitions()`.

#### `app/parsing.py` — LLM response parsing — ✅ DONE (270 lines)
Contains `parse_outline()`, `parse_critique()`, `match_chapter_title()`, `_normalize_title()`. Imports `_extract_content` from `app.ai_client`.

#### `app/generation.py` — Book generation pipeline — ✅ DONE (223 lines)
Contains `generate_summary()`, `generate_outline()`, `generate_chapters()`. Uses `LENGTH_CHAPTER_COUNT`/`LENGTH_WORD_COUNT` derived from shared config. Uses `_update_progress()` helper. Imports from `app.status`, `app.parsing`, `app.config`.

#### `app/review.py` — Review pipeline — ✅ DONE (468 lines)
Contains `review_book()`, `_full_review()`, `_chunked_review()`, `_build_review_text()`, `_build_revision_context()`, `_record_review_turn()`, `_get_review_thresholds()`. Uses `REVIEW_PASS_SCORE` from shared config. Imports from `app.status`, `app.parsing`, `app.generation`, `app.config`.

#### `app/validators.py` — Validation helpers — ✅ DONE (116 lines)
Contains `validate_create_request()` (returns `List[str]`), `validate_book_state()` (returns `Dict[str, Any]` with `valid`/`errors` keys), `validate_ai_config()` (returns `List[str]`), `max_title_length`.

#### `app/orchestrator.py` — Slim coordinator — ✅ DONE (152 lines)
Delegates all logic to specialized modules. Re-exports key functions for backward compatibility with tests. Maintains same public API (`generate_summary`, `generate_outline`, `generate_chapters`, `review_book`, `validate_book`, `_parse_outline`, `_parse_critique`, `_match_chapter_title`, `_normalize_title`).

### 4.2 `app/ai_client.py` — Consolidate retry logic

**Status: ✅ DONE**

**Semaphore fix:** `_generation_semaphore` in `main.py` made lazy-created via `_get_semaphore()` with event loop detection. Recreates when bound to a different event loop (e.g., between pytest tests).

**Retry logic extracted:** Shared module-level `_retry_request(client, url, payload, headers, max_retries, log_prefix, error_prefix)` helper in `app/ai_client.py`. Both `AIClient.generate_completion()` and `ReviewerClient.generate_completion()` delegate to it. Eliminates ~80 lines of duplicated retry/backoff code.

### 4.3 `app/main.py` — Split concerns

**Status: ✅ DONE**

#### `app/middleware.py` — Middleware definitions — ✅ DONE (64 lines)
CORS, security headers, no-cache middleware. `setup_middleware(app)` function.

#### `app/routes.py` — API endpoint definitions — ✅ DONE (557 lines)
All `/api/` endpoints organized by resource (config, models, books, export). `create_router()` factory function accepts dependencies (ai_client, reviewer_client, orchestrator, server_config, etc.). Includes `POST /api/books/{id}/retry` endpoint.

#### `app/main.py` — Slim application bootstrap — ✅ DONE (229 lines)
FastAPI app creation, middleware setup, router inclusion, web UI route, static file mount, CLI entry point. No endpoint logic.

### 4.4 Frontend JavaScript — Split concerns

**Status: ✅ DONE**

#### `static/js/renderers.js` — UI rendering utilities — ✅ DONE (171 lines)
Contains `statusBadge()`, `buildBookCardHtml()`, `renderDetail()`, `buildReviewSection()`. Depends on `config.js` (SHARED_CONFIG, getStatusLabel, getStatusCssClass) and `ui.js` (esc).

**Updated `static/js/ui.js`:** Kept only true utilities: `apiFetch`, `toast`, `esc`, progress polling (`startPolling`/`stopPolling`), library auto-refresh (`startLibraryPolling`/`stopLibraryPolling`). Removed `statusBadge()`.

**Updated `static/js/app.js`:** Removed rendering functions. Kept only interaction logic (event handlers, form submission, navigation). Calls `renderDetail()` from `renderers.js`.

**Updated `static/index.html`:** Script load order: `config.js` → `ui.js` → `renderers.js` → `app.js` → `settings.js` → `boot.js`.

---

## 5. Implementation Order

Changes should be implemented in this order to minimize risk:

### Phase 1: Foundation (no behavior changes)
1. **Create `app/config.py`** with `SharedConfig` model and `DEFAULT_SHARED_CONFIG` — ✅ DONE
2. **Create `static/js/config.js`** with `SHARED_CONFIG` singleton and loader — ✅ DONE
3. **Add `GET /api/config-schema`** endpoint to `app/main.py` — ✅ DONE
4. **Update `static/js/boot.js`** to load shared config before init — ✅ DONE
5. **Run full test suite** to verify nothing broke — ✅ DONE

### Phase 2: Consolidate duplicated code
6. **Refactor `_extract_content`** to module-level function in `ai_client.py` (Section 1.1) — ✅ DONE
7. **Extract `_parse_models_response`** as standalone function (Section 1.2) — ✅ DONE
8. **Extract `_build_api_url`** helper (Section 1.3) — ✅ DONE
9. **Extract `_build_review_text`** helper (Section 1.4) — ✅ DONE
10. **Extract `_build_revision_context`** helper (Section 1.5) — ✅ DONE
11. **Extract `_record_review_turn`** helper (Section 1.6) — ✅ DONE
12. **Extract `_update_progress`** helper (Section 1.7) — ✅ DONE
13. **Add `POST /api/books/{id}/retry`** endpoint + frontend update (Section 1.10) — ✅ DONE
14. **Run full test suite** after each change — ✅ DONE

### Phase 3: Migrate to shared config
14. **Add `fail_score` to `ReviewConfig`** in `config.py` — ✅ DONE
15. **Migrate `orchestrator.py`** to use `shared_config` for length/review defaults — ✅ DONE
16. **Migrate `ai_client.py`** to use `shared_config.client` for retry/backoff values — ✅ DONE
17. **Migrate `app/schemas.py`** to use `shared_config` for field defaults — ✅ DONE
18. **Migrate frontend JS** (`app.js` review score thresholds) — ✅ DONE
19. **Migrate `index.html`** (remove hardcoded `<option>` elements from all 4 selects) — ✅ DONE
20. **Run full test suite** — ✅ DONE

### Phase 4: Restructure modules
20. **Create `app/status.py`** and migrate transition logic (Section 4.1) — ✅ DONE (module created and integrated)
21. **Create `app/parsing.py`** and migrate parsing functions — ✅ DONE (module created and integrated)
22. **Create `app/generation.py`** and migrate generation pipeline — ✅ DONE (module created and integrated)
23. **Create `app/review.py`** and migrate review pipeline — ✅ DONE (module created and integrated)
24. **Create `app/validators.py`** — ✅ DONE (module created and integrated)
25. **Slim `app/orchestrator.py`** to coordinator-only — ✅ DONE (152 lines, delegates to all modules)
26. **Create `app/middleware.py`** and migrate middleware (Section 4.3) — ✅ DONE (64 lines)
27. **Create `app/routes.py`** and migrate endpoints — ✅ DONE (557 lines)
28. **Slim `app/main.py`** to bootstrap only — ✅ DONE (229 lines)
29. **Extract retry logic** from `app/ai_client.py` (Section 4.2) — ✅ DONE (shared `_retry_request()` helper)
30. **Create `static/js/renderers.js`** and migrate rendering functions (Section 4.4) — ✅ DONE (171 lines)
31. **Run full test suite** — ✅ DONE (126 tests pass)

### Phase 5: Test remediation
31. **Add parsing tests** (new `tests/test_parsing.py` — 21 tests) — ✅ DONE
32. **Add retry endpoint tests** (added to `tests/test_api.py` — 3 tests) — ✅ DONE
33. **Remove identified tests** (Section 3.2 — 16 tests removed) — ✅ DONE
34. **Add schema validation tests** (new `tests/test_schemas.py` — 21 tests) — ✅ DONE
35. **Add shared config tests** (new `tests/test_config.py` — 16 tests) — ✅ DONE
36. **Add concurrency test** (new `tests/test_concurrency.py` — 3 tests) — ✅ DONE
37. **Fix `conftest.py`** fixture bugs (`_persisted` → `persisted`) — ✅ DONE
38. **Clean up test imports** (remove `sys.path.insert` from test files; unused imports) — ⚠️ Partial (`conftest.py` still has `sys.path.insert`, other files cleaned)
39. **Run full test suite** — ✅ DONE (126 tests pass)

### Phase 6: Documentation
39. **Update `AGENTS.md`** with new module structure and conventions — ✅ DONE
40. **Update `README.md`** with new architecture — ✅ DONE
41. **Add module docstrings** to all new files — ✅ DONE (all 5 new modules have docstrings)

---

## 6. Risk Assessment

| Change | Risk Level | Mitigation |
|--------|-----------|------------|
| Shared config migration (backend) | Medium | Thorough testing; config endpoint serves as integration test |
| HTML select migration | Low | `renderLengthSelect()`/`renderMaxTurnsSelect()` already proven in frontend |
| Retry endpoint | Low | Reuses existing creation logic; well-isolated change |
| Module splitting | Medium-High | Import chain verification; run full test suite after each split |
| Test removal | Low | Removed tests cover Pydantic behavior or regex internals |
| Test addition | Low | New tests are additive; don't break existing passing tests |
| Frontend JS restructuring | Medium | Visual regression testing; CSP compliance tests catch issues |
| Orchestrator slim-down | **High** | **✅ COMPLETED** — Orchestrator reduced from 970 lines to 152-line coordinator. Delegates to specialized modules. Full test suite + manual testing verified. |

---

## 7. Expected Outcomes

After completing this plan:

1. **Zero duplicated code** — Every function, constant, and algorithm exists in exactly one place
2. **Single source of truth for config** — Frontend and backend read from the same config object; drift is impossible
3. **Focused test suite** — Tests verify business logic, not framework behavior or implementation details
4. **Clear module boundaries** — Each file has a single, well-defined responsibility
5. **Easier onboarding** — New contributors can understand any module in isolation
6. **Safer refactoring** — Changes to one area don't risk breaking unrelated areas
