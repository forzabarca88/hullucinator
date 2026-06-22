"""Tests for the FastAPI application endpoints."""
import asyncio
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app, ai_client
from app.storage import (
    BOOKS_DIR, CONFIG_FILE, EXPORTS_DIR,
    ensure_data_dir, ensure_exports_dir,
    set_test_dirs, reset_to_defaults,
)


@pytest_asyncio.fixture
async def client():
    """Create an async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _isolate_api_tests(tmp_path):
    """Redirect storage paths to tmp_path and reset AI client config.

    CRITICAL: Must redirect BOOKS_DIR/CONFIG_FILE/EXPORTS_DIR to tmp_path
    before any test runs, otherwise tests operate on the real
    ~/.hullucinator_data directory and can destroy production data.
    """
    import app.main as _m

    # Redirect storage paths to temp directory — MUST happen before any test
    set_test_dirs(tmp_path)

    # Reset AI client config
    ai_client.endpoint_url = ""
    ai_client.model_name = ""
    ai_client.api_key = None
    _m.server_config.configured = False
    _m.server_config.reviewer_client = None
    _m.server_config.persisted = None
    _m.reviewer_client = None
    _m.orchestrator.reviewer_client = None

    # Reset semaphore to allow re-creation for new event loop
    _m._generation_semaphore = None

    # Ensure temp directories exist
    ensure_data_dir()
    ensure_exports_dir()

    yield

    # Cleanup: restore paths to real defaults and reset config
    reset_to_defaults()
    ai_client.endpoint_url = ""
    ai_client.model_name = ""
    ai_client.api_key = None
    _m.server_config.configured = False
    _m.server_config.reviewer_client = None
    _m.server_config.persisted = None
    _m.reviewer_client = None
    _m.orchestrator.reviewer_client = None


class TestHealthEndpoint:
    """Test the health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "hullucinator"


class TestConfigEndpoints:
    """Test AI configuration endpoints."""

    @pytest.mark.asyncio
    async def test_get_config_unconfigured(self, client):
        """GET /api/config returns configured=false when nothing is set."""
        ai_client.endpoint_url = ""
        ai_client.model_name = ""
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["endpoint_url"] == ""
        assert data["model_name"] == ""
        assert data["api_key_set"] is False

    @pytest.mark.asyncio
    async def test_post_config(self, client):
        """POST /api/config updates AI settings."""
        resp = await client.post("/api/config", json={
            "endpoint_url": "http://localhost:8080",
            "model_name": "gpt-4o",
            "api_key": "test-key-123",
            "reviewer_endpoint_url": "",
            "reviewer_model_name": "",
            "review_max_turns": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["config"]["configured"] is True
        assert data["config"]["endpoint_url"] == "http://localhost:8080"
        assert data["config"]["model_name"] == "gpt-4o"
        assert data["config"]["api_key_set"] is True
        assert data["config"]["review_max_turns"] == 3

    @pytest.mark.asyncio
    async def test_post_config_partial(self, client):
        """POST /api/config with partial updates preserves existing values."""
        # First set full config
        await client.post("/api/config", json={
            "endpoint_url": "http://localhost:8080",
            "model_name": "gpt-4o",
            "api_key": "test-key-123",
            "review_max_turns": 2,
        })

        # Then update only model
        resp = await client.post("/api/config", json={
            "model_name": "llama-3.1-70b",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["config"]["endpoint_url"] == "http://localhost:8080"  # preserved
        assert data["config"]["model_name"] == "llama-3.1-70b"  # updated

    @pytest.mark.asyncio
    async def test_get_config_after_save(self, client):
        """GET /api/config reflects saved settings."""
        await client.post("/api/config", json={
            "endpoint_url": "http://test-endpoint.com",
            "model_name": "test-model",
            "api_key": "secret",
        })

        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["endpoint_url"] == "http://test-endpoint.com"
        assert data["model_name"] == "test-model"
        assert data["api_key_set"] is True

    @pytest.mark.asyncio
    async def test_validate_config_no_endpoint(self, client):
        """POST /api/config/validate rejects config without endpoint."""
        resp = await client.post("/api/config/validate", json={
            "endpoint_url": "",
            "model_name": "gpt-4o",
            "api_key": "test-key",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["writer_ok"] is False
        assert "endpoint" in data["writer_error"].lower()

    @pytest.mark.asyncio
    async def test_validate_config_no_model(self, client):
        """POST /api/config/validate rejects config without model."""
        resp = await client.post("/api/config/validate", json={
            "endpoint_url": "http://localhost:8080",
            "model_name": "",
            "api_key": "test-key",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["writer_ok"] is False
        assert "model" in data["writer_error"].lower()

    @pytest.mark.asyncio
    async def test_validate_config_invalid_key(self, client):
        """POST /api/config/validate detects invalid API key."""
        with patch("app.routes.AIClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.list_models = AsyncMock(
                side_effect=Exception("401: Unauthorized")
            )
            mock_instance.close = AsyncMock()
            MockClient.return_value = mock_instance

            resp = await client.post("/api/config/validate", json={
                "endpoint_url": "http://localhost:8080",
                "model_name": "gpt-4o",
                "api_key": "invalid-key",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is False
            assert data["writer_ok"] is False

    @pytest.mark.asyncio
    async def test_validate_config_fallback_to_saved(self, client):
        """POST /api/config/validate uses saved config when fields are empty."""
        # Set up saved config
        await client.post("/api/config", json={
            "endpoint_url": "http://localhost:8080",
            "model_name": "gpt-4o",
            "api_key": "invalid-key",
        })

        with patch("app.routes.AIClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.list_models = AsyncMock(
                side_effect=Exception("401: Unauthorized")
            )
            mock_instance.close = AsyncMock()
            MockClient.return_value = mock_instance

            # Validate with empty fields — should fall back to saved config
            resp = await client.post("/api/config/validate", json={})
            assert resp.status_code == 200
            data = resp.json()
            # Should detect the invalid key from saved config
            assert data["valid"] is False

    @pytest.mark.asyncio
    async def test_validate_config_reviewer_separate(self, client):
        """POST /api/config/validate checks reviewer separately when configured."""
        with patch("app.routes.AIClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.list_models = AsyncMock(
                side_effect=Exception("Connection error")
            )
            mock_instance.close = AsyncMock()
            MockClient.return_value = mock_instance

            resp = await client.post("/api/config/validate", json={
                "endpoint_url": "http://localhost:8080",
                "model_name": "gpt-4o",
                "api_key": "writer-key",
                "reviewer_endpoint_url": "http://localhost:9090",
                "reviewer_model_name": "reviewer-model",
                "reviewer_api_key": "reviewer-key",
            })
            assert resp.status_code == 200
            data = resp.json()
            # Both writer and reviewer will fail since endpoints don't respond
            assert data["writer_ok"] is False
            assert data["reviewer_ok"] is False

    @pytest.mark.asyncio
    async def test_validate_config_reviewer_fallback(self, client):
        """POST /api/config/validate uses writer config when reviewer is not separate."""
        with patch("app.routes.AIClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.list_models = AsyncMock(
                side_effect=Exception("Connection error")
            )
            mock_instance.close = AsyncMock()
            MockClient.return_value = mock_instance

            resp = await client.post("/api/config/validate", json={
                "endpoint_url": "http://localhost:8080",
                "model_name": "gpt-4o",
                "api_key": "test-key",
            })
            assert resp.status_code == 200
            data = resp.json()
            # No separate reviewer configured, so reviewer_ok mirrors writer_ok
            assert data["reviewer_ok"] == data["writer_ok"]


class TestModelListing:
    """Test model listing endpoints."""

    @pytest.mark.asyncio
    async def test_list_models_unconfigured(self, client):
        """GET /api/models fails when no endpoint is set."""
        ai_client.endpoint_url = ""
        resp = await client.get("/api/models")
        assert resp.status_code == 400
        data = resp.json()
        assert "Endpoint URL is required" in data["detail"]

    @pytest.mark.asyncio
    async def test_list_models_with_endpoint(self, client):
        """GET /api/models succeeds when endpoint is set."""
        ai_client.endpoint_url = "http://localhost:8080"

        # (C4 fix: list_available_models creates a temp AIClient. Patch
        # AIClient.list_models at the class level so ALL instances — shared
        # and temp — return the mocked data. Can't patch httpx.AsyncClient.get
        # at class level because the test fixture's AsyncClient also uses it.)
        async def mock_list_models(self):
            return [
                {"id": "gpt-4o", "name": "gpt-4o"},
                {"id": "gpt-3.5-turbo", "name": "gpt-3.5-turbo"},
            ]

        with patch.object(
            type(ai_client), "list_models", mock_list_models,
        ):
            resp = await client.get("/api/models")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["models"]) == 2
            assert data["models"][0]["id"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_list_models_with_query_params(self, client):
        """GET /api/models with endpoint_url query param works during setup."""
        ai_client.endpoint_url = ""  # Not configured yet

        async def mock_list_models(self):
            return [{"id": "qwen3.6-27b", "name": "qwen3.6-27b"}]

        with patch.object(
            type(ai_client), "list_models", mock_list_models,
        ):
            resp = await client.get("/api/models", params={
                "endpoint_url": "http://test.com",
                "api_key": "test-key",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["models"]) == 1
            assert data["models"][0]["id"] == "qwen3.6-27b"

        # Verify original values are restored after fetch
        assert ai_client.endpoint_url == ""
        assert ai_client.api_key is None

    @pytest.mark.asyncio
    async def test_reviewer_models_no_client(self, client):
        """GET /api/reviewer/models returns uses_writer when no reviewer client."""
        resp = await client.get("/api/reviewer/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["uses_writer"] is True
        assert data["models"] == []

    @pytest.mark.asyncio
    async def test_reviewer_models_with_endpoint(self, client):
        """GET /api/reviewer/models with endpoint_url query param works."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={
            "data": [{"id": "critic-model", "name": "critic-model"}]
        })

        # (reviewer models with endpoint_url uses ai_client._client.get directly
        # — this is an instance-level patch, safe because the test fixture's
        # AsyncClient is a different instance.)
        with patch.object(ai_client._client, "get", new_callable=AsyncMock, return_value=mock_response):
            resp = await client.get("/api/reviewer/models", params={
                "endpoint_url": "http://reviewer.com",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["uses_writer"] is False
            assert len(data["models"]) == 1
            assert data["models"][0]["id"] == "critic-model"


class TestBookEndpoints:
    """Test book creation and management endpoints."""

    @pytest.mark.asyncio
    async def test_create_book_unconfigured(self, client):
        """POST /api/books/create fails when AI is not configured."""
        ai_client.endpoint_url = ""
        ai_client.model_name = ""
        resp = await client.post("/api/books/create", json={
            "title": "Test Book",
            "prompt": "A test book",
        })
        assert resp.status_code == 400
        data = resp.json()
        assert "not configured" in data["detail"]

    @pytest.mark.asyncio
    async def test_create_book_success(self, client):
        """POST /api/books/create succeeds when configured."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"

        resp = await client.post("/api/books/create", json={
            "title": "Test Book",
            "prompt": "A test book",
            "tags": ["sci-fi"],
            "length": "novel",
            "review_max_turns": 2,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "book_id" in data
        assert data["status"] == "pending"
        assert data["review_max_turns"] == 2

    @pytest.mark.asyncio
    async def test_get_nonexistent_book(self, client):
        """GET /api/books/{id} returns 404 for unknown book."""
        resp = await client.get("/api/books/nonexistent-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        """GET /api/books returns empty list when no books exist."""
        resp = await client.get("/api/books")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_book_long_prompt(self, client):
        """POST /api/books/create accepts prompts exceeding 5000 characters.

        Regression test: previously the schema had max_length=5000 on prompt,
        causing 422 errors when users pasted detailed background text.
        """
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"

        # Generate a prompt that exceeds the old 5000-character limit
        long_prompt = "A detailed historical account. " * 100  # ~3000+ chars
        long_prompt += "With extensive background context and timeline details. " * 100  # well over 5000

        resp = await client.post("/api/books/create", json={
            "title": "Long Prompt Book",
            "prompt": long_prompt,
        })
        assert resp.status_code == 200, f"Got {resp.status_code}: {resp.json()}"
        data = resp.json()
        assert "book_id" in data








class TestWebUI:
    """Test the web interface."""

    @pytest.mark.asyncio
    async def test_index_page(self, client):
        """GET / returns the web interface HTML with required scripts."""
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        body = resp.text
        # Verify required JS modules are loaded (in correct order)
        assert "config.js" in body
        assert "ui.js" in body
        assert "renderers.js" in body
        assert "app.js" in body
        assert "settings.js" in body
        assert "boot.js" in body

class TestRetryEndpoint:
    """Test the POST /api/books/{id}/retry endpoint."""

    @pytest.mark.asyncio
    async def test_retry_creates_new_book(self, client):
        """Retry creates a new book with same content and deletes the old one."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"

        # Create a book
        resp = await client.post("/api/books/create", json={
            "title": "Retry Test",
            "prompt": "A test book for retry",
            "tags": ["comedy"],
            "length": "novella",
            "review_max_turns": 3,
        })
        assert resp.status_code == 200
        old_book = resp.json()
        old_id = old_book["book_id"]

        # Retry
        resp = await client.post(f"/api/books/{old_id}/retry")
        assert resp.status_code == 200
        retry_response = resp.json()
        new_book_id = retry_response["book_id"]
        assert new_book_id != old_id
        assert retry_response["status"] == "pending"

        # Fetch the new book to verify all fields
        resp = await client.get(f"/api/books/{new_book_id}")
        assert resp.status_code == 200
        new_book = resp.json()

        # New book has same content
        assert new_book["title"] == "Retry Test"
        assert new_book["prompt"] == "A test book for retry"
        assert new_book["tags"] == ["comedy"]
        assert new_book["length"] == "novella"
        assert new_book["review_max_turns"] == 3
        assert new_book["id"] != old_id
        assert new_book["status"] == "pending"

        # Old book is deleted
        resp = await client.get(f"/api/books/{old_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_nonexistent_book(self, client):
        """Retry on non-existent book returns 404."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        resp = await client.post("/api/books/nonexistent/retry")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_preserves_all_fields(self, client):
        """Retry preserves all book fields including optional ones."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"

        # Create a book with all fields
        resp = await client.post("/api/books/create", json={
            "title": "Full Fields Test",
            "prompt": "A comprehensive test",
            "tags": ["sci-fi", "comedy"],
            "length": "epic",
            "review_max_turns": 5,
            "skip_review": True,
        })
        assert resp.status_code == 200
        old_book = resp.json()
        old_id = old_book["book_id"]

        # Retry
        resp = await client.post(f"/api/books/{old_id}/retry")
        assert resp.status_code == 200
        retry_response = resp.json()
        new_book_id = retry_response["book_id"]

        # Fetch the new book to verify all fields
        resp = await client.get(f"/api/books/{new_book_id}")
        assert resp.status_code == 200
        new_book = resp.json()

        assert new_book["title"] == "Full Fields Test"
        assert new_book["prompt"] == "A comprehensive test"
        assert new_book["tags"] == ["sci-fi", "comedy"]
        assert new_book["length"] == "epic"
        assert new_book["review_max_turns"] == 5
        assert new_book["skip_review"] is True
        assert new_book["status"] == "pending"
