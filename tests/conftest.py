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
    """Create data directories before each test, clean up after."""
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    # Remove persisted config for clean test state
    config_file = DATA_DIR / "config.json"
    if config_file.exists():
        config_file.unlink()
    yield
    # Clean up test artifacts
    import shutil
    for f in BOOKS_DIR.glob("*.json"):
        f.unlink()
    if config_file.exists():
        config_file.unlink()


@pytest.fixture
def project_root():
    return PROJECT_ROOT
