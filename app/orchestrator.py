"""
Pipeline coordinator for book generation.

Slim coordinator that delegates to specialized modules:
- ``app.status`` — status transition management
- ``app.parsing`` — LLM response parsing
- ``app.generation`` — book generation pipeline
- ``app.review`` — review pipeline
- ``app.validators`` — validation helpers

Each step validates preconditions before proceeding and persists state
to disk. Status transitions are enforced to prevent data inconsistencies.

Key features:
- Chapter continuity: each chapter receives cumulative context from prior chapters
- Post-completion review: professional critic reviews the finished book
- Iterative correction loop: critic reviews → corrections → re-review until approved
  or max turns reached
- Separate reviewer client: optional different endpoint/model for review tasks
- Full audit trail: per-turn review results stored in book metadata
"""
import logging
from typing import List, Optional

from app.ai_client import AIClient, ReviewerClient, _extract_content
from app.storage import save_book, load_config
from app.schemas import BookState
from app.config import get_default_shared_config

# Re-export from status module
from app.status import (
    VALID_TRANSITIONS,
    _transition,
    is_terminal_status,
    get_allowed_transitions,
)

# Re-export from generation module
from app.generation import (
    generate_summary as _gen_generate_summary,
    generate_outline as _gen_generate_outline,
    generate_chapters as _gen_generate_chapters,
    _update_progress,
    _summarize_chapter,
    _parse_chapter_range,
    LENGTH_CHAPTER_COUNT,
    LENGTH_WORD_COUNT,
)

# Re-export from parsing module
from app.parsing import (
    parse_outline,
    parse_critique,
    match_chapter_title,
    _normalize_title,
)

# Re-export from review module
from app.review import (
    review_book as _review_book,
    _get_review_thresholds,
    _build_review_text,
    _build_revision_context,
    _record_review_turn,
    REVIEW_PASS_SCORE,
    REVIEW_WORD_THRESHOLD,
    REVIEW_CHUNK_SIZE,
)

# Re-export from validators module
from app.validators import (
    validate_create_request,
    validate_book_state,
    validate_ai_config,
    max_title_length,
)

logger = logging.getLogger(__name__)

# Shared config — single source of truth for all tunable parameters
_shared_config = get_default_shared_config()
_gen_config = _shared_config.generation


class Orchestrator:
    """Slim coordinator that delegates to specialized modules.

    Maintains the same public API as before for backward compatibility
    with ``main.py`` and tests, but all logic is delegated to the
    new modular components.
    """

    def __init__(self, ai_client: AIClient, reviewer_client: Optional[ReviewerClient] = None):
        self.ai_client = ai_client
        # Reviewer client for critique tasks (may use different endpoint/model)
        # If None, falls back to the main ai_client
        self.reviewer_client = reviewer_client

    def _get_reviewer(self) -> AIClient | ReviewerClient:
        """Return the client to use for review tasks."""
        return self.reviewer_client if self.reviewer_client else self.ai_client

    # ── Delegated generation methods ──────────────────────────────

    async def generate_summary(self, book_state: BookState):
        """Generate a book summary from the user's prompt."""
        await _gen_generate_summary(self.ai_client, book_state)

    async def generate_outline(self, book_state: BookState):
        """Generate chapter outline from the summary."""
        await _gen_generate_outline(self.ai_client, book_state)

    async def generate_chapters(self, book_state: BookState):
        """Generate all chapters from the outline, with continuity context."""
        await _gen_generate_chapters(self.ai_client, book_state)

    # ── Delegated review method ───────────────────────────────────

    async def review_book(self, book_state: BookState, max_turns: Optional[int] = None):
        """
        Review the completed book as a professional critic, running an
        iterative critique → correct → re-critique loop until the book
        passes review or max_turns is reached.
        """
        reviewer = self._get_reviewer()
        await _review_book(self.ai_client, book_state, reviewer_client=reviewer)

    # ── Delegated validation ──────────────────────────────────────

    def validate_book(self, book_state: BookState) -> dict:
        """
        Validate that the book content meets the necessary constraints.
        Returns {"valid": bool, "errors": list[str]}.
        """
        return validate_book_state(book_state)

    # ── Parsing wrappers (for backward compat with tests) ─────────

    def _parse_outline(self, outline_content: str) -> List[str]:
        """Parse chapter titles from LLM output."""
        return parse_outline(outline_content, ["Chapter 1", "Chapter 2", "Chapter 3"])

    def _parse_critique(self, raw: str) -> dict:
        """Parse the critique response from the LLM."""
        return parse_critique(raw)

    def _match_chapter_title(self, query: str, chapters: dict) -> Optional[str]:
        """Find the best matching chapter title for a given query string."""
        return match_chapter_title(query, chapters)

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize a chapter title for comparison."""
        return _normalize_title(title)
