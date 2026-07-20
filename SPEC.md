# Hullucinator — Feature Specification

An application that generates complete e-books from a simple user prompt, using one or more LLM providers through OpenAI-compatible APIs.

---

## 1. Book Generation Pipeline

The core feature: transform a user prompt into a complete, reviewed book through a multi-step pipeline.

### Step 1 — Summary

Given a title, user prompt, genre tags, and desired book length, generate a single-paragraph summary capturing the core premise, main conflict, and overall direction.

### Step 2 — Outline

From the summary, generate a chapter-by-chapter outline as a list of descriptive chapter titles. The number of chapters is determined by the selected book length tier. The outline must follow a clear narrative arc from beginning to end.

### Step 3 — Chapter Generation

Generate each chapter sequentially. Each chapter receives cumulative context from all previously generated chapters (via condensed one-paragraph summaries) to maintain continuity, consistent tone, character voices, and narrative pacing.

### Step 4 — Review (Optional)

After all chapters are generated, run an iterative professional review:

- A critic LLM evaluates the book for plot holes, character inconsistencies, pacing problems, continuity errors, tone inconsistencies, and unresolved threads
- Returns a score (0–10), a verdict ("ready" or "needs_revision"), and a list of specific issues with suggested fixes
- For each issue, the writer LLM rewrites the affected chapter to address the problem
- The cycle repeats until the book passes review (score meets threshold and verdict is "ready") or a configurable maximum number of turns is reached
- If max turns is reached without passing, the book is marked as reviewed with a note that some issues may remain

**Skip Review:** Users may opt out of the review step entirely for quick drafts.

### Chunked Review

For long books that exceed a configurable word count threshold, review is performed in batches of chapters (configurable chunk size) to avoid context window overflow. Each chunk is critiqued independently; the overall verdict passes only when all chunks pass.

### Book Length Tiers

| Tier | Chapters | Word Count |
|---|---|---|
| Short Story | 1 | 1,000–7,500 |
| Novella | 3–5 | 7,500–20,000 |
| Novel | 8–15 | 20,000–50,000 |
| Epic | 15–25 | 50,000+ |

### Per-Book Review Settings

Each book carries its own `review_max_turns` setting (overrides the global default), allowing users to choose between quick review (1 turn) and exhaustive review (up to 5 turns).

---

## 2. LLM Provider Configuration

### Writer Provider

The primary LLM endpoint used for summary, outline, chapter generation, and chapter corrections. Configured with:
- Endpoint URL (OpenAI-compatible)
- Model name
- API key (optional — some endpoints don't require one)

### Reviewer Provider (Optional)

A separate LLM endpoint dedicated to critique tasks. Can use a different endpoint, model, and API key from the writer. When not configured, the writer provider is used for review tasks.

### Credential Validation

Before queuing any book for generation, retry, or review, the system validates API credentials by sending a lightweight test request to the provider's models endpoint. This prevents books from being queued when credentials are invalid.

### Model Discovery

Users can fetch available models from any configured endpoint. The setup wizard and settings panel provide "Fetch" buttons that query the provider and display available models for selection.

### Runtime Reconfiguration

All AI settings (endpoint, model, API key, review parameters) can be changed at any time without restarting the server. Changes take effect immediately for all subsequent tasks.

---

## 3. Book Lifecycle

### Status States

Books progress through a defined status graph:

```
pending → summary_generated → outline_generated → in_progress → completed → reviewing → reviewed
```

Any step can transition to `failed` on error. Failed books can be retried (reset to `pending`).

### Auto-Resume on Restart

Books interrupted by server shutdown automatically resume on restart. The system scans all stored books for non-terminal statuses and continues the pipeline from wherever it left off, preserving all already-generated content.

### Manual Resume

Users can manually trigger resume for any book in a non-terminal status. Resume skips already-completed steps and continues from the current point.

### Retry

Failed, completed, or reviewed books can be retried. Retry creates a new book with the same parameters (title, prompt, tags, length, review settings) and deletes the old book.

### Delete

Books can be deleted at any time, cancelling any active generation task.

### Concurrency Limit

A configurable maximum number of simultaneous book generations prevents resource exhaustion. Books beyond the limit are queued and processed as slots become available.

---

## 4. Export

Books in `completed` or `reviewed` status can be exported in two formats:

### EPUB

- Styled with serif body text, justified paragraphs, drop caps on first paragraph of each chapter, and automatic hyphenation
- Cover page with title, genre tags, and review score/verdict
- Table of contents linking all chapters
- Markdown-to-HTML conversion for chapter content

### PDF

- Decorative title page with borders, tags, and review information
- Each chapter on its own page with styled heading and underline
- Body text with clean formatting (markdown stripped)
- Uses bundled fonts (no system font dependencies)

Exported files are stored persistently and served for download.

---

## 5. Web Interface

### Setup Wizard

First-time users see a guided setup overlay before accessing the main application:
1. **Connection** — Endpoint URL and API key
2. **Writer Model** — Model name input with fetch button for provider model listing
3. **Reviewer Model** (Optional) — Separate endpoint, API key, and model for review tasks
4. **Review Settings** — Max review turns, chunked review word threshold, chunk size

Credentials are validated before saving. On success, the wizard dismisses and the main interface appears.

### Create Book Form

- **Title** — Required, up to 200 characters
- **Prompt / Concept** — Required, free-form text with live character counter and warning at configurable threshold
- **Tags** — Genre/theme labels entered via keyboard (Enter to add), displayed as removable badges
- **Book Length** — Dropdown of length tiers with chapter and word count descriptions
- **Max Review Turns** — Dropdown of preset options (1–5 turns with descriptive labels)
- **Skip Review** — Option to bypass the review step

### Library

Displays all books as cards showing:
- Title, status badge (color-coded), length tier, genre tags
- Prompt preview (truncated)
- Progress bar with percentage (color: teal during generation, green on completion, red on failure)
- Current step description (e.g., "Writing Chapter 3…")
- Delete button

Library auto-refreshes when active books are generating; stops polling when all books reach terminal status.

### Book Detail Modal

Clicking a book card opens a modal with:
- **Settings** — Original creation parameters (prompt, length, tags, review turns)
- **Status** — Current status badge
- **Progress** — Progress bar, percentage, chapter count, error message (if failed)
- **Summary** — Generated book summary (rendered as formatted text)
- **Outline** — Numbered chapter list
- **Chapters** — Collapsible sections, each showing full chapter content (rendered as formatted text)
- **Review Results** (if reviewed) — Score display (color-coded: green/amber/red), verdict (Approved/Needs Revision), max-turns-reached warning, and expandable turn-by-turn history showing critique text, issues found, and corrections applied

**Action Buttons:**
- Download EPUB / Download PDF (available for completed or reviewed books)
- Trigger Review (available for completed books)
- Retry (available for failed, completed, or reviewed books)
- Delete

Progress polling updates the modal in real-time for active books.

### Settings Panel

Slide-out panel (accessible via header button) for already-configured users:
- Connection settings (endpoint, API key)
- Writer model with fetch button
- Reviewer model (optional) with fetch button
- Review settings (max turns, word threshold, chunk size)
- Validates credentials before saving
- Changes apply immediately to all subsequent tasks

### Design

- Warm, tactile, bookish aesthetic with a paper-and-ink color palette
- Three-font system: serif for headings, sans-serif for body text, monospace for data labels
- All fonts self-hosted (no external dependencies)
- Responsive layout for mobile
- Accessibility: reduced-motion support, keyboard focus indicators

### Security

- Strict Content Security Policy: no external resources (CDNs, scripts, fonts)
- Security headers: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy
- API keys never persisted to disk — stored in memory only
- Static assets served with no-cache headers

---

## 6. Configuration System

All tunable parameters are defined in a single shared configuration that both backend and frontend consume, preventing drift.

### Generation Parameters

- Temperature per step (summary, outline, chapter, chapter summary, critique, revision)
- System prompt templates per step (configurable with placeholder substitution)
- Minimum chapter content length (characters) before accepting generated content

### Review Parameters

- Default max review turns (range: 1–10)
- Pass score threshold (score at or above which review passes)
- Fail score threshold (score below which review fails)
- Chunked review word threshold (books exceeding this use chunked review)
- Chunk size (chapters per review batch)

### Client Parameters

- Max retry attempts per request
- Retry wait times (separate for HTTP status errors and general errors)
- Jitter factor for randomized backoff
- HTTP request timeout

### UI Parameters

- Detail modal polling interval
- Library auto-refresh interval
- Prompt input warning threshold
- Maximum title length

---

## 7. Error Handling

### Generation Failures

- Retry logic with jittered exponential backoff for transient errors (429, 500, 503)
- Empty responses trigger retries
- On final failure, book status transitions to `failed` with error details stored in metadata
- Full traceback captured for debugging

### Parsing Robustness

Outline parsing handles multiple LLM output formats: JSON arrays/objects, numbered lists, markdown headings, bullet lists, and plain prose. Falls back to sensible defaults when parsing fails.

Critique parsing extracts structured data from both JSON and free-text responses.

Chapter title matching uses progressive fuzzy matching (exact → normalized → substring → token similarity) to handle discrepancies between critique issue references and actual chapter titles.

### JSON Unwrapping

When the LLM returns JSON despite being asked for plain text, the system attempts to unwrap the content by checking common wrapper keys.

---

## 8. Data Persistence

### Storage

All data stored in a user's home directory, ensuring persistence regardless of where the application is installed or how it's run.

### Book Storage

Each book stored as a self-contained record containing: identity (ID, title), creation parameters (prompt, tags, length), generated content (summary, outline, chapters, chapter summaries), review results (per-turn history), and progress tracking data.

### Configuration Storage

Persisted settings include endpoint URLs, model names, and review parameters. API keys are never persisted — they must be provided via environment variables or entered at runtime.

---

## 9. Operational Requirements

### Startup

1. Load persisted configuration
2. Initialize LLM client(s) with persisted settings and environment-provided API keys
3. Auto-resume any books interrupted by previous shutdown
4. Bind to configurable host and port

### Shutdown

Graceful cleanup of HTTP connections.

### Concurrency

Configurable limit on simultaneous book generations. Excess books queue and process as slots free up.

### Logging

Structured logging with configurable verbosity. Errors logged with full tracebacks.

---

## 10. Testing

- Full test suite covering all modules: AI client, API endpoints, concurrency, configuration, export, frontend, orchestrator, parsing, schemas, and storage
- Tests use isolated temporary directories — never touch real production data
- Async tests supported with automatic event loop handling
