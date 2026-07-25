"""
Tool definitions and implementations for LLM tool calling.

Provides tool specifications in OpenAI tool-calling format and
implementations for each tool. Tools let the LLM fetch external
information during generation or review.

Uses a persistent httpx.AsyncClient at module level to avoid creating
a new connection per tool call. Timeout is configurable via shared config.
"""
import json
import logging
from typing import Any, Dict, List

import httpx

from app.config import get_default_shared_config

logger = logging.getLogger(__name__)

# Shared config for tool call timeout
_tool_config = get_default_shared_config().client

# Persistent HTTP client for tool calls (Wikipedia, DuckDuckGo, etc.)
# Reused across all tool executions to avoid connection overhead.
_tool_client: httpx.AsyncClient = httpx.AsyncClient(
    timeout=float(_tool_config.http_timeout)
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

# ── Tool definitions (OpenAI tool-calling format) ──────────────────

WIKIPEDIA_SEARCH: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "wikipedia_search",
        "description": (
            "Search Wikipedia for a topic and return a concise summary. "
            "Use this to verify facts, get background information, or "
            "research real-world references for the book."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query or topic to look up on Wikipedia.",
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
            "the needed information or for more recent topics."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up on the web.",
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

async def wikipedia_search(query: str) -> str:
    """
    Search Wikipedia for a topic and return a summary.

    Uses the Wikipedia REST API v1 which returns structured summary data.
    Falls back to the search endpoint if direct title lookup fails.
    """
    client = get_tool_client()
    # Try direct title lookup first
    title = query.strip()
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        return _format_wikipedia_result(data)
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            logger.warning("Wikipedia direct lookup failed: %s", e)
            return f"Error searching Wikipedia for '{query}': {e.response.text}"
    except Exception as e:
        logger.warning("Wikipedia direct lookup error: %s", e)

    # Fallback: use search endpoint to find the right page
    search_url = "https://en.wikipedia.org/w/api.php"
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
    }
    try:
        response = await client.get(search_url, params=search_params)
        response.raise_for_status()
        data = response.json()
        results = data.get("query", {}).get("search", [])
        if not results:
            return f"No Wikipedia results found for '{query}'."

        # Use the top result's pageid to get summary
        top_result = results[0]
        page_id = top_result["pageid"]
        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/{page_id}/summary"
        summary_response = await client.get(summary_url)
        summary_response.raise_for_status()
        summary_data = summary_response.json()
        return _format_wikipedia_result(summary_data)
    except Exception as e:
        logger.warning("Wikipedia search fallback failed: %s", e)
        return f"Error searching Wikipedia for '{query}': {str(e)}"


def _format_wikipedia_result(data: Dict[str, Any]) -> str:
    """Format a Wikipedia REST API summary response into readable text."""
    title = data.get("title", "Unknown")
    description = data.get("description", "")
    extract = data.get("extract", "")

    parts = [f"Wikipedia: {title}"]
    if description:
        parts.append(f"{description}")
    if extract:
        parts.append(f"{extract}")

    return "\n".join(parts)


async def web_search(query: str) -> str:
    """
    Perform a web search using DuckDuckGo Instant Answer API.

    Returns the abstract/answer if available, or relevant results.
    """
    client = get_tool_client()
    url = "https://api.duckduckgo.com/"
    params = {
        "q": query,
        "format": "json",
    }
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        result_parts = []

        # Instant answer (abstract)
        abstract = data.get("Abstract", "")
        abstract_url = data.get("AbstractURL", "")
        if abstract:
            result_parts.append(f"Answer: {abstract}")
            if abstract_url:
                result_parts.append(f"Source: {abstract_url}")

        # Related topics
        related_topics = data.get("RelatedTopics", [])
        if related_topics and not abstract:
            for topic in related_topics[:5]:
                text = topic.get("Text", "")
                if text:
                    result_parts.append(text)

        if not result_parts:
            return f"No results found for web search '{query}'."

        return "\n\n".join(result_parts)

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
