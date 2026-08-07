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


def _get_current_date_str() -> str:
    """Return the current UTC date/time formatted as 'YYYY-MM-DD HH:MM UTC'."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M UTC")


def _inject_grounding_instruction(messages: list, date_str: str | None = None) -> list:
    """Prepend a grounding instruction system message to encourage tool use.

    Injects a single system message at the start of the messages list that
    includes the current date/time and instructs the LLM to use available
    research tools (Wikipedia, web search) BEFORE generating content.

    This is injected once per request rather than appended to every system
    message, to minimise token overhead. The date is included here so the
    LLM has temporal context when deciding what to research.

    Returns a new list with the grounding instruction prepended.
    """
    date_line = (
        f"Current date and time: {date_str}. "
        f"Treat this date as authoritative — it reflects the actual present moment. "
        f"Do not second-guess, dispute, or flag content as fabricated or future "
        f"simply because it post-dates your training data cutoff. "
        f"Evaluate all facts and events relative to this date.\n\n"
    ) if date_str else ""

    grounding_instruction = (
        f"{date_line}"
        "Research tools are available: you can call wikipedia_search to look up "
        "factual information on Wikipedia, and web_search to find current information "
        "from the web. ALWAYS use these tools to research relevant facts BEFORE writing "
        "your response. Do not skip the research step — use the tools to gather accurate "
        "information first, then incorporate what you find into your output. "
        "For topics involving real people, events, organizations, or technical subjects, "
        "search for each key subject to ensure factual accuracy. "
        "Make multiple searches if needed to cover all relevant aspects."
    )

    return [
        {"role": "system", "content": grounding_instruction},
    ] + list(messages)


async def _generate_with_optional_tools(
    client: WebGroundingClient,
    messages: list,
    temperature: float,
) -> dict:
    """Generate a completion, using tool calling if web grounding is enabled.

    Falls back to regular generate_completion when web grounding is disabled
    or when the endpoint doesn't support tool calling.
    Works with both AIClient and ReviewerClient.

    When web grounding is enabled:
    - Prepends a grounding instruction system message (with date) encouraging tool use
    - Passes available tools to the LLM for research calls
    """
    if not _is_web_grounding_enabled():
        return await client.generate_completion(messages, temperature=temperature)

    # Prepend grounding instruction (with date) to encourage the LLM to use tools
    date_str = _get_current_date_str()
    messages = _inject_grounding_instruction(messages, date_str)

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
        # keeping the grounding-injected messages
        return await client.generate_completion(messages, temperature=temperature)
