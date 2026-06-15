# Hullucinator — AI-Powered E-Book Generator

A FastAPI service with a polished web interface that generates complete e-books from a simple prompt. Provide a title, a topic, genre tags, and desired book length — the system orchestrates an LLM to produce a summary, ASCII art cover, chapter outline, full chapter content, and exports to EPUB or PDF.

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
- **Live progress** — Real-time progress bar showing generation status
- **Book library** — Browse all your generated books with status indicators, tags, and length badges
- **Book details** — View summary, outline, ASCII cover, and chapter content
- **Downloads** — Export completed books as EPUB (with genre metadata) or PDF
- **Auto-polling** — Progress updates automatically without page refresh

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web interface (HTML) |
| `GET` | `/api/health` | Health check |
| `POST` | `/api/books/create` | Create a new book (background generation) |
| `GET` | `/api/books` | List all books |
| `GET` | `/api/books/{book_id}` | Get book status and content |
| `GET` | `/api/books/{book_id}/validate` | Validate book completeness |
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

### Export

```bash
# EPUB (rich formatting, table of contents, CSS styling)
curl -o mybook.epub http://localhost:8000/api/books/567a1645-7fb7-4b85-a7f4-0be75b849c99/export/epub

# PDF (simpler formatting, plain text)
curl -o mybook.pdf http://localhost:8000/api/books/567a1645-7fb7-4b85-a7f4-0be75b849c99/export/pdf
```

## Book Generation Pipeline

The orchestrator runs these steps sequentially, incorporating genre tags and length throughout:

1. **Summary** — LLM generates a detailed book summary from the prompt, guided by genre tags and length
2. **ASCII Cover** — LLM creates an ASCII art book cover themed to the genre
3. **Outline** — LLM produces chapter titles from the summary, with chapter count determined by book length
4. **Chapters** — Each chapter is generated one at a time, using the summary, tags, and target word count for context

Status transitions: `pending` → `summary_generated` → `outline_generated` → `in_progress` → `completed` (or `failed` at any step)

Generation runs as a **background task** — the API returns immediately and you can poll `/api/books/{book_id}` for progress.

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

## Project Structure

```
hullucinator/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, endpoints, background tasks, web UI
│   ├── schemas.py       # Pydantic data models (BookState, BookCreateRequest)
│   ├── storage.py       # JSON file persistence (absolute paths)
│   ├── ai_client.py     # HTTP client for LLM API (async, persistent connection)
│   ├── orchestrator.py  # Generation pipeline with enforced status transitions
│   └── exporter.py      # EPUB & PDF export (configurable fonts)
├── static/
│   └── index.html       # Polished web interface
├── data/
│   └── books/           # Generated books stored as JSON files
├── exports/             # Exported EPUB/PDF files
├── .env.example         # Environment variable template
├── pyproject.toml       # Python project metadata & dependencies
├── requirements.txt     # Pip dependencies
├── Dockerfile           # Container build
└── README.md
```

## Requirements

- Python 3.9+
- `fastapi`, `uvicorn`, `httpx`, `pydantic`
- `ebooklib` (EPUB export)
- `fpdf` (PDF export)
- DejaVu fonts (for PDF export, configurable via `PDF_FONT_DIR`)
