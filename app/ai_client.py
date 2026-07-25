"""
HTTP client for OpenAI-compatible LLM API endpoints.

Key features:
- Reuses a single httpx.AsyncClient instead of creating one per request
- Uses async `await asyncio.sleep()` instead of blocking `time.sleep()`
- Configurable via environment variables
- Runtime-reconfigurable endpoint, model, and API key
- Model listing via OpenAI-compatible /v1/models endpoint
- Optional separate reviewer client for review/correction tasks
"""
import asyncio
import json
import os
import random
import logging
from typing import List, Dict, Optional, Any

import httpx

from app.logging import log_error_with_trace

from app.config import get_default_shared_config
from app.tools import execute_tool_call, parse_tool_calls, has_tool_calls

logger = logging.getLogger(__name__)

# ── Shared tool-calling helpers ───────────────────────────────────────────
# Extracted from AIClient/ReviewerClient to eliminate ~60 lines of duplication.


async def _execute_tool_calls_helper(
    tool_calls: List[Dict[str, Any]],
    log_prefix: str,
) -> List[Dict[str, Any]]:
    """
    Process each tool call and return results.

    Args:
        tool_calls: List of tool_call dicts from LLM response.
        log_prefix: Prefix for log messages (e.g. 'AIClient', 'ReviewerClient').

    Returns:
        List of result dicts with 'tool_call_id' and 'result' keys.
    """
    results = []
    for tc in tool_calls:
        result = await execute_tool_call(tc)
        results.append({
            "tool_call_id": tc.get("id"),
            "result": result,
        })
        logger.info(
            "%s tool '%s' executed (id=%s)",
            log_prefix,
            tc.get("function", {}).get("name", "unknown"),
            tc.get("id"),
        )
    return results


async def _generate_completion_with_tools_helper(
    generate_completion_fn,
    execute_tool_calls_fn,
    messages: List[Dict[str, str]],
    temperature: float,
    tools: List[Dict[str, Any]],
    max_retries: int,
    max_turns: int,
    model_override: Optional[str],
    log_prefix: str,
) -> Dict[str, Any]:
    """
    Send a completion request with tools and handle the full
    tool-calling loop: send → detect tool calls → execute → re-send.

    Args:
        generate_completion_fn: The client's generate_completion method.
        execute_tool_calls_fn: The client's execute_tool_calls method.
        messages: Initial chat messages
        temperature: Sampling temperature
        tools: List of tool definitions (OpenAI format)
        max_retries: Number of retry attempts per request
        max_turns: Maximum tool-call turns before forcing completion
        model_override: Optional model name to use instead of default
        log_prefix: Prefix for log messages

    Returns:
        Final response dict with text content (after all tool calls resolved).

    Raises:
        RuntimeError: If endpoint doesn't support tool calling or max turns exceeded.
    """
    working_messages = list(messages)

    for turn in range(max_turns):
        response = await generate_completion_fn(
            messages=working_messages,
            temperature=temperature,
            max_retries=max_retries,
            model_override=model_override,
            tools=tools,
        )

        tool_calls = parse_tool_calls(response)
        if not tool_calls:
            # No tool calls — we have the final response
            return response

        # Execute all tool calls and append results
        results = await execute_tool_calls_fn(tool_calls)

        # Append assistant message with tool calls to conversation
        assistant_msg = response.get("choices", [{}])[0].get("message", {})
        working_messages.append({
            "role": "assistant",
            "content": assistant_msg.get("content"),
            "tool_calls": tool_calls,
        })

        # Append tool results
        for result in results:
            working_messages.append({
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "content": result["result"],
            })

        logger.info("%s tool call turn %d/%d completed", log_prefix, turn + 1, max_turns)

    logger.error("%s tool calling exceeded max turns (%d)", log_prefix, max_turns)
    raise RuntimeError(f"Tool calling exceeded maximum turns ({max_turns})")

# Shared config for retry/timeout defaults
_client_config = get_default_shared_config().client
_gen_config = get_default_shared_config().generation


def _parse_models_response(result: dict) -> list:
    """Parse OpenAI-compatible /v1/models response into a sorted list of model dicts."""
    models = []
    if "data" in result:
        for item in result["data"]:
            models.append({
                "id": item.get("id", item.get("name", "")),
                "name": item.get("id", item.get("name", "")),
            })
    elif isinstance(result, list):
        for item in result:
            models.append({
                "id": item.get("id", item.get("name", "")),
                "name": item.get("id", item.get("name", "")),
            })
    elif "error" in result:
        logger.warning("Model listing returned error response: %s", result.get("error"))
    else:
        models = [{"id": k, "name": k} for k in result.keys() if isinstance(k, str)]
    models.sort(key=lambda m: m["id"])
    return models


def _build_api_url(endpoint: str, path_suffix: str) -> str:
    """Build the full API URL, handling /v1 suffix correctly.

    If endpoint already ends with /v1, append path_suffix directly.
    Otherwise, prepend /v1/ before path_suffix.
    """
    base = endpoint.rstrip('/')
    if base.endswith('/v1'):
        return f"{base}/{path_suffix}"
    return f"{base}/v1/{path_suffix}"


def _extract_content(result: Dict[str, Any]) -> str:
    """Extract text content from an LLM response, handling both string and list formats.

    Some providers (e.g. Mistral) return content as a list of text blocks:
    [{"type": "text", "text": "..."}, ...]

    Does NOT unwrap JSON-wrapped content — that's handled by the calling
    function which knows whether JSON wrapping is expected or not.
    """
    raw = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(raw, list):
        parts = [item.get("text", "") for item in raw if isinstance(item, dict)]
        return "\n".join(parts).strip()
    return str(raw).strip()


def _unwrap_json_content(text: str) -> str:
    """If text looks like JSON wrapping plain content, extract the inner text.

    Returns the original text if it's not valid JSON or doesn't contain
    a recognizable content wrapper.
    """
    # Try parsing as JSON
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text

    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return "\n".join(str(item) for item in data).strip()
    if isinstance(data, dict):
        # Check common keys for wrapped content
        for key in ("content", "text", "body", "response", "output"):
            if key in data:
                return str(data[key]).strip()
        # "chapters" key means the LLM returned JSON when asked for plain text
        if "chapters" in data and isinstance(data["chapters"], list):
            return "\n\n".join(str(c) for c in data["chapters"]).strip()
        # Last resort: serialize the whole dict back
        return json.dumps(data, indent=2)
    return text


async def _retry_request(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    headers: dict,
    max_retries: int,
    log_prefix: str,
    error_prefix: str,
    is_tool_call_request: bool = False,
) -> Dict[str, Any]:
    """
    Send a POST request with retry logic and jittered backoff.

    Retries on 429/500/503 status codes or empty responses.
    Uses async sleep to avoid blocking the event loop.

    When is_tool_call_request is True, empty content is not treated as
    a retry condition — tool-call responses legitimately have null content
    with tool_calls instead.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()

            # Check if content is empty and retry
            # Skip this check for tool-call requests (tool responses have no content)
            if not is_tool_call_request:
                content = _extract_content(result)
                if not content and attempt < max_retries:
                    base_wait = _client_config.empty_response_wait * (attempt + 1)
                    wait = base_wait * (_client_config.jitter_factor + random.random())
                    logger.warning("[%s] Empty response, retrying in %.1fs...", log_prefix, wait)
                    await asyncio.sleep(wait)
                    continue

            return result

        except httpx.HTTPStatusError as e:
            last_error = Exception(
                f"{error_prefix} request failed with status {e.response.status_code}: {e.response.text}"
            )
            if e.response.status_code in (429, 500, 503) and attempt < max_retries:
                base_wait = _client_config.retry_status_wait * (attempt + 1)
                wait = base_wait * (_client_config.jitter_factor + random.random())
                logger.warning("[%s] Status %d, retrying in %.1fs...", log_prefix, e.response.status_code, wait)
                await asyncio.sleep(wait)
                continue
            raise last_error

        except Exception as e:
            last_error = Exception(f"{error_prefix} error: {str(e)}")
            if attempt < max_retries:
                base_wait = _client_config.retry_base_wait * (attempt + 1)
                wait = base_wait * (_client_config.jitter_factor + random.random())
                logger.warning("[%s] Error, retrying in %.1fs...", log_prefix, wait)
                await asyncio.sleep(wait)
                continue
            log_error_with_trace("[%s] Final attempt failed: %s", log_prefix, last_error, exc=last_error, logger_obj=logger)
            raise last_error

    final_error = last_error or Exception(f"{log_prefix} max retries exceeded")
    log_error_with_trace("[%s] Max retries exceeded: %s", log_prefix, final_error, exc=final_error, logger_obj=logger)
    raise final_error


class AIClient:
    def __init__(self, endpoint_url: str, model_name: str, api_key: Optional[str] = None):
        self._endpoint_url = endpoint_url.rstrip('/')
        self._model_name = model_name
        self._api_key = api_key
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        # Single persistent async client reused across all requests
        # (L1) Configurable timeout via AI_TIMEOUT env var (override) or shared config
        timeout_secs = float(os.environ.get("AI_TIMEOUT", str(_client_config.http_timeout)))
        self._client = httpx.AsyncClient(timeout=timeout_secs)

    # ── Mutable configuration properties ──────────────────────────────

    @property
    def endpoint_url(self) -> str:
        return self._endpoint_url

    @endpoint_url.setter
    def endpoint_url(self, value: str):
        self._endpoint_url = value.rstrip('/')
        logger.info("AI endpoint URL changed to: %s", self._endpoint_url)

    @property
    def model_name(self) -> str:
        return self._model_name

    @model_name.setter
    def model_name(self, value: str):
        self._model_name = value
        logger.info("AI model changed to: %s", self._model_name)

    @property
    def api_key(self) -> Optional[str]:
        return self._api_key

    @api_key.setter
    def api_key(self, value: Optional[str]):
        self._api_key = value
        if value:
            self._headers["Authorization"] = f"Bearer {value}"
        elif "Authorization" in self._headers:
            del self._headers["Authorization"]
        logger.info("AI API key updated")

    def get_config(self) -> Dict[str, Any]:
        """Return current AI configuration."""
        return {
            "endpoint_url": self._endpoint_url,
            "model_name": self._model_name,
            "api_key_set": self._api_key is not None and self._api_key != "",
        }

    async def update_config(self, endpoint_url: Optional[str] = None,
                            model_name: Optional[str] = None,
                            api_key: Optional[str] = None):
        """Update AI configuration at runtime."""
        if endpoint_url is not None:
            self.endpoint_url = endpoint_url
        if model_name is not None:
            self.model_name = model_name
        if api_key is not None:
            self.api_key = api_key

    async def list_models(self) -> List[Dict[str, Any]]:
        """
        Fetch the list of available models from the LLM API.
        Uses the OpenAI-compatible /v1/models endpoint.
        """
        url = _build_api_url(self._endpoint_url, "models")
        try:
            response = await self._client.get(url, headers=self._headers)
            response.raise_for_status()
            result = response.json()

            models = _parse_models_response(result)

            logger.info("Fetched %d models from %s", len(models), self._endpoint_url)
            return models

        except httpx.HTTPStatusError as e:
            logger.warning("Model listing failed (HTTP %d): %s", e.response.status_code, e.response.text)
            return []
        except Exception as e:
            log_error_with_trace("Model listing failed: %s", e, exc=e, logger_obj=logger)
            return []

    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = _gen_config.summary_temperature,
        max_retries: int = _client_config.max_retries,
        model_override: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Send a completion request to the LLM API with retry logic.

        Retries on 429/500/503 status codes or empty responses.
        Uses async sleep to avoid blocking the event loop.

        When tools are provided, the response may contain tool_calls
        instead of text content. Returns the raw response in that case.

        Args:
            messages: Chat messages
            temperature: Sampling temperature
            max_retries: Number of retry attempts
            model_override: Optional model name to use instead of self._model_name
            tools: Optional list of tool definitions (OpenAI format)
        """
        # Handle /v1 suffix
        url = _build_api_url(self._endpoint_url, "chat/completions")
        payload: Dict[str, Any] = {
            "model": model_override or self._model_name,
            "messages": messages,
            "temperature": temperature,
        }

        if tools:
            payload["tools"] = tools

        is_tool_call_request = tools is not None

        return await _retry_request(
            self._client, url, payload, self._headers, max_retries,
            "AIClient", "API",
            is_tool_call_request=is_tool_call_request,
        )

    async def execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Process each tool call and return results."""
        return await _execute_tool_calls_helper(tool_calls, "AIClient")

    async def generate_completion_with_tools(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        tools: List[Dict[str, Any]],
        max_retries: int = _client_config.max_retries,
        max_turns: int = 5,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a completion request with tools and handle the full
        tool-calling loop: send → detect tool calls → execute → re-send.

        Args:
            messages: Initial chat messages
            temperature: Sampling temperature
            tools: List of tool definitions (OpenAI format)
            max_retries: Number of retry attempts per request
            max_turns: Maximum tool-call turns before forcing completion
            model_override: Optional model name to use instead of self._model_name

        Returns:
            Final response dict with text content (after all tool calls resolved).

        Raises:
            RuntimeError: If endpoint doesn't support tool calling or max turns exceeded.
        """
        return await _generate_completion_with_tools_helper(
            self.generate_completion,
            self.execute_tool_calls,
            messages,
            temperature,
            tools,
            max_retries,
            max_turns,
            model_override,
            "AIClient",
        )

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.aclose()


class ReviewerClient:
    """
    A dedicated client for review/correction tasks. Can use a different
    endpoint, model, and API key than the main AIClient while sharing
    the same HTTP connection.
    """

    def __init__(self, main_client: AIClient,
                 endpoint_url: Optional[str] = None,
                 model_name: Optional[str] = None,
                 api_key: Optional[str] = None):
        """
        Args:
            main_client: The primary AIClient (for shared HTTP connection)
            endpoint_url: Override endpoint (uses main_client's if None)
            model_name: Override model (uses main_client's if None)
            api_key: Override API key (uses main_client's if None)
        """
        self._main = main_client
        self._endpoint_url = (endpoint_url or main_client.endpoint_url).rstrip('/')
        self._model_name = model_name or main_client.model_name
        self._api_key = api_key  # None means use main client's key

    @property
    def endpoint_url(self) -> str:
        """Return effective endpoint URL. Falls back to main client if empty."""
        if self._endpoint_url:
            return self._endpoint_url
        return self._main.endpoint_url

    @endpoint_url.setter
    def endpoint_url(self, value: str):
        self._endpoint_url = value.rstrip('/')
        logger.info("Reviewer endpoint URL changed to: %s", self._endpoint_url)

    @property
    def model_name(self) -> str:
        """Return effective model name. Falls back to main client if empty."""
        if self._model_name:
            return self._model_name
        return self._main.model_name

    @model_name.setter
    def model_name(self, value: str):
        self._model_name = value
        logger.info("Reviewer model changed to: %s", self._model_name)

    @property
    def api_key(self) -> Optional[str]:
        """Return effective API key. Falls back to main client if empty."""
        if self._api_key:
            return self._api_key
        return self._main.api_key

    @api_key.setter
    def api_key(self, value: Optional[str]):
        self._api_key = value
        logger.info("Reviewer API key updated")

    @property
    def _headers(self) -> dict:
        """Compute headers dynamically, falling back to main client's API key.

        Using a property ensures headers always reflect the current state of
        both the reviewer and main client, even when the main client's API key
        changes independently.
        """
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        elif self._main.api_key:
            headers["Authorization"] = f"Bearer {self._main.api_key}"
        return headers

    def get_config(self) -> Dict[str, Any]:
        """Return reviewer configuration (effective values with fallback)."""
        return {
            "endpoint_url": self.endpoint_url,
            "model_name": self.model_name,
            "api_key_set": self.api_key is not None and self.api_key != "",
        }

    async def update_config(self, endpoint_url: Optional[str] = None,
                            model_name: Optional[str] = None,
                            api_key: Optional[str] = None):
        """Update reviewer configuration at runtime."""
        if endpoint_url is not None:
            self.endpoint_url = endpoint_url
        if model_name is not None:
            self.model_name = model_name
        if api_key is not None:
            # Normalize empty string to None so getter falls back to main client
            self.api_key = api_key if api_key != "" else None

    async def list_models(self) -> List[Dict[str, Any]]:
        """
        Fetch the list of available models from the reviewer's LLM API.
        Uses the reviewer's endpoint URL and API key with the shared HTTP connection.
        """
        url = _build_api_url(self.endpoint_url, "models")
        try:
            response = await self._main._client.get(url, headers=self._headers)
            response.raise_for_status()
            result = response.json()

            models = _parse_models_response(result)

            logger.info("Fetched %d reviewer models from %s", len(models), self.endpoint_url)
            return models

        except httpx.HTTPStatusError as e:
            logger.warning("Reviewer model listing failed (HTTP %d): %s", e.response.status_code, e.response.text)
            return []
        except Exception as e:
            log_error_with_trace("Reviewer model listing failed: %s", e, exc=e, logger_obj=logger)
            return []

    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = _gen_config.summary_temperature,
        max_retries: int = _client_config.max_retries,
        model_override: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Send a completion request using the reviewer's endpoint/model
        but sharing the main client's HTTP connection and auth headers.

        When tools are provided, the response may contain tool_calls
        instead of text content. Returns the raw response in that case.

        (M3 fix: added model_override parameter for consistency with AIClient)
        (F2 fix: use effective endpoint/model via property getters for fallback)
        (T7: added tools parameter for tool calling support)

        Args:
            messages: Chat messages
            temperature: Sampling temperature
            max_retries: Number of retry attempts
            model_override: Optional model name to use instead of effective model
            tools: Optional list of tool definitions (OpenAI format)
        """
        # Handle /v1 suffix (use effective endpoint via property)
        url = _build_api_url(self.endpoint_url, "chat/completions")
        payload: Dict[str, Any] = {
            "model": model_override or self.model_name,
            "messages": messages,
            "temperature": temperature,
        }

        if tools:
            payload["tools"] = tools

        is_tool_call_request = tools is not None

        return await _retry_request(
            self._main._client, url, payload, self._headers, max_retries,
            "ReviewerClient", "Reviewer API",
            is_tool_call_request=is_tool_call_request,
        )

    async def execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Process each tool call and return results."""
        return await _execute_tool_calls_helper(tool_calls, "ReviewerClient")

    async def generate_completion_with_tools(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        tools: List[Dict[str, Any]],
        max_retries: int = _client_config.max_retries,
        max_turns: int = 5,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a completion request with tools and handle the full
        tool-calling loop: send → detect tool calls → execute → re-send.

        Args:
            messages: Initial chat messages
            temperature: Sampling temperature
            tools: List of tool definitions (OpenAI format)
            max_retries: Number of retry attempts per request
            max_turns: Maximum tool-call turns before forcing completion
            model_override: Optional model name to use instead of effective model

        Returns:
            Final response dict with text content (after all tool calls resolved).

        Raises:
            RuntimeError: If endpoint doesn't support tool calling or max turns exceeded.
        """
        return await _generate_completion_with_tools_helper(
            self.generate_completion,
            self.execute_tool_calls,
            messages,
            temperature,
            tools,
            max_retries,
            max_turns,
            model_override,
            "ReviewerClient",
        )
