"""Pytest configuration for Hullucinator tests."""
import os
import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so `app` module is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure data directories exist for tests
DATA_DIR = PROJECT_ROOT / "data"
BOOKS_DIR = DATA_DIR / "books"
EXPORTS_DIR = PROJECT_ROOT / "exports"


@pytest.fixture(autouse=True)
def _ensure_dirs():
    """Create data directories before each test, clean up books after.
    
    (M8 fix: preserve config.json across tests so that tests depending on
    persisted config state can work correctly. Only clean up book data and
    exports, not the config file.)
    """
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    # Note: config.json is preserved across tests. Tests that need a clean
    # config state should use the _reset_config fixture explicitly.
    yield
    # Clean up test artifacts (books and exports, but NOT config)
    import shutil
    for f in BOOKS_DIR.glob("*.json"):
        f.unlink()
    for f in EXPORTS_DIR.glob("*"):
        f.unlink()


@pytest.fixture
def project_root():
    return PROJECT_ROOT


@pytest.fixture
def _reset_config():
    """Reset config to clean state. Use this fixture explicitly in tests
    that need a fresh config (not autouse, to avoid breaking tests that
    depend on persisted config state).
    
    Usage: Add _reset_config to your test function parameters.
    """
    from app import server_config
    config_file = DATA_DIR / "config.json"
    
    # Save current config if it exists
    saved_config = None
    if config_file.exists():
        saved_config = config_file.read_text()
    
    # Reset to defaults
    if config_file.exists():
        config_file.unlink()
    server_config.configured = False
    server_config.endpoint_url = ""
    server_config.model_name = ""
    server_config.reviewer_endpoint_url = ""
    server_config.reviewer_model_name = ""
    server_config.review_max_turns = 2
    server_config._persisted = False
    
    yield
    
    # Restore config if it was saved
    if saved_config:
        config_file.write_text(saved_config)
        server_config._persisted = True
    elif config_file.exists():
        # If config was recreated during test, mark as persisted
        server_config._persisted = True
