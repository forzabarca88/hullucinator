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


class GenerationConfig(BaseModel):
    """Generation pipeline tuning parameters."""
    # Temperature settings per step
    summary_temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    outline_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    chapter_temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    chapter_summary_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    critique_temperature: float = Field(default=0.5, ge=0.0, le=2.0)
    revision_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    # Minimum chapter content length (characters) before it's considered valid
    min_chapter_chars: int = Field(default=100, ge=1, description="Minimum characters for a generated chapter to be accepted")
    # Max retry attempts for outline generation when chapter count is out of range
    outline_max_retries: int = Field(default=3, ge=1, le=10, description="Max attempts to generate a valid outline before giving up")
    # System prompts for each generation step
    summary_system_prompt: str = Field(
        default=(
            "You are a content generation assistant. Generate a concise one-paragraph summary "
            "that faithfully captures what the user is asking for. Stay close to the user's request — "
            "do not invent a narrative arc, fictional premise, or creative interpretation unless "
            "the user explicitly asks for fiction. For factual, informational, or reference content, "
            "the summary should describe the subject matter and scope accurately."
        ),
        description="System prompt template for summary generation. No format placeholders."
    )
    outline_system_prompt: str = Field(
        default=(
            "You are a content generation assistant. Generate a chapter outline for a {length} "
            "({word_count} words) in the {tags} genre. "
            "The book must have {chapter_guidance}. "
            "The outline must faithfully address the user's original request — do not invent a "
            "fictional narrative unless the user explicitly asks for one. Structure the chapters "
            "to cover all aspects the user asked about."
        ),
        description="System prompt template for outline generation. Use {length}, {word_count}, {tags}, {chapter_guidance} as placeholders."
    )
    chapter_system_prompt: str = Field(
        default=(
            "You are a content generation assistant. Write chapter {chapter_num} of a {length} "
            "in the {tags} genre. Target {word_count} words for the full book. "
            "Faithfully address the user's original request — do not invent a fictional narrative "
            "unless the user explicitly asks for one. Stay aligned with what the user asked for. "
            "Return ONLY plain text content — do NOT wrap output in JSON or code blocks."
        ),
        description="System prompt template for chapter generation. Use {chapter_num}, {length}, {tags}, {word_count} as placeholders."
    )
    chapter_summary_system_prompt: str = Field(
        default=(
            "Summarize the following chapter in a single, concise paragraph "
            "(2-4 sentences) capturing the key content, main points, and any information "
            "that carries forward to subsequent chapters."
        ),
        description="System prompt template for chapter summary generation."
    )
    critique_system_prompt: str = Field(
        default=(
            "You are a professional content reviewer and editor. Review the following content critically. "
            "First, check that the content faithfully addresses the user's original request — identify any "
            "drift from what was asked for. Then identify any other major issues including:\n"
            "- Logical inconsistencies or factual errors\n"
            "- Continuity errors (chapters that contradict each other)\n"
            "- Tone or style inconsistencies across chapters\n"
            "- Unresolved topics or incomplete coverage of requested subjects\n"
            "- Pacing problems (rushed chapters, dragging chapters)\n\n"
            "Return your review as a JSON object with this exact structure:\n"
            '{"issues": [{"chapter": "chapter_title", "type": "issue_type", "description": "what is wrong", "suggestion": "how to fix"}], "overall_score": 0-10, "verdict": "needs_revision" | "ready"}\n\n'
            "Be constructive but honest. Only flag issues that would genuinely affect reader experience. "
            "If the content is solid and addresses the user's request (score >= {pass_score}), "
            "set verdict to 'ready' with an empty issues array."
        ),
        description="System prompt template for critique. Use {pass_score} as placeholder."
    )
    critique_chunk_system_prompt: str = Field(
        default=(
            "You are a professional content reviewer and editor. Review the following chapters critically. "
            "Check that the content faithfully addresses the user's original request — identify any "
            "drift from what was asked for. Identify any major issues including logical inconsistencies, "
            "continuity errors, tone inconsistencies, unresolved topics, and pacing problems.\n\n"
            "Return your review as a JSON object with this exact structure:\n"
            '{"issues": [{"chapter": "chapter_title", "type": "issue_type", "description": "what is wrong", "suggestion": "how to fix"}], "overall_score": 0-10, "verdict": "needs_revision" | "ready"}\n\n'
            "Only flag issues in the chapters provided above. Score based on these chapters but consider overall content quality."
        ),
        description="System prompt template for chunked critique."
    )
    revision_system_prompt: str = Field(
        default=(
            "You are a skilled content writer revising a chapter. Rewrite the chapter to address "
            "the specific issues identified while preserving the core content and style. "
            "Ensure consistency with the rest of the book and alignment with the user's original request."
        ),
        description="System prompt template for chapter revision."
    )


class ClientConfig(BaseModel):
    """AI client retry and timeout configuration."""
    max_retries: int = Field(default=2, ge=0)
    retry_base_wait: float = Field(default=10.0, description="Base wait seconds for general error retries")
    retry_status_wait: float = Field(default=15.0, description="Base wait seconds for HTTP status retries (429/500/503)")
    empty_response_wait: float = Field(default=10.0, description="Base wait seconds for empty response retries")
    jitter_factor: float = Field(default=0.5, description="Random multiplier range for jitter")
    http_timeout: float = Field(default=1800.0, description="HTTP request timeout in seconds")


class ConcurrencyConfig(BaseModel):
    """Server concurrency configuration."""
    max_concurrent_generations: int = Field(default=5, ge=1, le=50, description="Max simultaneous book generations")


class ValidationConfig(BaseModel):
    """Validation thresholds."""
    min_word_threshold: int = Field(default=1_000, ge=1, description="Minimum review word threshold")
    min_chunk_size: int = 1
    max_chunk_size: int = 20
    min_chapter_chars: int = Field(default=200, ge=1, description="Minimum characters for chapter validation")


class UISchema(BaseModel):
    """Frontend UI behavior configuration."""
    polling_interval_ms: int = Field(default=3000, description="Detail modal progress polling interval")
    library_polling_interval_ms: int = Field(default=10000, description="Library auto-refresh interval")
    prompt_warn_threshold: int = Field(default=10000, description="Characters before prompt input warning")
    title_max_length: int = Field(default=200, description="Maximum title length")


class ToolConfig(BaseModel):
    """Tool calling configuration."""
    allow_web_grounding: bool = Field(default=False, description="Enable tool calls for Wikipedia and web search during generation")
    max_retries: int = Field(default=3, ge=1, le=10, description="Max retry attempts for each tool call")
    retry_delay: float = Field(default=1.0, ge=0.1, description="Base delay in seconds between tool call retries")


class SharedConfig(BaseModel):
    """Complete shared configuration object."""
    lengths: List[LengthConfig]
    statuses: List[StatusConfig]
    review: ReviewConfig
    generation: GenerationConfig
    client: ClientConfig
    concurrency: ConcurrencyConfig
    validation: ValidationConfig
    ui: UISchema
    tools: ToolConfig


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
    generation=GenerationConfig(),
    client=ClientConfig(
        max_retries=2,
        retry_base_wait=10.0,
        retry_status_wait=15.0,
        empty_response_wait=10.0,
        jitter_factor=0.5,
        http_timeout=1800.0,
    ),
    concurrency=ConcurrencyConfig(
        max_concurrent_generations=5,
    ),
    validation=ValidationConfig(
        min_word_threshold=1_000,
        min_chunk_size=1,
        max_chunk_size=20,
        min_chapter_chars=200,
    ),
    ui=UISchema(
        polling_interval_ms=3000,
        library_polling_interval_ms=10000,
        prompt_warn_threshold=10000,
        title_max_length=200,
    ),
    tools=ToolConfig(
        allow_web_grounding=False,
        max_retries=3,
        retry_delay=1.0,
    ),
)
