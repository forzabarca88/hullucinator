"""Tests for SharedConfig model and config loading/saving (L10)."""
import pytest
from pydantic import ValidationError

from app.config import SharedConfig, LengthConfig, StatusConfig, ReviewConfig, ClientConfig, UISchema, get_default_shared_config


class TestSharedConfig:
    """Test SharedConfig model structure and constraints."""

    def test_default_instance(self):
        """get_default_shared_config returns valid config."""
        config = get_default_shared_config()
        assert config is not None

    def test_length_config(self):
        """lengths list has correct entries for all tiers."""
        config = get_default_shared_config()
        assert isinstance(config.lengths, list)
        keys = [l.key for l in config.lengths]
        assert "short_story" in keys
        assert "novella" in keys
        assert "novel" in keys
        assert "epic" in keys

        for length in config.lengths:
            assert length.key in ("short_story", "novella", "novel", "epic")
            assert length.label != ""
            assert length.chapter_range != ""
            assert length.word_range != ""

    def test_status_config(self):
        """statuses list has correct entries."""
        config = get_default_shared_config()
        assert isinstance(config.statuses, list)
        keys = [s.key for s in config.statuses]
        assert "pending" in keys
        assert "summary_generated" in keys
        assert "outline_generated" in keys
        assert "in_progress" in keys
        assert "completed" in keys
        assert "reviewing" in keys
        assert "reviewed" in keys
        assert "failed" in keys

        terminal = [s.key for s in config.statuses if s.is_terminal]
        assert "completed" in terminal
        assert "reviewed" in terminal
        assert "failed" in terminal

        active = [s.key for s in config.statuses if s.is_active]
        assert "in_progress" in active
        assert "reviewing" in active

    def test_review_config(self):
        """ReviewConfig has correct defaults and constraints."""
        config = get_default_shared_config()
        assert config.review.max_turns_default == 2
        assert config.review.max_turns_min == 1
        assert config.review.max_turns_max == 10
        assert config.review.pass_score == 7
        assert config.review.fail_score == 4
        assert config.review.word_threshold_default == 30000
        assert config.review.chunk_size_default == 5
        assert len(config.review.turn_options) > 0

    def test_ui_config(self):
        """UISchema has correct values."""
        config = get_default_shared_config()
        assert config.ui.polling_interval_ms == 3000
        assert config.ui.library_polling_interval_ms == 10000
        assert config.ui.prompt_warn_threshold == 10000
        assert config.ui.title_max_length == 200

    def test_client_config(self):
        """ClientConfig has correct defaults."""
        config = get_default_shared_config()
        assert config.client.max_retries == 2
        assert config.client.retry_base_wait == 10.0
        assert config.client.retry_status_wait == 15.0
        assert config.client.empty_response_wait == 10.0
        assert config.client.jitter_factor == 0.5
        assert config.client.http_timeout == 1800.0

    def test_custom_config(self):
        """SharedConfig accepts custom values within constraints."""
        config = SharedConfig(
            lengths=[],
            statuses=[],
            review=ReviewConfig(
                max_turns_default=3,
                pass_score=8,
                fail_score=5,
            ),
            client=ClientConfig(),
            ui=UISchema(),
        )
        assert config.review.max_turns_default == 3
        assert config.review.pass_score == 8
        assert config.review.fail_score == 5

    def test_review_max_turns_constraints(self):
        """max_turns_default respects ge=1, le=10 bounds."""
        with pytest.raises(ValidationError, match="max_turns_default"):
            SharedConfig(
                lengths=[],
                statuses=[],
                review=ReviewConfig(max_turns_default=0),
                client=ClientConfig(),
                ui=UISchema(),
            )
        with pytest.raises(ValidationError, match="max_turns_default"):
            SharedConfig(
                lengths=[],
                statuses=[],
                review=ReviewConfig(max_turns_default=11),
                client=ClientConfig(),
                ui=UISchema(),
            )

    def test_word_threshold_constraints(self):
        """word_threshold must be >= 1000."""
        with pytest.raises(ValidationError, match="word_threshold"):
            SharedConfig(
                lengths=[],
                statuses=[],
                review=ReviewConfig(word_threshold_default=100),
                client=ClientConfig(),
                ui=UISchema(),
            )

    def test_chunk_size_constraints(self):
        """chunk_size must be within valid range."""
        with pytest.raises(ValidationError, match="chunk_size"):
            SharedConfig(
                lengths=[],
                statuses=[],
                review=ReviewConfig(chunk_size_default=0),
                client=ClientConfig(),
                ui=UISchema(),
            )
        with pytest.raises(ValidationError, match="chunk_size"):
            SharedConfig(
                lengths=[],
                statuses=[],
                review=ReviewConfig(chunk_size_default=21),
                client=ClientConfig(),
                ui=UISchema(),
            )


class TestConfigSubModels:
    """Test individual sub-models."""

    def test_length_config_fields(self):
        """LengthConfig has all required fields."""
        lc = LengthConfig(key="novel", label="Novel", chapter_range="8-15", word_range="20,000-50,000")
        assert lc.key == "novel"
        assert lc.label == "Novel"
        assert lc.chapter_range == "8-15"
        assert lc.word_range == "20,000-50,000"

    def test_status_config_fields(self):
        """StatusConfig has all required fields."""
        sc = StatusConfig(key="completed", label="Completed", css_class="status-completed", is_terminal=True, is_active=False)
        assert sc.key == "completed"
        assert sc.is_terminal is True
        assert sc.is_active is False

    def test_client_config_custom(self):
        """ClientConfig accepts custom values."""
        cc = ClientConfig(max_retries=5, retry_base_wait=5.0, http_timeout=300.0)
        assert cc.max_retries == 5
        assert cc.retry_base_wait == 5.0
        assert cc.http_timeout == 300.0

    def test_ui_schema_custom(self):
        """UISchema accepts custom values."""
        ui = UISchema(polling_interval_ms=1000, prompt_warn_threshold=5000, title_max_length=100)
        assert ui.polling_interval_ms == 1000
        assert ui.prompt_warn_threshold == 5000
        assert ui.title_max_length == 100


class TestConfigDerivations:
    """Verify that other modules derive defaults from shared config."""

    def test_schemas_use_shared_defaults(self):
        """Schema defaults must match shared config values."""
        from app.config import get_default_shared_config
        from app.schemas import (
            SCHEMA_DEFAULT_MAX_TURNS,
            SCHEMA_DEFAULT_WORD_THRESHOLD,
            SCHEMA_DEFAULT_CHUNK_SIZE,
            SCHEMA_MAX_TURNS_MIN,
            SCHEMA_MAX_TURNS_MAX,
        )
        shared = get_default_shared_config()
        assert SCHEMA_DEFAULT_MAX_TURNS == shared.review.max_turns_default
        assert SCHEMA_DEFAULT_WORD_THRESHOLD == shared.review.word_threshold_default
        assert SCHEMA_DEFAULT_CHUNK_SIZE == shared.review.chunk_size_default
        assert SCHEMA_MAX_TURNS_MIN == shared.review.max_turns_min
        assert SCHEMA_MAX_TURNS_MAX == shared.review.max_turns_max

    def test_orchestrator_uses_shared_constants(self):
        """Orchestrator constants must match shared config."""
        from app.config import get_default_shared_config
        shared = get_default_shared_config()

        from app.generation import LENGTH_CHAPTER_COUNT, LENGTH_WORD_COUNT
        for length in shared.lengths:
            assert length.key in LENGTH_CHAPTER_COUNT
            assert length.key in LENGTH_WORD_COUNT

        from app.review import REVIEW_PASS_SCORE
        assert REVIEW_PASS_SCORE == shared.review.pass_score
