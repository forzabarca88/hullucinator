"""Tests for orchestrator parsing and matching logic (L9)."""
import pytest

from app.orchestrator import Orchestrator, _transition


class TestParseOutline:
    """Test _parse_outline with various LLM output formats."""

    def test_standard_json_list(self):
        """Parse a standard JSON array of chapter titles."""
        orch = Orchestrator(None)
        raw = '["Chapter 1: The Beginning", "Chapter 2: The Journey", "Chapter 3: The End"]'
        result = orch._parse_outline(raw)
        assert result == ["Chapter 1: The Beginning", "Chapter 2: The Journey", "Chapter 3: The End"]

    def test_json_with_code_fences(self):
        """Parse JSON wrapped in markdown code fences."""
        orch = Orchestrator(None)
        raw = '''```json
["Chapter 1", "Chapter 2", "Chapter 3"]
```'''
        result = orch._parse_outline(raw)
        assert result == ["Chapter 1", "Chapter 2", "Chapter 3"]

    def test_numbered_list(self):
        """Parse a numbered list format."""
        orch = Orchestrator(None)
        raw = """1. The Awakening
2. The Discovery
3. The Confrontation
4. The Resolution"""
        result = orch._parse_outline(raw)
        assert len(result) == 4
        assert "The Awakening" in result
        assert "The Resolution" in result

    def test_bulleted_list(self):
        """Parse a bulleted list format."""
        orch = Orchestrator(None)
        raw = """- Prologue
- Chapter One: The Call
- Chapter Two: The Quest
- Epilogue"""
        result = orch._parse_outline(raw)
        assert len(result) == 4

    def test_mixed_format_with_numbers(self):
        """Parse mixed format with Chapter N: Title patterns."""
        orch = Orchestrator(None)
        raw = """Chapter 1: Introduction
Chapter 2: Rising Action
Chapter 3: Climax
Chapter 4: Falling Action
Chapter 5: Resolution"""
        result = orch._parse_outline(raw)
        assert len(result) == 5

    def test_prose_with_chapters(self):
        """Parse prose text containing chapter references."""
        orch = Orchestrator(None)
        raw = """Here's the outline for your book:

Chapter 1: The Setup - Introduce the main character and setting
Chapter 2: The Conflict - The hero faces their first challenge
Chapter 3: The Climax - The final confrontation

I hope this helps!"""
        result = orch._parse_outline(raw)
        assert len(result) == 3
        # parse_outline strips the "Chapter N:" prefix, keeping the title
        assert result[0] == "The Setup - Introduce the main character and setting"
        assert result[1] == "The Conflict - The hero faces their first challenge"
        assert result[2] == "The Climax - The final confrontation"


class TestParseCritique:
    """Test _parse_critique with various LLM output formats."""

    def test_valid_json(self):
        """Parse valid JSON critique response."""
        orch = Orchestrator(None)
        raw = '{"issues": [{"chapter": "Chapter 1", "type": "pacing", "description": "Too slow", "suggestion": "Add conflict"}], "overall_score": 6, "verdict": "needs_revision"}'
        result = orch._parse_critique(raw)
        assert result["overall_score"] == 6
        assert result["verdict"] == "needs_revision"
        assert len(result["issues"]) == 1
        assert result["issues"][0]["chapter"] == "Chapter 1"

    def test_json_with_code_fences(self):
        """Parse JSON wrapped in code fences."""
        orch = Orchestrator(None)
        raw = '''```json
{"issues": [], "overall_score": 8, "verdict": "ready"}
```'''
        result = orch._parse_critique(raw)
        assert result["overall_score"] == 8
        assert result["verdict"] == "ready"
        assert result["issues"] == []

    def test_json_with_language_header(self):
        """Parse JSON with json language header in code fences."""
        orch = Orchestrator(None)
        raw = '''```json
{"issues": [{"chapter": "Ch 2", "type": "continuity", "description": "Character age inconsistent"}], "overall_score": 5, "verdict": "needs_revision"}
```'''
        result = orch._parse_critique(raw)
        assert result["verdict"] == "needs_revision"

    def test_empty_input(self):
        """Handle empty input gracefully."""
        orch = Orchestrator(None)
        result = orch._parse_critique("")
        assert result["issues"] == []
        assert result["overall_score"] == 5
        assert result["verdict"] == "ready"


class TestMatchChapterTitle:
    """Test _match_chapter_title fuzzy matching."""

    def test_exact_match(self):
        """Exact title match returns immediately."""
        orch = Orchestrator(None)
        chapters = {"Chapter 1: The Beginning": "content", "Chapter 2: The End": "content"}
        result = orch._match_chapter_title("Chapter 1: The Beginning", chapters)
        assert result == "Chapter 1: The Beginning"

    def test_substring_match(self):
        """Query that's a substring of the title."""
        orch = Orchestrator(None)
        chapters = {"Chapter 1: The Long Beginning": "content"}
        result = orch._match_chapter_title("The Beginning", chapters)
        assert result == "Chapter 1: The Long Beginning"

    def test_fuzzy_match(self):
        """Token-based fuzzy matching for similar titles."""
        orch = Orchestrator(None)
        chapters = {"Chapter One: The Start": "content"}
        result = orch._match_chapter_title("Chapter 1: Start", chapters)
        # Should match via token similarity
        assert result is not None

    def test_no_match(self):
        """Returns None when no match found."""
        orch = Orchestrator(None)
        chapters = {"Chapter 1: Alpha": "content", "Chapter 2: Beta": "content"}
        result = orch._match_chapter_title("Chapter 99: Gamma", chapters)
        assert result is None

    def test_normalize_title(self):
        """Title normalization removes punctuation and lowercases."""
        result = Orchestrator._normalize_title("Chapter 1: The Beginning!")
        assert result == "chapter 1 the beginning"
        result = Orchestrator._normalize_title("  Ch. 2:  Mid-Point  ")
        assert result == "ch 2 midpoint"


class TestTransition:
    """Test _transition status validation."""

    def test_valid_transition(self):
        """Valid status transitions succeed."""
        from app.schemas import BookState
        book = BookState(id="test-1", title="Test", prompt="A test", status="pending")
        _transition(book, "summary_generated")
        assert book.status == "summary_generated"

    def test_invalid_status_transition(self):
        """Invalid status transitions raise ValueError."""
        from app.schemas import BookState
        book = BookState(id="test-1", title="Test", prompt="A test", status="pending")
        with pytest.raises(ValueError, match="Invalid status transition"):
            _transition(book, "completed")
