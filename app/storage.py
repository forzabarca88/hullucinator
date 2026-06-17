"""
JSON file persistence layer.

Stores all persisted data in the user's home directory under
`~/.hullucinator_data/` so that books, config, and exports survive
regardless of where the project is cloned or installed.

Directory layout:
    ~/.hullucinator_data/
    ├── data/
    │   ├── config.json
    │   └── books/          # one JSON file per book
    └── exports/            # exported EPUB/PDF files

Works on both Linux and Windows (Path.home() resolves to the
platform-appropriate home directory).
"""
import json
from pathlib import Path
from typing import Optional, List

from app.schemas import BookState, AIConfig

# User's home directory — platform-independent (works on Linux and Windows)
HULLUCINATOR_DATA_DIR = Path.home() / ".hullucinator_data"
DATA_DIR = HULLUCINATOR_DATA_DIR / "data"
BOOKS_DIR = DATA_DIR / "books"
EXPORTS_DIR = HULLUCINATOR_DATA_DIR / "exports"
CONFIG_FILE = DATA_DIR / "config.json"

def ensure_data_dir():
    """Create the data/ and data/books/ directories under ~/.hullucinator_data/."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)

def ensure_exports_dir():
    """Create the exports/ directory under ~/.hullucinator_data/."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ── Book persistence ──────────────────────────────────────────────────

def save_book(book_id: str, state: BookState):
    """Persist a BookState to disk as a JSON file."""
    if state.id != book_id:
        raise ValueError(f"Book ID mismatch: filename '{book_id}' != model id '{state.id}'")
    ensure_data_dir()
    file_path = BOOKS_DIR / f"{book_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(state.model_dump_json(indent=4))


def load_book(book_id: str) -> Optional[BookState]:
    """Load a BookState from disk. Returns None if file doesn't exist."""
    file_path = BOOKS_DIR / f"{book_id}.json"
    if not file_path.exists():
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return BookState(**data)


def list_books() -> List[BookState]:
    """Return all stored books sorted by creation time (newest first)."""
    books = []
    ensure_data_dir()
    for file_path in sorted(BOOKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            books.append(BookState(**data))
        except (json.JSONDecodeError, Exception):
            continue
    return books


# ── Config persistence ────────────────────────────────────────────────

def save_config(config: AIConfig):
    """
    Persist AI configuration to disk.
    API keys are NEVER saved — only endpoint URLs, model names, and review settings.
    """
    ensure_data_dir()
    data = config.model_dump()
    # Strip any API key data — never persist secrets
    data.pop("api_key", None)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def load_config() -> Optional[AIConfig]:
    """Load persisted AI configuration. Returns None if file doesn't exist."""
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # API key is never persisted; it must come from env var or runtime update
    return AIConfig(**data)
