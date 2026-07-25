"""Tests for tool calling infrastructure (app/tools.py and app/ai_client.py tool support)."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.tools import (
    get_available_tools,
    parse_tool_calls,
    has_tool_calls,
    execute_tool_call,
    wikipedia_search,
    web_search,
    get_tool_client,
    WIKIPEDIA_SEARCH,
    WEB_SEARCH,
)
from app.ai_client import AIClient, ReviewerClient


class TestGetAvailableTools:
    """Test get_available_tools returns correct tool definitions."""

    def test_returns_two_tools(self):
        tools = get_available_tools()
        assert len(tools) == 2

    def test_wikipedia_search_structure(self):
        tools = get_available_tools()
        wiki = [t for t in tools if t["function"]["name"] == "wikipedia_search"][0]
        assert wiki["type"] == "function"
        assert wiki["function"]["name"] == "wikipedia_search"
        assert "query" in wiki["function"]["parameters"]["properties"]
        assert "query" in wiki["function"]["parameters"]["required"]

    def test_web_search_structure(self):
        tools = get_available_tools()
        web = [t for t in tools if t["function"]["name"] == "web_search"][0]
        assert web["type"] == "function"
        assert web["function"]["name"] == "web_search"
        assert "query" in web["function"]["parameters"]["properties"]
        assert "query" in web["function"]["parameters"]["required"]

    def test_tool_descriptions_present(self):
        tools = get_available_tools()
        for tool in tools:
            assert "description" in tool["function"]
            assert len(tool["function"]["description"]) > 0


class TestParseToolCalls:
    """Test parse_tool_calls extracts tool calls from LLM responses."""

    def test_parses_tool_calls(self):
        response = {
            "choices": [{
                "message": {
                    "content": None,
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "wikipedia_search",
                                "arguments": '{"query": "quantum physics"}',
                            },
                        },
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": '{"query": "latest news"}',
                            },
                        },
                    ],
                },
            }],
        }
        result = parse_tool_calls(response)
        assert len(result) == 2
        assert result[0]["id"] == "call_1"
        assert result[1]["id"] == "call_2"

    def test_empty_when_no_tool_calls(self):
        response = {
            "choices": [{
                "message": {
                    "content": "Here is the chapter...",
                    "role": "assistant",
                },
            }],
        }
        assert parse_tool_calls(response) == []

    def test_empty_when_tool_calls_key_missing(self):
        response = {
            "choices": [{
                "message": {
                    "content": "Some text",
                    "role": "assistant",
                },
            }],
        }
        assert parse_tool_calls(response) == []

    def test_empty_when_tool_calls_none(self):
        response = {
            "choices": [{
                "message": {
                    "content": "Some text",
                    "tool_calls": None,
                    "role": "assistant",
                },
            }],
        }
        assert parse_tool_calls(response) == []

    def test_empty_when_tool_calls_empty_list(self):
        response = {
            "choices": [{
                "message": {
                    "content": "Some text",
                    "tool_calls": [],
                    "role": "assistant",
                },
            }],
        }
        assert parse_tool_calls(response) == []


class TestHasToolCalls:
    """Test has_tool_calls detection."""

    def test_true_with_tool_calls(self):
        response = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function"}],
                },
            }],
        }
        assert has_tool_calls(response) is True

    def test_false_without_tool_calls(self):
        response = {
            "choices": [{
                "message": {
                    "content": "Some text",
                },
            }],
        }
        assert has_tool_calls(response) is False

    def test_false_with_none_tool_calls(self):
        response = {
            "choices": [{
                "message": {
                    "content": "Some text",
                    "tool_calls": None,
                },
            }],
        }
        assert has_tool_calls(response) is False


class TestExecuteToolCall:
    """Test execute_tool_call dispatcher."""

    @pytest.mark.asyncio
    async def test_dispatches_wikipedia_search(self):
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "wikipedia_search",
                "arguments": '{"query": "Python"}',
            },
        }
        with patch("app.tools.wikipedia_search", new_callable=AsyncMock) as mock_wiki:
            mock_wiki.return_value = "Python is a programming language"
            result = await execute_tool_call(tool_call)
            mock_wiki.assert_called_once_with(query="Python")
            assert result == "Python is a programming language"

    @pytest.mark.asyncio
    async def test_dispatches_web_search(self):
        tool_call = {
            "id": "call_2",
            "type": "function",
            "function": {
                "name": "web_search",
                "arguments": '{"query": "AI news"}',
            },
        }
        with patch("app.tools.web_search", new_callable=AsyncMock) as mock_web:
            mock_web.return_value = "AI is advancing rapidly"
            result = await execute_tool_call(tool_call)
            mock_web.assert_called_once_with(query="AI news")
            assert result == "AI is advancing rapidly"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        tool_call = {
            "id": "call_3",
            "type": "function",
            "function": {
                "name": "unknown_tool",
                "arguments": '{"query": "test"}',
            },
        }
        result = await execute_tool_call(tool_call)
        assert "unknown tool" in result.lower()

    @pytest.mark.asyncio
    async def test_invalid_json_arguments_returns_error(self):
        tool_call = {
            "id": "call_4",
            "type": "function",
            "function": {
                "name": "wikipedia_search",
                "arguments": "not valid json",
            },
        }
        result = await execute_tool_call(tool_call)
        assert "invalid arguments" in result.lower()


class TestWikipediaSearch:
    """Test wikipedia_search implementation."""

    @pytest.mark.asyncio
    async def test_success_response(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "title": "Python",
            "description": "Programming language",
            "extract": "Python is a high-level programming language.",
        }

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.tools.get_tool_client", return_value=mock_client):
            result = await wikipedia_search("Python")
            assert "Python" in result
            assert "Programming language" in result
            assert "high-level" in result

    @pytest.mark.asyncio
    async def test_404_fallback_to_search(self):
        direct_response = MagicMock()
        direct_response.status_code = 404
        direct_response.raise_for_status = MagicMock(side_effect=Exception("404"))

        search_response = MagicMock()
        search_response.status_code = 200
        search_response.raise_for_status = MagicMock()
        search_response.json.return_value = {
            "query": {
                "search": [{"pageid": 123, "title": "Python"}],
            },
        }

        summary_response = MagicMock()
        summary_response.status_code = 200
        summary_response.raise_for_status = MagicMock()
        summary_response.json.return_value = {
            "title": "Python",
            "description": "Programming language",
            "extract": "Python is a high-level programming language.",
        }

        mock_client = MagicMock()
        mock_client.get.side_effect = [direct_response, search_response, summary_response]

        with patch("app.tools.get_tool_client", return_value=mock_client):
            result = await wikipedia_search("Python")
            assert "Python" in result


class TestWebSearch:
    """Test web_search implementation."""

    @pytest.mark.asyncio
    async def test_success_with_abstract(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "Abstract": "Python is a programming language.",
            "AbstractURL": "https://python.org",
        }

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.tools.get_tool_client", return_value=mock_client):
            result = await web_search("Python")
            assert "Python is a programming language" in result
            assert "python.org" in result

    @pytest.mark.asyncio
    async def test_no_results(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "Abstract": "",
            "RelatedTopics": [],
        }

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("app.tools.get_tool_client", return_value=mock_client):
            result = await web_search("obscure topic")
            assert "No results found" in result


class TestAIClientToolSupport:
    """Test AIClient tool calling support."""

    def test_generate_completion_without_tools(self):
        """Backward compatibility: generate_completion works without tools."""
        client = AIClient("https://example.com", "model")
        # Just verify the method accepts the call without tools
        assert hasattr(client, "generate_completion")
        assert hasattr(client, "execute_tool_calls")
        assert hasattr(client, "generate_completion_with_tools")

    @pytest.mark.asyncio
    async def test_generate_completion_with_tools_parameter(self):
        """generate_completion accepts tools parameter."""
        client = AIClient("https://example.com", "model")
        tools = get_available_tools()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Here is the result.",
                },
            }],
        }

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.generate_completion(
                messages=[{"role": "user", "content": "test"}],
                temperature=0.5,
                tools=tools,
            )
            # Verify tools were included in the request
            call_args = client._client.post.call_args
            payload = call_args[1]["json"]
            assert "tools" in payload
            assert result["choices"][0]["message"]["content"] == "Here is the result."

    @pytest.mark.asyncio
    async def test_generate_completion_without_tools_parameter(self):
        """Without tools parameter, payload has no tools key."""
        client = AIClient("https://example.com", "model")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Here is the result.",
                },
            }],
        }

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.generate_completion(
                messages=[{"role": "user", "content": "test"}],
                temperature=0.5,
            )
            call_args = client._client.post.call_args
            payload = call_args[1]["json"]
            assert "tools" not in payload

    @pytest.mark.asyncio
    async def test_execute_tool_calls(self):
        """execute_tool_calls processes tool calls and returns results."""
        client = AIClient("https://example.com", "model")
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "wikipedia_search",
                    "arguments": '{"query": "Python"}',
                },
            },
        ]

        with patch("app.tools.wikipedia_search", new_callable=AsyncMock) as mock_wiki:
            mock_wiki.return_value = "Python summary"
            results = await client.execute_tool_calls(tool_calls)
            assert len(results) == 1
            assert results[0]["tool_call_id"] == "call_1"
            assert results[0]["result"] == "Python summary"

    @pytest.mark.asyncio
    async def test_generate_completion_with_tools_no_tool_calls(self):
        """When response has no tool calls, returns immediately."""
        client = AIClient("https://example.com", "model")
        tools = get_available_tools()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Final answer without tool calls.",
                },
            }],
        }

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.generate_completion_with_tools(
                messages=[{"role": "user", "content": "test"}],
                temperature=0.5,
                tools=tools,
            )
            # Should return after single call (no tool calls to process)
            assert client._client.post.call_count == 1
            assert result["choices"][0]["message"]["content"] == "Final answer without tool calls."


class TestReviewerClientToolSupport:
    """Test ReviewerClient tool calling support."""

    @pytest.mark.asyncio
    async def test_generate_completion_with_tools_parameter(self):
        """ReviewerClient.generate_completion accepts tools parameter."""
        main = AIClient("https://example.com", "model")
        reviewer = ReviewerClient(main)
        tools = get_available_tools()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Review result.",
                },
            }],
        }

        with patch.object(main._client, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await reviewer.generate_completion(
                messages=[{"role": "user", "content": "test"}],
                temperature=0.5,
                tools=tools,
            )
            call_args = main._client.post.call_args
            payload = call_args[1]["json"]
            assert "tools" in payload
            assert result["choices"][0]["message"]["content"] == "Review result."

    @pytest.mark.asyncio
    async def test_reviewer_execute_tool_calls(self):
        """ReviewerClient.execute_tool_calls processes tool calls."""
        main = AIClient("https://example.com", "model")
        reviewer = ReviewerClient(main)
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "web_search",
                    "arguments": '{"query": "facts"}',
                },
            },
        ]

        with patch("app.tools.web_search", new_callable=AsyncMock) as mock_web:
            mock_web.return_value = "Web search result"
            results = await reviewer.execute_tool_calls(tool_calls)
            assert len(results) == 1
            assert results[0]["tool_call_id"] == "call_1"
            assert results[0]["result"] == "Web search result"

    @pytest.mark.asyncio
    async def test_reviewer_generate_completion_with_tools(self):
        """ReviewerClient.generate_completion_with_tools handles full loop."""
        main = AIClient("https://example.com", "model")
        reviewer = ReviewerClient(main)
        tools = get_available_tools()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Review complete.",
                },
            }],
        }

        with patch.object(main._client, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await reviewer.generate_completion_with_tools(
                messages=[{"role": "user", "content": "test"}],
                temperature=0.5,
                tools=tools,
            )
            assert main._client.post.call_count == 1
