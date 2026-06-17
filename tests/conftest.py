"""Pytest configuration for Hullucinator tests."""
import os
import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so `app` module is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


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
    from app.storage import CONFIG_FILE, reset_to_defaults, set_test_dirs
    from app import server_config

    # Save current config if it exists
    saved_config = None
    if CONFIG_FILE.exists():
        saved_config = CONFIG_FILE.read_text()

    # Reset to defaults
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
    server_config.configured = False
    server_config._persisted = None

    yield

    # Restore config if it was saved
    if saved_config:
        CONFIG_FILE.write_text(saved_config)
        server_config._persisted = True
    elif CONFIG_FILE.exists():
        # If config was recreated during test, mark as persisted
        server_config._persisted = True

    # Restore storage paths to real defaults after test
    reset_to_defaults()
