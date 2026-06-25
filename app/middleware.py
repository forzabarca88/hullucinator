"""
Middleware definitions for Hullucinator.

Provides:
- CORS middleware for cross-origin access
- Security headers (CSP, X-Frame-Options, etc.)
- Cache control for static assets
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi.middleware.cors import CORSMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add Content Security Policy and other security headers."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' https:; "
            "script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self';"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Embedder-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


def add_cors_middleware(app):
    """Add CORS middleware to the FastAPI app."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )


def add_security_headers(app):
    """Add security headers middleware to the FastAPI app."""
    app.add_middleware(SecurityHeadersMiddleware)


async def no_cache_static(request: Request, call_next):
    """Disable browser caching for static assets so UI updates take effect immediately."""
    if request.url.path.startswith("/static/"):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return await call_next(request)


def setup_middleware(app):
    """Register all middleware on the FastAPI app."""
    add_cors_middleware(app)
    add_security_headers(app)
    app.middleware("http")(no_cache_static)
