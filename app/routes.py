"""
API endpoint definitions for Hullucinator.

Organized by resource:
- Health check
- Configuration (shared schema, AI config get/set)
- Model listing (writer and reviewer)
- Books (create, list, get, validate, review, export, retry, delete)
- Web UI (index page)
"""
import uuid
import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse

from app.ai_client import AIClient, ReviewerClient, _parse_models_response, _build_api_url
from app.orchestrator import Orchestrator
from app.storage import save_book, load_book, list_books, delete_book, save_config, load_config
from app.exporter import export_to_epub, export_to_pdf
from app.config import get_default_shared_config
from app.schemas import BookState, BookCreateRequest, AIConfig, AIConfigUpdate, ModelInfo, AIConfigResponse, ConfigValidationResult

logger = logging.getLogger(__name__)


def _safe_download_name(title: str) -> str:
    """Sanitize a title for use as a filename."""
    import re
    name = re.sub(r"[^\w\s-]", "", title)
    name = re.sub(r"\s+", "-", name).strip("-")
    return name[:80] or "book"


# Minimal fallback when static files are unavailable
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


async def _run_generation_pipeline(book_id: str, orchestrator, save_book):
    """
    Run the full book generation pipeline as a background task.
    Updates book state on disk at each step for progress polling.
    After chapters are complete, runs the iterative review step (unless skipped).
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



def create_router(
    ai_client: AIClient,
    reviewer_client: ReviewerClient,
    orchestrator: Orchestrator,
    server_config,
    static_dir: Path,
    active_tasks: dict,
    get_semaphore,
    check_configured,
    check_endpoint,
) -> APIRouter:
    """Create an APIRouter with all Hullucinator endpoints.

    Dependencies are passed explicitly to avoid circular imports.
    """
    router = APIRouter()

    # ── Web UI ──────────────────────────────────────────────────────────

    @router.get("/", response_class=HTMLResponse)
    async def web_index():
        """Serve the polished web interface."""
        index_path = static_dir / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
        return HTMLResponse(content=_MINIMAL_INDEX, status_code=200)

    # ── Health Check ────────────────────────────────────────────────────

    @router.get("/api/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": "hullucinator", "configured": server_config.configured}

    # ── Shared Config Schema ────────────────────────────────────────────

    @router.get("/api/config-schema")
    async def get_config_schema():
        """Return the shared configuration schema for frontend consumption.

        This is the single source of truth for all tunable parameters.
        Frontend reads this to populate dropdowns, defaults, and thresholds.
        """
        config = get_default_shared_config()
        return config.model_dump()

    # ── AI Configuration Endpoints ──────────────────────────────────────

    @router.get("/api/config")
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

    @router.post("/api/config")
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
            # User explicitly cleared reviewer config — null out the client
            # so orchestrator falls back to the main ai_client for review tasks
            server_config.reviewer_client = None
            orchestrator.reviewer_client = None
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

    @router.post("/api/config/validate")
    async def validate_config(config: AIConfigUpdate):
        """
        Validate AI configuration by testing the endpoint connectivity and credentials.
        Returns validation results without persisting anything.
        """
        writer_ok = False
        writer_error = ""
        reviewer_ok = False
        reviewer_error = ""

        # Validate writer
        writer_endpoint = config.endpoint_url or ai_client.endpoint_url
        writer_key = config.api_key or ai_client.api_key
        writer_model = config.model_name or ai_client.model_name

        if not writer_endpoint:
            writer_error = "Writer endpoint URL is required"
        elif not writer_model:
            writer_error = "Writer model name is required"
        else:
            check_endpoint(writer_endpoint)
            temp_client = AIClient(
                endpoint_url=writer_endpoint,
                model_name=writer_model,
                api_key=writer_key,
            )
            try:
                models = await temp_client.list_models()
                if models:
                    writer_ok = True
                else:
                    writer_error = "No models returned — check endpoint URL and API key"
            except Exception as e:
                writer_error = str(e)
            finally:
                await temp_client.close()

        # Validate reviewer (only if separate reviewer is configured)
        r_ep = config.reviewer_endpoint_url
        r_model = config.reviewer_model_name
        r_key = config.reviewer_api_key
        has_reviewer = any(v for v in [r_ep, r_model, r_key] if v)

        if has_reviewer:
            # Use reviewer endpoint if provided, otherwise writer's
            rev_endpoint = r_ep if r_ep else writer_endpoint
            rev_model = r_model if r_model else writer_model
            rev_key = r_key if r_key else writer_key

            if not rev_endpoint:
                reviewer_error = "Reviewer endpoint URL is required"
            elif not rev_model:
                reviewer_error = "Reviewer model name is required"
            else:
                check_endpoint(rev_endpoint)
                temp_client = AIClient(
                    endpoint_url=rev_endpoint,
                    model_name=rev_model,
                    api_key=rev_key,
                )
                try:
                    models = await temp_client.list_models()
                    if models:
                        reviewer_ok = True
                    else:
                        reviewer_error = "No models returned — check endpoint URL and API key"
                except Exception as e:
                    reviewer_error = str(e)
                finally:
                    await temp_client.close()
        else:
            # No separate reviewer — reviewer will use writer's config
            reviewer_ok = writer_ok

        overall_valid = writer_ok and (reviewer_ok or not has_reviewer)
        error = ""
        if not overall_valid:
            errors = [e for e in [writer_error, reviewer_error] if e]
            error = "; ".join(errors)

        return ConfigValidationResult(
            valid=overall_valid,
            writer_ok=writer_ok,
            reviewer_ok=reviewer_ok,
            error=error,
            writer_error=writer_error,
            reviewer_error=reviewer_error,
        )

    # ── Model Listing ───────────────────────────────────────────────────

    @router.get("/api/models")
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
        check_endpoint(effective_endpoint)

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

    @router.get("/api/reviewer/models")
    async def list_reviewer_models(
        endpoint_url: str | None = None,
        api_key: str | None = None,
    ):
        """
        List available models from the reviewer LLM provider.
        Accepts optional endpoint_url/api_key query params for setup wizard.
        """
        # No reviewer client configured and no endpoint param → uses writer's
        if server_config.reviewer_client is None and not endpoint_url:
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
        rc = server_config.reviewer_client
        if rc is None:
            return {"models": [], "current_model": "", "uses_writer": True}

        # If reviewer has no effective API key (and main client also has none),
        # use the query param key if provided, otherwise defer to writer
        if not rc.api_key:
            if api_key:
                url = _build_api_url(rc.endpoint_url, "models")
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
                try:
                    response = await ai_client._client.get(url, headers=headers)
                    response.raise_for_status()
                    models = _parse_models_response(response.json())
                    return {"models": models, "current_model": rc.model_name or "", "uses_writer": False}
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"Failed to fetch models: {str(e)}")
            # No key available — signal frontend to use writer endpoint instead
            return {"models": [], "current_model": "", "uses_writer": True}

        models = await rc.list_models()
        return {"models": models, "current_model": rc.model_name or "", "uses_writer": False}

    # ── Book Endpoints ──────────────────────────────────────────────────

    @router.post("/api/books/create")
    async def create_book(request: BookCreateRequest, background_tasks: BackgroundTasks):
        """
        Create a new book and start generation in the background.

        Returns the book_id immediately so the client can poll for progress.
        Generation is rate-limited by a semaphore to prevent resource exhaustion.
        """
        check_configured()

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
            async with await get_semaphore():
                await _run_generation_pipeline(book_id, orchestrator, save_book)

        task = asyncio.create_task(_semaphore_task())
        active_tasks[book_id] = task

        logger.info("Book '%s' (%s) queued for generation (max_review_turns=%d, skip_review=%s)",
                    request.title, book_id, request.review_max_turns, request.skip_review)
        return {"book_id": book_id, "status": "pending", "review_max_turns": request.review_max_turns, "skip_review": request.skip_review}

    @router.get("/api/books")
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

    @router.get("/api/books/{book_id}")
    async def get_book_status(book_id: str):
        """Get full book status and content."""
        book_state = load_book(book_id)
        if not book_state:
            raise HTTPException(status_code=404, detail="Book not found")
        return book_state.model_dump()

    @router.get("/api/books/{book_id}/validate")
    async def validate_book(book_id: str):
        """Validate book completeness."""
        book_state = load_book(book_id)
        if not book_state:
            raise HTTPException(status_code=404, detail="Book not found")
        return orchestrator.validate_book(book_state)

    @router.post("/api/books/{book_id}/review")
    async def trigger_review(book_id: str, background_tasks: BackgroundTasks):
        """
        Trigger an iterative professional review of a completed book.
        Runs critique → correct → re-critique until approved or max turns reached.

        The review runs in the background. Poll the book status to track progress.
        """
        check_configured()

        book_state = load_book(book_id)
        if not book_state:
            raise HTTPException(status_code=404, detail="Book not found")

        if book_state.status not in ("completed", "reviewing"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot review: book is in '{book_state.status}' status. Must be 'completed'.",
            )

        async def _run_review():
            async with await get_semaphore():
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
        active_tasks[book_id] = task

        return {"status": "review_started", "book_id": book_id, "max_turns": book_state.review_max_turns}

    @router.get("/api/books/{book_id}/export/{fmt}")
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

    # ── Retry Book ──────────────────────────────────────────────────────

    @router.post("/api/books/{book_id}/retry")
    async def retry_book_endpoint(book_id: str, background_tasks: BackgroundTasks):
        """Retry a failed book by creating a new one with the same parameters.

        Loads the failed book's fields, constructs a new BookCreateRequest,
        queues generation in the background, and deletes the old book.
        """
        check_configured()

        book_state = load_book(book_id)
        if not book_state:
            raise HTTPException(status_code=404, detail="Book not found")

        # Cancel any active generation task for this book
        task = active_tasks.pop(book_id, None)
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
            async with await get_semaphore():
                await _run_generation_pipeline(new_book_id, orchestrator, save_book)

        task = asyncio.create_task(_semaphore_task())
        active_tasks[new_book_id] = task

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

    # ── Delete Book ─────────────────────────────────────────────────────

    @router.delete("/api/books/{book_id}")
    async def delete_book_endpoint(book_id: str):
        """Delete a book and its data from storage."""
        book_state = load_book(book_id)
        if not book_state:
            raise HTTPException(status_code=404, detail="Book not found")

        # Cancel active task if the book is being generated
        task = active_tasks.pop(book_id, None)
        if task and not task.done():
            task.cancel()
            logger.info("Cancelled active generation task for book '%s' (%s)", book_state.title, book_id)

        # Delete the book file
        deleted = delete_book(book_id)
        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete book file")

        logger.info("Deleted book '%s' (%s)", book_state.title, book_id)
        return {"status": "deleted", "book_id": book_id}

    return router
