"""
Validation helpers for book generation pipeline.

Provides input validation, book state validation, and config validation.
"""
import logging
from typing import Dict, Any, List

from app.schemas import BookState, BookCreateRequest, AIConfig
from app.config import get_default_shared_config

logger = logging.getLogger(__name__)

# Shared config for validation constraints
_config = get_default_shared_config()


def validate_create_request(req: BookCreateRequest) -> List[str]:
    """Validate a BookCreateRequest and return list of error messages."""
    errors = []

    if not req.title or not req.title.strip():
        errors.append("Title is required and cannot be empty.")
    elif len(req.title) > _config.ui.max_title_length:
        errors.append(f"Title must be {max_title_length} characters or fewer.")

    if not req.prompt or not req.prompt.strip():
        errors.append("Prompt is required and cannot be empty.")

    if req.tags:
        for tag in req.tags:
            if not tag.strip():
                errors.append("Tags cannot be empty strings.")
                break

    if req.length not in [l.key for l in _config.lengths]:
        errors.append(f"Length must be one of: {', '.join(l.key for l in _config.lengths)}")

    if req.review_max_turns < _config.review.max_turns_min or req.review_max_turns > _config.review.max_turns_max:
        errors.append(f"Max turns must be between {_config.review.max_turns_min} and {_config.review.max_turns_max}.")

    return errors


def validate_book_state(book: BookState) -> Dict[str, Any]:
    """
    Validate that the book content meets the necessary constraints.

    Returns {"valid": bool, "errors": list[str]}.
    """
    errors = []

    if not book.summary:
        errors.append("Summary is missing.")
    if not book.outline:
        errors.append("Outline is missing.")

    if book.outline and book.chapters:
        # Parse outline to get expected chapter count
        outline_lines = book.outline.strip().split("\n")
        outline_chapters = []
        import re
        for line in outline_lines:
            line = line.strip()
            if not line:
                continue
            match = re.match(r"\d+[\)\.]\s*(.+)", line)
            if match:
                outline_chapters.append(match.group(1).strip())

        if len(book.chapters) != len(outline_chapters):
            errors.append(
                f"Chapter count ({len(book.chapters)}) does not match the outline ({len(outline_chapters)})."
            )

    # Validate chapter content
    if book.chapters:
        for title, content in book.chapters.items():
            if not content or not content.strip():
                errors.append(f"Chapter '{title}' has empty content.")
            elif len(content) < 200:
                errors.append(f"Chapter '{title}' is too short ({len(content)} chars).")

    return {"valid": len(errors) == 0, "errors": errors}


def validate_ai_config(cfg: AIConfig) -> List[str]:
    """Validate AI config and return list of error messages."""
    errors = []

    if not cfg.endpoint_url or not cfg.endpoint_url.strip():
        errors.append("Writer endpoint URL is required.")

    if not cfg.model_name or not cfg.model_name.strip():
        errors.append("Writer model name is required.")

    if cfg.reviewer_endpoint_url and not cfg.reviewer_endpoint_url.strip():
        errors.append("Reviewer endpoint URL cannot be blank (omit entirely to use writer's endpoint).")

    if cfg.reviewer_model_name and not cfg.reviewer_model_name.strip():
        errors.append("Reviewer model name cannot be blank (omit entirely to use writer's model).")

    if cfg.review_max_turns < _config.review.max_turns_min or cfg.review_max_turns > _config.review.max_turns_max:
        errors.append(f"Max turns must be between {_config.review.max_turns_min} and {_config.review.max_turns_max}.")

    if cfg.review_word_threshold < 1000:
        errors.append("Word threshold must be at least 1,000.")

    if cfg.review_chunk_size < 1 or cfg.review_chunk_size > 20:
        errors.append("Chunk size must be between 1 and 20.")

    return errors


# Re-export max_title_length for frontend use
max_title_length = _config.ui.max_title_length
