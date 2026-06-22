"""Tests for AIClient and ReviewerClient."""
import asyncio
import pytest

from app.ai_client import AIClient, ReviewerClient, _unwrap_json_content


class TestReviewerClientFallback:
    """Test ReviewerClient fallback behavior."""

    def test_api_key_fallback_to_main(self):
        """Reviewer falls back to main client's API key when its own is None."""
        main = AIClient("https://example.com", "model", api_key="main-key")
        reviewer = ReviewerClient(main, api_key=None)
        assert reviewer.api_key == "main-key"

    def test_api_key_fallback_on_empty_string(self):
        """Reviewer falls back to main client's API key when its own is empty string."""
        main = AIClient("https://example.com", "model", api_key="main-key")
        reviewer = ReviewerClient(main, api_key="")
        # Empty string is falsy, so getter falls back
        assert reviewer.api_key == "main-key"

    def test_api_key_no_fallback_when_set(self):
        """Reviewer uses its own API key when explicitly set."""
        main = AIClient("https://example.com", "model", api_key="main-key")
        reviewer = ReviewerClient(main, api_key="reviewer-key")
        assert reviewer.api_key == "reviewer-key"

    def test_endpoint_url_fallback(self):
        """Reviewer falls back to main client's endpoint when its own is empty."""
        main = AIClient("https://main.com", "model")
        reviewer = ReviewerClient(main, endpoint_url="")
        assert reviewer.endpoint_url == "https://main.com"

    def test_model_name_fallback(self):
        """Reviewer falls back to main client's model when its own is empty."""
        main = AIClient("https://example.com", "main-model")
        reviewer = ReviewerClient(main, model_name="")
        assert reviewer.model_name == "main-model"

    def test_headers_fallback(self):
        """Reviewer headers fall back to main client's API key."""
        main = AIClient("https://example.com", "model", api_key="main-key")
        reviewer = ReviewerClient(main, api_key=None)
        assert reviewer._headers["Authorization"] == "Bearer main-key"

    def test_headers_uses_own_key(self):
        """Reviewer headers use its own API key when set."""
        main = AIClient("https://example.com", "model", api_key="main-key")
        reviewer = ReviewerClient(main, api_key="reviewer-key")
        assert reviewer._headers["Authorization"] == "Bearer reviewer-key"

    def test_headers_dynamic_on_main_change(self):
        """Reviewer headers reflect main client key changes."""
        main = AIClient("https://example.com", "model", api_key="old-key")
        reviewer = ReviewerClient(main, api_key=None)
        assert reviewer._headers["Authorization"] == "Bearer old-key"

        # Change main client's key
        main.api_key = "new-key"
        assert reviewer._headers["Authorization"] == "Bearer new-key"

    def test_update_config_clears_api_key(self):
        """update_config with empty string normalizes to None, enabling fallback."""
        main = AIClient("https://example.com", "model", api_key="main-key")
        reviewer = ReviewerClient(main, api_key="reviewer-key")
        assert reviewer.api_key == "reviewer-key"

        asyncio.run(reviewer.update_config(api_key=""))
        # Empty string is normalized to None, so getter falls back
        assert reviewer.api_key == "main-key"
        assert reviewer._api_key is None

    def test_get_config_api_key_set(self):
        """get_config reports api_key_set based on effective key."""
        main = AIClient("https://example.com", "model", api_key="main-key")
        reviewer = ReviewerClient(main, api_key=None)
        config = reviewer.get_config()
        assert config["api_key_set"] is True  # Falls back to main, so key is set

    def test_get_config_api_key_not_set(self):
        """get_config reports api_key_set=False when neither has a key."""
        main = AIClient("https://example.com", "model", api_key=None)
        reviewer = ReviewerClient(main, api_key=None)
        config = reviewer.get_config()
        assert config["api_key_set"] is False


class TestAIClient:
    """Test AIClient configuration."""

    def test_api_key_setter_updates_headers(self):
        """Setting API key updates Authorization header."""
        client = AIClient("https://example.com", "model", api_key="old-key")
        assert client._headers["Authorization"] == "Bearer old-key"
        client.api_key = "new-key"
        assert client._headers["Authorization"] == "Bearer new-key"

    def test_api_key_setter_removes_header_on_none(self):
        """Setting API key to None removes Authorization header."""
        client = AIClient("https://example.com", "model", api_key="some-key")
        assert "Authorization" in client._headers
        client.api_key = None
        assert "Authorization" not in client._headers

    def test_get_config(self):
        """get_config returns current configuration."""
        client = AIClient("https://example.com", "model", api_key="key123")
        config = client.get_config()
        assert config["endpoint_url"] == "https://example.com"
        assert config["model_name"] == "model"
        assert config["api_key_set"] is True

    def test_endpoint_url_trailing_slash(self):
        """Endpoint URL strips trailing slash."""
        client = AIClient("https://example.com/", "model")
        assert client.endpoint_url == "https://example.com"


class TestUnwrapJsonContent:
    """Test _unwrap_json_content for handling JSON-wrapped chapter content."""

    def test_plain_text_passthrough(self):
        """Plain text is returned unchanged."""
        text = "Once upon a time, there was a dragon."
        assert _unwrap_json_content(text) == text

    def test_json_string_wrapped(self):
        """JSON string value is unwrapped."""
        text = '"Hello world"'
        assert _unwrap_json_content(text) == "Hello world"

    def test_json_content_key(self):
        """Dict with 'content' key is unwrapped."""
        text = '{"content": "Chapter content here"}'
        assert _unwrap_json_content(text) == "Chapter content here"

    def test_json_text_key(self):
        """Dict with 'text' key is unwrapped."""
        text = '{"text": "The story continues"}'
        assert _unwrap_json_content(text) == "The story continues"

    def test_json_body_key(self):
        """Dict with 'body' key is unwrapped."""
        text = '{"body": "Full chapter text"}'
        assert _unwrap_json_content(text) == "Full chapter text"

    def test_json_response_key(self):
        """Dict with 'response' key is unwrapped."""
        text = '{"response": "Narrative output"}'
        assert _unwrap_json_content(text) == "Narrative output"

    def test_json_output_key(self):
        """Dict with 'output' key is unwrapped."""
        text = '{"output": "Generated text"}'
        assert _unwrap_json_content(text) == "Generated text"

    def test_json_chapters_list(self):
        """Dict with 'chapters' key joins list with double newlines."""
        text = '{"chapters": ["Chapter one text", "Chapter two text"]}'
        assert _unwrap_json_content(text) == "Chapter one text\n\nChapter two text"

    def test_json_array(self):
        """Bare JSON array is joined with newlines."""
        text = '["Line one", "Line two", "Line three"]'
        assert _unwrap_json_content(text) == "Line one\nLine two\nLine three"

    def test_json_unknown_dict_serialized(self):
        """Dict with unrecognized keys is serialized back."""
        text = '{"custom_key": "value"}'
        result = _unwrap_json_content(text)
        assert '"custom_key"' in result

    def test_invalid_json_passthrough(self):
        """Invalid JSON is returned unchanged."""
        text = "Not json { at all"
        assert _unwrap_json_content(text) == text

    def test_multiline_content_preserved(self):
        """Content with newlines is preserved after unwrapping."""
        text = '{"content": "Para 1\\n\\nPara 2"}'
        assert _unwrap_json_content(text) == "Para 1\n\nPara 2"

    def test_nested_json_serialized(self):
        """Deeply nested JSON without recognized keys is serialized."""
        text = '{"metadata": {"author": "test"}, "version": 1}'
        result = _unwrap_json_content(text)
        assert '"metadata"' in result

    def test_empty_string(self):
        """Empty string is returned unchanged."""
        assert _unwrap_json_content("") == ""

    def test_newlines_in_content(self):
        """Newlines in unwrapped content are preserved."""
        text = '{"content": "Line 1\\nLine 2\\nLine 3"}'
        assert _unwrap_json_content(text) == "Line 1\nLine 2\nLine 3"
