"""Tests for parsing utilities (outline, critique, chapter matching)."""
import pytest
from app.parsing import parse_outline, parse_critique, match_chapter_title, _extract_balanced_json


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


class TestExtractBalancedJson:
    """Test balanced JSON extraction from text."""

    def test_simple_object(self):
        """Extract a simple JSON object."""
        text = '{"key": "value"}'
        assert _extract_balanced_json(text) == '{"key": "value"}'

    def test_nested_object(self):
        """Extract nested JSON object."""
        text = '{"outer": {"inner": "value"}}'
        assert _extract_balanced_json(text) == '{"outer": {"inner": "value"}}'

    def test_simple_array(self):
        """Extract a simple JSON array."""
        text = '["a", "b", "c"]'
        assert _extract_balanced_json(text) == '["a", "b", "c"]'

    def test_array_of_objects(self):
        """Extract array containing objects."""
        text = '[{"name": "Alice"}, {"name": "Bob"}]'
        assert _extract_balanced_json(text) == '[{"name": "Alice"}, {"name": "Bob"}]'

    def test_json_with_trailing_text(self):
        """Extract JSON even when followed by prose."""
        text = '{"chapters": ["Ch1", "Ch2"]}\n\nSome extra text here.'
        assert _extract_balanced_json(text) == '{"chapters": ["Ch1", "Ch2"]}'

    def test_json_with_leading_text(self):
        """Extract JSON even when preceded by prose."""
        text = 'Here is the outline:\n{"chapters": ["Ch1"]}'
        assert _extract_balanced_json(text) == '{"chapters": ["Ch1"]}'

    def test_brackets_in_string_ignored(self):
        """Brackets inside strings don't affect depth counting."""
        text = '{"note": "use {curly} brackets"}'
        assert _extract_balanced_json(text) == '{"note": "use {curly} brackets"}'

    def test_no_json_returns_none(self):
        """Returns None when no JSON is found."""
        text = "This is plain text with no JSON."
        assert _extract_balanced_json(text) is None

    def test_invalid_json_returns_none(self):
        """Returns None when braces don't form valid JSON."""
        text = '{"key": }'
        assert _extract_balanced_json(text) is None

    def test_empty_string_returns_none(self):
        """Returns None for empty input."""
        assert _extract_balanced_json("") is None

    def test_multiline_json(self):
        """Extract multiline JSON object."""
        text = '''{
  "chapters": [
    "Chapter 1: The Beginning",
    "Chapter 2: The Journey"
  ]
}'''
        result = _extract_balanced_json(text)
        assert result is not None
        import json
        data = json.loads(result)
        assert data["chapters"] == ["Chapter 1: The Beginning", "Chapter 2: The Journey"]

    def test_greedy_regex_avoided(self):
        """Balanced extraction doesn't greedily consume across multiple JSON blocks."""
        text = '{"a": 1}\nSome text\n{"b": 2}'
        result = _extract_balanced_json(text)
        # Should extract only the first JSON object, not both
        assert result == '{"a": 1}'

    def test_json_fragment_in_line(self):
        """Skip lines that look like JSON fragments in outline parsing."""
        # This tests the regex guard in parse_outline's line-based fallback
        # The fragment '"chapters": [' is not valid JSON, so balanced
        # extraction returns None. Then line-based parsing skips it via
        # the JSON fragment regex guard.
        raw = '"chapters": [\n"Chapter 1"\n]'
        result = parse_outline(raw, [])
        # The balanced JSON extractor finds ["Chapter 1"] as valid JSON,
        # so it returns that array. parse_outline parses it as a list.
        assert result == ["Chapter 1"]

        # But a truly malformed fragment like '"chapters": [' gets skipped
        raw2 = '"chapters": ['
        result2 = parse_outline(raw2, ["Fallback"])
        assert result2 == ["Fallback"]
