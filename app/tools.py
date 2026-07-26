"""
Tool definitions and implementations for LLM tool calling.

Provides tool specifications in OpenAI tool-calling format and
implementations for each tool. Tools let the LLM fetch external
information during generation or review.

Wikipedia search uses a persistent httpx.AsyncClient at module level
to avoid creating a new connection per call. Timeout is configurable
via shared config. Web search uses the ddgs package (DuckDuckGo HTML
search) which manages its own connections.
"""
import asyncio
import json
import logging
import random
import re
from typing import Any, Callable, Dict, List, TypeVar

import httpx
from ddgs import DDGS

from app.config import get_default_shared_config

logger = logging.getLogger(__name__)

# Shared config
_shared_config = get_default_shared_config()
_tool_config = _shared_config.tools
_client_config = _shared_config.client

# Retry settings from tool config
_TOOL_MAX_RETRIES = _tool_config.max_retries
_TOOL_RETRY_DELAY = _tool_config.retry_delay
_CLIENT_JITTER = _client_config.jitter_factor

# Persistent HTTP client for Wikipedia search.
# Reused across all Wikipedia tool executions to avoid connection overhead.
# User-Agent header is required by the Wikipedia API.
_tool_client: httpx.AsyncClient = httpx.AsyncClient(
    timeout=float(_client_config.http_timeout),
    headers={"User-Agent": "Hullucinator/1.0 (ebook generator)"},
)


def close_tool_client() -> None:
    """Close the persistent tool call HTTP client.

    Call this during application shutdown to release resources.
    Uses sync close when no running event loop (typical during shutdown),
    async close when a loop is actively running.
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        # Event loop is running — schedule async close
        loop.create_task(_tool_client.aclose())
    else:
        # No running event loop (e.g., during shutdown) — use sync close
        if hasattr(_tool_client, 'close'):
            _tool_client.close()


def get_tool_client() -> httpx.AsyncClient:
    """Return the persistent tool call HTTP client."""
    return _tool_client


T = TypeVar("T")

# Errors that indicate transient failures worth retrying.
# Includes both httpx errors (Wikipedia) and standard library errors (ddgs web search).
# OSError is intentionally excluded — while ConnectionError and TimeoutError are
# subclasses of OSError, bare OSError is too broad (catches file-not-found, permission
# denied, etc.) and would cause non-transient errors to be retried unnecessarily.
_RETRYABLE_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
    ConnectionError,
    TimeoutError,
)

# HTTP status codes that indicate transient server errors
_RETRYABLE_STATUS = (500, 502, 503, 504)


def _is_retryable_error(exc: Exception) -> bool:
    """Check if an exception represents a transient failure worth retrying."""
    if isinstance(exc, _RETRYABLE_ERRORS):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


def _compute_delay(attempt: int) -> float:
    """Compute retry delay with exponential backoff and jitter."""
    base = _TOOL_RETRY_DELAY * (2 ** (attempt - 1))
    jitter = random.uniform(0, base * _CLIENT_JITTER)
    return base + jitter


async def _with_retry(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """
    Execute an async function with retries on transient failures.

    Retries up to _TOOL_MAX_RETRIES times with exponential backoff and jitter.
    Only retries on transient errors (connection failures, timeouts, 5xx).
    Does NOT retry on 4xx errors (except 429), or non-error responses like
    'No results found'.
    """
    last_exc = None
    for attempt in range(1, _TOOL_MAX_RETRIES + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_error(exc):
                # Not a transient error — give up immediately
                raise
            if attempt < _TOOL_MAX_RETRIES:
                delay = _compute_delay(attempt)
                logger.warning(
                    "Tool retry %d/%d for %s after %s: delaying %.1fs",
                    attempt, _TOOL_MAX_RETRIES,
                    fn.__name__, exc, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Tool %s failed after %d attempts: %s",
                    fn.__name__, _TOOL_MAX_RETRIES, exc,
                )
                raise


# ── Tool definitions (OpenAI tool-calling format) ──────────────────

WIKIPEDIA_SEARCH: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "wikipedia_search",
        "description": (
            "Search Wikipedia for a topic and return a concise summary. "
            "Use this to verify facts, get background information, or "
            "research real-world references for the book. "
            "Query tips: use specific topic names or proper nouns (e.g., ""quantum mechanics"", ""Marie Curie""). "
            "Avoid overly broad terms like ""science"" — narrow to the specific subject. "
            "For people, use full names. For events, include the year or date. "
            "For technical topics, use the standard terminology."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The specific topic, person, event, or concept to look up on Wikipedia.",
                },
            },
            "required": ["query"],
        },
    },
}

WEB_SEARCH: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Perform a general web search to find current information, "
            "facts, or references. Use this when Wikipedia doesn't have "
            "the needed information or for more recent topics. "
            "Query tips: use specific, focused keywords. Include proper nouns, dates, and names. "
            "Avoid vague or overly broad terms. Use quotes for exact phrases when needed. "
            "Break complex topics into multiple focused searches rather than one broad query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The specific search query to look up on the web.",
                },
            },
            "required": ["query"],
        },
    },
}

# Registry of all available tools
_TOOLS: List[Dict[str, Any]] = [WIKIPEDIA_SEARCH, WEB_SEARCH]


def get_available_tools() -> List[Dict[str, Any]]:
    """Return the list of available tool definitions."""
    return list(_TOOLS)


# ── Tool implementations ───────────────────────────────────────────

async def _wikipedia_search_impl(query: str) -> str:
    """
    Search Wikipedia for a topic and return a summary.

    Uses the MediaWiki search endpoint to find the correct page title,
    then fetches the summary via REST API v1 using that title. Falls back
    to action=query with prop=extracts if the REST summary endpoint returns
    404 (happens for some newer pages that lack REST summary data).

    Raises transient errors (connection, timeout, 5xx) so the retry wrapper
    can handle them. Returns formatted strings for non-transient outcomes.
    """
    client = get_tool_client()

    # Step 1: Search to find the correct page title
    search_url = "https://en.wikipedia.org/w/api.php"
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
    }
    response = await client.get(search_url, params=search_params)
    response.raise_for_status()
    data = response.json()
    results = data.get("query", {}).get("search", [])
    if not results:
        return f"No Wikipedia results found for '{query}'."

    top_result = results[0]
    title = top_result["title"]
    page_id = top_result["pageid"]

    # Step 2: Try REST API summary by title (most reliable for plain text)
    wiki_title = title.replace(" ", "_")
    summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_title}"
    summary_response = await client.get(summary_url)
    if summary_response.status_code == 200:
        summary_data = summary_response.json()
        return _format_wikipedia_result(summary_data)

    # Step 3: Fallback — REST summary by pageid
    summary_url2 = f"https://en.wikipedia.org/api/rest_v1/page/{page_id}/summary"
    summary_response2 = await client.get(summary_url2)
    if summary_response2.status_code == 200:
        summary_data = summary_response2.json()
        return _format_wikipedia_result(summary_data)

    # Step 4: Final fallback — action=query with prop=extracts (returns HTML)
    extract_url = "https://en.wikipedia.org/w/api.php"
    extract_params = {
        "action": "query",
        "pageids": page_id,
        "prop": "extracts",
        "exlimit": 1,
        "format": "json",
    }
    extract_response = await client.get(extract_url, params=extract_params)
    extract_response.raise_for_status()
    extract_data = extract_response.json()
    page = list(extract_data.get("query", {}).get("pages", {}).values())[0]
    raw_extract = page.get("extract", "")
    clean_extract = _strip_html(raw_extract)
    return f"Wikipedia: {title}\n\n{clean_extract}"


def _format_wikipedia_result(data: Dict[str, Any]) -> str:
    """Format a Wikipedia REST API summary response into readable text."""
    title = data.get("title", "Unknown")
    description = data.get("description", "")
    extract = data.get("extract", "")

    parts = [f"Wikipedia: {title}"]
    if description:
        parts.append(description)
    if extract:
        parts.append(extract)

    return "\n".join(parts)


def _strip_html(html: str) -> str:
    """Strip HTML tags from a string, preserving paragraph breaks."""
    # Replace <p> tags with newlines
    text = re.sub(r"<p[^>]*>", "\n", html)
    text = re.sub(r"</p>", "\n", text)
    # Remove all other tags
    text = re.sub(r"<[^>]+>", "", text)
    # Clean up multiple blank lines
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


async def _web_search_impl(query: str) -> str:
    """
    Perform a web search using the ddgs package (DuckDuckGo HTML search).

    Returns formatted results with title, snippet, and URL for each hit.
    Runs the synchronous DDGS client in a thread to avoid blocking the event loop.
    Raises transient errors so the retry wrapper can handle them.
    """
    def _search_sync() -> str:
        with DDGS() as search:
            results = search.text(query, max_results=10)

        if not results:
            return f"No results found for web search '{query}'."

        parts = []
        for r in results:
            title = r.get("title", "Unknown")
            snippet = r.get("body", "")
            link = r.get("href", "")
            parts.append(f"Title: {title}\nSnippet: {snippet}\nURL: {link}")

        return "\n\n".join(parts)

    return await asyncio.to_thread(_search_sync)


# ── Public tool functions (wrapped with retry) ─────────────────────

async def wikipedia_search(query: str) -> str:
    """
    Search Wikipedia for a topic and return a summary.

    Retries on transient failures (connection errors, timeouts, 5xx).
    """
    try:
        return await _with_retry(_wikipedia_search_impl, query)
    except Exception as e:
        logger.warning("Wikipedia search failed: %s", e)
        return f"Error searching Wikipedia for '{query}': {str(e)}"


async def web_search(query: str) -> str:
    """
    Perform a web search using DuckDuckGo.

    Retries on transient failures (connection errors, timeouts, 5xx).
    """
    try:
        return await _with_retry(_web_search_impl, query)
    except Exception as e:
        logger.warning("Web search failed: %s", e)
        return f"Error performing web search for '{query}': {str(e)}"


# ── Dispatcher and parser ──────────────────────────────────────────

# Known tool names (used for validation, not for dispatching)
_KNOWN_TOOLS = {"wikipedia_search", "web_search"}


async def execute_tool_call(tool_call: Dict[str, Any]) -> str:
    """
    Execute a single tool call and return the result as a string.

    Args:
        tool_call: Dictionary with 'id', 'type', and 'function' keys
                   matching OpenAI tool_call format.

    Returns:
        The tool's output as a string.
    """
    func_data = tool_call.get("function", {})
    name = func_data.get("name", "")
    arguments = func_data.get("arguments", "{}")

    if name not in _KNOWN_TOOLS:
        logger.warning("Unknown tool called: %s", name)
        return f"Error: unknown tool '{name}'"

    # Resolve implementation dynamically so patches in tests work
    import importlib
    mod = importlib.import_module("app.tools")
    impl = getattr(mod, name, None)

    if impl is None:
        logger.error("Tool implementation not found: %s", name)
        return f"Error: tool '{name}' not found"

    # Parse arguments
    try:
        kwargs = json.loads(arguments)
    except json.JSONDecodeError as e:
        logger.warning("Invalid tool arguments for %s: %s", name, e)
        return f"Error: invalid arguments for '{name}'"

    # Execute
    try:
        result = await impl(**kwargs)
        return str(result)
    except Exception as e:
        logger.error("Tool execution failed for %s: %s", name, e)
        return f"Error executing '{name}': {str(e)}"


def parse_tool_calls(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract tool_call entries from an LLM response.

    Returns an empty list if the response has no tool calls.
    """
    message = response.get("choices", [{}])[0].get("message", {})
    tool_calls = message.get("tool_calls")

    if tool_calls and isinstance(tool_calls, list):
        return tool_calls
    return []


def has_tool_calls(response: Dict[str, Any]) -> bool:
    """Check if an LLM response contains tool calls."""
    message = response.get("choices", [{}])[0].get("message", {})
    tool_calls = message.get("tool_calls")
    return bool(tool_calls)
