"""
Status transition logic for book generation pipeline.

Enforced status transitions prevent data inconsistencies.
Each status can only transition to specific next statuses.
"""
from typing import Dict, List

from app.schemas import BookState


# Valid status transition graph
VALID_TRANSITIONS: Dict[str, List[str]] = {
    "pending": ["summary_generated", "failed"],
    "summary_generated": ["outline_generated", "failed"],
    "outline_generated": ["in_progress", "failed"],
    "in_progress": ["completed", "failed"],
    "completed": ["reviewing", "failed"],
    "reviewing": ["reviewed", "failed"],
    "reviewed": ["failed"],
    "failed": ["pending"],  # allow retry
}


def _transition(book: BookState, new_status: str) -> None:
    """
    Transition a book to a new status, enforcing valid transitions.

    Raises ValueError if the transition is not allowed.
    """
    if new_status not in VALID_TRANSITIONS.get(book.status, []):
        raise ValueError(
            f"Invalid status transition: '{book.status}' -> '{new_status}'"
        )
    book.status = new_status


def is_terminal_status(status: str) -> bool:
    """Check if a status is terminal (no outgoing transitions)."""
    return status not in VALID_TRANSITIONS


def get_allowed_transitions(status: str) -> List[str]:
    """Get the list of valid next statuses for a given status."""
    return VALID_TRANSITIONS.get(status, [])
