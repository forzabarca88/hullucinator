"""Tests for app/web_grounding.py — shared web grounding utilities."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.web_grounding import (
    _inject_date_to_system_messages,
    _generate_with_optional_tools,
    WebGroundingClient,
)


class TestInjectDateToSystemMessages:
    """Test _inject_date_to_system_messages appends date to system messages."""

    def test_injects_date_into_single_system_message(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        result = _inject_date_to_system_messages(messages)

        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "You are a helpful assistant." in result[0]["content"]
        assert "Current date and time:" in result[0]["content"]
        assert "UTC" in result[0]["content"]
        # User message unchanged
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_preserves_original_messages(self):
        """Original messages list is not mutated."""
        original = [
            {"role": "system", "content": "Original prompt"},
            {"role": "user", "content": "User input"},
        ]
        _inject_date_to_system_messages(original)

        # Original should be unchanged
        assert original[0]["content"] == "Original prompt"
        assert "Current date and time:" not in original[0]["content"]

    def test_no_system_message(self):
        """Messages without system role are copied unchanged."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = _inject_date_to_system_messages(messages)

        assert result == messages
        assert "Current date and time:" not in str(result)

    def test_multiple_system_messages(self):
        """Each system message gets the date appended."""
        messages = [
            {"role": "system", "content": "First system prompt"},
            {"role": "user", "content": "Input"},
            {"role": "system", "content": "Second system prompt"},
        ]
        result = _inject_date_to_system_messages(messages)

        assert len(result) == 3
        assert "Current date and time:" in result[0]["content"]
        assert "First system prompt" in result[0]["content"]
        assert result[1] == {"role": "user", "content": "Input"}
        assert "Current date and time:" in result[2]["content"]
        assert "Second system prompt" in result[2]["content"]

    def test_date_format(self):
        """Date is formatted as YYYY-MM-DD HH:MM UTC."""
        messages = [
            {"role": "system", "content": "Test"},
        ]
        result = _inject_date_to_system_messages(messages)

        import re
        # Check for expected format: 2024-01-15 14:30 UTC
        pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC"
        assert re.search(pattern, result[0]["content"]) is not None

    def test_empty_messages_list(self):
        """Empty list returns empty list."""
        result = _inject_date_to_system_messages([])
        assert result == []

    def test_system_message_with_multiline_content(self):
        """Multiline system prompt preserves newlines."""
        messages = [
            {"role": "system", "content": "Line one\nLine two\nLine three"},
        ]
        result = _inject_date_to_system_messages(messages)

        assert "Line one\nLine two\nLine three" in result[0]["content"]
        assert "\n\nCurrent date and time:" in result[0]["content"]


class TestGenerateWithOptionalTools:
    """Test _generate_with_optional_tools date injection behavior."""

    def _make_mock_client(self):
        """Create a mock client satisfying WebGroundingClient protocol."""
        client = MagicMock(spec=WebGroundingClient)
        client.generate_completion = AsyncMock(return_value={"choices": [{"message": {"content": "result"}}]})
        client.generate_completion_with_tools = AsyncMock(
            return_value={"choices": [{"message": {"content": "tool_result"}}]}
        )
        return client

    @pytest.mark.asyncio
    async def test_no_date_injection_when_web_grounding_disabled(self):
        """When web grounding is disabled, messages pass through unchanged."""
        client = self._make_mock_client()
        messages = [
            {"role": "system", "content": "You are a writer."},
            {"role": "user", "content": "Write a story."},
        ]

        with patch("app.web_grounding._is_web_grounding_enabled", return_value=False):
            await _generate_with_optional_tools(client, messages, temperature=0.7)

            # Should call generate_completion (not with_tools)
            client.generate_completion.assert_called_once()
            call_args = client.generate_completion.call_args
            passed_messages = call_args[0][0]

            # Messages should NOT have date injected
            assert passed_messages[0]["content"] == "You are a writer."
            assert "Current date and time:" not in passed_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_date_injected_when_web_grounding_enabled(self):
        """When web grounding is enabled, date is injected into system messages."""
        client = self._make_mock_client()
        messages = [
            {"role": "system", "content": "You are a writer."},
            {"role": "user", "content": "Write a story."},
        ]

        with patch("app.web_grounding._is_web_grounding_enabled", return_value=True), \
             patch("app.web_grounding.get_available_tools", return_value=[{"type": "function"}]):
            await _generate_with_optional_tools(client, messages, temperature=0.7)

            # Should call generate_completion_with_tools
            client.generate_completion_with_tools.assert_called_once()
            call_args = client.generate_completion_with_tools.call_args
            passed_messages = call_args[1]["messages"]

            # System message should have date injected
            assert "Current date and time:" in passed_messages[0]["content"]
            assert "You are a writer." in passed_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_date_injected_on_fallback_when_no_tools(self):
        """When web grounding is enabled but no tools available, date still injected."""
        client = self._make_mock_client()
        messages = [
            {"role": "system", "content": "You are a writer."},
            {"role": "user", "content": "Write a story."},
        ]

        with patch("app.web_grounding._is_web_grounding_enabled", return_value=True), \
             patch("app.web_grounding.get_available_tools", return_value=[]):
            await _generate_with_optional_tools(client, messages, temperature=0.7)

            # Falls back to generate_completion
            client.generate_completion.assert_called_once()
            call_args = client.generate_completion.call_args
            passed_messages = call_args[0][0]

            # Date should still be injected
            assert "Current date and time:" in passed_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_date_injected_on_runtime_error_fallback(self):
        """When tool calling raises RuntimeError, date stays injected in fallback."""
        client = self._make_mock_client()
        # First call to generate_completion_with_tools raises RuntimeError
        client.generate_completion_with_tools = AsyncMock(side_effect=[RuntimeError("no tools"), AsyncMock()])
        client.generate_completion.reset_mock()

        messages = [
            {"role": "system", "content": "You are a writer."},
            {"role": "user", "content": "Write a story."},
        ]

        with patch("app.web_grounding._is_web_grounding_enabled", return_value=True), \
             patch("app.web_grounding.get_available_tools", return_value=[{"type": "function"}]):
            await _generate_with_optional_tools(client, messages, temperature=0.7)

            # Should have called generate_completion_with_tools first, then fallback
            assert client.generate_completion_with_tools.call_count == 1
            client.generate_completion.assert_called_once()
            call_args = client.generate_completion.call_args
            passed_messages = call_args[0][0]

            # Date should still be injected in fallback
            assert "Current date and time:" in passed_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_original_messages_not_mutated(self):
        """Original messages list is not modified."""
        client = self._make_mock_client()
        original_messages = [
            {"role": "system", "content": "You are a writer."},
            {"role": "user", "content": "Write a story."},
        ]
        original_content = original_messages[0]["content"]

        with patch("app.web_grounding._is_web_grounding_enabled", return_value=True), \
             patch("app.web_grounding.get_available_tools", return_value=[{"type": "function"}]):
            await _generate_with_optional_tools(client, original_messages, temperature=0.7)

        # Original should be unchanged
        assert original_messages[0]["content"] == original_content
        assert "Current date and time:" not in original_messages[0]["content"]
