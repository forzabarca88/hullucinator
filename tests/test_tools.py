"""Tests for tool calling infrastructure (app/tools.py and app/ai_client.py tool support)."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx

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
    _is_retryable_error,
    _with_retry,
    _compute_delay,
    _wikipedia_search_impl,
    _web_search_impl,
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
    async def test_success_via_rest_title(self):
        """Happy path: search finds page, REST summary by title succeeds."""
        # Call 1: search endpoint
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.raise_for_status = MagicMock()
        search_response.json.return_value = {
            "query": {
                "search": [{"pageid": 123, "title": "Python"}],
            },
        }

        # Call 2: REST summary by title (succeeds)
        summary_response = MagicMock()
        summary_response.status_code = 200
        summary_response.raise_for_status = MagicMock()
        summary_response.json.return_value = {
            "title": "Python",
            "description": "Programming language",
            "extract": "Python is a high-level programming language.",
        }

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=[search_response, summary_response])

        with patch("app.tools.get_tool_client", return_value=mock_client):
            result = await wikipedia_search("Python")
            assert "Python" in result
            assert "Programming language" in result
            assert "high-level" in result
            assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_fallback_to_pageid_then_extracts(self):
        """REST summary by title returns 404, pageid also 404, falls back to extracts."""
        # Call 1: search endpoint
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.raise_for_status = MagicMock()
        search_response.json.return_value = {
            "query": {
                "search": [{"pageid": 99999, "title": "New Topic"}],
            },
        }

        # Call 2: REST summary by title (404)
        title_404 = MagicMock()
        title_404.status_code = 404

        # Call 3: REST summary by pageid (404)
        pageid_404 = MagicMock()
        pageid_404.status_code = 404

        # Call 4: action=query extracts fallback
        extract_response = MagicMock()
        extract_response.status_code = 200
        extract_response.raise_for_status = MagicMock()
        extract_response.json.return_value = {
            "query": {
                "pages": {
                    "99999": {
                        "pageid": 99999,
                        "title": "New Topic",
                        "extract": "<p><b>New Topic</b> is something important.</p>",
                    },
                },
            },
        }

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=[search_response, title_404, pageid_404, extract_response])

        with patch("app.tools.get_tool_client", return_value=mock_client):
            result = await wikipedia_search("New Topic")
            assert "New Topic" in result
            assert "something important" in result
            assert "<" not in result  # HTML tags stripped
            assert mock_client.get.call_count == 4

    @pytest.mark.asyncio
    async def test_no_results_found(self):
        """Search returns no results."""
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.raise_for_status = MagicMock()
        search_response.json.return_value = {
            "query": {
                "search": [],
            },
        }

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=search_response)

        with patch("app.tools.get_tool_client", return_value=mock_client):
            result = await wikipedia_search("xyznonexistent123")
            assert "No Wikipedia results found" in result

    @pytest.mark.asyncio
    async def test_search_http_error(self):
        """Search endpoint returns HTTP error."""
        search_response = MagicMock()
        search_response.status_code = 500
        search_response.raise_for_status = MagicMock(
            side_effect=Exception("500 Internal Server Error")
        )

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=search_response)

        with patch("app.tools.get_tool_client", return_value=mock_client):
            result = await wikipedia_search("test")
            assert "Error searching Wikipedia" in result

    @pytest.mark.asyncio
    async def test_strip_html(self):
        """_strip_html removes tags and preserves paragraph breaks."""
        from app.tools import _strip_html

        result = _strip_html("<p><b>Bold</b> text</p><p>Second paragraph</p>")
        assert "Bold" in result
        assert "text" in result
        assert "Second paragraph" in result
        assert "<" not in result

        # Multiple blank lines collapsed
        result2 = _strip_html("<p>One</p><p>Two</p><p>Three</p>")
        lines = [l for l in result2.split("\n") if l.strip()]
        assert len(lines) == 3


class TestWebSearch:
    """Test web_search implementation (ddgs package)."""

    @pytest.mark.asyncio
    async def test_success_with_results(self):
        """Happy path: ddgs returns search results with title, body, href."""
        mock_search = MagicMock()
        mock_search.text.return_value = [
            {"title": "Python Programming", "body": "Python is a programming language.", "href": "https://python.org"},
            {"title": "Python Docs", "body": "Official documentation.", "href": "https://docs.python.org"},
        ]
        # DDGS is used as a context manager: with DDGS() as search:
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_search)
        mock_ddgs.__exit__ = MagicMock(return_value=False)

        with patch("app.tools.DDGS", return_value=mock_ddgs):
            result = await web_search("Python")
            assert "Python is a programming language" in result
            assert "python.org" in result
            assert "Python Programming" in result
            mock_search.text.assert_called_once_with("Python", max_results=10)

    @pytest.mark.asyncio
    async def test_no_results(self):
        """ddgs returns empty list — graceful no-results message."""
        mock_search = MagicMock()
        mock_search.text.return_value = []
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_search)
        mock_ddgs.__exit__ = MagicMock(return_value=False)

        with patch("app.tools.DDGS", return_value=mock_ddgs):
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


class TestRetryLogic:
    """Test retry helpers for tool calls."""

    def test_is_retryable_connection_error(self):
        assert _is_retryable_error(httpx.ConnectError("")) is True
        assert _is_retryable_error(httpx.ConnectTimeout("")) is True
        assert _is_retryable_error(httpx.NetworkError("")) is True

    def test_is_retryable_timeout(self):
        assert _is_retryable_error(httpx.ReadTimeout("")) is True
        assert _is_retryable_error(httpx.PoolTimeout("")) is True

    def test_is_retryable_5xx(self):
        for code in [500, 502, 503, 504]:
            resp = MagicMock()
            resp.status_code = code
            assert _is_retryable_error(httpx.HTTPStatusError("", request=MagicMock(), response=resp)) is True

    def test_is_not_retryable_4xx(self):
        for code in [400, 401, 403, 404, 429]:
            resp = MagicMock()
            resp.status_code = code
            assert _is_retryable_error(httpx.HTTPStatusError("", request=MagicMock(), response=resp)) is False

    def test_is_not_retryable_generic(self):
        assert _is_retryable_error(ValueError("bad")) is False
        assert _is_retryable_error(RuntimeError("fail")) is False

    def test_compute_delay(self):
        # Delays increase with attempt number (exponential backoff + jitter)
        d1 = _compute_delay(1)
        d2 = _compute_delay(2)
        d3 = _compute_delay(3)
        assert d1 >= 1.0  # base delay
        assert d2 >= 2.0  # 2x base
        assert d3 >= 4.0  # 4x base

    @pytest.mark.asyncio
    async def test_with_retry_success_first_try(self):
        """No retry needed when function succeeds."""
        async def fn():
            return "ok"

        result = await _with_retry(fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_with_retry_transient_failure(self):
        """Retries on transient errors, succeeds eventually."""
        call_count = 0
        async def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("network down")
            return "recovered"

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await _with_retry(flaky_fn)
            assert result == "recovered"
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_non_retryable_error(self):
        """Does NOT retry on non-retryable errors."""
        call_count = 0
        async def bad_fn():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            await _with_retry(bad_fn)
        assert call_count == 1  # Only called once, no retry

    @pytest.mark.asyncio
    async def test_with_retry_exhausted(self):
        """Gives up after max retries on persistent transient error."""
        call_count = 0
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("permanent failure")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.ConnectError):
                await _with_retry(always_fail)
        # Called max_retries times (default 3)
        from app.config import get_default_shared_config
        max_retries = get_default_shared_config().tools.max_retries
        assert call_count == max_retries

    @pytest.mark.asyncio
    async def test_wikipedia_search_retries_on_transient(self):
        """wikipedia_search retries on connection failure, succeeds."""
        call_count = 0

        # Search response (returned by w/api.php)
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.raise_for_status = MagicMock()
        search_response.json.return_value = {
            "query": {"search": [{"pageid": 1, "title": "Test"}]},
        }

        # Summary response (returned by rest_v1/page/summary/*)
        summary_response = MagicMock()
        summary_response.status_code = 200
        summary_response.raise_for_status = MagicMock()
        summary_response.json.return_value = {
            "title": "Test",
            "description": "A test topic",
            "extract": "This is the test extract.",
        }

        async def smart_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("down")
            # After retries exhausted, return appropriate response per URL
            if "w/api.php" in url:
                return search_response
            return summary_response

        mock_client = MagicMock()
        mock_client.get = smart_get

        with patch("app.tools.get_tool_client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await wikipedia_search("Test")
            assert "Test" in result
            assert "A test topic" in result
            # 2 failed search attempts + 1 successful search + 1 summary = 4 calls
            assert call_count == 4

    @pytest.mark.asyncio
    async def test_web_search_retries_on_transient(self):
        """web_search retries on connection failure, succeeds."""
        call_count = 0

        def flaky_text(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("network down")
            return [{"title": "Found it!", "body": "Success.", "href": "https://example.com"}]

        mock_search = MagicMock()
        mock_search.text = flaky_text
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_search)
        mock_ddgs.__exit__ = MagicMock(return_value=False)

        with patch("app.tools.DDGS", return_value=mock_ddgs), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await web_search("Test")
            assert "Found it!" in result
            assert "example.com" in result
            assert call_count == 2  # Failed once, succeeded on 2nd
