"""Tests for generation pipeline: summary, outline, chapters."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.generation import generate_outline, _format_chapter_guidance
from app.schemas import BookState
from app.storage import set_test_dirs, reset_to_defaults


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path):
    """Redirect all storage paths to a temp directory for test isolation."""
    set_test_dirs(tmp_path)
    yield
    reset_to_defaults()


def _make_book(length: str = "novella", status: str = "summary_generated") -> BookState:
    """Create a minimal BookState ready for outline generation."""
    return BookState(
        id="test-book-1",
        title="Test Book",
        prompt="A test book about testing",
        tags=["test"],
        length=length,
        status=status,
        summary="A summary of the test book.",
        outline=None,
        chapters=None,
        chapter_summaries=None,
        progress={
            "current_step": "summary generated",
            "total_chapters": 0,
            "chapters_completed": 0,
            "percentage": 20,
        },
    )


class TestFormatChapterGuidance:
    """Test _format_chapter_guidance conversion."""

    def test_single_chapter(self):
        assert _format_chapter_guidance("1") == "exactly 1 chapter"

    def test_multiple_single(self):
        assert _format_chapter_guidance("3") == "exactly 3 chapters"

    def test_range(self):
        assert _format_chapter_guidance("3-5") == "between 3 and 5 chapters"

    def test_wide_range(self):
        assert _format_chapter_guidance("8-15") == "between 8 and 15 chapters"

    def test_epic_range(self):
        assert _format_chapter_guidance("15-25") == "between 15 and 25 chapters"


class TestGenerateOutline:
    """Test generate_outline retry logic."""

    def test_passes_on_first_attempt(self):
        """Outline passes on first attempt when chapter count is valid."""
        book = _make_book(length="novella")  # novella: 3-5 chapters allowed

        with patch("app.generation._generate_with_optional_tools", new_callable=AsyncMock) as mock_gen:
            # Return valid outline with 3 chapters (within 3-5 range)
            mock_gen.return_value = {
                "choices": [{"message": {"content": "1. Chapter One\n2. Chapter Two\n3. Chapter Three"}}],
            }

            mock_client = AsyncMock(spec=["generate_completion"])
            asyncio.run(generate_outline(mock_client, book))

            assert mock_gen.call_count == 1
            assert book.outline == ["Chapter One", "Chapter Two", "Chapter Three"]
            assert book.status == "outline_generated"
            assert book.progress["current_step"] == "Outline generated"
            assert book.progress["total_chapters"] == 3

    def test_retries_when_too_many_chapters(self):
        """Outline retries when count exceeds max, succeeds on retry."""
        book = _make_book(length="novella")  # novella: 3-5 chapters allowed

        with patch("app.generation._generate_with_optional_tools", new_callable=AsyncMock) as mock_gen:
            # First attempt: 6 chapters (too many, max is 5)
            # Second attempt: 4 chapters (valid)
            mock_gen.side_effect = [
                {"choices": [{"message": {"content": "1. Ch1\n2. Ch2\n3. Ch3\n4. Ch4\n5. Ch5\n6. Ch6"}}]},
                {"choices": [{"message": {"content": "1. Ch1\n2. Ch2\n3. Ch3\n4. Ch4"}}]},
            ]

            mock_client = AsyncMock(spec=["generate_completion"])
            asyncio.run(generate_outline(mock_client, book))

            assert mock_gen.call_count == 2
            assert book.outline == ["Ch1", "Ch2", "Ch3", "Ch4"]
            assert book.status == "outline_generated"

    def test_retries_when_too_few_chapters(self):
        """Outline retries when count is below min, succeeds on retry."""
        book = _make_book(length="novella")  # novella: 3-5 chapters allowed

        with patch("app.generation._generate_with_optional_tools", new_callable=AsyncMock) as mock_gen:
            # First attempt: 2 chapters (too few, min is 3)
            # Second attempt: 4 chapters (valid)
            mock_gen.side_effect = [
                {"choices": [{"message": {"content": "1. Ch1\n2. Ch2"}}]},
                {"choices": [{"message": {"content": "1. Ch1\n2. Ch2\n3. Ch3\n4. Ch4"}}]},
            ]

            mock_client = AsyncMock(spec=["generate_completion"])
            asyncio.run(generate_outline(mock_client, book))

            assert mock_gen.call_count == 2
            assert book.outline == ["Ch1", "Ch2", "Ch3", "Ch4"]
            assert book.status == "outline_generated"

    def test_value_error_after_max_retries_too_many(self):
        """ValueError raised after max retries exhausted (too many chapters)."""
        book = _make_book(length="novella")  # novella: 3-5 chapters allowed

        with patch("app.generation._generate_with_optional_tools", new_callable=AsyncMock) as mock_gen:
            # All attempts produce too many chapters
            mock_gen.return_value = {
                "choices": [{"message": {"content": "1. Ch1\n2. Ch2\n3. Ch3\n4. Ch4\n5. Ch5\n6. Ch6"}}],
            }

            mock_client = AsyncMock(spec=["generate_completion"])
            with pytest.raises(ValueError, match="has 6 chapters but novella allows max 5"):
                asyncio.run(generate_outline(mock_client, book))

            # Default outline_max_retries is 3
            assert mock_gen.call_count == 3

    def test_value_error_after_max_retries_too_few(self):
        """ValueError raised after max retries exhausted (too few chapters)."""
        book = _make_book(length="novella")  # novella: 3-5 chapters allowed

        with patch("app.generation._generate_with_optional_tools", new_callable=AsyncMock) as mock_gen:
            # All attempts produce too few chapters
            mock_gen.return_value = {
                "choices": [{"message": {"content": "1. Ch1\n2. Ch2"}}],
            }

            mock_client = AsyncMock(spec=["generate_completion"])
            with pytest.raises(ValueError, match="has 2 chapters but novella requires min 3"):
                asyncio.run(generate_outline(mock_client, book))

            assert mock_gen.call_count == 3

    def test_progress_label_includes_attempt_number(self):
        """Progress label updates with attempt number during retries."""
        book = _make_book(length="novella")  # novella: 3-5 chapters allowed
        save_calls: list = []

        def capture_save(book_id: str, state: BookState):
            save_calls.append(state.progress["current_step"])

        with patch("app.generation._generate_with_optional_tools", new_callable=AsyncMock) as mock_gen:
            with patch("app.generation.save_book", side_effect=capture_save):
                # First two attempts fail, third succeeds
                mock_gen.side_effect = [
                    {"choices": [{"message": {"content": "1. Ch1\n2. Ch2"}}]},  # too few
                    {"choices": [{"message": {"content": "1. Ch1\n2. Ch2"}}]},  # too few
                    {"choices": [{"message": {"content": "1. Ch1\n2. Ch2\n3. Ch3"}}]},  # valid
                ]

                mock_client = AsyncMock(spec=["generate_completion"])
                asyncio.run(generate_outline(mock_client, book))

        assert save_calls == [
            "Generating outline... (attempt 1/3)",
            "Generating outline... (attempt 2/3)",
            "Generating outline... (attempt 3/3)",
            "Outline generated",
        ]

    def test_wrong_status_raises(self):
        """generate_outline rejects books not in summary_generated status."""
        book = _make_book(status="pending")
        mock_client = AsyncMock(spec=["generate_completion"])
        with pytest.raises(ValueError, match="expected 'summary_generated'"):
            asyncio.run(generate_outline(mock_client, book))


