"""
Data models for Hullucinator.

BookState tracks the full lifecycle of a generated book including progress
information for the web interface.
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

from app.config import get_default_shared_config

# Defaults from shared config (single source of truth)
_DEFAULTS = get_default_shared_config()
SCHEMA_DEFAULT_MAX_TURNS = _DEFAULTS.review.max_turns_default
SCHEMA_DEFAULT_WORD_THRESHOLD = _DEFAULTS.review.word_threshold_default
SCHEMA_DEFAULT_CHUNK_SIZE = _DEFAULTS.review.chunk_size_default
SCHEMA_MAX_TURNS_MIN = _DEFAULTS.review.max_turns_min
SCHEMA_MAX_TURNS_MAX = _DEFAULTS.review.max_turns_max
SCHEMA_WORD_THRESHOLD_MIN = 1_000  # minimum from ReviewConfig constraints


class BookState(BaseModel):
    id: str
    title: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1)
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
    review_max_turns: int = Field(default=SCHEMA_DEFAULT_MAX_TURNS, ge=SCHEMA_MAX_TURNS_MIN, le=SCHEMA_MAX_TURNS_MAX)
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
    title: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1)
    tags: list[str] = []
    length: str = "novel"
    # Maximum review-correction turns (overrides global default)
    review_max_turns: int = Field(default=SCHEMA_DEFAULT_MAX_TURNS, ge=SCHEMA_MAX_TURNS_MIN, le=SCHEMA_MAX_TURNS_MAX)
    # Skip the review step entirely (H3: allows quick drafts without review)
    skip_review: bool = False


class AIConfig(BaseModel):
    """Persisted AI configuration (saved to ~/.hullucinator_data/data/config.json, no API keys)."""
    endpoint_url: str = ""
    model_name: str = ""
    reviewer_endpoint_url: str = ""
    reviewer_model_name: str = ""
    review_max_turns: int = Field(default=SCHEMA_DEFAULT_MAX_TURNS, ge=SCHEMA_MAX_TURNS_MIN, le=SCHEMA_MAX_TURNS_MAX)
    # Review thresholds for chunked review of long books
    review_word_threshold: int = Field(default=SCHEMA_DEFAULT_WORD_THRESHOLD, ge=SCHEMA_WORD_THRESHOLD_MIN, description="Words before chunked review is used")
    review_chunk_size: int = Field(default=SCHEMA_DEFAULT_CHUNK_SIZE, ge=1, le=20, description="Chapters per review chunk")


class AIConfigUpdate(BaseModel):
    """Schema for updating AI configuration."""
    endpoint_url: str | None = None
    model_name: str | None = None
    api_key: str | None = None
    # Reviewer settings (optional — empty/None means use same as writer)
    reviewer_endpoint_url: str | None = None
    reviewer_model_name: str | None = None
    reviewer_api_key: str | None = None
    review_max_turns: int | None = None
    review_word_threshold: int | None = None
    review_chunk_size: int | None = None


class ModelInfo(BaseModel):
    id: str
    name: str


class AIConfigResponse(BaseModel):
    """Schema for the GET /api/config response."""
    configured: bool
    endpoint_url: str
    model_name: str
    api_key_set: bool
    reviewer_endpoint_url: str
    reviewer_model_name: str
    reviewer_api_key_set: bool
    review_max_turns: int
    review_word_threshold: int
    review_chunk_size: int


class ConfigValidationResult(BaseModel):
    """Schema for the POST /api/config/validate response."""
    valid: bool
    writer_ok: bool
    reviewer_ok: bool
    error: str = ""
    writer_error: str = ""
    reviewer_error: str = ""
