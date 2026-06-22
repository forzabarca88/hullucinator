"""
Hullucinator — AI-Powered E-Book Generator

FastAPI application bootstrap:
- Server configuration and singleton instances (AIClient, ReviewerClient, Orchestrator)
- Middleware setup (CORS, security headers, cache control)
- Static file serving for the web UI
- API router inclusion (endpoints defined in app/routes.py)
- CLI entry point
"""
import os
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from starlette.staticfiles import StaticFiles
from app.middleware import setup_middleware
from app.routes import create_router
from app.schemas import AIConfig
from app.ai_client import AIClient, ReviewerClient
from app.orchestrator import Orchestrator
from app.storage import load_config
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
_shared_config = get_default_shared_config()
MAX_CONCURRENT_GENERATIONS = int(os.environ.get("HULLUCINATOR_MAX_CONCURRENT", str(_shared_config.concurrency.max_concurrent_generations)))
_generation_semaphore: asyncio.Semaphore | None = None


async def _get_semaphore() -> asyncio.Semaphore:
    """Get or create the generation semaphore, lazily bound to current event loop."""
    global _generation_semaphore
    if _generation_semaphore is None:
        _generation_semaphore = asyncio.Semaphore(MAX_CONCURRENT_GENERATIONS)
    return _generation_semaphore


def _check_configured():
    """Raise 400 if AI is not configured (checks live client state).

    Requires endpoint URL, model name, and a non-empty API key.
    """
    if not ai_client.endpoint_url or not ai_client.model_name:
        server_config.configured = False
        raise HTTPException(
            status_code=400,
            detail="AI is not configured. Please set your endpoint URL, model, and API key in Settings first.",
        )
    if ai_client.api_key is None or ai_client.api_key == "":
        server_config.configured = False
        raise HTTPException(
            status_code=400,
            detail="API key is not set. Please configure your API key in Settings before queuing a book.",
        )
    server_config.configured = True


async def _check_configured_and_connected():
    """Raise 400 if AI is not configured or credentials are invalid.

    Performs the basic configured check, then sends a lightweight test
    request to the models endpoint to verify the API key works.
    Rejects book creation before queuing to avoid wasted background tasks.
    """
    _check_configured()

    try:
        models = await ai_client.list_models()
        if not models:
            raise HTTPException(
                status_code=400,
                detail="API key appears invalid — no models returned from the endpoint. Please check your API key in Settings.",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to verify API credentials: {e}. Please check your endpoint URL and API key in Settings.",
        )


def _check_endpoint(endpoint_url: str | None = None):
    """Raise 400 if no endpoint URL is set. Used for model listing during setup."""
    check_url = endpoint_url if endpoint_url is not None else ai_client.endpoint_url
    if not check_url:
        raise HTTPException(
            status_code=400,
            detail="Endpoint URL is required. Set it in Settings first.",
        )


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

# ── Middleware ────────────────────────────────────────────────────────────
# CORS, security headers, and cache control
setup_middleware(app)

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


# ── API Routes ────────────────────────────────────────────────────────────
# All endpoints defined in app/routes.py
app.include_router(
    create_router(
        ai_client=ai_client,
        reviewer_client=reviewer_client,
        orchestrator=orchestrator,
        server_config=server_config,
        static_dir=STATIC_DIR,
        active_tasks=_active_tasks,
        get_semaphore=_get_semaphore,
        check_configured=_check_configured,
        check_configured_and_connected=_check_configured_and_connected,
        check_endpoint=_check_endpoint,
    )
)


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
