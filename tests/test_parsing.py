"""Tests for parsing utilities (outline, critique, chapter matching)."""
import pytest
from app.parsing import parse_outline, parse_critique, match_chapter_title


class TestParseOutline:
    """Test outline parsing from LLM responses."""

    def test_json_list_format(self):
        """Parse JSON with chapters as a list."""
        raw = '{"chapters": ["Chapter 1: The Beginning", "Chapter 2: The Journey", "Chapter 3: The End"]}'
        result = parse_outline(raw, [])
        assert result == ["Chapter 1: The Beginning", "Chapter 2: The Journey", "Chapter 3: The End"]

    def test_json_dict_format(self):
        """Parse JSON with chapters as a dict."""
        raw = '{"chapters": {"The Beginning": "summary 1", "The Journey": "summary 2"}}'
        result = parse_outline(raw, [])
        assert result == ["The Beginning", "The Journey"]

    def test_json_in_code_fences(self):
        """Parse JSON wrapped in code fences."""
        raw = '''Here's your outline:
```json
{"chapters": ["Prologue", "Chapter 1", "Epilogue"]}
```
Hope this helps!
'''
        result = parse_outline(raw, [])
        assert result == ["Prologue", "Chapter 1", "Epilogue"]

    def test_numbered_list_fallback(self):
        """Parse numbered list format when JSON fails."""
        raw = """1. The Awakening
2. Into the Wild
3. The Confrontation
4. Resolution"""
        result = parse_outline(raw, [])
        assert result == ["The Awakening", "Into the Wild", "The Confrontation", "Resolution"]

    def test_chapter_prefix_format(self):
        """Parse 'Chapter N: Title' format."""
        raw = """Chapter 1: The Beginning
Chapter 2: Rising Action
Chapter 3: Climax"""
        result = parse_outline(raw, [])
        assert result == ["The Beginning", "Rising Action", "Climax"]

    def test_empty_response_uses_defaults(self):
        """Empty response falls back to default chapters."""
        raw = ""
        defaults = ["Default 1", "Default 2"]
        result = parse_outline(raw, defaults)
        assert result == ["Default 1", "Default 2"]

    def test_invalid_json_uses_defaults(self):
        """Invalid JSON falls back to defaults."""
        raw = "not valid json at all"
        defaults = ["Fallback 1", "Fallback 2"]
        result = parse_outline(raw, defaults)
        assert result == ["Fallback 1", "Fallback 2"]

    def test_dict_response(self):
        """Parse dict response (from AI client)."""
        raw = {"choices": [{"message": {"content": '{"chapters": ["Ch1", "Ch2"]}'}}]}
        result = parse_outline(raw, [])
        assert result == ["Ch1", "Ch2"]


class TestParseCritique:
    """Test critique parsing from LLM responses."""

    def test_json_format(self):
        """Parse standard JSON critique."""
        raw = '{"issues": [{"chapter": "Ch1", "type": "plot", "description": "hole", "suggestion": "fix"}], "overall_score": 8, "verdict": "ready"}'
        result = parse_critique(raw)
        assert result["overall_score"] == 8
        assert result["verdict"] == "ready"
        assert len(result["issues"]) == 1
        assert result["issues"][0]["chapter"] == "Ch1"

    def test_json_in_code_fences(self):
        """Parse JSON wrapped in code fences."""
        raw = '''```json
{"issues": [], "overall_score": 9, "verdict": "ready"}
```'''
        result = parse_critique(raw)
        assert result["overall_score"] == 9
        assert result["verdict"] == "ready"
        assert result["issues"] == []

    def test_text_fallback(self):
        """Parse text format critique."""
        raw = """Overall Score: 6/10
Verdict: needs_revision

Issue #1
Chapter: Chapter 3
Type: pacing
Description: Too slow in the middle
Suggestion: Add more action

Issue #2
Chapter: Chapter 5
Type: continuity
Description: Character was dead in chapter 2
Suggestion: Remove character or revive"""
        result = parse_critique(raw)
        assert result["overall_score"] == 6
        assert result["verdict"] == "needs_revision"
        assert len(result["issues"]) == 2

    def test_empty_response_defaults(self):
        """Empty response returns safe defaults."""
        raw = ""
        result = parse_critique(raw)
        assert result == {"issues": [], "overall_score": 5, "verdict": "ready"}

    def test_dict_response(self):
        """Parse dict response from AI client."""
        raw = {"choices": [{"message": {"content": '{"issues": [], "overall_score": 7, "verdict": "ready"}'}}]}
        result = parse_critique(raw)
        assert result["overall_score"] == 7
        assert result["verdict"] == "ready"


class TestMatchChapterTitle:
    """Test fuzzy chapter title matching."""

    def test_exact_match(self):
        """Exact title match."""
        chapters = {"The Beginning": "content", "The End": "content"}
        assert match_chapter_title("The Beginning", chapters) == "The Beginning"

    def test_case_insensitive(self):
        """Case-insensitive matching."""
        chapters = {"The Beginning": "content"}
        assert match_chapter_title("the beginning", chapters) == "The Beginning"

    def test_punctuation_tolerance(self):
        """Ignore punctuation differences."""
        chapters = {"Chapter 1: The Beginning": "content"}
        assert match_chapter_title("Chapter 1 - The Beginning", chapters) == "Chapter 1: The Beginning"

    def test_substring_match(self):
        """Match when query is substring of title."""
        chapters = {"Chapter 1: The Long Beginning": "content"}
        assert match_chapter_title("The Long Beginning", chapters) == "Chapter 1: The Long Beginning"

    def test_fuzzy_match(self):
        """Token-based fuzzy matching."""
        chapters = {"The Dark Beginning": "content", "The Happy End": "content"}
        assert match_chapter_title("The Beginning", chapters) == "The Dark Beginning"

    def test_no_match(self):
        """Return None when no match found."""
        chapters = {"Chapter 1: Alpha": "content", "Chapter 2: Beta": "content"}
        assert match_chapter_title("Chapter 99: Gamma", chapters) is None

    def test_empty_query(self):
        """Return None for empty query."""
        assert match_chapter_title("", {"Ch1": "content"}) is None
        assert match_chapter_title(None, {"Ch1": "content"}) is None

    def test_empty_chapters(self):
        """Return None for empty chapters dict."""
        assert match_chapter_title("Some Title", {}) is None
