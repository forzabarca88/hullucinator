"""
Data models for Hullucinator.

BookState tracks the full lifecycle of a generated book including progress
information for the web interface.
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any


class BookState(BaseModel):
    id: str
    title: str
    prompt: str
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
    review: Optional[Dict[str, Any]] = None  # {"critique": str, "corrections": list[dict], "reviewed": bool}

    # Progress tracking for the web interface
    progress: Dict[str, Any] = Field(default_factory=lambda: {
        "current_step": "pending",
        "total_chapters": 0,
        "chapters_completed": 0,
        "percentage": 0,
    })


class BookCreateRequest(BaseModel):
    title: str
    prompt: str
    tags: list[str] = []
    length: str = "novel"
