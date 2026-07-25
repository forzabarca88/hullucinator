"""
Shared web grounding utilities.

Provides a protocol type for clients that support tool calling, and
shared helper functions used by both generation and review modules.

This eliminates duplicated `_is_web_grounding_enabled()` and
`_generate_with_optional_tools()` functions from generation.py and review.py.
"""
from typing import Protocol, runtime_checkable

from app.storage import load_config
from app.config import get_default_shared_config
from app.tools import get_available_tools

# Shared config — single source of truth
_shared_config = get_default_shared_config()


@runtime_checkable
class WebGroundingClient(Protocol):
    """Protocol for clients that support tool calling.

    Both AIClient and ReviewerClient satisfy this protocol.
    """
    def generate_completion(self, messages: list, temperature: float,
                            max_retries: int = ..., model_override: str = ...,
                            tools: list = ...) -> dict: ...

    def generate_completion_with_tools(self, messages: list, temperature: float,
                                       tools: list, max_retries: int = ...,
                                       max_turns: int = ...,
                                       model_override: str = ...) -> dict: ...


def _is_web_grounding_enabled() -> bool:
    """Check if web grounding is enabled in the persisted config."""
    persisted = load_config()
    if persisted:
        return persisted.allow_web_grounding
    return _shared_config.tools.allow_web_grounding


async def _generate_with_optional_tools(
    client: WebGroundingClient,
    messages: list,
    temperature: float,
) -> dict:
    """Generate a completion, using tool calling if web grounding is enabled.

    Falls back to regular generate_completion when web grounding is disabled
    or when the endpoint doesn't support tool calling.
    Works with both AIClient and ReviewerClient.
    """
    if not _is_web_grounding_enabled():
        return await client.generate_completion(messages, temperature=temperature)

    tools = get_available_tools()
    if not tools:
        return await client.generate_completion(messages, temperature=temperature)

    try:
        return await client.generate_completion_with_tools(
            messages=messages,
            temperature=temperature,
            tools=tools,
        )
    except RuntimeError:
        # Endpoint doesn't support tool calling — fall back gracefully
        return await client.generate_completion(messages, temperature=temperature)
