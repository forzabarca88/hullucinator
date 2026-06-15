"""
HTTP client for OpenAI-compatible LLM API endpoints.

Key fixes:
- Reuses a single httpx.AsyncClient instead of creating one per request
- Uses async `await asyncio.sleep()` instead of blocking `time.sleep()`
- Configurable via environment variables
"""
import asyncio
import logging
from typing import List, Dict, Optional, Any

import httpx

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self, endpoint_url: str, model_name: str, api_key: Optional[str] = None):
        self.endpoint_url = endpoint_url.rstrip('/')
        self.model_name = model_name
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        # Single persistent async client reused across all requests
        self._client = httpx.AsyncClient(timeout=1800.0)

    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Send a completion request to the LLM API with retry logic.

        Retries on 429/500/503 status codes or empty responses.
        Uses async sleep to avoid blocking the event loop.
        """
        url = f"{self.endpoint_url}/v1/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self._client.post(url, json=payload, headers=self.headers)
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
