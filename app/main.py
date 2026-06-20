"""
Hullucinator — AI-Powered E-Book Generator

FastAPI application with:
- GUI-first configuration (no environment variable defaults)
- Runtime-reconfigurable AI settings via API (persisted to ~/.hullucinator_data/data/config.json)
- Model listing from the LLM provider
- Separate reviewer endpoint/model for review tasks
- Iterative review-correction loop with configurable max turns
- Background task support for non-blocking book generation
- Progress polling endpoint for the web interface
- Static file serving for the polished web UI
- All REST API endpoints (create, list, get, validate, export, review)
"""
import os
import re
import uuid
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field

# Characters not allowed in filenames on any major OS
_INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00]')


def _safe_download_name(title: str) -> str:
    """Sanitize a book title for use as a cross-platform download filename."""
    safe = _INVALID_FILENAME_RE.sub('_', title).strip().strip('. ')
    return safe or 'untitled'

from app.schemas import BookState, BookCreateRequest, AIConfig
from app.ai_client import AIClient, ReviewerClient, _parse_models_response, _build_api_url
from app.orchestrator import Orchestrator
from app.storage import save_book, load_book, list_books, delete_book, save_config, load_config
from app.exporter import export_to_epub, export_to_pdf
from app.config import get_default_shared_config

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Network bind (only env vars that affect the server itself, not AI) ──
HOST = os.environ.get("HULLUCINATOR_HOST", "0.0.0.0")
PORT = int(os.environ.get("HULLUCINATOR_PORT", "8000"))

# ── Server configuration object (replaces fragile global variables) ──

@dataclass
class ServerConfig:
    """Mutable server configuration, replacing module-level global variables."""
    configured: bool = False
    reviewer_client: "ReviewerClient | None" = None
    persisted: "AIConfig | None" = None
    max_concurrent_tasks: int = 5
    reviewer_api_key: str | None = None


# ── Load persisted config (the ONLY source of AI configuration) ─────────
# No env var defaults. User must configure via the GUI first.

_persisted = load_config()
configured = bool(_persisted and _persisted.endpoint_url and _persisted.model_name)

logger.info("Configured: %s", configured)
if _persisted:
    logger.info("Loaded persisted config (endpoint=%s, model=%s, reviewer_endpoint=%s, reviewer_model=%s)",
                _persisted.endpoint_url, _persisted.model_name,
                _persisted.reviewer_endpoint_url, _persisted.reviewer_model_name)

# ── Singleton instances ─────────────────────────────────────────────────

# Create the AI client. If not yet configured, use placeholder values.
# The client is reconfigured at runtime when the user saves settings.
ai_client = AIClient(
    endpoint_url=_persisted.endpoint_url if _persisted and _persisted.endpoint_url else "",
    model_name=_persisted.model_name if _persisted and _persisted.model_name else "",
    api_key=os.environ.get("AI_API_KEY") or None,  # API key from env only — never persisted
)

# Reviewer client: created only if persisted config specifies one
reviewer_client: ReviewerClient | None = None
reviewer_api_key = os.environ.get("REVIEWER_API_KEY") or None
if _persisted and (_persisted.reviewer_endpoint_url or _persisted.reviewer_model_name):
    reviewer_client = ReviewerClient(
        ai_client,
        endpoint_url=_persisted.reviewer_endpoint_url or None,
        model_name=_persisted.reviewer_model_name or None,
        api_key=reviewer_api_key or None,
    )
    logger.info("Reviewer Endpoint: %s, Model: %s",
                reviewer_client.endpoint_url, reviewer_client.model_name)

orchestrator = Orchestrator(ai_client, reviewer_client=reviewer_client)

# ── Server config (replaces global configured, reviewer_client, _persisted) ──
server_config = ServerConfig(
    configured=configured,
    reviewer_client=reviewer_client,
    persisted=_persisted,
    reviewer_api_key=reviewer_api_key,
)

# ── Background task registry ────────────────────────────────────────────

# Map of book_id → asyncio.Task for in-progress generations
_active_tasks: dict[str, "asyncio.Task"] = {}

# Concurrency limiter: controls how many books can be generated simultaneously
MAX_CONCURRENT_GENERATIONS = int(os.environ.get("HULLUCINATOR_MAX_CONCURRENT", "5"))
_generation_semaphore: asyncio.Semaphore | None = None


async def _get_semaphore() -> asyncio.Semaphore:
    """Get or create the generation semaphore, lazily bound to current event loop."""
    global _generation_semaphore
    if _generation_semaphore is None:
        _generation_semaphore = asyncio.Semaphore(MAX_CONCURRENT_GENERATIONS)
    return _generation_semaphore


def _check_configured():
    """Raise 400 if AI is not configured (checks live client state)."""
    if not ai_client.endpoint_url or not ai_client.model_name:
        server_config.configured = False
        raise HTTPException(
            status_code=400,
            detail="AI is not configured. Please set your endpoint URL, model, and API key in Settings first.",
        )
    server_config.configured = True


def _check_endpoint(endpoint_url: str | None = None):
    """Raise 400 if no endpoint URL is set. Used for model listing during setup."""
    check_url = endpoint_url if endpoint_url is not None else ai_client.endpoint_url
    if not check_url:
        raise HTTPException(
            status_code=400,
            detail="Endpoint URL is required. Set it in Settings first.",
        )


async def _run_generation_pipeline(book_id: str):
    """
    Run the full book generation pipeline as a background task.
    Updates book state on disk at each step for progress polling.
    After chapters are complete, runs the iterative review step (unless skipped).
    Uses a semaphore to limit concurrent generations.
    """
    book_state = load_book(book_id)
    if not book_state:
        logger.error("Background task: book %s not found", book_id)
        return

    try:
        await orchestrator.generate_summary(book_state)
        await orchestrator.generate_outline(book_state)
        await orchestrator.generate_chapters(book_state)

        # Auto-trigger iterative review after chapters are complete (unless skipped)
        if not book_state.skip_review:
            await orchestrator.review_book(book_state, max_turns=book_state.review_max_turns)
            logger.info("Book '%s' (%s) generation + review completed", book_state.title, book_id)
        else:
            logger.info("Book '%s' (%s) generation completed (review skipped)", book_state.title, book_id)

    except Exception as e:
        logger.error("Book '%s' (%s) generation failed: %s", book_state.title, book_id, e)
        book_state.status = "failed"
        book_state.metadata = {"error": str(e)}
        book_state.progress["current_step"] = "failed"
        book_state.progress["error"] = str(e)
        save_book(book_id, book_state)

    finally:
        _active_tasks.pop(book_id, None)


# ── Request/Response schemas ────────────────────────────────────────────

class AIConfigUpdate(BaseModel):
    """Schema for updating AI configuration."""
    endpoint_url: str | None = None
    model_name: str | None = None
    api_key: str | None = None
    # Reviewer settings (optional — empty/None means use same as writer)
    reviewer_endpoint_url: str | None = None
    reviewer_model_name: str | None = None
    reviewer_api_key: str | None = None
    review_max_turns: int | None = None
    review_word_threshold: int | None = None
    review_chunk_size: int | None = None


class ModelInfo(BaseModel):
    id: str
    name: str


class AIConfigResponse(BaseModel):
    """Schema for the GET /api/config response."""
    configured: bool
    endpoint_url: str
    model_name: str
    api_key_set: bool
    reviewer_endpoint_url: str
    reviewer_model_name: str
    reviewer_api_key_set: bool
    review_max_turns: int
    review_word_threshold: int
    review_chunk_size: int


# ── Lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Hullucinator starting up (configured=%s)...", configured)
    yield
    # Shutdown: close HTTP client
    await ai_client.close()
    logger.info("Hullucinator shut down.")


# ── Application ─────────────────────────────────────────────────────────

app = FastAPI(
    title="Hullucinator",
    description="AI-Powered E-Book Generator — generate complete e-books from a simple prompt",
    version="1.2.0",
    lifespan=lifespan,
)

# ── CORS Middleware (H2) ─────────────────────────────────────────────────
# Allows the web UI to work when served from a different origin
# (e.g., behind a reverse proxy, CDN, or separate frontend deployment)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Security Headers (L4) ───────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add Content Security Policy and other security headers."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ── Static file resolution ──────────────────────────────────────────────
# Works both from source tree and from installed package (uv pip install .)
def _resolve_static_dir() -> Path:
    # 1. Try source tree (project root / static)
    source_static = Path(__file__).resolve().parent.parent / "static"
    if (source_static / "index.html").exists():
        return source_static
    # 2. Try installed package via importlib.resources (M1 fix)
    #    Use "app" package since "static" is package data under app, not its own package
    try:
        from importlib import resources
        pkg = resources.files("app") / "static"
        if (pkg / "index.html").is_file():
            return pkg
    except (ImportError, OSError):
        pass
    # 3. Fallback: return source path even if missing
    return source_static

STATIC_DIR = _resolve_static_dir()

if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Disable browser caching for static assets so UI updates take effect immediately."""
    if request.url.path.startswith("/static/"):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return await call_next(request)


# ── Web UI Routes ───────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def web_index():
    """Serve the polished web interface."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    # If static files aren't available, serve a minimal inline page
    return HTMLResponse(content=_MINIMAL_INDEX, status_code=200)


# Minimal fallback when static files are unavailable (L3: reduced to essential message)
_MINIMAL_INDEX = """\
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hullucinator</title>
<style>body{font-family:system-ui,sans-serif;background:#0f0f1a;color:#eaeaea;
margin:0;padding:2rem;text-align:center}h1{color:#e94560;font-size:2rem;margin:0 0 .5rem}
p{color:#a0a0b8}</style>
</head><body><h1>Hullucinator</h1>
<p>Static files not found. Please ensure the <code>static/</code> directory is available.</p>
<p style="font-size:.8rem;margin-top:2rem;color:#6c6c80">
AI-Powered E-Book Generator</p></body></html>"""



# ── API Endpoints ───────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "hullucinator", "configured": server_config.configured}


@app.get("/api/config-schema")
async def get_config_schema():
    """Return the shared configuration schema for frontend consumption.

    This is the single source of truth for all tunable parameters.
    Frontend reads this to populate dropdowns, defaults, and thresholds.
    """
    config = get_default_shared_config()
    return config.model_dump()


# ── AI Configuration Endpoints ──────────────────────────────────────────

@app.get("/api/config")
async def get_ai_config():
    """Get current AI configuration (including reviewer settings)."""
    reviewer_ep = ""
    reviewer_model = ""
    reviewer_key_set = False
    rc = server_config.reviewer_client
    if rc:
        rconf = rc.get_config()
        reviewer_ep = rconf.get("endpoint_url", "")
        reviewer_model = rconf.get("model_name", "")
        reviewer_key_set = rconf.get("api_key_set", False)

    # Use persisted config values, or fall back to defaults
    persisted = server_config.persisted
    default_turns = persisted.review_max_turns if persisted else 2
    default_word_threshold = persisted.review_word_threshold if persisted else 30_000
    default_chunk_size = persisted.review_chunk_size if persisted else 5

    # Re-evaluate configured status from live client state
    server_config.configured = bool(ai_client.endpoint_url and ai_client.model_name)

    return AIConfigResponse(
        configured=server_config.configured,
        endpoint_url=ai_client.endpoint_url,
        model_name=ai_client.model_name,
        api_key_set=ai_client.api_key is not None and ai_client.api_key != "",
        reviewer_endpoint_url=reviewer_ep,
        reviewer_model_name=reviewer_model,
        reviewer_api_key_set=reviewer_key_set,
        review_max_turns=default_turns,
        review_word_threshold=default_word_threshold,
        review_chunk_size=default_chunk_size,
    )


@app.post("/api/config")
async def update_ai_config(config: AIConfigUpdate):
    """
    Update AI configuration at runtime. Changes take effect immediately
    for all subsequent tasks. Persisted to ~/.hullucinator_data/data/config.json (no API keys).
    """
    # Update writer client
    await ai_client.update_config(
        endpoint_url=config.endpoint_url,
        model_name=config.model_name,
        api_key=config.api_key,
    )

    # Update reviewer client — empty string means "clear this field"
    if config.reviewer_endpoint_url == "" or config.reviewer_model_name == "":
        # User explicitly cleared reviewer config
        if server_config.reviewer_client:
            if config.reviewer_endpoint_url == "":
                server_config.reviewer_client.endpoint_url = ""
            if config.reviewer_model_name == "":
                server_config.reviewer_client.model_name = ""
            if config.reviewer_api_key == "":
                server_config.reviewer_client.api_key = ""
    elif config.reviewer_endpoint_url is not None or config.reviewer_model_name is not None or config.reviewer_api_key is not None:
        if server_config.reviewer_client is None:
            # Create one if it doesn't exist yet
            endpoint = config.reviewer_endpoint_url or ai_client.endpoint_url
            model = config.reviewer_model_name or ai_client.model_name
            rkey = config.reviewer_api_key or None
            if endpoint or model:
                server_config.reviewer_client = ReviewerClient(ai_client, endpoint_url=endpoint, model_name=model, api_key=rkey)
                orchestrator.reviewer_client = server_config.reviewer_client
                logger.info("Created reviewer client: endpoint=%s, model=%s", endpoint, model)
        else:
            await server_config.reviewer_client.update_config(
                endpoint_url=config.reviewer_endpoint_url,
                model_name=config.reviewer_model_name,
                api_key=config.reviewer_api_key,
            )

    # Update server-level reviewer API key
    if config.reviewer_api_key is not None:
        server_config.reviewer_api_key = config.reviewer_api_key if config.reviewer_api_key != "" else None

    # Persist config (without API keys)
    rc = server_config.reviewer_client
    persisted = AIConfig(
        endpoint_url=config.endpoint_url or ai_client.endpoint_url,
        model_name=config.model_name or ai_client.model_name,
        reviewer_endpoint_url=config.reviewer_endpoint_url or (rc.endpoint_url if rc else ""),
        reviewer_model_name=config.reviewer_model_name or (rc.model_name if rc else ""),
        review_max_turns=config.review_max_turns if config.review_max_turns is not None else (server_config.persisted.review_max_turns if server_config.persisted else 2),
        review_word_threshold=config.review_word_threshold if config.review_word_threshold is not None else (server_config.persisted.review_word_threshold if server_config.persisted else 30_000),
        review_chunk_size=config.review_chunk_size if config.review_chunk_size is not None else (server_config.persisted.review_chunk_size if server_config.persisted else 5),
    )
    save_config(persisted)
    logger.info("Config saved to disk: endpoint=%s, model=%s",
                persisted.endpoint_url, persisted.model_name)

    # Update server_config so get_ai_config returns fresh values
    server_config.persisted = persisted

    # Re-evaluate configured status
    server_config.configured = bool(ai_client.endpoint_url and ai_client.model_name)

    return {"status": "ok", "config": await get_ai_config()}


@app.get("/api/models")
async def list_available_models(
    endpoint_url: str | None = None,
    api_key: str | None = None,
):
    """
    List available models from the LLM provider.
    Accepts optional endpoint_url/api_key query params for setup wizard
    fetching before config is saved.

    Uses a temporary client to avoid mutating the shared ai_client state
    (fixes race condition with concurrent requests).
    """
    effective_endpoint = endpoint_url or ai_client.endpoint_url
    effective_api_key = api_key or ai_client.api_key
    _check_endpoint(effective_endpoint)

    # Build a temporary client for this request — doesn't mutate shared state
    temp_client = AIClient(
        endpoint_url=effective_endpoint,
        model_name=ai_client.model_name,
        api_key=effective_api_key,
    )
    try:
        models = await temp_client.list_models()
        return {"models": models, "current_model": ai_client.model_name}
    finally:
        await temp_client.close()


@app.get("/api/reviewer/models")
async def list_reviewer_models(
    endpoint_url: str | None = None,
    api_key: str | None = None,
):
    """
    List available models from the reviewer LLM provider.
    Accepts optional endpoint_url/api_key query params for setup wizard.
    """
    # No reviewer client configured and no endpoint param → uses writer's
    if reviewer_client is None and not endpoint_url:
        return {"models": [], "current_model": "", "uses_writer": True}

    # Setup wizard: make a direct request without modifying client state
    if endpoint_url:
        url = _build_api_url(endpoint_url, "models")
        headers = ai_client._headers
        if api_key:
            headers = {**headers, "Authorization": f"Bearer {api_key}"}
        try:
            response = await ai_client._client.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()
            models = _parse_models_response(result)
            return {"models": models, "current_model": "", "uses_writer": False}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch models: {str(e)}")

    # Normal path: use existing reviewer client
    if reviewer_client is None:
        return {"models": [], "current_model": "", "uses_writer": True}
    if not reviewer_client.endpoint_url:
        raise HTTPException(
            status_code=400,
            detail="Reviewer endpoint URL is required. Set it first.",
        )
    models = await reviewer_client.list_models()
    return {"models": models, "current_model": reviewer_client.model_name or "", "uses_writer": False}


# ── Book Endpoints ──────────────────────────────────────────────────────

@app.post("/api/books/create")
async def create_book(request: BookCreateRequest, background_tasks: BackgroundTasks):
    """
    Create a new book and start generation in the background.

    Returns the book_id immediately so the client can poll for progress.
    Generation is rate-limited by a semaphore to prevent resource exhaustion.
    """
    _check_configured()

    book_id = str(uuid.uuid4())
    book_state = BookState(
        id=book_id,
        title=request.title,
        prompt=request.prompt,
        tags=request.tags,
        length=request.length,
        status="pending",
        review_max_turns=request.review_max_turns,
        skip_review=request.skip_review,
        progress={"current_step": "pending", "total_chapters": 0, "chapters_completed": 0, "percentage": 0},
    )

    # Save initial state
    save_book(book_id, book_state)

    # Start generation as a background task (with concurrency limit)
    async def _semaphore_task():
        async with await _get_semaphore():
            await _run_generation_pipeline(book_id)

    task = asyncio.create_task(_semaphore_task())
    _active_tasks[book_id] = task

    logger.info("Book '%s' (%s) queued for generation (max_review_turns=%d, skip_review=%s)",
                request.title, book_id, request.review_max_turns, request.skip_review)
    return {"book_id": book_id, "status": "pending", "review_max_turns": request.review_max_turns, "skip_review": request.skip_review}


@app.get("/api/books")
async def list_all_books():
    """List all books (newest first)."""
    books = list_books()
    # Return lightweight summary for each book
    return [
        {
            "id": b.id,
            "title": b.title,
            "status": b.status,
            "progress": b.progress,
            "prompt": b.prompt,
            "tags": b.tags,
            "length": b.length,
            "review_max_turns": b.review_max_turns,
            "skip_review": b.skip_review,
            "review": b.review,
            "review_history": b.review_history,
        }
        for b in books
    ]


@app.get("/api/books/{book_id}")
async def get_book_status(book_id: str):
    """Get full book status and content."""
    book_state = load_book(book_id)
    if not book_state:
        raise HTTPException(status_code=404, detail="Book not found")
    return book_state.model_dump()


@app.get("/api/books/{book_id}/validate")
async def validate_book(book_id: str):
    """Validate book completeness."""
    book_state = load_book(book_id)
    if not book_state:
        raise HTTPException(status_code=404, detail="Book not found")
    return orchestrator.validate_book(book_state)


@app.post("/api/books/{book_id}/review")
async def trigger_review(book_id: str, background_tasks: BackgroundTasks):
    """
    Trigger an iterative professional review of a completed book.
    Runs critique → correct → re-critique until approved or max turns reached.

    The review runs in the background. Poll the book status to track progress.
    """
    _check_configured()

    book_state = load_book(book_id)
    if not book_state:
        raise HTTPException(status_code=404, detail="Book not found")

    if book_state.status not in ("completed", "reviewing"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot review: book is in '{book_state.status}' status. Must be 'completed'.",
        )

    async def _run_review():
        async with await _get_semaphore():
            try:
                # Reload to get latest state
                book = load_book(book_id)
                if not book:
                    return
                await orchestrator.review_book(book, max_turns=book.review_max_turns)
                logger.info("Iterative review completed for '%s' (%s)", book.title, book_id)
            except Exception as e:
                logger.error("Review failed for book %s: %s", book_id, e)
                book = load_book(book_id)
                if book:
                    book.status = "failed"
                    book.metadata = {"error": str(e)}
                    book.progress["current_step"] = "review_failed"
                    book.progress["error"] = str(e)
                    save_book(book_id, book)

    task = asyncio.create_task(_run_review())
    _active_tasks[book_id] = task

    return {"status": "review_started", "book_id": book_id, "max_turns": book_state.review_max_turns}


@app.get("/api/books/{book_id}/export/{fmt}")
async def export_book(book_id: str, fmt: str):
    """
    Export a completed or reviewed book to EPUB or PDF.

    Validates the book before exporting.
    """
    book_state = load_book(book_id)
    if not book_state:
        raise HTTPException(status_code=404, detail="Book not found")

    validation = orchestrator.validate_book(book_state)
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail=f"Book is not ready for export. Errors: {validation['errors']}",
        )

    try:
        review_data = book_state.review if book_state.review else None
        download_name = _safe_download_name(book_state.title)
        if fmt == "epub":
            path = export_to_epub(book_id, book_state.title, book_state.chapters, book_state.tags, review=review_data)
            return FileResponse(
                path,
                media_type="application/epub+zip",
                filename=f"{download_name}.epub",
            )
        elif fmt == "pdf":
            path = export_to_pdf(book_id, book_state.title, book_state.chapters, book_state.tags, review=review_data)
            return FileResponse(
                path,
                media_type="application/pdf",
                filename=f"{download_name}.pdf",
            )
        else:
            raise HTTPException(status_code=400, detail=f"Invalid format '{fmt}'. Use 'epub' or 'pdf'.")
    except Exception as e:
        logger.error("Export failed for book %s: %s", book_id, e)
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


# ── Retry Book ──────────────────────────────────────────────────

@app.post("/api/books/{book_id}/retry")
async def retry_book_endpoint(book_id: str, background_tasks: BackgroundTasks):
    """Retry a failed book by creating a new one with the same parameters.

    Loads the failed book's fields, constructs a new BookCreateRequest,
    queues generation in the background, and deletes the old book.
    """
    _check_configured()

    book_state = load_book(book_id)
    if not book_state:
        raise HTTPException(status_code=404, detail="Book not found")

    # Cancel any active generation task for this book
    task = _active_tasks.pop(book_id, None)
    if task and not task.done():
        task.cancel()
        logger.info("Cancelled active generation task for book '%s' (%s)", book_state.title, book_id)

    # Build a new BookCreateRequest from the old book's fields
    request = BookCreateRequest(
        title=book_state.title,
        prompt=book_state.prompt,
        tags=book_state.tags,
        length=book_state.length,
        review_max_turns=book_state.review_max_turns,
        skip_review=book_state.skip_review,
    )

    # Create new book
    new_book_id = str(uuid.uuid4())
    new_book_state = BookState(
        id=new_book_id,
        title=request.title,
        prompt=request.prompt,
        tags=request.tags,
        length=request.length,
        status="pending",
        review_max_turns=request.review_max_turns,
        skip_review=request.skip_review,
        progress={"current_step": "pending", "total_chapters": 0, "chapters_completed": 0, "percentage": 0},
    )
    save_book(new_book_id, new_book_state)

    # Start generation as background task
    async def _semaphore_task():
        async with await _get_semaphore():
            await _run_generation_pipeline(new_book_id)

    task = asyncio.create_task(_semaphore_task())
    _active_tasks[new_book_id] = task

    # Delete the old book
    delete_book(book_id)

    logger.info("Retry: created new book '%s' (%s) from failed book '%s' (%s)",
                new_book_state.title, new_book_id, book_state.title, book_id)
    return {
        "book_id": new_book_id,
        "status": "pending",
        "old_book_id": book_id,
        "review_max_turns": request.review_max_turns,
        "skip_review": request.skip_review,
    }


# ── Delete Book ─────────────────────────────────────────────────

@app.delete("/api/books/{book_id}")
async def delete_book_endpoint(book_id: str):
    """Delete a book and its data from storage."""
    book_state = load_book(book_id)
    if not book_state:
        raise HTTPException(status_code=404, detail="Book not found")

    # Cancel active task if the book is being generated
    task = _active_tasks.pop(book_id, None)
    if task and not task.done():
        task.cancel()
        logger.info("Cancelled active generation task for book '%s' (%s)", book_state.title, book_id)

    # Delete the book file
    deleted = delete_book(book_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete book file")

    logger.info("Deleted book '%s' (%s)", book_state.title, book_id)
    return {"status": "deleted", "book_id": book_id}


# ── CLI entry point ─────────────────────────────────────────────────────

def main():
    """Run the server via CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="hullucinator",
        description="AI-Powered E-Book Generator — generate complete e-books from a simple prompt",
    )
    parser.add_argument(
        "--host", default=HOST, help="Bind address (default: %(default)s)"
    )
    parser.add_argument(
        "--port", type=int, default=PORT, help="Port (default: %(default)s)"
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s 1.2.0"
    )

    args = parser.parse_args()

    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
