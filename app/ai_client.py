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
import logging
from typing import List, Dict, Optional, Any

import httpx

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self, endpoint_url: str, model_name: str, api_key: Optional[str] = None):
        self._endpoint_url = endpoint_url.rstrip('/')
        self._model_name = model_name
        self._api_key = api_key
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        # Single persistent async client reused across all requests
        self._client = httpx.AsyncClient(timeout=1800.0)

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
        # Handle /v1 suffix: if endpoint already ends in /v1, don't double-append
        url = f"{self._endpoint_url}/models" if self._endpoint_url.endswith('/v1') else f"{self._endpoint_url}/v1/models"
        try:
            response = await self._client.get(url, headers=self._headers)
            response.raise_for_status()
            result = response.json()

            # Handle both OpenAI-style and generic responses
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
                # Provider returned an error JSON on 200 OK — treat as empty
                logger.warning("Model listing returned error response: %s", result.get("error"))
                return []
            else:
                # Try to extract model info from a dict response
                models = [{"id": k, "name": k} for k in result.keys() if isinstance(k, str)]

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
        max_retries: int = 2,
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
        url = f"{self._endpoint_url}/chat/completions" if self._endpoint_url.endswith('/v1') else f"{self._endpoint_url}/v1/chat/completions"
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
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if not content and attempt < max_retries:
                    wait = 10 * (attempt + 1)
                    logger.warning("[AIClient] Empty response, retrying in %ds...", wait)
                    await asyncio.sleep(wait)
                    continue

                return result

            except httpx.HTTPStatusError as e:
                last_error = Exception(
                    f"API request failed with status {e.response.status_code}: {e.response.text}"
                )
                if e.response.status_code in (429, 500, 503) and attempt < max_retries:
                    wait = 15 * (attempt + 1)
                    logger.warning("[AIClient] Status %d, retrying in %ds...", e.response.status_code, wait)
                    await asyncio.sleep(wait)
                    continue
                raise last_error

            except Exception as e:
                last_error = Exception(f"An error occurred: {str(e)}")
                if attempt < max_retries:
                    wait = 10 * (attempt + 1)
                    logger.warning("[AIClient] Error, retrying in %ds...", wait)
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
    endpoint and model than the main AIClient while sharing the same
    API key and HTTP connection.
    """

    def __init__(self, main_client: AIClient,
                 endpoint_url: Optional[str] = None,
                 model_name: Optional[str] = None):
        """
        Args:
            main_client: The primary AIClient (for shared API key + HTTP client)
            endpoint_url: Override endpoint (uses main_client's if None)
            model_name: Override model (uses main_client's if None)
        """
        self._main = main_client
        self._endpoint_url = (endpoint_url or main_client.endpoint_url).rstrip('/')
        self._model_name = model_name or main_client.model_name

    @property
    def endpoint_url(self) -> str:
        return self._endpoint_url

    @endpoint_url.setter
    def endpoint_url(self, value: str):
        self._endpoint_url = value.rstrip('/')
        logger.info("Reviewer endpoint URL changed to: %s", self._endpoint_url)

    @property
    def model_name(self) -> str:
        return self._model_name

    @model_name.setter
    def model_name(self, value: str):
        self._model_name = value
        logger.info("Reviewer model changed to: %s", self._model_name)

    def get_config(self) -> Dict[str, Any]:
        """Return reviewer configuration."""
        return {
            "endpoint_url": self._endpoint_url,
            "model_name": self._model_name,
        }

    async def update_config(self, endpoint_url: Optional[str] = None,
                            model_name: Optional[str] = None):
        """Update reviewer configuration at runtime."""
        if endpoint_url is not None:
            self.endpoint_url = endpoint_url
        if model_name is not None:
            self.model_name = model_name

    async def list_models(self) -> List[Dict[str, Any]]:
        """
        Fetch the list of available models from the reviewer's LLM API.
        Uses the reviewer's endpoint URL but shares the main client's
        HTTP connection and auth headers.
        """
        # Handle /v1 suffix
        url = f"{self._endpoint_url}/models" if self._endpoint_url.endswith('/v1') else f"{self._endpoint_url}/v1/models"
        try:
            response = await self._main._client.get(url, headers=self._main._headers)
            response.raise_for_status()
            result = response.json()

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
                logger.warning("Reviewer model listing returned error response: %s", result.get("error"))
                return []
            else:
                models = [{"id": k, "name": k} for k in result.keys() if isinstance(k, str)]

            logger.info("Fetched %d reviewer models from %s", len(models), self._endpoint_url)
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
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Send a completion request using the reviewer's endpoint/model
        but sharing the main client's HTTP connection and auth headers.
        """
        # Handle /v1 suffix
        url = f"{self._endpoint_url}/chat/completions" if self._endpoint_url.endswith('/v1') else f"{self._endpoint_url}/v1/chat/completions"
        payload = {
            "model": self._model_name,
            "messages": messages,
            "temperature": temperature,
        }

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self._main._client.post(url, json=payload, headers=self._main._headers)
                response.raise_for_status()
                result = response.json()

                content = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if not content and attempt < max_retries:
                    wait = 10 * (attempt + 1)
                    logger.warning("[ReviewerClient] Empty response, retrying in %ds...", wait)
                    await asyncio.sleep(wait)
                    continue

                return result

            except httpx.HTTPStatusError as e:
                last_error = Exception(
                    f"Reviewer API request failed with status {e.response.status_code}: {e.response.text}"
                )
                if e.response.status_code in (429, 500, 503) and attempt < max_retries:
                    wait = 15 * (attempt + 1)
                    logger.warning("[ReviewerClient] Status %d, retrying in %ds...", e.response.status_code, wait)
                    await asyncio.sleep(wait)
                    continue
                raise last_error

            except Exception as e:
                last_error = Exception(f"Reviewer error: {str(e)}")
                if attempt < max_retries:
                    wait = 10 * (attempt + 1)
                    logger.warning("[ReviewerClient] Error, retrying in %ds...", wait)
                    await asyncio.sleep(wait)
                    continue
                raise last_error

        raise last_error or Exception("Reviewer max retries exceeded")
