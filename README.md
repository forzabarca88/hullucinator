# Hullucinator — AI-Powered E-Book Generator

A FastAPI service with a polished web interface that generates complete e-books from a simple prompt. Provide a title, a topic, genre tags, and desired book length — the system orchestrates an LLM to produce a summary, chapter outline, full chapter content with narrative continuity, professional review with corrections, and exports to EPUB or PDF.

## Features

- **Smart book generation** — LLM produces summary, chapter outline, and full chapters
- **Chapter continuity** — Each chapter receives context from all prior chapters for cohesive writing
- **Professional review** — Iterative critique → correct → re-critique loop catches plot holes, inconsistencies, and pacing issues
- **Separate reviewer** — Optional different LLM endpoint/model for unbiased review
- **Configurable max review turns** — Control review depth per-book or globally (default: 2 turns)
- **Auto-correction** — Identified issues are corrected with full per-turn audit trail
- **Configurable AI provider** — Change endpoint URL, API key, model, and reviewer settings from the GUI at runtime
- **Config persistence** — AI settings saved to disk and restored on restart (API keys excluded for security)
- **Model discovery** — Fetch available models from your LLM provider
- **Rich exports** — EPUB with CSS styling, TOC, drop caps, and review metadata; PDF with configurable fonts
- **Live progress tracking** — Real-time progress bar with chapter-by-chapter updates

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure AI provider (copy and edit)
cp .env.example .env

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Or use the CLI entry point
hullucinator
```

Open http://localhost:8000 in your browser to use the web interface.

## Web Interface

The built-in web interface provides:

- **Create books** — Enter a title, prompt, genre tags, and book length, then click "Generate Book"
- **Genre tags** — Comma-separated tags (e.g. "comedy, time travel") guide the story's tone and style
- **Book length** — Choose Short Story, Novella, Novel, or Epic / Saga to control chapter count and word count
- **Live progress** — Real-time progress bar showing generation status (including review phase)
- **Book library** — Browse all your generated books with status indicators, tags, and length badges
- **Book details** — View summary, outline, chapter content, and review audit trail
- **Professional review** — See critique score, verdict, and corrections applied
- **Downloads** — Export completed books as EPUB (with genre metadata and review info) or PDF
- **Delete books** — Remove books from the library via hover button on cards or delete button in detail modal (with confirmation)
- **Retry failed books** — Restart generation for failed books; the old failed entry is automatically removed
- **Auto-polling** — Progress updates automatically without page refresh
- **Settings panel** — Configure AI endpoint URL, API key, model, reviewer endpoint, reviewer model, and max review turns from the GUI (top-right ⚙️ button)

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web interface (HTML) |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/config` | Get current AI configuration (writer + reviewer settings) |
| `POST` | `/api/config` | Update AI configuration at runtime (writer endpoint/model/key, reviewer endpoint/model/key, max review turns, review thresholds). Persisted to `~/.hullucinator_data/data/config.json` (no API keys). |
| `GET` | `/api/models` | List available models from writer's LLM provider |
| `GET` | `/api/reviewer/models` | List available models from reviewer's LLM provider |
| `POST` | `/api/books/create` | Create a new book (background generation) |
| `GET` | `/api/books` | List all books |
| `GET` | `/api/books/{book_id}` | Get book status and content |
| `GET` | `/api/books/{book_id}/validate` | Validate book completeness |
| `POST` | `/api/books/{book_id}/review` | Trigger professional review |
| `DELETE` | `/api/books/{book_id}` | Delete a book (cancels active task if generating) |
| `GET` | `/api/books/{book_id}/export/{format}` | Download as `epub` or `pdf` |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_ENDPOINT_URL` | `http://192.168.0.40:1234` | Writer LLM API endpoint |
| `AI_MODEL_NAME` | `qwen3.6-27b` | Writer model name |
| `AI_API_KEY` | *(empty)* | API key (Bearer auth) |
| `REVIEWER_ENDPOINT_URL` | *(empty)* | Reviewer LLM endpoint (empty = use writer's) |
| `REVIEWER_MODEL_NAME` | *(empty)* | Reviewer model (empty = use writer's) |
| `REVIEWER_API_KEY` | *(empty)* | Reviewer API key (empty = use writer's) |
| `HULLUCINATOR_HOST` | `0.0.0.0` | Server bind address |
| `HULLUCINATOR_PORT` | `8000` | Server port |
| `PDF_FONT_DIR` | `/usr/share/fonts/truetype/dejavu` | PDF font directory |
| `LOG_LEVEL` | `INFO` | Logging level |

### Runtime Configuration

AI settings can be changed at runtime without restarting the server:

```bash
# Update writer endpoint and model
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"endpoint_url": "http://my-server:8080", "model_name": "llama3-70b"}'

# Configure separate reviewer
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"reviewer_endpoint_url": "http://reviewer-server:9000", "reviewer_model_name": "critic-model", "reviewer_api_key": "sk-reviewer-key", "review_max_turns": 3, "review_word_threshold": 25000, "review_chunk_size": 4}'

# Update API key only
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-new-key-here"}'

# List available models
curl http://localhost:8000/api/models
```

**Note:** Config changes are persisted to `~/.hullucinator_data/data/config.json` automatically. API keys are never saved for security.

### Create a Book (API)

```bash
curl -X POST http://localhost:8000/api/books/create \
  -H "Content-Type: application/json" \
  -d '{"title": "The Martian Garden", "prompt": "A short story about a botanist who grows a garden on Mars.", "tags": ["science fiction", "comedy"], "length": "short_story", "review_max_turns": 2}'
```

**Book length options:**

| Length | Chapters | Target Word Count |
|--------|----------|-------------------|
| `short_story` | 1 | 1,000–7,500 |
| `novella` | 3–5 | 7,500–20,000 |
| `novel` | 8–15 | 20,000–50,000 |
| `epic` | 15–25 | 50,000+ |

**Tags** (optional) guide the LLM on genre, tone, and themes. Examples: `comedy`, `dark fantasy`, `biography`, `space opera`.

**Max review turns** (optional, default: 2) controls how many critique→correct iterations the reviewer will perform. Set per-book or globally via the Settings panel.

Response (returns immediately, generation runs in background):
```json
{"book_id": "567a1645-7fb7-4b85-a7f4-0be75b849c99", "status": "pending", "review_max_turns": 2}
```

### Check Progress

```bash
curl http://localhost:8000/api/books/567a1645-7fb7-4b85-a7f4-0be75b849c99
```

### Trigger Review

```bash
curl -X POST http://localhost:8000/api/books/567a1645-7fb7-4b85-a7f4-0be75b849c99/review
```

### Export

```bash
# EPUB (rich formatting, table of contents, CSS styling, review metadata)
curl -o mybook.epub http://localhost:8000/api/books/567a1645-7fb7-4b85-a7f4-0be75b849c99/export/epub

# PDF (simpler formatting, plain text, review metadata on title page)
curl -o mybook.pdf http://localhost:8000/api/books/567a1645-7fb7-4b85-a7f4-0be75b849c99/export/pdf
```

### Delete

```bash
curl -X DELETE http://localhost:8000/api/books/567a1645-7fb7-4b85-a7f4-0be75b849c99
```

Deletes the book permanently. If the book is actively being generated, the background task is cancelled first. In the web UI, a delete button (🗑) appears on book cards (visible on hover) and in the detail modal. Confirmation is required before deletion.

## Book Generation Pipeline

The orchestrator runs these steps sequentially, incorporating genre tags and length throughout:

1. **Summary** — LLM generates a detailed book summary from the prompt, guided by genre tags and length
2. **Outline** — LLM produces chapter titles from the summary, with chapter count determined by book length
3. **Chapters** — Each chapter is generated one at a time with **cumulative context** from prior chapters:
   - Book summary (overall direction)
   - Full outline (structural awareness)
   - Condensed summaries of all previously generated chapters (narrative continuity)
4. **Review** — Professional critic reviews the complete book using an **iterative correction loop**:
   - Critic evaluates the full book and identifies issues (plot holes, inconsistencies, pacing, continuity)
   - Affected chapters are re-revisioned with full context
   - Critic re-evaluates the corrected book
   - Loop continues until the book passes review (score ≥ 7) or max turns is reached
   - Full per-turn audit trail stored in `review_history`
   - Uses a separate reviewer LLM if configured (`REVIEWER_ENDPOINT_URL`/`REVIEWER_MODEL_NAME`)

Status transitions: `pending` → `summary_generated` → `outline_generated` → `in_progress` → `completed` → `reviewing` → `reviewed` (or `failed` at any step)

Generation runs as a **background task** — the API returns immediately and you can poll `/api/books/{book_id}` for progress. The review step runs automatically after chapter generation completes, or can be triggered manually via `POST /api/books/{book_id}/review`.

## Configuration

Create a `.env` file from `.env.example`:

```bash
# AI Provider (Writer)
AI_ENDPOINT_URL=http://your-llm-server:8080
AI_MODEL_NAME=your-model-name
AI_API_KEY=your-api-key

# Reviewer (optional — leave empty to use writer's endpoint/model)
REVIEWER_ENDPOINT_URL=
REVIEWER_MODEL_NAME=
REVIEWER_API_KEY=

# Server
HULLUCINATOR_HOST=0.0.0.0
HULLUCINATOR_PORT=8000
```

You can also configure the AI provider directly from the web interface using the ⚙️ Settings panel.

## Project Structure

```
hullucinator/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, endpoints, background tasks, web UI
│   ├── schemas.py       # Pydantic data models (BookState, BookCreateRequest)
│   ├── storage.py       # JSON file persistence (absolute paths)
│   ├── ai_client.py     # HTTP client for LLM API (async, persistent, reconfigurable). Includes ReviewerClient for separate review endpoint/model.
│   ├── orchestrator.py  # Generation pipeline with chapter continuity + iterative review loop
│   └── exporter.py      # EPUB & PDF export (configurable fonts, review metadata)
├── static/
│   ├── css/
│   │   └── styles.css   # All styles (variables, components, responsive)
│   ├── js/
│   │   ├── ui.js        # Shared utilities (apiFetch, toast, polling, escaping)
│   │   ├── app.js       # Main app (create form, library, detail modal, review section)
│   │   └── settings.js  # Settings panel (writer/reviewer config, model fetch)
│   └── index.html       # Clean HTML skeleton (links CSS/JS, defines DOM structure)
├── ~/.hullucinator_data/   # User data directory (cross-platform)
│   ├── data/
│   │   ├── books/           # Generated books stored as JSON files
│   │   └── config.json      # Persisted AI config (endpoint URLs, model names, review settings — no API keys)
│   └── exports/             # Exported EPUB/PDF files
├── .env.example         # Environment variable template
├── pyproject.toml       # Python project metadata & dependencies
├── requirements.txt     # Pip dependencies
├── Dockerfile           # Container build
├── AGENTS.md            # Architectural decisions and conventions
└── README.md
```

## Requirements

- Python 3.9+
- `fastapi`, `uvicorn`, `httpx`, `pydantic`
- `ebooklib` (EPUB export)
- `fpdf` (PDF export)
- DejaVu fonts (for PDF export, configurable via `PDF_FONT_DIR`)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
