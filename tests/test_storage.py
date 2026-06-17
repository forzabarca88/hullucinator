"""Tests for the storage layer — round-trip save/load fidelity."""
import json
from pathlib import Path

import pytest

from app.storage import (
    save_book, load_book, list_books,
    save_config, load_config,
    set_test_dirs, reset_to_defaults,
)
from app.schemas import BookState, AIConfig


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path):
    """Redirect all storage paths to a temp directory for test isolation.

    CRITICAL: Never write to ~/.hullucinator_data during tests.
    Always use tmp_path to avoid polluting the user's real data.
    """
    set_test_dirs(tmp_path)
    yield
    reset_to_defaults()


class TestBookPersistence:
    """Test BookState save/load round-trip."""

    def test_save_and_load(self):
        """Saving and loading a BookState preserves all fields."""
        state = BookState(
            id="test-uuid-1",
            title="The Martian Garden",
            prompt="A story about gardening on Mars",
            tags=["sci-fi", "comedy"],
            length="novel",
            status="pending",
            summary=None,
            outline=None,
            chapters=None,
            chapter_summaries=None,
            metadata=None,
            review=None,
            review_history=None,
            review_max_turns=3,
            progress={
                "current_step": "pending",
                "total_chapters": 0,
                "chapters_completed": 0,
                "percentage": 0,
            },
        )
        save_book("test-uuid-1", state)

        loaded = load_book("test-uuid-1")
        assert loaded is not None
        assert loaded.id == state.id
        assert loaded.title == state.title
        assert loaded.prompt == state.prompt
        assert loaded.tags == state.tags
        assert loaded.length == state.length
        assert loaded.status == state.status
        assert loaded.review_max_turns == state.review_max_turns
        assert loaded.progress == state.progress

    def test_save_with_full_content(self):
        """Saving a book with summary, outline, and chapters preserves everything."""
        state = BookState(
            id="test-uuid-2",
            title="Epic Quest",
            prompt="An epic fantasy adventure",
            tags=["fantasy", "adventure"],
            length="epic",
            status="completed",
            summary="A hero embarks on a journey...",
            outline=["Chapter 1: The Call", "Chapter 2: The Journey", "Chapter 3: The Return"],
            chapters={
                "Chapter 1: The Call": "Once upon a time...",
                "Chapter 2: The Journey": "The hero set forth...",
                "Chapter 3: The Return": "And so they returned...",
            },
            chapter_summaries={
                "Chapter 1: The Call": "Hero receives a mysterious call to adventure.",
                "Chapter 2: The Journey": "Hero travels through dangerous lands.",
            },
            review={
                "turn": 1,
                "overall_score": 8,
                "verdict": "ready",
                "issues": [],
                "corrections": [],
                "reviewed": True,
            },
            review_history=[
                {
                    "turn": 1,
                    "critique": "Good book, minor pacing issues.",
                    "issues": [{"chapter": "Chapter 2", "type": "pacing", "description": "Too slow"}],
                    "overall_score": 8,
                    "verdict": "ready",
                    "corrections": [],
                }
            ],
            review_max_turns=2,
            progress={
                "current_step": "completed",
                "total_chapters": 3,
                "chapters_completed": 3,
                "percentage": 95,
            },
        )
        save_book("test-uuid-2", state)

        loaded = load_book("test-uuid-2")
        assert loaded.summary == state.summary
        assert loaded.outline == state.outline
        assert loaded.chapters == state.chapters
        assert loaded.chapter_summaries == state.chapter_summaries
        assert loaded.review == state.review
        assert loaded.review_history == state.review_history

    def test_load_nonexistent(self):
        """Loading a non-existent book returns None."""
        assert load_book("nonexistent-uuid") is None

    def test_id_mismatch(self):
        """Saving with mismatched filename and model ID raises ValueError."""
        state = BookState(
            id="real-id",
            title="Test",
            prompt="Test prompt",
            status="pending",
        )
        try:
            save_book("different-id", state)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "mismatch" in str(e).lower()

    def test_list_books(self):
        """list_books returns all books sorted by modification time."""
        # Save two books
        state1 = BookState(id="list-test-1", title="First Book", prompt="First", status="pending")
        state2 = BookState(id="list-test-2", title="Second Book", prompt="Second", status="completed")
        save_book("list-test-1", state1)
        save_book("list-test-2", state2)

        books = list_books()
        assert len(books) == 2
        # Newest (most recently modified) first
        assert books[0].id == "list-test-2"
        assert books[1].id == "list-test-1"


class TestConfigPersistence:
    """Test AIConfig save/load round-trip."""

    def test_save_and_load_basic(self):
        """Saving and loading AIConfig preserves endpoint, model, review settings."""
        config = AIConfig(
            endpoint_url="http://localhost:8080",
            model_name="gpt-4o",
            reviewer_endpoint_url="http://localhost:9090",
            reviewer_model_name="llama-3.1-70b",
            review_max_turns=3,
        )
        save_config(config)

        loaded = load_config()
        assert loaded is not None
        assert loaded.endpoint_url == config.endpoint_url
        assert loaded.model_name == config.model_name
        assert loaded.reviewer_endpoint_url == config.reviewer_endpoint_url
        assert loaded.reviewer_model_name == config.reviewer_model_name
        assert loaded.review_max_turns == config.review_max_turns

    def test_save_and_load_no_reviewer(self):
        """Config without reviewer settings."""
        config = AIConfig(
            endpoint_url="http://localhost:8080",
            model_name="qwen3.6-27b",
            reviewer_endpoint_url="",
            reviewer_model_name="",
            review_max_turns=2,
        )
        save_config(config)

        loaded = load_config()
        assert loaded.endpoint_url == config.endpoint_url
        assert loaded.model_name == config.model_name
        assert loaded.reviewer_endpoint_url == ""
        assert loaded.reviewer_model_name == ""
        assert loaded.review_max_turns == 2

    def test_load_nonexistent(self):
        """Loading from a non-existent config file returns None."""
        # With autouse fixture, CONFIG_FILE points to tmp_path which is clean
        # so load_config should return None
        result = load_config()
        assert result is None

    def test_api_key_never_persisted(self):
        """API key is stripped before saving."""
        config = AIConfig(
            endpoint_url="http://localhost:8080",
            model_name="gpt-4o",
            reviewer_endpoint_url="",
            reviewer_model_name="",
            review_max_turns=2,
        )
        save_config(config)

        # Read the raw JSON file to verify no api_key field
        from app.storage import CONFIG_FILE
        with open(CONFIG_FILE, "r") as f:
            raw = json.load(f)
        assert "api_key" not in raw
