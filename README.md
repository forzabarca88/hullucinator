# Hullucinator — AI-Powered E-Book Generator

Generate complete e-books from a simple prompt. Provide a title, topic, genre tags, and desired length — the system orchestrates an LLM to produce a polished book with professional review, then exports to EPUB or PDF.

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

### Install

Hullucinator uses `uv` for package management. Create a virtual environment and install dependencies:

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### Configure

Create a `.env` file from the provided template:

```bash
cp .env.example .env
```

Edit `.env` to point at your LLM provider:

```ini
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

You can also configure everything from the web interface using the ⚙️ Settings panel — no `.env` file needed.

### Run

```bash
# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Or use the CLI entry point
hullucinator
```

Open http://localhost:8000 in your browser. On first launch, the setup wizard guides you through configuring your AI provider.

## Using the Web Interface

### Create a Book

1. Enter a **title** for your book
2. Write a **prompt** describing what you want the book to be about
3. Add optional **genre tags** (comma-separated, e.g. "comedy, time travel") to guide tone and style
4. Choose a **book length**:
   | Length | Chapters | Target Word Count |
   |--------|----------|-------------------|
   | Short Story | 1 | 1,000–7,500 |
   | Novella | 3–5 | 7,500–20,000 |
   | Novel | 8–15 | 20,000–50,000 |
   | Epic / Saga | 15–25 | 50,000+ |
5. Click **"Generate Book"** — generation runs in the background with a live progress bar

### Browse Your Library

- See all generated books with status indicators, genre tags, and length badges
- Click any book to view its summary, outline, chapter content, and review audit trail
- Progress updates automatically without refreshing the page

### Review

After chapter generation completes, the book goes through professional review automatically. You can see:
- **Critique score** and verdict
- **Corrections applied** during each review turn
- Full per-turn audit trail

You can also trigger a manual review at any time from the book detail view.

### Export

Once a book is complete (or reviewed), download it in your preferred format:

- **EPUB** — Rich formatting, table of contents, drop caps, genre metadata, and review info
- **PDF** — Clean formatting with configurable fonts

### Delete & Retry

- **Delete** — Hover over a book card to reveal the 🗑 button, or use the delete button in the detail modal. Confirmation is required.
- **Retry** — Restart generation for failed books; the old failed entry is automatically removed.

## Settings

Click the ⚙️ button in the top-right corner to configure:

- **Writer** — Endpoint URL, API key, and model name
- **Reviewer** — Separate endpoint URL, API key, and model name (leave empty to use writer's settings)
- **Max review turns** — How many critique→correct iterations per book (default: 2)
- **Model discovery** — Fetch available models from your LLM provider directly in the settings panel

Settings are saved to disk automatically and restored on restart. API keys are never persisted for security.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_ENDPOINT_URL` | `http://192.168.0.40:1234` | Writer LLM API endpoint |
| `AI_MODEL_NAME` | `qwen3.6-27b` | Writer model name |
| `AI_API_KEY` | *(empty)* | API key (Bearer auth) |
| `REVIEWER_ENDPOINT_URL` | *(empty)* | Reviewer LLM endpoint |
| `REVIEWER_MODEL_NAME` | *(empty)* | Reviewer model |
| `REVIEWER_API_KEY` | *(empty)* | Reviewer API key |
| `HULLUCINATOR_HOST` | `0.0.0.0` | Server bind address |
| `HULLUCINATOR_PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level |

## Requirements

- Python 3.9+
- `uv` (for package management)
- Access to an LLM API (any OpenAI-compatible endpoint)

## Data Storage

Generated books and configuration are stored in `~/.hullucinator_data/`:

- `data/books/` — Generated books as JSON files
- `data/config.json` — Persisted AI config (no API keys)
- `exports/` — Exported EPUB and PDF files

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.