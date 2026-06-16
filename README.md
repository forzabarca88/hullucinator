# Hullucinator — AI-Powered E-Book Generator

A FastAPI service with a polished web interface that generates complete e-books from a simple prompt. Provide a title, a topic, genre tags, and desired book length — the system orchestrates an LLM to produce a summary, chapter outline, full chapter content with narrative continuity, professional review with corrections, and exports to EPUB or PDF.

## Features

- **Smart book generation** — LLM produces summary, chapter outline, and full chapters
- **Chapter continuity** — Each chapter receives context from all prior chapters for cohesive writing
- **Professional review** — Automatic post-completion review catches plot holes, inconsistencies, and pacing issues
- **Auto-correction** — Identified issues are corrected with full audit trail
- **Configurable AI provider** — Change endpoint URL, API key, and model from the GUI at runtime
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
- **Auto-polling** — Progress updates automatically without page refresh
- **Settings panel** — Configure AI endpoint URL, API key, and model from the GUI (top-right ⚙️ button)

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web interface (HTML) |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/config` | Get current AI configuration |
| `POST` | `/api/config` | Update AI configuration at runtime |
| `GET` | `/api/models` | List available models from LLM provider |
| `POST` | `/api/books/create` | Create a new book (background generation) |
| `GET` | `/api/books` | List all books |
| `GET` | `/api/books/{book_id}` | Get book status and content |
| `GET` | `/api/books/{book_id}/validate` | Validate book completeness |
| `POST` | `/api/books/{book_id}/review` | Trigger professional review |
| `GET` | `/api/books/{book_id}/export/{format}` | Download as `epub` or `pdf` |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_ENDPOINT_URL` | `http://192.168.0.40:1234` | LLM API endpoint |
| `AI_MODEL_NAME` | `qwen3.6-27b` | Model to use |
| `AI_API_KEY` | *(empty)* | API key (Bearer auth) |
| `HULLUCINATOR_HOST` | `0.0.0.0` | Server bind address |
| `HULLUCINATOR_PORT` | `8000` | Server port |
| `PDF_FONT_DIR` | `/usr/share/fonts/truetype/dejavu` | PDF font directory |
| `LOG_LEVEL` | `INFO` | Logging level |

### Runtime Configuration

AI settings can be changed at runtime without restarting the server:

```bash
# Update endpoint and model
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"endpoint_url": "http://my-server:8080", "model_name": "llama3-70b"}'

# Update API key only
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-new-key-here"}'

# List available models
curl http://localhost:8000/api/models
```

### Create a Book (API)

```bash
curl -X POST http://localhost:8000/api/books/create \
  -H "Content-Type: application/json" \
  -d '{"title": "The Martian Garden", "prompt": "A short story about a botanist who grows a garden on Mars.", "tags": ["science fiction", "comedy"], "length": "short_story"}'
```

**Book length options:**

| Length | Chapters | Target Word Count |
|--------|----------|-------------------|
| `short_story` | 1 | 1,000–7,500 |
| `novella` | 3–5 | 7,500–20,000 |
| `novel` | 8–15 | 20,000–50,000 |
| `epic` | 15–25 | 50,000+ |

**Tags** (optional) guide the LLM on genre, tone, and themes. Examples: `comedy`, `dark fantasy`, `biography`, `space opera`.

Response (returns immediately, generation runs in background):
```json
{"book_id": "567a1645-7fb7-4b85-a7f4-0be75b849c99", "status": "pending"}
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

## Book Generation Pipeline

The orchestrator runs these steps sequentially, incorporating genre tags and length throughout:

1. **Summary** — LLM generates a detailed book summary from the prompt, guided by genre tags and length
2. **Outline** — LLM produces chapter titles from the summary, with chapter count determined by book length
3. **Chapters** — Each chapter is generated one at a time with **cumulative context** from prior chapters:
   - Book summary (overall direction)
   - Full outline (structural awareness)
   - Condensed summaries of all previously generated chapters (narrative continuity)
4. **Review** — Professional critic reviews the complete book:
   - Identifies plot holes, character inconsistencies, pacing issues, and continuity errors
   - Auto-corrects chapters with issues
   - Full audit trail stored for transparency

Status transitions: `pending` → `summary_generated` → `outline_generated` → `in_progress` → `completed` → `reviewing` → `reviewed` (or `failed` at any step)

Generation runs as a **background task** — the API returns immediately and you can poll `/api/books/{book_id}` for progress. The review step runs automatically after chapter generation completes.

## Configuration

Create a `.env` file from `.env.example`:

```bash
# AI Provider
AI_ENDPOINT_URL=http://your-llm-server:8080
AI_MODEL_NAME=your-model-name
AI_API_KEY=your-api-key

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
│   ├── ai_client.py     # HTTP client for LLM API (async, persistent, reconfigurable)
│   ├── orchestrator.py  # Generation pipeline with continuity + review
│   └── exporter.py      # EPUB & PDF export (configurable fonts, review metadata)
├── static/
│   └── index.html       # Polished web interface with settings panel
├── data/
│   └── books/           # Generated books stored as JSON files
├── exports/             # Exported EPUB/PDF files
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
