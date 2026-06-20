"""Tests for BookState, BookCreateRequest, and AIConfig schemas (L10)."""
import pytest
from pydantic import ValidationError

from app.schemas import BookState, BookCreateRequest, AIConfig


class TestBookCreateRequest:
    """Test BookCreateRequest validation and defaults."""

    def test_minimal_valid(self):
        """BookCreateRequest with only required fields."""
        req = BookCreateRequest(title="My Book", prompt="A story about dragons")
        assert req.title == "My Book"
        assert req.prompt == "A story about dragons"
        assert req.tags == []
        assert req.length == "novel"
        assert req.review_max_turns == 2
        assert req.skip_review is False

    def test_all_fields(self):
        """BookCreateRequest with all optional fields."""
        req = BookCreateRequest(
            title="My Book",
            prompt="A story about dragons",
            tags=["fantasy", "comedy"],
            length="epic",
            review_max_turns=5,
            skip_review=True,
        )
        assert req.tags == ["fantasy", "comedy"]
        assert req.length == "epic"
        assert req.review_max_turns == 5
        assert req.skip_review is True

    def test_title_too_long(self):
        """Title exceeding 200 chars raises ValidationError."""
        with pytest.raises(ValidationError, match="title"):
            BookCreateRequest(title="A" * 201, prompt="story")

    def test_empty_title(self):
        """Empty title raises ValidationError."""
        with pytest.raises(ValidationError, match="title"):
            BookCreateRequest(title="", prompt="story")

    def test_empty_prompt(self):
        """Empty prompt raises ValidationError."""
        with pytest.raises(ValidationError, match="prompt"):
            BookCreateRequest(title="My Book", prompt="")

    def test_long_prompt(self):
        """Prompts >5000 chars are accepted (no upper limit)."""
        long_prompt = "word " * 6000  # ~30k chars
        req = BookCreateRequest(title="My Book", prompt=long_prompt)
        assert len(req.prompt) == len(long_prompt)

    def test_review_max_turns_too_low(self):
        """review_max_turns below minimum raises ValidationError."""
        with pytest.raises(ValidationError, match="review_max_turns"):
            BookCreateRequest(title="My Book", prompt="story", review_max_turns=0)

    def test_review_max_turns_too_high(self):
        """review_max_turns above maximum raises ValidationError."""
        with pytest.raises(ValidationError, match="review_max_turns"):
            BookCreateRequest(title="My Book", prompt="story", review_max_turns=11)

    def test_omitted_optional_fields(self):
        """Omitted optional fields use schema defaults."""
        req = BookCreateRequest(title="My Book", prompt="story")
        assert req.tags == []
        assert req.length == "novel"
        assert req.review_max_turns == 2
        assert req.skip_review is False


class TestBookState:
    """Test BookState validation and defaults."""

    def test_minimal_valid(self):
        """BookState with only required fields."""
        state = BookState(id="test-123", title="My Book", prompt="story", status="pending")
        assert state.id == "test-123"
        assert state.title == "My Book"
        assert state.status == "pending"
        assert state.length == "novel"
        assert state.tags == []
        assert state.summary is None
        assert state.outline is None
        assert state.chapters is None
        assert state.review is None
        assert state.review_history is None
        assert state.review_max_turns == 2
        assert state.skip_review is False
        assert state.progress == {
            "current_step": "pending",
            "total_chapters": 0,
            "chapters_completed": 0,
            "percentage": 0,
        }

    def test_title_too_long(self):
        """Title exceeding 200 chars raises ValidationError."""
        with pytest.raises(ValidationError, match="title"):
            BookState(id="test", title="A" * 201, prompt="story", status="pending")

    def test_empty_title(self):
        """Empty title raises ValidationError."""
        with pytest.raises(ValidationError, match="title"):
            BookState(id="test", title="", prompt="story", status="pending")

    def test_empty_prompt(self):
        """Empty prompt raises ValidationError."""
        with pytest.raises(ValidationError, match="prompt"):
            BookState(id="test", title="My Book", prompt="", status="pending")

    def test_review_max_turns_constraints(self):
        """review_max_turns respects min/max bounds."""
        # Valid range
        state = BookState(id="test", title="Book", prompt="story", status="pending", review_max_turns=1)
        assert state.review_max_turns == 1
        state = BookState(id="test", title="Book", prompt="story", status="pending", review_max_turns=10)
        assert state.review_max_turns == 10

        # Out of range
        with pytest.raises(ValidationError, match="review_max_turns"):
            BookState(id="test", title="Book", prompt="story", status="pending", review_max_turns=0)
        with pytest.raises(ValidationError, match="review_max_turns"):
            BookState(id="test", title="Book", prompt="story", status="pending", review_max_turns=11)


class TestAIConfig:
    """Test AIConfig validation and defaults."""

    def test_defaults(self):
        """AIConfig with all defaults."""
        config = AIConfig()
        assert config.endpoint_url == ""
        assert config.model_name == ""
        assert config.reviewer_endpoint_url == ""
        assert config.reviewer_model_name == ""
        assert config.review_max_turns == 2
        assert config.review_word_threshold == 30000
        assert config.review_chunk_size == 5

    def test_custom_values(self):
        """AIConfig with custom values."""
        config = AIConfig(
            endpoint_url="http://my-llm:8080",
            model_name="custom-model",
            reviewer_endpoint_url="http://reviewer:9090",
            reviewer_model_name="review-model",
            review_max_turns=4,
            review_word_threshold=20000,
            review_chunk_size=3,
        )
        assert config.endpoint_url == "http://my-llm:8080"
        assert config.model_name == "custom-model"
        assert config.reviewer_endpoint_url == "http://reviewer:9090"
        assert config.reviewer_model_name == "review-model"
        assert config.review_max_turns == 4
        assert config.review_word_threshold == 20000
        assert config.review_chunk_size == 3

    def test_review_max_turns_constraints(self):
        """review_max_turns respects min/max bounds."""
        with pytest.raises(ValidationError, match="review_max_turns"):
            AIConfig(review_max_turns=0)
        with pytest.raises(ValidationError, match="review_max_turns"):
            AIConfig(review_max_turns=11)

    def test_review_word_threshold_min(self):
        """review_word_threshold below minimum raises ValidationError."""
        with pytest.raises(ValidationError, match="review_word_threshold"):
            AIConfig(review_word_threshold=500)

    def test_review_chunk_size_constraints(self):
        """review_chunk_size respects min/max bounds."""
        with pytest.raises(ValidationError, match="review_chunk_size"):
            AIConfig(review_chunk_size=0)
        with pytest.raises(ValidationError, match="review_chunk_size"):
            AIConfig(review_chunk_size=21)

    def test_no_api_keys(self):
        """AIConfig has no api_key field (security)."""
        config = AIConfig()
        assert not hasattr(config, "api_key")
        assert not hasattr(config, "reviewer_api_key")


class TestSchemaConfigSync:
    """Verify schema defaults are synchronized with shared config."""
    def test_defaults_match_shared_config(self):
        """Schema defaults must match shared config values."""
        from app.config import get_default_shared_config
        shared = get_default_shared_config()

        req = BookCreateRequest(title="Test", prompt="story")
        assert req.review_max_turns == shared.review.max_turns_default
        assert req.skip_review is False

        config = AIConfig()
        assert config.review_max_turns == shared.review.max_turns_default
        assert config.review_word_threshold == shared.review.word_threshold_default
        assert config.review_chunk_size == shared.review.chunk_size_default
