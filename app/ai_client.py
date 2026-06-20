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
import os
import random
import logging
from typing import List, Dict, Optional, Any

import httpx

from app.config import get_default_shared_config

logger = logging.getLogger(__name__)

# Shared config for retry/timeout defaults
_client_config = get_default_shared_config().client


def _parse_models_response(result: dict) -> list:
    """Parse OpenAI-compatible /v1/models response into a list of model dicts."""
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
    """
    raw = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(raw, list):
        parts = [item.get("text", "") for item in raw if isinstance(item, dict)]
        return "\n".join(parts).strip()
    return str(raw).strip()


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
            logger.warning("Model listing failed: %s", e)
            return []

    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_retries: int = _client_config.max_retries,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a completion request to the LLM API with retry logic.

        Retries on 429/500/503 status codes or empty responses.
        Uses async sleep to avoid blocking the event loop.

        Args:
            messages: Chat messages
            temperature: Sampling temperature
            max_retries: Number of retry attempts
            model_override: Optional model name to use instead of self._model_name
        """
        # Handle /v1 suffix
        url = _build_api_url(self._endpoint_url, "chat/completions")
        payload = {
            "model": model_override or self._model_name,
            "messages": messages,
            "temperature": temperature,
        }

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self._client.post(url, json=payload, headers=self._headers)
                response.raise_for_status()
                result = response.json()

                # Check if content is empty and retry
                content = _extract_content(result)
                if not content and attempt < max_retries:
                    # (L2) Jitter: randomize wait time to prevent thunder-herd retries
                    base_wait = _client_config.empty_response_wait * (attempt + 1)
                    wait = base_wait * (_client_config.jitter_factor + random.random())
                    logger.warning("[AIClient] Empty response, retrying in %.1fs...", wait)
                    await asyncio.sleep(wait)
                    continue

                return result

            except httpx.HTTPStatusError as e:
                last_error = Exception(
                    f"API request failed with status {e.response.status_code}: {e.response.text}"
                )
                if e.response.status_code in (429, 500, 503) and attempt < max_retries:
                    # (L2) Jitter for status code retries
                    base_wait = _client_config.retry_status_wait * (attempt + 1)
                    wait = base_wait * (_client_config.jitter_factor + random.random())
                    logger.warning("[AIClient] Status %d, retrying in %.1fs...", e.response.status_code, wait)
                    await asyncio.sleep(wait)
                    continue
                raise last_error

            except Exception as e:
                last_error = Exception(f"An error occurred: {str(e)}")
                if attempt < max_retries:
                    # (L2) Jitter for general error retries
                    base_wait = _client_config.retry_base_wait * (attempt + 1)
                    wait = base_wait * (_client_config.jitter_factor + random.random())
                    logger.warning("[AIClient] Error, retrying in %.1fs...", wait)
                    await asyncio.sleep(wait)
                    continue
                raise last_error

        raise last_error or Exception("Max retries exceeded")

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
        self._headers = {"Content-Type": "application/json"}
        if self._api_key:
            self._headers["Authorization"] = f"Bearer {self._api_key}"
        elif main_client.api_key:
            self._headers["Authorization"] = f"Bearer {main_client.api_key}"

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
        self._rebuild_headers()
        logger.info("Reviewer API key updated")

    def _rebuild_headers(self):
        """Rebuild the Authorization header based on current key config."""
        self._headers = {"Content-Type": "application/json"}
        if self._api_key:
            self._headers["Authorization"] = f"Bearer {self._api_key}"
        elif self._main.api_key:
            self._headers["Authorization"] = f"Bearer {self._main.api_key}"

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
            self.api_key = api_key

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
            logger.warning("Reviewer model listing failed: %s", e)
            return []

    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_retries: int = _client_config.max_retries,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a completion request using the reviewer's endpoint/model
        but sharing the main client's HTTP connection and auth headers.

        (M3 fix: added model_override parameter for consistency with AIClient)
        (F2 fix: use effective endpoint/model via property getters for fallback)
        """
        # Handle /v1 suffix (use effective endpoint via property)
        url = _build_api_url(self.endpoint_url, "chat/completions")
        payload = {
            "model": model_override or self.model_name,
            "messages": messages,
            "temperature": temperature,
        }

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self._main._client.post(url, json=payload, headers=self._headers)
                response.raise_for_status()
                result = response.json()

                content = _extract_content(result)
                if not content and attempt < max_retries:
                    # (L2) Jitter for empty response retries
                    base_wait = _client_config.empty_response_wait * (attempt + 1)
                    wait = base_wait * (_client_config.jitter_factor + random.random())
                    logger.warning("[ReviewerClient] Empty response, retrying in %.1fs...", wait)
                    await asyncio.sleep(wait)
                    continue

                return result

            except httpx.HTTPStatusError as e:
                last_error = Exception(
                    f"Reviewer API request failed with status {e.response.status_code}: {e.response.text}"
                )
                if e.response.status_code in (429, 500, 503) and attempt < max_retries:
                    # (L2) Jitter for status code retries
                    base_wait = _client_config.retry_status_wait * (attempt + 1)
                    wait = base_wait * (_client_config.jitter_factor + random.random())
                    logger.warning("[ReviewerClient] Status %d, retrying in %.1fs...", e.response.status_code, wait)
                    await asyncio.sleep(wait)
                    continue
                raise last_error

            except Exception as e:
                last_error = Exception(f"Reviewer error: {str(e)}")
                if attempt < max_retries:
                    # (L2) Jitter for general error retries
                    base_wait = _client_config.retry_base_wait * (attempt + 1)
                    wait = base_wait * (_client_config.jitter_factor + random.random())
                    logger.warning("[ReviewerClient] Error, retrying in %.1fs...", wait)
                    await asyncio.sleep(wait)
                    continue
                raise last_error

        raise last_error or Exception("Reviewer max retries exceeded")
