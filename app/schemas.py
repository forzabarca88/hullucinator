"""
Data models for Hullucinator.

BookState tracks the full lifecycle of a generated book including progress
information for the web interface.
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any


class BookState(BaseModel):
    id: str
    title: str = Field(..., max_length=200)
    prompt: str = Field(..., max_length=5000)
    tags: list[str] = []
    length: str = "novel"  # short_story | novella | novel | epic
    status: str  # pending | summary_generated | outline_generated | in_progress | completed | reviewing | reviewed | failed

    summary: Optional[str] = None
    outline: Optional[List[str]] = None
    chapters: Optional[Dict[str, str]] = None
    # Condensed one-paragraph summaries of each chapter (for continuity context)
    chapter_summaries: Optional[Dict[str, str]] = None
    metadata: Optional[Dict[str, Any]] = None

    # Review audit trail
    # review_history: list of per-turn results {turn, critique, issues, overall_score, verdict, corrections}
    # review: the latest/final turn's result (kept for backward compat)
    review: Optional[Dict[str, Any]] = None
    review_history: Optional[List[Dict[str, Any]]] = None
    # Maximum number of review-correction turns before giving up (default 2)
    review_max_turns: int = Field(default=2, ge=1, le=10)
    # Skip the review step entirely (H3: allows quick drafts without review)
    skip_review: bool = False

    # Progress tracking for the web interface
    progress: Dict[str, Any] = Field(default_factory=lambda: {
        "current_step": "pending",
        "total_chapters": 0,
        "chapters_completed": 0,
        "percentage": 0,
    })


class BookCreateRequest(BaseModel):
    title: str = Field(..., max_length=200)
    prompt: str = Field(..., max_length=5000)
    tags: list[str] = []
    length: str = "novel"
    # Maximum review-correction turns (overrides global default)
    review_max_turns: int = Field(default=2, ge=1, le=10)
    # Skip the review step entirely (H3: allows quick drafts without review)
    skip_review: bool = False


class AIConfig(BaseModel):
    """Persisted AI configuration (saved to data/config.json, no API keys)."""
    endpoint_url: str = ""
    model_name: str = ""
    reviewer_endpoint_url: str = ""
    reviewer_model_name: str = ""
    review_max_turns: int = Field(default=2, ge=1, le=10)
