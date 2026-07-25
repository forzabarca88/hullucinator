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
    BOOKS_DIR, CONFIG_FILE, EXPORTS_DIR, COVERS_DIR,
    ensure_data_dir, ensure_exports_dir, ensure_covers_dir,
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
    ensure_covers_dir()

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
    async def test_web_grounding_toggle(self, client):
        """POST /api/config can toggle allow_web_grounding and it persists."""
        # Default is False
        resp = await client.get("/api/config")
        assert resp.json()["allow_web_grounding"] is False

        # Enable it
        resp = await client.post("/api/config", json={
            "endpoint_url": "http://localhost:8080",
            "model_name": "gpt-4o",
            "api_key": "test-key",
            "allow_web_grounding": True,
        })
        assert resp.json()["config"]["allow_web_grounding"] is True

        # Verify it persists through get
        resp = await client.get("/api/config")
        assert resp.json()["allow_web_grounding"] is True

        # Disable it
        resp = await client.post("/api/config", json={
            "allow_web_grounding": False,
        })
        assert resp.json()["config"]["allow_web_grounding"] is False

        # Verify disabled
        resp = await client.get("/api/config")
        assert resp.json()["allow_web_grounding"] is False

    @pytest.mark.asyncio
    async def test_config_schema_includes_tools(self, client):
        """GET /api/config-schema includes tools section with allow_web_grounding."""
        resp = await client.get("/api/config-schema")
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        assert data["tools"]["allow_web_grounding"] is False

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
    async def test_create_book_no_api_key(self, client):
        """POST /api/books/create fails when credentials are invalid (live test request fails)."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        ai_client.api_key = None

        async def mock_list_models_fail(self):
            raise Exception("API request failed with status 401: {\"detail\":\"Unauthorized\"}")

        with patch.object(type(ai_client), "list_models", mock_list_models_fail):
            resp = await client.post("/api/books/create", json={
                "title": "Test Book",
                "prompt": "A test book",
            })
            assert resp.status_code == 400
            data = resp.json()
            assert "credentials" in data["detail"].lower() or "invalid" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_book_invalid_api_key(self, client):
        """POST /api/books/create fails when API key is invalid (401 from LLM)."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        ai_client.api_key = "invalid-key"

        async def mock_list_models_fail(self):
            raise Exception("API request failed with status 401: {\"detail\":\"Unauthorized\"}")

        with patch.object(type(ai_client), "list_models", mock_list_models_fail):
            resp = await client.post("/api/books/create", json={
                "title": "Test Book",
                "prompt": "A test book",
            })
            assert resp.status_code == 400
            data = resp.json()
            assert "invalid" in data["detail"].lower() or "credentials" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_book_success(self, client):
        """POST /api/books/create succeeds when fully configured with valid credentials."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        with patch.object(type(ai_client), "list_models", mock_list_models):
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
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        # Generate a prompt that exceeds the old 5000-character limit
        long_prompt = "A detailed historical account. " * 100  # ~3000+ chars
        long_prompt += "With extensive background context and timeline details. " * 100  # well over 5000

        with patch.object(type(ai_client), "list_models", mock_list_models):
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
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        with patch.object(type(ai_client), "list_models", mock_list_models):
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
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        with patch.object(type(ai_client), "list_models", mock_list_models):
            resp = await client.post("/api/books/nonexistent/retry")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_preserves_all_fields(self, client):
        """Retry preserves all book fields including optional ones."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        with patch.object(type(ai_client), "list_models", mock_list_models):
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

    @pytest.mark.asyncio
    async def test_retry_completed_book(self, client):
        """Retry works for completed books, not just failed ones."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        with patch.object(type(ai_client), "list_models", mock_list_models):
            # Create a book
            resp = await client.post("/api/books/create", json={
                "title": "Completed Retry Test",
                "prompt": "A book to retry after completion",
                "tags": ["fantasy"],
                "length": "novel",
                "review_max_turns": 2,
            })
            assert resp.status_code == 200
            old_book = resp.json()
            old_id = old_book["book_id"]

            # Simulate the book reaching completed status
            resp = await client.get(f"/api/books/{old_id}")
            book = resp.json()
            book["status"] = "completed"

            # Retry the completed book
            resp = await client.post(f"/api/books/{old_id}/retry")
            assert resp.status_code == 200
            retry_response = resp.json()
            new_book_id = retry_response["book_id"]
            assert new_book_id != old_id
            assert retry_response["status"] == "pending"

            # New book has same content
            resp = await client.get(f"/api/books/{new_book_id}")
            assert resp.status_code == 200
            new_book = resp.json()
            assert new_book["title"] == "Completed Retry Test"
            assert new_book["prompt"] == "A book to retry after completion"
            assert new_book["tags"] == ["fantasy"]
            assert new_book["status"] == "pending"

            # Old book is deleted
            resp = await client.get(f"/api/books/{old_id}")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_preserves_cover_image(self, client):
        """Retry preserves cover_image path and copies the cover file to the new book."""
        # Import COVERS_DIR inside the test to get the redirected (tmp_path) value
        from app.storage import COVERS_DIR as _COVERS_DIR

        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        with patch.object(type(ai_client), "list_models", mock_list_models):
            # Create a book
            resp = await client.post("/api/books/create", json={
                "title": "Cover Retry Test",
                "prompt": "A book with a cover",
                "tags": ["sci-fi"],
                "length": "novella",
            })
            assert resp.status_code == 200
            old_book = resp.json()
            old_id = old_book["book_id"]

            # Upload a cover image (webp format)
            webp_data = b'RIFF' + b'\x00' * 100 + b'WEBP'
            resp = await client.post(
                f"/api/books/{old_id}/cover",
                files={"file": ("cover.webp", webp_data, "image/webp")},
            )
            assert resp.status_code == 200
            old_cover_path = resp.json()["cover_image"]
            assert old_cover_path == f"covers/{old_id}.webp"

            # Verify the cover file exists
            cover_file = _COVERS_DIR / f"{old_id}.webp"
            assert cover_file.exists()

            # Retry the book
            resp = await client.post(f"/api/books/{old_id}/retry")
            assert resp.status_code == 200
            retry_response = resp.json()
            new_book_id = retry_response["book_id"]
            assert new_book_id != old_id

            # Fetch the new book to verify cover_image was preserved
            resp = await client.get(f"/api/books/{new_book_id}")
            assert resp.status_code == 200
            new_book = resp.json()
            assert new_book["cover_image"] == f"covers/{new_book_id}.webp"

            # Verify the new cover file exists with correct format
            new_cover_file = _COVERS_DIR / f"{new_book_id}.webp"
            assert new_cover_file.exists()
            # Verify content was copied
            assert new_cover_file.read_bytes() == webp_data

            # Old cover file should be deleted
            assert not cover_file.exists()

            # Verify cover serves correctly
            resp = await client.get(f"/api/books/{new_book_id}/cover")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "image/webp"


class TestResumeEndpoint:
    """Test the POST /api/books/{id}/resume endpoint."""

    @pytest.mark.asyncio
    async def test_resume_nonexistent_book(self, client):
        """Resume on non-existent book returns 404."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        with patch.object(type(ai_client), "list_models", mock_list_models):
            resp = await client.post("/api/books/nonexistent/resume")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_resume_terminal_status(self, client):
        """Resume on terminal status (completed, reviewed, failed) returns 400."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        with patch.object(type(ai_client), "list_models", mock_list_models):
            # Create a book
            resp = await client.post("/api/books/create", json={
                "title": "Terminal Book",
                "prompt": "A test book",
                "length": "short_story",
            })
            assert resp.status_code == 200
            book_id = resp.json()["book_id"]

            # Set to completed status (terminal)
            from app.storage import load_book, save_book
            book = load_book(book_id)
            book.status = "completed"
            save_book(book_id, book)

            # Try to resume — should fail
            resp = await client.post(f"/api/books/{book_id}/resume")
            assert resp.status_code == 400
            assert "Cannot resume" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_resume_unconfigured(self, client):
        """Resume fails when AI is not configured."""
        ai_client.endpoint_url = ""
        ai_client.model_name = ""

        # Create a book in pending status directly
        from app.schemas import BookState
        from app.storage import save_book
        import uuid
        book_id = str(uuid.uuid4())
        book_state = BookState(
            id=book_id,
            title="Resume Test",
            prompt="A test book",
            status="pending",
        )
        save_book(book_id, book_state)

        resp = await client.post(f"/api/books/{book_id}/resume")
        assert resp.status_code == 400
        assert "not configured" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_resume_in_progress(self, client):
        """Resume a book stuck in in_progress status queues it for continuation."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        with patch.object(type(ai_client), "list_models", mock_list_models):
            # Create a book and simulate it being stuck in in_progress
            from app.schemas import BookState
            from app.storage import save_book
            import uuid
            book_id = str(uuid.uuid4())
            book_state = BookState(
                id=book_id,
                title="Interrupted Book",
                prompt="A book that was interrupted",
                tags=["sci-fi"],
                length="novella",
                status="in_progress",
                summary="A summary of the book",
                outline=["Chapter 1: The Beginning", "Chapter 2: The Journey", "Chapter 3: The End"],
                chapters={"Chapter 1: The Beginning": "Content of chapter 1"},
                chapter_summaries={"Chapter 1: The Beginning": "Summary of chapter 1"},
                progress={"current_step": "Writing Chapter 2...", "total_chapters": 3,
                          "chapters_completed": 1, "percentage": 50},
                review_max_turns=2,
                skip_review=True,
            )
            save_book(book_id, book_state)

            # Resume
            resp = await client.post(f"/api/books/{book_id}/resume")
            assert resp.status_code == 200
            data = resp.json()
            assert data["book_id"] == book_id
            assert data["resuming_from"] == "in_progress"

            # Book should still be in in_progress status (task queued, not yet complete)
            resp = await client.get(f"/api/books/{book_id}")
            assert resp.status_code == 200
            book = resp.json()
            assert book["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_resume_preserves_generated_content(self, client):
        """Resume preserves already-generated content (chapters, summaries)."""
        ai_client.endpoint_url = "http://localhost:8080"
        ai_client.model_name = "gpt-4o"
        ai_client.api_key = "test-key"

        async def mock_list_models(self):
            return [{"id": "gpt-4o", "name": "gpt-4o"}]

        with patch.object(type(ai_client), "list_models", mock_list_models):
            # Create a book with partial progress
            from app.schemas import BookState
            from app.storage import save_book
            import uuid
            book_id = str(uuid.uuid4())
            book_state = BookState(
                id=book_id,
                title="Partial Book",
                prompt="A book with partial progress",
                tags=["fantasy"],
                length="short_story",
                status="in_progress",
                summary="A fantasy adventure",
                outline=["Chapter 1: The Call", "Chapter 2: The Quest"],
                chapters={"Chapter 1: The Call": "Original chapter 1 content"},
                chapter_summaries={"Chapter 1: The Call": "Original summary"},
                progress={"current_step": "Writing Chapter 2...", "total_chapters": 2,
                          "chapters_completed": 1, "percentage": 60},
                review_max_turns=2,
                skip_review=True,
            )
            save_book(book_id, book_state)

            # Resume
            resp = await client.post(f"/api/books/{book_id}/resume")
            assert resp.status_code == 200

            # Verify the book still exists and has the original chapter preserved
            resp = await client.get(f"/api/books/{book_id}")
            assert resp.status_code == 200
            book = resp.json()
            # Chapter 1 content should be preserved (resume doesn't regenerate existing chapters)
            assert "Chapter 1: The Call" in book["chapters"]
            assert book["chapters"]["Chapter 1: The Call"] == "Original chapter 1 content"


class TestCoverEndpoints:
    """Test cover image upload, retrieval, and deletion endpoints."""

    @pytest.fixture(autouse=True)
    def _ensure_covers_dir(self):
        """Ensure the covers directory exists for cover endpoint tests."""
        ensure_covers_dir()

    @pytest.mark.asyncio
    async def test_upload_cover_success(self, client):
        """POST /api/books/{id}/cover uploads a valid PNG cover image."""
        # Create a book first
        from app.schemas import BookState
        from app.storage import save_book
        import uuid
        book_id = str(uuid.uuid4())
        book_state = BookState(
            id=book_id,
            title="Cover Test",
            prompt="A test book",
            status="pending",
        )
        save_book(book_id, book_state)

        # Upload a valid PNG (minimal valid PNG header)
        png_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        resp = await client.post(
            f"/api/books/{book_id}/cover",
            files={"file": ("cover.png", png_data, "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cover_image"] == f"covers/{book_id}.png"

        # Verify book state was updated
        resp = await client.get(f"/api/books/{book_id}")
        book = resp.json()
        assert book["cover_image"] == f"covers/{book_id}.png"

    @pytest.mark.asyncio
    async def test_upload_cover_nonexistent_book(self, client):
        """POST /api/books/{id}/cover returns 404 for unknown book."""
        png_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        resp = await client.post(
            "/api/books/nonexistent-id/cover",
            files={"file": ("cover.png", png_data, "image/png")},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_upload_cover_invalid_format(self, client):
        """POST /api/books/{id}/cover rejects unsupported image formats."""
        from app.schemas import BookState
        from app.storage import save_book
        import uuid
        book_id = str(uuid.uuid4())
        book_state = BookState(
            id=book_id,
            title="Cover Test",
            prompt="A test book",
            status="pending",
        )
        save_book(book_id, book_state)

        # Try uploading a GIF (not allowed)
        gif_data = b'GIF89a' + b'\x00' * 100
        resp = await client.post(
            f"/api/books/{book_id}/cover",
            files={"file": ("cover.gif", gif_data, "image/gif")},
        )
        assert resp.status_code == 400
        assert "Invalid image format" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_cover_too_large(self, client):
        """POST /api/books/{id}/cover rejects images over 5MB."""
        from app.schemas import BookState
        from app.storage import save_book
        import uuid
        book_id = str(uuid.uuid4())
        book_state = BookState(
            id=book_id,
            title="Cover Test",
            prompt="A test book",
            status="pending",
        )
        save_book(book_id, book_state)

        # Send a file larger than 5MB
        large_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * (5 * 1024 * 1024 + 1)
        resp = await client.post(
            f"/api/books/{book_id}/cover",
            files={"file": ("cover.png", large_data, "image/png")},
        )
        assert resp.status_code == 400
        assert "too large" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_cover_success(self, client):
        """GET /api/books/{id}/cover serves the cover image."""
        from app.schemas import BookState
        from app.storage import save_book, save_cover_image
        import uuid
        book_id = str(uuid.uuid4())
        cover_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        cover_path = save_cover_image(book_id, cover_bytes)

        book_state = BookState(
            id=book_id,
            title="Cover Test",
            prompt="A test book",
            status="pending",
            cover_image=cover_path,
        )
        save_book(book_id, book_state)

        resp = await client.get(f"/api/books/{book_id}/cover")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    @pytest.mark.asyncio
    async def test_get_cover_no_cover_set(self, client):
        """GET /api/books/{id}/cover returns 404 when no cover is set."""
        from app.schemas import BookState
        from app.storage import save_book
        import uuid
        book_id = str(uuid.uuid4())
        book_state = BookState(
            id=book_id,
            title="No Cover Book",
            prompt="A test book",
            status="pending",
        )
        save_book(book_id, book_state)

        resp = await client.get(f"/api/books/{book_id}/cover")
        assert resp.status_code == 404
        assert "No cover image" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_cover_nonexistent_book(self, client):
        """GET /api/books/{id}/cover returns 404 for unknown book."""
        resp = await client.get("/api/books/nonexistent-id/cover")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_cover_success(self, client):
        """DELETE /api/books/{id}/cover removes the cover image."""
        from app.schemas import BookState
        from app.storage import save_book, save_cover_image
        import uuid
        book_id = str(uuid.uuid4())
        cover_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        cover_path = save_cover_image(book_id, cover_bytes)

        book_state = BookState(
            id=book_id,
            title="Cover Test",
            prompt="A test book",
            status="pending",
            cover_image=cover_path,
        )
        save_book(book_id, book_state)

        resp = await client.delete(f"/api/books/{book_id}/cover")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cover_deleted"
        assert data["book_id"] == book_id

        # Verify book state was cleared
        resp = await client.get(f"/api/books/{book_id}")
        book = resp.json()
        assert book["cover_image"] is None

        # Verify file was deleted
        cover_file = COVERS_DIR / f"{book_id}.png"
        assert not cover_file.exists()

    @pytest.mark.asyncio
    async def test_delete_cover_no_cover_set(self, client):
        """DELETE /api/books/{id}/cover returns 404 when no cover is set."""
        from app.schemas import BookState
        from app.storage import save_book
        import uuid
        book_id = str(uuid.uuid4())
        book_state = BookState(
            id=book_id,
            title="No Cover Book",
            prompt="A test book",
            status="pending",
        )
        save_book(book_id, book_state)

        resp = await client.delete(f"/api/books/{book_id}/cover")
        assert resp.status_code == 404
        assert "No cover image" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_delete_cover_nonexistent_book(self, client):
        """DELETE /api/books/{id}/cover returns 404 for unknown book."""
        resp = await client.delete("/api/books/nonexistent-id/cover")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_books_includes_cover_image(self, client):
        """GET /api/books response includes cover_image field."""
        from app.schemas import BookState
        from app.storage import save_book, save_cover_image
        import uuid
        book_id = str(uuid.uuid4())
        cover_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        cover_path = save_cover_image(book_id, cover_bytes)

        book_state = BookState(
            id=book_id,
            title="Cover Book",
            prompt="A test book",
            status="pending",
            cover_image=cover_path,
        )
        save_book(book_id, book_state)

        resp = await client.get("/api/books")
        assert resp.status_code == 200
        books = resp.json()
        assert len(books) == 1
        assert "cover_image" in books[0]
        assert books[0]["cover_image"] == cover_path

    @pytest.mark.asyncio
    async def test_get_book_status_includes_cover_image(self, client):
        """GET /api/books/{id} response includes cover_image field."""
        from app.schemas import BookState
        from app.storage import save_book, save_cover_image
        import uuid
        book_id = str(uuid.uuid4())
        cover_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        cover_path = save_cover_image(book_id, cover_bytes)

        book_state = BookState(
            id=book_id,
            title="Cover Book",
            prompt="A test book",
            status="pending",
            cover_image=cover_path,
        )
        save_book(book_id, book_state)

        resp = await client.get(f"/api/books/{book_id}")
        assert resp.status_code == 200
        book = resp.json()
        assert "cover_image" in book
        assert book["cover_image"] == cover_path
