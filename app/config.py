"""
Shared configuration — the single source of truth for all tunable parameters.

Served to the frontend via GET /api/config-schema so frontend and backend
can never drift out of sync.
"""
from pydantic import BaseModel, Field
from typing import List, Literal


class LengthConfig(BaseModel):
    """Definition of a book length tier."""
    key: str                    # "short_story", "novella", "novel", "epic"
    label: str                  # human-readable: "Short Story"
    chapter_range: str          # "1", "3-5", "8-15", "15-25"
    word_range: str             # "1,000-7,500", "7,500-20,000", etc.


class StatusConfig(BaseModel):
    """Definition of a pipeline status."""
    key: str                    # "pending", "summary_generated", etc.
    label: str                  # display label: "pending", "summary", etc.
    css_class: str              # "status-pending", "status-summary_generated", etc.
    is_terminal: bool           # True for completed, reviewed, failed
    is_active: bool             # True for statuses that trigger polling


class ReviewConfig(BaseModel):
    """Review pipeline tuning parameters."""
    max_turns_default: int = Field(default=2, ge=1, le=10)
    max_turns_min: int = 1
    max_turns_max: int = 10
    word_threshold_default: int = Field(default=30_000, ge=1_000)
    chunk_size_default: int = Field(default=5, ge=1, le=20)
    pass_score: int = Field(default=7, ge=0, le=10, description="Score threshold for 'ready' verdict")
    fail_score: int = Field(default=4, ge=0, le=10, description="Score below this is considered failing")
    turn_options: List[dict] = Field(
        default_factory=lambda: [
            {"value": 1, "label": "1 turn — quick review"},
            {"value": 2, "label": "2 turns — balanced"},
            {"value": 3, "label": "3 turns — thorough"},
            {"value": 4, "label": "4 turns — very thorough"},
            {"value": 5, "label": "5 turns — exhaustive"},
        ]
    )


class ClientConfig(BaseModel):
    """AI client retry and timeout configuration."""
    max_retries: int = Field(default=2, ge=0)
    retry_base_wait: float = Field(default=10.0, description="Base wait seconds for general error retries")
    retry_status_wait: float = Field(default=15.0, description="Base wait seconds for HTTP status retries (429/500/503)")
    empty_response_wait: float = Field(default=10.0, description="Base wait seconds for empty response retries")
    jitter_factor: float = Field(default=0.5, description="Random multiplier range for jitter")
    http_timeout: float = Field(default=1800.0, description="HTTP request timeout in seconds")


class UISchema(BaseModel):
    """Frontend UI behavior configuration."""
    polling_interval_ms: int = Field(default=3000, description="Detail modal progress polling interval")
    library_polling_interval_ms: int = Field(default=10000, description="Library auto-refresh interval")
    prompt_warn_threshold: int = Field(default=10000, description="Characters before prompt input warning")
    title_max_length: int = Field(default=200, description="Maximum title length")


class SharedConfig(BaseModel):
    """Complete shared configuration object."""
    lengths: List[LengthConfig]
    statuses: List[StatusConfig]
    review: ReviewConfig
    client: ClientConfig
    ui: UISchema


def get_default_shared_config() -> SharedConfig:
    """Return the default shared configuration instance."""
    return DEFAULT_SHARED_CONFIG


# ── Default configuration ──────────────────────────────────────────

DEFAULT_SHARED_CONFIG = SharedConfig(
    lengths=[
        LengthConfig(key="short_story", label="Short Story", chapter_range="1", word_range="1,000-7,500"),
        LengthConfig(key="novella", label="Novella", chapter_range="3-5", word_range="7,500-20,000"),
        LengthConfig(key="novel", label="Novel", chapter_range="8-15", word_range="20,000-50,000"),
        LengthConfig(key="epic", label="Epic", chapter_range="15-25", word_range="50,000+"),
    ],
    statuses=[
        StatusConfig(key="pending", label="Pending", css_class="status-pending", is_terminal=False, is_active=True),
        StatusConfig(key="summary_generated", label="Summary", css_class="status-summary_generated", is_terminal=False, is_active=True),
        StatusConfig(key="outline_generated", label="Outline", css_class="status-outline_generated", is_terminal=False, is_active=True),
        StatusConfig(key="in_progress", label="In Progress", css_class="status-in_progress", is_terminal=False, is_active=True),
        StatusConfig(key="completed", label="Completed", css_class="status-completed", is_terminal=True, is_active=False),
        StatusConfig(key="reviewing", label="Reviewing", css_class="status-reviewing", is_terminal=False, is_active=True),
        StatusConfig(key="reviewed", label="Reviewed", css_class="status-reviewed", is_terminal=True, is_active=False),
        StatusConfig(key="failed", label="Failed", css_class="status-failed", is_terminal=True, is_active=False),
    ],
    review=ReviewConfig(
        max_turns_default=2,
        word_threshold_default=30_000,
        chunk_size_default=5,
        pass_score=7,
        fail_score=4,
        turn_options=[
            {"value": 1, "label": "1 turn — quick review"},
            {"value": 2, "label": "2 turns — balanced"},
            {"value": 3, "label": "3 turns — thorough"},
            {"value": 4, "label": "4 turns — very thorough"},
            {"value": 5, "label": "5 turns — exhaustive"},
        ],
    ),
    client=ClientConfig(
        max_retries=2,
        retry_base_wait=10.0,
        retry_status_wait=15.0,
        empty_response_wait=10.0,
        jitter_factor=0.5,
        http_timeout=1800.0,
    ),
    ui=UISchema(
        polling_interval_ms=3000,
        library_polling_interval_ms=10000,
        prompt_warn_threshold=10000,
        title_max_length=200,
    ),
)
