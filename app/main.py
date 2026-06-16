"""
Hullucinator — AI-Powered E-Book Generator

FastAPI application with:
- Environment-variable configuration (AI endpoint, model, API key)
- Runtime-reconfigurable AI settings via API (persisted to data/config.json)
- Model listing from the LLM provider
- Separate reviewer endpoint/model for review tasks
- Iterative review-correction loop with configurable max turns
- Background task support for non-blocking book generation
- Progress polling endpoint for the web interface
- Static file serving for the polished web UI
- All REST API endpoints (create, list, get, validate, export, review)
"""
import os
import sys
import uuid
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.schemas import BookState, BookCreateRequest, AIConfig
from app.ai_client import AIClient, ReviewerClient
from app.orchestrator import Orchestrator
from app.storage import save_book, load_book, list_books, save_config, load_config
from app.exporter import export_to_epub, export_to_pdf

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration from environment variables ────────────────────────────

AI_ENDPOINT_URL = os.environ.get("AI_ENDPOINT_URL", "http://192.168.0.40:1234")
AI_MODEL_NAME = os.environ.get("AI_MODEL_NAME", "qwen3.6-27b")
AI_API_KEY = os.environ.get("AI_API_KEY", "")
HOST = os.environ.get("HULLUCINATOR_HOST", "0.0.0.0")
PORT = int(os.environ.get("HULLUCINATOR_PORT", "8000"))

# Reviewer defaults (empty = use same as writer)
REVIEWER_ENDPOINT_URL = os.environ.get("REVIEWER_ENDPOINT_URL", "")
REVIEWER_MODEL_NAME = os.environ.get("REVIEWER_MODEL_NAME", "")

logger.info("AI Endpoint: %s", AI_ENDPOINT_URL)
logger.info("AI Model: %s", AI_MODEL_NAME)

# ── Load persisted config (overrides env vars where set) ────────────────

_persisted = load_config()
if _persisted:
    if _persisted.endpoint_url:
        AI_ENDPOINT_URL = _persisted.endpoint_url
    if _persisted.model_name:
        AI_MODEL_NAME = _persisted.model_name
    logger.info("Loaded persisted config (endpoint=%s, model=%s)",
                _persisted.endpoint_url, _persisted.model_name)

# ── Singleton instances ─────────────────────────────────────────────────

ai_client = AIClient(
    endpoint_url=AI_ENDPOINT_URL,
    model_name=AI_MODEL_NAME,
    api_key=AI_API_KEY if AI_API_KEY else None,
)

# Reviewer client: uses different endpoint/model if configured
reviewer_client: ReviewerClient | None = None
if REVIEWER_ENDPOINT_URL or REVIEWER_MODEL_NAME:
    reviewer_client = ReviewerClient(
        ai_client,
        endpoint_url=REVIEWER_ENDPOINT_URL or None,
        model_name=REVIEWER_MODEL_NAME or None,
    )
    logger.info("Reviewer Endpoint: %s, Model: %s",
                reviewer_client.endpoint_url, reviewer_client.model_name)

orchestrator = Orchestrator(ai_client, reviewer_client=reviewer_client)

# ── Background task registry ────────────────────────────────────────────

# Map of book_id → asyncio.Task for in-progress generations
_active_tasks: dict[str, "asyncio.Task"] = {}


async def _run_generation_pipeline(book_id: str):
    """
    Run the full book generation pipeline as a background task.
    Updates book state on disk at each step for progress polling.
    After chapters are complete, runs the iterative review step automatically.
    """
    book_state = load_book(book_id)
    if not book_state:
        logger.error("Background task: book %s not found", book_id)
        return

    try:
        await orchestrator.generate_summary(book_state)
        await orchestrator.generate_outline(book_state)
        await orchestrator.generate_chapters(book_state)
        # Auto-trigger iterative review after chapters are complete
        await orchestrator.review_book(book_state, max_turns=book_state.review_max_turns)
        logger.info("Book '%s' (%s) generation + review completed", book_state.title, book_id)

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
    review_max_turns: int | None = None


class ModelInfo(BaseModel):
    id: str
    name: str


class AIConfigResponse(BaseModel):
    """Schema for the GET /api/config response."""
    endpoint_url: str
    model_name: str
    api_key_set: bool
    reviewer_endpoint_url: str
    reviewer_model_name: str
    review_max_turns: int


# ── Lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Hullucinator starting up...")
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

# ── Static file resolution ──────────────────────────────────────────────
# Works both from source tree and from installed package (uv pip install .)
def _resolve_static_dir() -> Path:
    # 1. Try source tree (project root / static)
    source_static = Path(__file__).resolve().parent.parent / "static"
    if (source_static / "index.html").exists():
        return source_static
    # 2. Try installed package via importlib.resources
    try:
        from importlib import resources
        pkg = resources.files("static")
        if (pkg / "index.html").is_file():
            return pkg
    except (ImportError, OSError):
        pass
    # 3. Fallback: return source path even if missing
    return source_static

STATIC_DIR = _resolve_static_dir()

if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Web UI Routes ───────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def web_index():
    """Serve the polished web interface."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    # If static files aren't available, serve a minimal inline page
    return HTMLResponse(content=_MINIMAL_INDEX, status_code=200)


# Minimal fallback when static files are unavailable
_MINIMAL_INDEX = """\
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hullucinator</title>
<style>body{font-family:system-ui,sans-serif;background:#0f0f1a;color:#eaeaea;
margin:0;padding:2rem;text-align:center}.box{max-width:480px;margin:auto;
background:#16213e;border:1px solid rgba(255,255,255,.08);border-radius:12px;
padding:2rem;text-align:left}h1{color:#e94560;font-size:2rem;margin:0 0 .5rem}
label{display:block;font-size:.8rem;color:#a0a0b8;margin:.5rem 0 .2rem;
text-transform:uppercase}input,textarea{width:100%;padding:.7rem;
background:#1a1a2e;border:1px solid rgba(255,255,255,.08);border-radius:8px;
color:#eaeaea;font-size:.95rem;margin-bottom:.5rem}textarea{min-height:100px;
resize:vertical}button{background:#e94560;color:#fff;border:none;padding:.8rem
1.5rem;border-radius:8px;font-weight:600;cursor:pointer;font-size:.95rem}
button:hover{background:#ff6b81}button:disabled{opacity:.5;cursor:not-allowed}
.books{margin-top:2rem}.book{background:#16213e;border:1px solid
rgba(255,255,255,.08);border-radius:8px;padding:1rem;margin-bottom:.5rem;
cursor:pointer}.book:hover{border-color:#e94560}.status{display:inline-block;
padding:.2rem .6rem;border-radius:12px;font-size:.7rem;font-weight:600;
text-transform:uppercase}.s-completed{background:rgba(46,204,113,.15);color:#2ecc71}
.s-failed{background:rgba(231,76,60,.15);color:#e74c3c}.s-in_progress{
background:rgba(243,156,18,.15);color:#f39c12}.s-pending{
background:rgba(52,152,219,.15);color:#3498db}.toast{position:fixed;top:1rem;
right:1rem;background:#16213e;border:1px solid rgba(255,255,255,.08);
padding:.8rem 1.2rem;border-radius:8px;font-size:.9rem;z-index:999;
animation:fade .3s}@keyframes fade{from{opacity:0;transform:translateX(100%)}
to{opacity:1;transform:translateX(0)}}a{color:#3498db}</style>
</head><body><h1>Hullucinator</h1><p style="color:#a0a0b8;margin-bottom:2rem">
AI-Powered E-Book Generator</p>
<div class="box"><form id="createForm"><label>Book Title</label>
<input id="title" placeholder="The Martian Garden" required>
<label>Prompt</label><textarea id="prompt" placeholder="Describe your book..."
required></textarea><button type="submit" id="createBtn">Generate Book</button>
</form></div><div class="books" id="booksList"></div>
<script>
const API='/api';async function apiFetch(p,o={}){const r=await fetch(API+p,{
headers:{'Content-Type':'application/json'},...o});if(!r.ok){const e=await r.json()
.catch(()=>({detail:r.statusText}));throw new Error(e.detail||r.statusText)}
return r.json()}
function toast(m){const t=document.createElement('div');t.className='toast';
t.textContent=m;document.body.appendChild(t);setTimeout(()=>t.remove(),3000)}
function statusBadge(s){const c={completed:'s-completed',failed:'s-failed',
in_progress:'s-in_progress',pending:'s-pending',summary_generated:'s-pending',
outline_generated:'s-in_progress'};return`<span class="status ${c[s]||''}">${s}</span>`}
async function loadBooks(){try{const books=await apiFetch('/books');
const list=document.getElementById('booksList');if(!books.length){
list.innerHTML='<p style="color:#6c6c80;text-align:center">No books yet.</p>';return}
list.innerHTML=books.map(b=>`<div class="book" onclick="openDetail('${b.id}')">
<strong>${b.title}</strong> ${statusBadge(b.status)}<br><small style="color:#a0a0b8">
${b.prompt}</small></div>`).join('')}catch(e){console.error(e)}}
async function openDetail(id){try{const b=await apiFetch('/books/'+id);
let h=`<h2>${b.title}</h2>${statusBadge(b.status)}<br><br>`;
if(b.summary)h+=`<h3>Summary</h3><p>${b.summary}</p>`;
if(b.outline)h+=`<h3>Outline</h3><ol>`+b.outline.map(c=>`<li>${c}</li>`).join('')+
`</ol>`;if(b.chapters)for(const[t,c]of Object.entries(b.chapters))
h+=`<details><summary>${t}</summary><pre>${c}</pre></details>`;
if(b.status==='completed')h+=`<br><a href="${API}/books/${id}/export/epub">Download EPUB</a>
 | <a href="${API}/books/${id}/export/pdf">Download PDF</a>`;
if(b.status==='failed'&&b.metadata?.error)h+=`<p style="color:#e74c3c">Error: ${b.metadata.error}</p>`;
if(b.status!=='completed'&&b.status!=='failed'){
const p=b.progress||{};h+=`<p>Progress: ${p.current_step||b.status} (${p.percentage||0}%)</p>`}
alert(h);if(b.status==='completed'||b.status==='failed')loadBooks()
}catch(e){toast('Error: '+e.message)}}
document.getElementById('createForm').addEventListener('submit',async e=>{
e.preventDefault();const btn=document.getElementById('createBtn');
btn.disabled=true;btn.textContent='Creating...';
try{await apiFetch('/books/create',{method:'POST',body:JSON.stringify({
title:document.getElementById('title').value,prompt:document.getElementById('prompt')
.value})});document.getElementById('title').value='';
document.getElementById('prompt').value='';toast('Book queued!');loadBooks()
}catch(e){toast('Error: '+e.message)}finally{btn.disabled=false;
btn.textContent='Generate Book'}});
loadBooks();setInterval(loadBooks,10000);
</script></body></html>"""



# ── API Endpoints ───────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "hullucinator"}


# ── AI Configuration Endpoints ──────────────────────────────────────────

@app.get("/api/config")
async def get_ai_config():
    """Get current AI configuration (including reviewer settings)."""
    reviewer_ep = ""
    reviewer_model = ""
    if reviewer_client:
        rconf = reviewer_client.get_config()
        reviewer_ep = rconf.get("endpoint_url", "")
        reviewer_model = rconf.get("model_name", "")

    return AIConfigResponse(
        endpoint_url=ai_client.endpoint_url,
        model_name=ai_client.model_name,
        api_key_set=ai_client.api_key is not None and ai_client.api_key != "",
        reviewer_endpoint_url=reviewer_ep,
        reviewer_model_name=reviewer_model,
        review_max_turns=2,  # global default
    )


@app.post("/api/config")
async def update_ai_config(config: AIConfigUpdate):
    """
    Update AI configuration at runtime. Changes take effect immediately
    for all subsequent tasks. Persisted to data/config.json (no API keys).
    """
    # Update writer client
    await ai_client.update_config(
        endpoint_url=config.endpoint_url,
        model_name=config.model_name,
        api_key=config.api_key,
    )

    # Update reviewer client
    if config.reviewer_endpoint_url is not None or config.reviewer_model_name is not None:
        if reviewer_client is None:
            # Create one if it doesn't exist yet
            endpoint = config.reviewer_endpoint_url or ai_client.endpoint_url
            model = config.reviewer_model_name or ai_client.model_name
            if endpoint or model:
                reviewer_client = ReviewerClient(ai_client, endpoint_url=endpoint, model_name=model)
                orchestrator.reviewer_client = reviewer_client
                logger.info("Created reviewer client: endpoint=%s, model=%s", endpoint, model)
        else:
            await reviewer_client.update_config(
                endpoint_url=config.reviewer_endpoint_url,
                model_name=config.reviewer_model_name,
            )

    # Persist config (without API key)
    persisted = AIConfig(
        endpoint_url=config.endpoint_url or ai_client.endpoint_url,
        model_name=config.model_name or ai_client.model_name,
        reviewer_endpoint_url=config.reviewer_endpoint_url or (reviewer_client.endpoint_url if reviewer_client else ""),
        reviewer_model_name=config.reviewer_model_name or (reviewer_client.model_name if reviewer_client else ""),
        review_max_turns=config.review_max_turns if config.review_max_turns is not None else 2,
    )
    save_config(persisted)
    logger.info("Config saved to disk: endpoint=%s, model=%s",
                persisted.endpoint_url, persisted.model_name)

    return {"status": "ok", "config": get_ai_config()}


@app.get("/api/models")
async def list_available_models():
    """List available models from the LLM provider."""
    models = await ai_client.list_models()
    return {"models": models, "current_model": ai_client.model_name}


# ── Book Endpoints ──────────────────────────────────────────────────────

@app.post("/api/books/create")
async def create_book(request: BookCreateRequest, background_tasks: BackgroundTasks):
    """
    Create a new book and start generation in the background.

    Returns the book_id immediately so the client can poll for progress.
    """
    book_id = str(uuid.uuid4())
    book_state = BookState(
        id=book_id,
        title=request.title,
        prompt=request.prompt,
        tags=request.tags,
        length=request.length,
        status="pending",
        review_max_turns=request.review_max_turns,
        progress={"current_step": "pending", "total_chapters": 0, "chapters_completed": 0, "percentage": 0},
    )

    # Save initial state
    save_book(book_id, book_state)

    # Start generation as a background task
    import asyncio
    task = asyncio.create_task(_run_generation_pipeline(book_id))
    _active_tasks[book_id] = task

    logger.info("Book '%s' (%s) queued for generation (max_review_turns=%d)",
                request.title, book_id, request.review_max_turns)
    return {"book_id": book_id, "status": "pending", "review_max_turns": request.review_max_turns}


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
    book_state = load_book(book_id)
    if not book_state:
        raise HTTPException(status_code=404, detail="Book not found")

    if book_state.status not in ("completed", "reviewing"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot review: book is in '{book_state.status}' status. Must be 'completed'.",
        )

    async def _run_review():
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

    import asyncio
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
        if fmt == "epub":
            path = export_to_epub(book_id, book_state.title, book_state.chapters, book_state.tags, review=review_data)
            return FileResponse(
                path,
                media_type="application/epub+zip",
                filename=f"{book_state.title}.epub",
            )
        elif fmt == "pdf":
            path = export_to_pdf(book_id, book_state.title, book_state.chapters, book_state.tags, review=review_data)
            return FileResponse(
                path,
                media_type="application/pdf",
                filename=f"{book_state.title}.pdf",
            )
        else:
            raise HTTPException(status_code=400, detail=f"Invalid format '{fmt}'. Use 'epub' or 'pdf'.")
    except Exception as e:
        logger.error("Export failed for book %s: %s", book_id, e)
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


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
