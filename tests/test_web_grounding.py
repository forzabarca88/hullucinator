"""Tests for app/web_grounding.py — shared web grounding utilities."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.web_grounding import (
    _get_current_date_str,
    _inject_grounding_instruction,
    _generate_with_optional_tools,
    WebGroundingClient,
)


class TestGetCurrentDateStr:
    """Test _get_current_date_str returns formatted UTC date."""

    def test_date_format(self):
        """Date is formatted as YYYY-MM-DD HH:MM UTC."""
        date_str = _get_current_date_str()

        import re
        pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC"
        assert re.search(pattern, date_str) is not None

    def test_returns_string(self):
        """Returns a string."""
        date_str = _get_current_date_str()
        assert isinstance(date_str, str)


class TestInjectGroundingInstruction:
    """Test _inject_grounding_instruction prepends a grounding instruction."""

    def test_prepends_grounding_instruction_with_date(self):
        messages = [
            {"role": "system", "content": "You are a writer."},
            {"role": "user", "content": "Write a story."},
        ]
        result = _inject_grounding_instruction(messages, date_str="2025-01-15 14:30 UTC")

        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert "Research tools are available" in result[0]["content"]
        assert "BEFORE writing" in result[0]["content"]
        assert "wikipedia_search" in result[0]["content"]
        assert "web_search" in result[0]["content"]
        assert "Current date and time: 2025-01-15 14:30 UTC" in result[0]["content"]
        assert "Treat this date as authoritative" in result[0]["content"]
        # Original messages preserved in order after the instruction
        assert result[1] == {"role": "system", "content": "You are a writer."}
        assert result[2] == {"role": "user", "content": "Write a story."}

    def test_preserves_original_messages(self):
        """Original messages list is not mutated."""
        original = [
            {"role": "system", "content": "Original prompt"},
            {"role": "user", "content": "User input"},
        ]
        _inject_grounding_instruction(original, date_str="2025-01-15 14:30 UTC")

        assert original[0]["content"] == "Original prompt"
        assert "Research tools" not in original[0]["content"]

    def test_empty_messages_list(self):
        """Empty list returns just the grounding instruction."""
        result = _inject_grounding_instruction([], date_str="2025-01-15 14:30 UTC")
        assert len(result) == 1
        assert result[0]["role"] == "system"
        assert "Research tools are available" in result[0]["content"]

    def test_no_system_message_in_input(self):
        """Works with messages that have no system role."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = _inject_grounding_instruction(messages, date_str="2025-01-15 14:30 UTC")

        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert "Research tools are available" in result[0]["content"]
        assert result[1] == {"role": "user", "content": "Hello"}
        assert result[2] == {"role": "assistant", "content": "Hi there"}

    def test_without_date_str(self):
        """Grounding instruction without date still works (no date line)."""
        messages = [
            {"role": "user", "content": "Hello"},
        ]
        result = _inject_grounding_instruction(messages, date_str=None)

        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "Research tools are available" in result[0]["content"]
        assert "Current date and time:" not in result[0]["content"]
        assert "Treat this date as authoritative" not in result[0]["content"]


class TestGenerateWithOptionalTools:
    """Test _generate_with_optional_tools grounding injection behavior."""

    def _make_mock_client(self):
        """Create a mock client satisfying WebGroundingClient protocol."""
        client = MagicMock(spec=WebGroundingClient)
        client.generate_completion = AsyncMock(return_value={"choices": [{"message": {"content": "result"}}]})
        client.generate_completion_with_tools = AsyncMock(
            return_value={"choices": [{"message": {"content": "tool_result"}}]}
        )
        return client

    @pytest.mark.asyncio
    async def test_no_injection_when_web_grounding_disabled(self):
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

            # Messages should NOT have grounding injected
            assert passed_messages[0]["content"] == "You are a writer."
            assert "Research tools are available" not in passed_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_grounding_injected_when_web_grounding_enabled(self):
        """When web grounding is enabled, grounding instruction is prepended with date."""
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

            # First message is the prepended grounding instruction (includes date)
            assert passed_messages[0]["role"] == "system"
            assert "Research tools are available" in passed_messages[0]["content"]
            assert "Current date and time:" in passed_messages[0]["content"]
            assert "Treat this date as authoritative" in passed_messages[0]["content"]
            # Original messages preserved after the instruction (no date appended)
            assert passed_messages[1] == {"role": "system", "content": "You are a writer."}
            assert passed_messages[2] == {"role": "user", "content": "Write a story."}

    @pytest.mark.asyncio
    async def test_grounding_injected_on_fallback_when_no_tools(self):
        """When web grounding is enabled but no tools available, grounding still injected."""
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

            # First message is grounding instruction (includes date)
            assert "Research tools are available" in passed_messages[0]["content"]
            assert "Current date and time:" in passed_messages[0]["content"]
            # Original messages preserved without date appended
            assert passed_messages[1] == {"role": "system", "content": "You are a writer."}

    @pytest.mark.asyncio
    async def test_grounding_injected_on_runtime_error_fallback(self):
        """When tool calling raises RuntimeError, grounding stays injected in fallback."""
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

            # Grounding instruction (with date) present in fallback
            assert "Research tools are available" in passed_messages[0]["content"]
            assert "Current date and time:" in passed_messages[0]["content"]
            # Original messages preserved without date appended
            assert passed_messages[1] == {"role": "system", "content": "You are a writer."}

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
        assert "Research tools are available" not in original_messages[0]["content"]
