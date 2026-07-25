"""
Shared web grounding utilities.

Provides a protocol type for clients that support tool calling, and
shared helper functions used by both generation and review modules.

This eliminates duplicated `_is_web_grounding_enabled()` and
`_generate_with_optional_tools()` functions from generation.py and review.py.
"""
import logging
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from app.storage import load_config
from app.config import get_default_shared_config
from app.tools import get_available_tools

logger = logging.getLogger(__name__)

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


def _inject_date_to_system_messages(messages: list) -> list:
    """Append current date/time to system messages so the LLM has temporal context.

    When web grounding is enabled, the LLM needs to know the current date
    so it can make informed search queries rather than relying on training
    data cut-off dates.

    Returns a new list with the date appended to each system message.
    Non-system messages are copied unchanged.
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d %H:%M UTC")

    result = []
    for msg in messages:
        if msg.get("role") == "system":
            original = msg["content"]
            result.append({
                "role": "system",
                "content": f"{original}\n\nCurrent date and time: {date_str}",
            })
        else:
            result.append(msg)

    return result


async def _generate_with_optional_tools(
    client: WebGroundingClient,
    messages: list,
    temperature: float,
) -> dict:
    """Generate a completion, using tool calling if web grounding is enabled.

    Falls back to regular generate_completion when web grounding is disabled
    or when the endpoint doesn't support tool calling.
    Works with both AIClient and ReviewerClient.

    When web grounding is enabled, the current date/time is injected into
    system messages so the LLM has temporal context for factual searches.
    """
    if not _is_web_grounding_enabled():
        return await client.generate_completion(messages, temperature=temperature)

    # Inject current date/time into system messages for temporal context
    messages = _inject_date_to_system_messages(messages)

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
        # Endpoint doesn't support tool calling — fall back gracefully,
        # keeping the date-injected messages
        return await client.generate_completion(messages, temperature=temperature)
